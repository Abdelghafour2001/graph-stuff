"""Replay a YAML extraction spec on a sheet (deterministic, no LLM) and run the checks that act as the Reflector.

Spec keys (all required):
  file, sheet, table_range (A1, includes header rows), header_rows (absolute row numbers),
  label_columns (letters holding row labels), row_dimensions (one name per label column),
  column_dimension (name for the combined header label), drop_rows, drop_columns, skip_rows_matching,
  skip_label_kinds (concept kinds, e.g. [region]: rows whose most specific label is a region are subtotals; resolved via the graph),
  operators (list of {op, args}; supported: ffill {target: header|labels},
    subtitle {dimension: name, rows: {row_number: value}} for stacked sections, e.g. {dimension: flow, rows: {6: export, 26: import}}, stack), value_unit (referential unit or alias), fixed (dict), notes.
"""
import os
import re
from pathlib import Path

import openpyxl
import yaml
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

from graph import driver

EXCEL_DIR = Path(os.environ["EXCEL_DIR"])
KEYS = ("file", "sheet", "table_range", "header_rows", "label_columns", "row_dimensions", "column_dimension",
        "drop_rows", "drop_columns", "skip_rows_matching", "skip_label_kinds", "operators", "value_unit", "fixed", "notes")
SUPPORTED_OPS = {"ffill", "subtitle", "stack"}
AUTO_TABLES_OPS = {"ffill", "stack", "wide_to_long", "transpose", "pivot", "explode", "subtitle"}
REFERENTIAL = yaml.safe_load((Path(__file__).parent.parent / "knowledge" / "market_intel_referential.yaml").read_text(encoding="utf-8"))
UNITS = set(REFERENTIAL["units"])
UNIT_ALIASES = {**{u: u for u in UNITS}, **{u.replace("_", " "): u for u in UNITS}, **{str(a).lower(): u for a, u in REFERENTIAL["unit_aliases"].items()}}
MORE_SPECIFIC = {  # if one of these is evidenced, the generic unit is probably wrong ("000 tonnes" is kiloton, not metric_ton)
    "metric_ton": ["kiloton_p2o5", "kiloton", "million_ton"],
    "kiloton": ["kiloton_p2o5"],
    "usd_per_ton": ["usd_per_ton_of_p2o5", "usd_per_short_ton"],
}
TOLERANCE = 0.01


def validate(spec: dict) -> None:
    missing = [k for k in KEYS if k not in spec]
    assert not missing, f"missing keys {missing}"
    ops = [o["op"] for o in spec["operators"]]
    assert all(o in AUTO_TABLES_OPS for o in ops), f"unknown operators {ops}, allowed {sorted(AUTO_TABLES_OPS)}"
    assert all(o in SUPPORTED_OPS for o in ops), f"operators {ops}: only {sorted(SUPPORTED_OPS)} are executable today"
    assert ops and ops[-1] == "stack", "the last operator must be stack (one value per output row)"
    assert len(spec["label_columns"]) == len(spec["row_dimensions"]), "one row_dimension per label column"
    assert canonical_unit(spec["value_unit"]) in UNITS, f"value_unit '{spec['value_unit']}' is not a referential unit or alias; e.g. {sorted(UNITS)[:12]}"
    min_col, min_row, max_col, max_row = range_boundaries(spec["table_range"])
    for key in ("header_rows", "drop_rows"):
        assert isinstance(spec[key], list), f"{key} must be a list of row numbers"
        outside = [r for r in spec[key] if not min_row <= r <= max_row]
        assert not outside, f"{key} {outside} are outside table_range rows {min_row}-{max_row}"
    for o in spec["operators"]:
        if o["op"] == "subtitle":
            assert set(o["args"]) == {"dimension", "rows"}, "subtitle args must be {dimension, rows: {row_number: value}}"
            outside = [r for r in o["args"]["rows"] if not isinstance(r, int) or not min_row <= r <= max_row]
            assert not outside, f"subtitle rows {outside} must be row numbers inside table_range"
    for key in ("label_columns", "drop_columns"):
        assert isinstance(spec[key], list), f"{key} must be a list of column letters"
        outside = [c for c in spec[key] if not min_col <= column_index_from_string(c) <= max_col]
        assert not outside, f"{key} {outside} are outside table_range columns"


