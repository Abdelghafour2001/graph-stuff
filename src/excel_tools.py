"""Agent tools over the workbook graph and the raw Excel files. Read-only, except propose_extraction_spec (review queue)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import yaml
from anthropic import beta_tool
from openpyxl.utils import get_column_letter, range_boundaries

from graph import read_graph
from spec_executor import check, execute, validate

EXCEL_DIR = Path(os.environ["EXCEL_DIR"])
SPECS = Path(__file__).parent.parent / "specs"
MAX_CELLS = 600


def cell_text(v) -> str:
    return "" if v is None else str(v)[:40]


@beta_tool
def find_sheets(concept_ids: list[str]) -> str:
    """Find workbook sheets whose headers, row labels or context mention ALL the given concepts. Data sheets first.

    Args:
        concept_ids: Concept ids from lookup_term, e.g. ["dap", "country_morocco", "fob"].
    """
    rows = read_graph(
        "MATCH (x:Sheet)-[m:MENTIONS]->(c:Concept) WHERE c.id IN $ids "
        "WITH x, collect(DISTINCT c.id) AS hit, sum(m.n) AS strength WHERE size(hit) = size($ids) "
        "RETURN x.file AS file, x.name AS sheet, x.role AS role, x.description AS description, strength "
        "ORDER BY x.role = 'data' DESC, strength DESC",
        ids=concept_ids,
    )
    return json.dumps(rows, ensure_ascii=False) if rows else "No sheet mentions all of these concepts. Try fewer concepts."


@beta_tool
def describe_sheet(file: str, sheet: str) -> str:
    """Layout features, linked concepts, a compact skeleton (first non-empty rows) of one sheet, and hints from the old
    ingestion pipeline (which hand-written caster was meant to read this sheet, and its documentation).

    Args:
        file: Workbook file name as returned by find_sheets.
        sheet: Sheet name.
    """
    rows = read_graph(
        "MATCH (x:Sheet {key: $key}) OPTIONAL MATCH (x)-[m:MENTIONS]->(c:Concept) "
        "WITH x, collect({concept: c.id, where: m.where, n: m.n}) AS mentions "
        "RETURN x {.*} AS sheet, mentions, "
        "[(x)-[r:ROUTED_TO]->(k:Caster) | {caster: k.code, skip: r.skip, doc: left(k.doc, 1500)}][..2] AS old_pipeline_hints",
        key=f"{file}::{sheet}",
    )
    assert rows, f"unknown sheet {file}::{sheet}"
    wb = openpyxl.load_workbook(EXCEL_DIR / file, read_only=True)
    skeleton = []
    for i, row in enumerate(wb[sheet].iter_rows(max_col=16, values_only=True), start=1):
        if any(v is not None for v in row):
            skeleton.append(f"r{i}: " + " | ".join(cell_text(v) for v in row))
        if len(skeleton) == 25:
            break
    wb.close()
    return json.dumps({**rows[0], "skeleton_first_16_cols": skeleton}, ensure_ascii=False, default=str)


@beta_tool
def read_range(file: str, sheet: str, cell_range: str) -> str:
    """Read raw cell values of a rectangular range (max 600 cells). Formulas are returned as text.

    Args:
        file: Workbook file name.
        sheet: Sheet name.
        cell_range: A1-style range, e.g. "A5:L30".
    """
    min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    assert (max_col - min_col + 1) * (max_row - min_row + 1) <= MAX_CELLS, f"range too large, max {MAX_CELLS} cells"
    wb = openpyxl.load_workbook(EXCEL_DIR / file, read_only=True)
    rows = wb[sheet].iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True)
    out = "\n".join(f"{get_column_letter(min_col)}{r}: " + " | ".join(cell_text(v) for v in row) for r, row in enumerate(rows, start=min_row))
    wb.close()
    return out


@beta_tool
def propose_extraction_spec(spec_yaml: str) -> str:
    """Propose how to turn a sheet into long rows (one value per row). The spec is executed immediately and checked
    (units, orientation, total rows/columns, region subtotals). Failed checks come back to you: fix the spec and call again.
    Passing specs go to human review.

    Args:
        spec_yaml: YAML with keys file, sheet, table_range (A1, including header rows), header_rows (absolute row numbers),
            label_columns (letters, e.g. [A]), row_dimensions (one name per label column, e.g. [importer]),
            column_dimension (name for the header label, e.g. exporter or period), drop_rows (absolute rows, e.g. unlabeled totals),
            drop_columns (letters, e.g. a Total column), skip_rows_matching (substrings, e.g. [total]),
            skip_label_kinds (e.g. [region] to drop region subtotal rows mixed with countries, else []),
            operators (list of {op, args}: ffill {target: header|labels} for merged/blank-repeated cells;
                subtitle {dimension, rows: {row_number: value}} when one sheet stacks sections, e.g. exports then imports; stack last),
            value_unit (unit from the ingestion referential, e.g. kiloton, kiloton_p2o5, million_ton, usd_per_ton, usd_per_short_ton, percent; aliases like kt, $/t accepted), fixed (dict, e.g. {product: dap, year: 2024}), notes.
    """
    spec = yaml.safe_load(spec_yaml)
    validate(spec)
    rows, ctx = execute(spec)
    results = check(spec, rows, ctx)
    failed = [r for r in results if not r["ok"]]
    status = "rejected" if failed else "proposed"
    folder = SPECS / status
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = f"{Path(spec['file']).stem}__{spec['sheet']}__{stamp}".replace(" ", "_").replace("/", "_")
    (folder / f"{name}.yaml").write_text(spec_yaml, encoding="utf-8")
    (folder / f"{name}.checks.json").write_text(json.dumps({"checks": results, "rows": len(rows), "sample": rows[:20]}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    report = {"status": status, "rows_extracted": len(rows), "checks": results, "sample_rows": rows[:5]}
    if failed:
        report["next"] = "Fix the failed checks (re-read the sheet with read_range if needed) and call propose_extraction_spec again."
    return json.dumps(report, ensure_ascii=False, default=str)
