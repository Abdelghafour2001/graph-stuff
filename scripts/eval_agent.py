"""Ask the agent to write an extraction spec for each target sheet; record attempts and final check status in data/eval_results.json."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
import agent  # noqa: E402
import yaml  # noqa: E402
from diff_vs_db import compare  # noqa: E402

TARGETS = [
    ("Argus Processed Phosphates Analytics - 4Q 2025.xlsx", "DAP TM 2024"),
    ("Argus Monthly Phosphates Outlook - Sep 2025.xlsx", "DAP Trade Balance"),
    ("Argus Monthly Phosphates Outlook - Sep 2025.xlsx", "Price Forecast"),
    ("Argus Monthly Phosphates Outlook - Sep 2025.xlsx", "Phosphoric Acid Trade Balance"),
    ("Argus Monthly Ammonia Outlook - October 2025.xlsx", "Ammonia Production Costs"),
    ("Argus Monthly Ammonia Outlook - October 2025.xlsx", "New Capacity"),
    ("phosphate-rock-market-outlook-march-2025-trade-matrices.xlsx", "Imports"),
    ("PhosphateOutlook_2025M10_Datafile_Costs_Prices.xlsx", "Yearly Price Forecast"),
]
PROMPT = "Propose an extraction spec for sheet '{sheet}' in workbook '{file}'. Inspect the layout first. If checks fail, fix and propose again until they pass (max 4 attempts). When done, summarise the spec and any remaining doubts in 3 lines."


def attempts_since(file: str, sheet: str, since: float) -> list[dict]:
    stem = f"{Path(file).stem}__{sheet}__".replace(" ", "_").replace("/", "_")
    found = []
    for status in ("proposed", "rejected"):
        for p in (ROOT / "specs" / status).glob(f"{stem}*.checks.json"):
            if p.stat().st_mtime >= since:
                checks = json.loads(p.read_text(encoding="utf-8"))
                found.append({"status": status, "at": p.stat().st_mtime, "rows": checks["rows"],
                              "failed": [c["check"] for c in checks["checks"] if not c["ok"]], "file": p.name})
    return sorted(found, key=lambda a: a["at"])


def main() -> None:
    results = []
    for file, sheet in TARGETS:
        print(f"\n### {file} :: {sheet}", flush=True)
        start = time.time()
        try:
            answer, _ = agent.ask([], PROMPT.format(file=file, sheet=sheet))
        except Exception as e:  # keep evaluating the other sheets
            answer = f"AGENT ERROR: {e}"
        tries = attempts_since(file, sheet, start)
        final = tries[-1] if tries else None
        diff = compare(yaml.safe_load((ROOT / "specs" / final["status"] / final["file"].replace(".checks.json", ".yaml")).read_text(encoding="utf-8")))             if final and final["status"] == "proposed" else {}
        results.append({"file": file, "sheet": sheet, "attempts": len(tries), "final_status": final["status"] if final else "no_spec", "db_diff": diff.get("verdict", ""),
                        "final_failed": final["failed"] if final else [], "rows": final["rows"] if final else 0,
                        "history": tries, "answer": answer, "seconds": round(time.time() - start)})
        print(f"-> attempts={len(tries)} final={results[-1]['final_status']} failed={results[-1]['final_failed']} db={results[-1]['db_diff']}", flush=True)
    out = ROOT / "data" / "eval_results.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    passed = sum(r["final_status"] == "proposed" for r in results)
    first_try = sum(r["attempts"] >= 1 and r["history"][0]["status"] == "proposed" for r in results)
    print(f"\nPASSED {passed}/{len(results)} (first try {first_try}); written {out}")


if __name__ == "__main__":
    main()
