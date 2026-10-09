"""Differential test: compare a spec's extracted values with what the old pipeline stored in market_knowledge_data.metrics for the same sheet.

Values are compared as rounded multisets (dimensions differ between the two models, values should not).
Run as a script to compare the latest spec of every sheet in specs/proposed and specs/approved; writes data/diff_results.json.
"""
import json
import os
import re
from collections import Counter
from pathlib import Path

import psycopg
import yaml

from spec_executor import execute, validate

ROOT = Path(__file__).parent.parent
SQL = """
select m.value from market_knowledge_data.metrics m
join market_knowledge_data.document_sheets s using (sheet_id)
join market_knowledge_data.documents d on d.document_id = s.document_id
where regexp_replace(lower(d.document_name), '[^a-z0-9]', '', 'g') = %s and lower(trim(s.sheet_name)) = %s
"""


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", Path(name).stem.lower())


def as_number(v) -> float | None:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def compare(spec: dict) -> dict:
    rows, _ = execute(spec)
    ours = Counter(round(r["value"], 2) for r in rows if r["value"] != 0)
    with psycopg.connect(os.environ["MARKET_INTEL_DSN"]) as pg:
        raw = [v for (v,) in pg.execute(SQL, (key(spec["file"]), spec["sheet"].strip().lower())).fetchall()]
    db_values = [as_number(v) for v in raw]
    theirs = Counter(v for v in db_values if v not in (None, 0))
    common = sum((ours & theirs).values())
    return {
        "file": spec["file"], "sheet": spec["sheet"], "ours_nonzero": sum(ours.values()), "db_nonzero": sum(theirs.values()),
        "db_unparseable": sum(1 for v, n in zip(raw, db_values) if n is None and v != "nan"),
        "ours_found_in_db_pct": round(100 * common / sum(ours.values()), 1) if ours else None,
        "db_found_in_ours_pct": round(100 * common / sum(theirs.values()), 1) if theirs else None,
        "verdict": "no DB rows for this sheet (old pipeline never extracted it)" if not theirs else
                   "agree" if common >= 0.9 * min(sum(ours.values()), sum(theirs.values())) else "disagree: inspect",
    }


def main() -> None:
    latest = {}
    for status in ("proposed", "approved"):
        for p in sorted((ROOT / "specs" / status).glob("*.yaml"), key=lambda p: p.stat().st_mtime):
            spec = yaml.safe_load(p.read_text(encoding="utf-8"))
            latest[(spec["file"], spec["sheet"])] = (status, p.name, spec)
    results = []
    for status, name, spec in latest.values():
        try:
            validate(spec)
        except AssertionError as e:  # specs written under an older schema are reported, not compared
            results.append({"status": status, "spec": name, "file": spec["file"], "sheet": spec["sheet"], "verdict": f"invalid under current schema: {e}"[:200]})
            continue
        results.append({"status": status, "spec": name, **compare(spec)})
        print(json.dumps(results[-1], ensure_ascii=False))
    (ROOT / "data" / "diff_results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