def canonical_unit(unit: str) -> str:
    u = unit.strip().lower()
    return UNIT_ALIASES.get(u) or UNIT_ALIASES.get(u.replace("_", " "), u)


def evidenced_units(text: str) -> set[str]:
    """Referential units whose name or alias appears as a standalone token in the text."""
    return {unit for alias, unit in UNIT_ALIASES.items() if alias and re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text)}


def load_grid(spec: dict) -> tuple[dict, list[str], dict]:
    """Cells of the table range as {(row, col_letter): value}, plus text found above the table (preamble)."""
    min_col, min_row, max_col, max_row = range_boundaries(spec["table_range"])
    wb = openpyxl.load_workbook(EXCEL_DIR / spec["file"], read_only=True)
    ws = wb[spec["sheet"]]
    grid = {}
    for r, row in enumerate(ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True), start=min_row):
        for c, v in enumerate(row, start=min_col):
            grid[(r, get_column_letter(c))] = v
    preamble = [str(v) for row in ws.iter_rows(min_row=max(1, min_row - 10), max_row=min_row - 1, values_only=True) for v in row if isinstance(v, str)]
    below = [v for row in ws.iter_rows(min_row=max_row + 1, max_row=max_row + 3, min_col=min_col, max_col=max_col, values_only=True) for v in row if isinstance(v, (int, float))]
    right = [v for row in ws.iter_rows(min_row=min_row, max_row=min(max_row, min_row + 20), min_col=max_col + 1, max_col=max_col + 2, values_only=True) for v in row if isinstance(v, (int, float))]
    wb.close()
    return grid, preamble, {"below": len(below), "right": len(right)}


def execute(spec: dict) -> tuple[list[dict], dict]:
    grid, preamble, outside = load_grid(spec)
    min_col, min_row, max_col, max_row = range_boundaries(spec["table_range"])
    cols = [get_column_letter(c) for c in range(min_col, max_col + 1)]
    ffill = {o["args"]["target"] for o in spec["operators"] if o["op"] == "ffill"}

    headers = {c: [] for c in cols}
    for r in spec["header_rows"]:
        last = None
        for c in cols:
            v = grid[(r, c)]
            last = v if v not in (None, "") else (last if "header" in ffill else None)
            if last not in (None, ""):
                headers[c].append(str(last).strip())
    candidate_cols = [c for c in cols if c not in spec["label_columns"] and headers[c]]
    value_cols = [c for c in candidate_cols if c not in spec["drop_columns"]]
    numbers = lambda r: {c: float(grid[(r, c)]) for c in candidate_cols if isinstance(grid[(r, c)], (int, float))}

    leaf_col = spec["label_columns"][-1]
    leaf_labels = {str(grid[(r, leaf_col)]).strip() for r in range(min_row, max_row + 1) if grid[(r, leaf_col)] not in (None, "")}
    kinds = label_kinds(sorted(leaf_labels)) if spec["skip_label_kinds"] else {}
    subtitle = next((o["args"] for o in spec["operators"] if o["op"] == "subtitle"), None)
    section = None
    section_of = {}
    rows, kept, subtotal_rows, non_numeric = [], [], [], 0
    last_labels = [None] * len(spec["label_columns"])
    skip = [s.lower() for s in spec["skip_rows_matching"]]
    for r in range(min_row, max_row + 1):
        if subtitle and r in subtitle["rows"]:
            section = subtitle["rows"][r]
        section_of[r] = section
        if r in spec["header_rows"] or r in spec["drop_rows"]:
            continue
        labels = []
        for i, c in enumerate(spec["label_columns"]):
            v = grid[(r, c)]
            v = str(v).strip() if v not in (None, "") else (last_labels[i] if "labels" in ffill else "")
            last_labels[i] = v or last_labels[i]
            labels.append(v)
        if any(s in lab.lower() for s in skip for lab in labels):
            continue
        if set(kinds.get(labels[-1].lower(), [])) & set(spec["skip_label_kinds"]) and "country" not in kinds.get(labels[-1].lower(), []):
            subtotal_rows.append((r, numbers(r)))
            continue
        values = {}
        for c in value_cols:
            v = grid[(r, c)]
            if v in (None, ""):
                continue
            if isinstance(v, (int, float)):
                values[c] = float(v)
            else:
                non_numeric += 1
        if not values:
            continue
        kept.append((r, labels, values, numbers(r)))
        sections = {subtitle["dimension"]: section} if subtitle else {}
        for c, v in values.items():
            rows.append({**spec["fixed"], **sections, **dict(zip(spec["row_dimensions"], labels)),
                         spec["column_dimension"]: " | ".join(headers[c]), "value": v, "unit": spec["value_unit"], "cell": f"{c}{r}"})
    dropped_rows = {r: numbers(r) for r in spec["drop_rows"] if r not in spec["header_rows"]}
    dropped_labels = {r: " ".join(str(grid[(r, c)] or "") for c in spec["label_columns"]).lower() for r in dropped_rows}
    context = {"outside": outside, "grid": grid, "preamble": preamble, "headers": headers, "value_cols": value_cols,
               "candidate_cols": candidate_cols, "kept": kept, "section_of": section_of, "subtotal_rows": subtotal_rows, "dropped_rows": dropped_rows, "dropped_labels": dropped_labels, "non_numeric": non_numeric}
    return rows, context


