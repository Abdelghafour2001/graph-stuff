"""Layout memory from the old ingestion pipeline: route each Sheet to the caster that was meant to read it, and attach that caster's doc.

Sources (snapshots in knowledge/ingestion_repo/): sheets_extractors.yaml (routing rules) and caster_docs/*.md (per-family READMEs).
Creates (:Caster {code, doc})<-[:ROUTED_TO {rule, skip}]-(:Sheet). Run after workbook_graph.py.
"""
import re
from pathlib import Path

import yaml

from graph import driver

REPO = Path(__file__).parent.parent / "knowledge" / "ingestion_repo"
SKIP_DOCS = {"INDEX.md", "COVERAGE_VERIFICATION.md"}
DOC_CHARS = 3000


def caster_doc(code: str, docs: dict[str, list[str]]) -> str:
    """The README section whose heading names the caster file, else the start of the README that mentions it."""
    for lines in docs.values():
        start = next((i for i, line in enumerate(lines) if line.startswith("#") and code in line), None)
        if start is None:
            continue
        level = len(lines[start]) - len(lines[start].lstrip("#"))
        end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("#") and len(lines[j]) - len(lines[j].lstrip("#")) <= level), len(lines))
        return "\n".join(lines[start:end])[:DOC_CHARS]
    mentioning = [lines for lines in docs.values() if any(code in line for line in lines)]
    return "\n".join(mentioning[0])[:DOC_CHARS] if mentioning else ""


def routes(file: str, sheet: str, rules: list[dict]) -> list[dict]:
    """All rules matching this sheet, following the old loader: exact sheet name or regex, plus optional file_regex."""
    out = []
    for rule in rules:
        rule_file_regex = rule.get("file_regex")
        for kind, items in (rule["matches"] or {}).items():
            for item in items:
                file_regex = item.get("file_regex") or rule_file_regex
                if file_regex and not re.search(file_regex, file, re.IGNORECASE):
                    continue
                hit = item["value"].strip().lower() == sheet.strip().lower() if kind == "exact" else re.match(item["pattern"], sheet)
                if hit:
                    out.append({"code": rule["extractor_code"], "rule": rule["name"], "skip": bool((item.get("params") or {}).get("skip"))})
    return out


def main() -> None:
    rules = yaml.safe_load((REPO / "sheets_extractors.yaml").read_text(encoding="utf-8"))["extractors"]
    docs = {p.name: p.read_text(encoding="utf-8").splitlines() for p in sorted((REPO / "caster_docs").glob("*.md")) if p.name not in SKIP_DOCS}
    codes = sorted({r["extractor_code"] for r in rules})
    with driver.session() as s:
        s.run("MATCH (c:Caster) DETACH DELETE c")
        s.run("UNWIND $rows AS r CREATE (:Caster {code: r.code, doc: r.doc})", rows=[{"code": c, "doc": caster_doc(c, docs)} for c in codes])
        sheets = s.run("MATCH (x:Sheet) RETURN x.file AS file, x.name AS sheet").data()
        found = [{"key": f"{x['file']}::{x['sheet']}", **r} for x in sheets for r in routes(x["file"], x["sheet"], rules)]
        links = list({(l["key"], l["code"]): l for l in found}.values())  # one edge per sheet and caster
        s.run(
            "UNWIND $links AS l MATCH (x:Sheet {key: l.key}), (c:Caster {code: l.code}) "
            "CREATE (x)-[:ROUTED_TO {rule: l.rule, skip: l.skip}]->(c)",
            links=links,
        )
    documented = sum(1 for c in codes if caster_doc(c, docs))
    print(f"{len(codes)} casters ({documented} with docs), {len(links)} sheet routes, {len({l['key'] for l in links})} sheets routed")


if __name__ == "__main__":
    main()
