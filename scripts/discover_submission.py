"""Read a branch submission that follows no template, recover its model, and mark it to market (docs/10-pnl-agent.md).

  python scripts/discover_submission.py <workbook.xlsx> --market-dir <folder with provider price files> [--target "Marge brute"]

Steps: structure discovery (formulas, identities, meaning, questions) -> P&L model of the main formula sheet ->
sensitivities of the target line -> each price assumption replaced by its market reference (actual months only) ->
order-independent bridge of the change by driver. Writes data/submissions/<file>.json. No LLM is called.
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
import discovery  # noqa: E402
import market  # noqa: E402
import pnl  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook", type=Path)
    ap.add_argument("--market-dir", type=Path, default=None)
    ap.add_argument("--target", default="marge", help="words of the target line (default: the margin line)")
    args = ap.parse_args()

    d = discovery.discover(args.workbook)
    print(f"# {d['file']}")
    for name, s in d["sheets"].items():
        roles = [r["role"] for r in s["rows"]]
        print(f"\n## {name}: {len(roles)} lines, {roles.count('input')} inputs, {len(roles) - roles.count('input')} computed, "
              f"periods {s['periods'][0][:7]}..{s['periods'][-1][:7]}")
        for r in s["rows"]:
            c = r["concept"]
            what = f"{c['concept']} ({c['decision']})" if c["concept"] else "?"
            print(f"  {r['role']:<19} {r['driver']:<17} {what:<26} {r['label']}" + (f"  =  {r['formula']}" if r["formula"] else ""))
    print("\n## Questions for the branch")
    for q in d["questions"]:
        print(f"  - {q}")

    # model of the formula sheet with the most computed lines (the branch's own model)
    name, sheet = max(d["sheets"].items(), key=lambda kv: sum(r["role"] == "computed" for r in kv[1]["rows"]))
    model = pnl.from_discovery(sheet)
    target = next(r["label"] for r in sheet["rows"] if args.target.lower() in r["label"].lower())
    plan = model.evaluate()
    months = [p[:7] for p in sheet["periods"]]
    print(f"\n## P&L model of '{name}' (computed by the engine from the branch's own formulas)")
    print(f"  {target}: " + ", ".join(f"{m} {v:.1f}" for m, v in zip(months, plan[target])) + f"  | total {model.total(target):.1f}")
    for r in sheet["rows"]:
        for col in r["overrides"]:
            i = ord(col) - ord("B")
            typed = r["values"][i] if i < len(r["values"]) else None
            if typed is not None and r["label"] in plan:
                print(f"  override: {r['label']} {months[i]} typed {typed:.2f} vs formula {plan[r['label']][i]:.2f} "
                      f"({typed - plan[r['label']][i]:+.2f}); the engine uses the formula and reports the gap")

    print(f"\n## Sensitivities of {target} (total over {len(months)} months)")
    for s in pnl.sensitivities(model, target)[:8]:
        print(f"  {s['input']:<46} +1%: {s['per_1pct']:+8.2f}   +1 unit: {s['per_unit']:+9.4f}")

    if args.market_dir:
        refs, used = {}, []
        for r in sheet["rows"]:
            c = r["concept"]
            if r["role"] == "input" and r["driver"] == "price" and c["concept"]:
                found = market.reference(c["concept"], "price", args.market_dir)
                if found:
                    series, desc = found
                    refs[r["label"]] = [series.get(m) for m in months]
                    used.append((r["label"], desc, refs[r["label"]]))
                else:
                    print(f"  no market reference for {r['label']} ({c['concept']}): kept as submitted")
        market_inputs = pnl.mark_to_market(model, refs)
        print("\n## Marked to market (provider actuals in place of the branch's price assumptions)")
        for label, desc, series in used:
            print(f"  {label}: plan {model.inputs[label]} -> market {[round(v, 1) if v is not None else None for v in series]}  [{desc}]")
        bridge = pnl.shapley(model, target, model.inputs, market_inputs)
        print(f"\n  {target}: plan {model.total(target):.1f} -> market-implied {model.total(target, market_inputs):.1f} "
              f"({bridge['total_change']:+.1f})")
        for k, v in bridge["by_input"].items():
            print(f"    {v:+8.1f}  {k}")
        print(f"    {bridge['unexplained']:+8.3f}  unexplained")
    else:
        bridge, used = None, []

    out = ROOT / "data" / "submissions" / f"{args.workbook.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"discovery": d, "model_sheet": name, "target": target, "plan": plan, "bridge": bridge,
                               "market_refs": [(l, desc) for l, desc, _ in used]}, ensure_ascii=False, indent=1,
                              default=lambda x: None if isinstance(x, float) and math.isnan(x) else str(x)), encoding="utf-8")
    print(f"\nwritten {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
