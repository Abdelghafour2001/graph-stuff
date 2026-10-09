"""Build the workbook graph: (:Workbook)-[:HAS_SHEET]->(:Sheet)-[:MENTIONS]->(:Concept), from data/excel_profile.json.

Sheet roles are deterministic heuristics. Sheet descriptions come from the workbook's own Contents/Index sheet when it has one.
"""
import json
import os
import re
from collections import Counter
from pathlib import Path

import openpyxl
from neo4j import GraphDatabase

PROFILE = Path(__file__).parent.parent / "data" / "excel_profile.json"
CONTENTS_WORDS = ("content", "index", "home", "readme", "about", "notes", "disclaimer", "legal", "info", "methodolog", "definition", "glossary")
DASHBOARD_WORDS = ("dashboard", "viewer", "pivot", "chart", "graph")


def sheet_role(s: dict) -> str:
    name = s["sheet"].lower()
    if any(w in name for w in CONTENTS_WORDS):
        return "contents"
    if any(w in name for w in DASHBOARD_WORDS):
        return "dashboard"
    if s["header_row"] is None:
        return "dashboard" if s["formulas"] else "other"
    return "data"


def load_matchers(session) -> list[tuple[re.Pattern, str]]:
    rows = session.run("MATCH (t:Term)-[:REFERS_TO]->(c:Concept) RETURN t.text AS text, c.id AS id").data()
    return [
        (re.compile(r"(?<![A-Za-z0-9])" + re.escape(r["text"]) + r"(?![A-Za-z0-9])", re.IGNORECASE), r["id"])
        for r in rows
        if len(r["text"]) >= 3
    ]


def mentions(texts: list[str], matchers: list[tuple[re.Pattern, str]]) -> Counter:
    joined = "\n".join(texts)
    return Counter({cid: len(p.findall(joined)) for p, cid in matchers if p.search(joined)})


def contents_descriptions(path: Path, contents_sheets: list[str], sheet_names: list[str]) -> dict[str, str]:
    """Rows of a Contents sheet that name another sheet become that sheet's description."""
    by_lower = {n.lower().strip(): n for n in sheet_names}
    wb = openpyxl.load_workbook(path, read_only=True)
    out = {}
    for cs in contents_sheets:
        for _, row in zip(range(400), wb[cs].iter_rows(values_only=True)):
            texts = [str(v).strip() for v in row if isinstance(v, str) and v.strip()]
            target = next((by_lower[t.lower()] for t in texts if t.lower() in by_lower and by_lower[t.lower()] != cs), None)
            if target:
                out[target] = " | ".join(t for t in texts if by_lower.get(t.lower()) != target)[:500]
    wb.close()
    return out


def main() -> None:
    workbooks = json.loads(PROFILE.read_text(encoding="utf-8"))
    excel_dir = Path(os.environ["EXCEL_DIR"])
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        s.run("CREATE CONSTRAINT sheet_key IF NOT EXISTS FOR (x:Sheet) REQUIRE x.key IS UNIQUE")
        s.run("MATCH (n) WHERE n:Workbook OR n:Sheet DETACH DELETE n")
        matchers = load_matchers(s)
        for wb in workbooks:
            sheets = wb["sheets"]
            for sh in sheets:
                sh["role"] = sheet_role(sh)
            descriptions = contents_descriptions(excel_dir / wb["file"], [sh["sheet"] for sh in sheets if sh["role"] == "contents"], [sh["sheet"] for sh in sheets])
            s.run("CREATE (:Workbook {file: $file, size_mb: $size})", file=wb["file"], size=wb["size_mb"])
            for sh in sheets:
                found = {
                    "header": mentions(sh["header_cells"], matchers),
                    "rows": mentions(sh["row_labels"], matchers),
                    "context": mentions([sh["sheet"], sh["title"], descriptions.get(sh["sheet"], ""), *sh["preamble"]], matchers),
                }
                s.run(
                    "MATCH (w:Workbook {file: $file}) "
                    "CREATE (w)-[:HAS_SHEET]->(x:Sheet {key: $file + '::' + $name, file: $file, name: $name, role: $role, description: $desc, "
                    "rows: $rows, cols: $cols, header_row: $header_row, header_depth: $header_depth, time_in_columns: $time_cols, "
                    "blocks: $blocks, formulas: $formulas, formula_total_rows: $totals, merged: $merged, hidden: $hidden, header_cells: $header_cells}) "
                    "WITH x UNWIND $links AS l MATCH (c:Concept {id: l.id}) CREATE (x)-[:MENTIONS {where: l.where, n: l.n}]->(c)",
                    file=wb["file"], name=sh["sheet"], role=sh["role"], desc=descriptions.get(sh["sheet"], ""),
                    rows=sh["rows"], cols=sh["cols"], header_row=sh["header_row"], header_depth=sh["header_depth"],
                    time_cols=sh["time_in_columns"], blocks=sh["blocks_in_first_rows"], formulas=sh["formulas"],
                    totals=sh["formula_total_rows"], merged=sh["merged_ranges"], hidden=sh["hidden"], header_cells=sh["header_cells"],
                    links=[{"id": cid, "where": where, "n": n} for where, counts in found.items() for cid, n in counts.items()],
                )
            print(f"{wb['file']}: {len(sheets)} sheets, {len(descriptions)} described by Contents")
    driver.close()


if __name__ == "__main__":
    main()