def label_kinds(labels: list[str]) -> dict[str, list[str]]:
    """Concept kinds (country, region, ...) each label resolves to in the graph, by exact term match."""
    with driver.session() as s:
        rows = s.run(
            "UNWIND $labels AS l MATCH (t:Term)-[:REFERS_TO]->(c:Concept) WHERE toLower(t.text) = l "
            "RETURN l AS label, collect(DISTINCT c.kind) AS kinds",
            labels=[lab.lower() for lab in labels],
        ).data()
    return {r["label"]: r["kinds"] for r in rows}


def near(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b), 1.0)


def check(spec: dict, rows: list[dict], ctx: dict) -> list[dict]:
    results = []
    add = lambda name, ok, detail: results.append({"check": name, "ok": ok, "detail": detail})

    numeric = len(rows)
    add("values_parse", numeric > 0 and ctx["non_numeric"] <= 0.1 * (numeric + ctx["non_numeric"]),
        f"{numeric} numeric values, {ctx['non_numeric']} non-numeric cells in value columns")

    header_cells = [ctx["grid"][(r, c)] for r in spec["header_rows"] for c in ctx["value_cols"] if ctx["grid"][(r, c)] not in (None, "")]
    numeric_headers = sum(isinstance(v, (int, float)) and not 1900 <= v <= 2100 for v in header_cells)
    add("header_is_text", numeric_headers <= 0.2 * max(len(header_cells), 1),
        f"{numeric_headers} of {len(header_cells)} header cells are numbers (years excepted): header_rows probably point at data rows")

    empty_labels = sum(1 for _, labs, _, _ in ctx["kept"] if not labs[-1])
    add("labels_present", empty_labels <= 0.2 * max(len(ctx["kept"]), 1),
        f"{empty_labels} of {len(ctx['kept'])} kept rows have an empty label in {spec['label_columns'][-1]}: wrong label column?")

    subtitle = next((o["args"] for o in spec["operators"] if o["op"] == "subtitle"), None)
    if subtitle:
        orphans = sorted({row["cell"] for row in rows if row[subtitle["dimension"]] is None})[:5]
        add("subtitle_covers_rows", not orphans, f"values before the first subtitle row get no {subtitle['dimension']}: {orphans}")

    add("covers_whole_table", not ctx["outside"]["below"] and not ctx["outside"]["right"],
        f"numeric cells just outside table_range: {ctx['outside']['below']} in the 3 rows below, {ctx['outside']['right']} in the 2 columns to the right. Extend the range or confirm a separate table starts there")

    text = " ".join([*ctx["preamble"], *(" ".join(h) for h in ctx["headers"].values())]).lower()
    unit = canonical_unit(spec["value_unit"])
    evidenced = evidenced_units(text)
    better = [u for u in MORE_SPECIFIC.get(unit, []) if u in evidenced]
    add("unit_evidence", unit in evidenced and not better,
        f"value_unit '{spec['value_unit']}' = {unit}; units evidenced in preamble/header text: {sorted(evidenced)}; more specific evidenced: {better}")

    corner = ctx["grid"].get((spec["header_rows"][-1], spec["label_columns"][0]))
    if isinstance(corner, str) and "\\" in corner:
        row_word, col_word = [p.strip().lower() for p in corner.split("\\", 1)]
        ok = row_word[:5] in spec["row_dimensions"][0].lower() and col_word[:5] in spec["column_dimension"].lower()
        add("corner_orientation", ok, f"corner cell '{corner}' means rows={row_word}, columns={col_word}; spec has rows={spec['row_dimensions'][0]}, columns={spec['column_dimension']}")

    # Checksums use every numeric column of the table, dropped ones included, so dropping a real column cannot hide a total.
    # Totals are compared within their section (subtitle), so a section total matches the sum of that section only.
    kept, value_cols, all_cols, section_of = ctx["kept"], ctx["value_cols"], ctx["candidate_cols"], ctx["section_of"]
    groups = {}
    for row in kept:
        groups.setdefault(section_of[row[0]], []).append(row)
    sums = {sec: {c: sum(full.get(c, 0.0) for *_, full in g) for c in all_cols} for sec, g in groups.items()}
    is_total_row = lambda r, vals: len(groups[section_of[r]]) > 2 and sum(1 for v in vals.values() if abs(v) > 0) >= 2         and all(near(vals.get(c, 0.0), sums[section_of[r]][c] - vals.get(c, 0.0)) for c in value_cols)
    is_total_col = lambda c: len(all_cols) > 2 and sum(1 for *_, full in kept if abs(full.get(c, 0.0)) > 0) >= 2 and all(near(full.get(c, 0.0), sum(full.values()) - full.get(c, 0.0)) for *_, full in kept)
    total_rows = [r for r, _, _, full in kept if is_total_row(r, full)]
    add("no_total_rows", not total_rows, f"rows equal to the sum of the other rows of their section (drop them): {total_rows}")
    total_cols = [c for c in value_cols if is_total_col(c)]
    add("no_total_columns", not total_cols, f"columns equal to the sum of the other columns (drop them): {total_cols}")

    bad_cols = [c for c in spec["drop_columns"] if c in all_cols and any(abs(full.get(c, 0.0)) > 0 for *_, full in kept) and not is_total_col(c)]
    add("dropped_columns_are_totals_or_empty", not bad_cols, f"dropped columns that hold real data (not a total, not empty): {bad_cols}")
    # A dropped row is justified if it is empty, explicitly labelled total, or equals the sum of its section's kept rows or subtotal rows.
    # Unlabeled rows (e.g. a blank-label total row under the header) must pass a checksum.
    subtotal_sums = {}
    for r, vals in ctx["subtotal_rows"]:
        for c in all_cols:
            subtotal_sums.setdefault(section_of[r], {}).setdefault(c, 0.0)
            subtotal_sums[section_of[r]][c] += vals.get(c, 0.0)
    matches = lambda vals, ref: all(near(vals.get(c, 0.0), ref.get(c, 0.0)) for c in value_cols)
    bad_rows = [r for r, vals in ctx["dropped_rows"].items()
                if vals and "total" not in ctx["dropped_labels"][r]
                and not matches(vals, sums.get(section_of[r], {})) and not matches(vals, subtotal_sums.get(section_of[r], {}))]
    add("dropped_rows_are_totals_or_empty", not bad_rows, f"dropped rows that are not empty, not labelled total, and match no checksum of their section: {bad_rows}")

    labels = sorted({labs[-1].lower() for _, labs, _, _ in kept if labs[-1]})
    kinds = label_kinds(labels)
    regions = [lab for lab, k in kinds.items() if k == ["region"]]
    countries = [lab for lab, k in kinds.items() if "country" in k]
    totals = [lab for lab in labels if "total" in lab]
    mixed = regions if countries else []
    add("no_subtotal_labels", not (mixed or totals),
        f"most specific label column mixes regions (subtotals) with countries: {mixed[:10]}; rows labelled total: {totals[:10]}. Use skip_label_kinds: [region] and/or skip_rows_matching")
    return results
