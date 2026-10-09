"""Run the variance diagnosis end to end on the real graph, in order:

  1. routes: check knowledge/driver_series.yaml against the assessments in the graph
  2. eval:   injected-shock evaluation on the real series (scripts/eval_variance.py --graph)
  3. report: the deterministic diagnosis for one month (what GET /variance returns)
  4. ask:    only with --ask, the agent answers the question with the configured LLM (costs money)

  python scripts/smoke_variance.py                       # steps 1-3, latest month with data for the product
  python scripts/smoke_variance.py --period 2026-08 --ask
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
import variance  # noqa: E402
from variance_tools import CONFIG, load_series, run_diagnosis  # noqa: E402


def step(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * (60 - len(title))}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric", default="gross_margin")
    ap.add_argument("--product", default="dap")
    ap.add_argument("--period", help="YYYY-MM; default: the latest complete month with data for the product")
    ap.add_argument("--ask", action="store_true", help="also ask the agent (calls the LLM)")
    args = ap.parse_args()

    step("1 routes")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "check_driver_series.py")], check=True)

    step("2 injected-shock evaluation on real series")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_variance.py"), "--graph"], check=False)

    step("3 deterministic diagnosis")
    period = args.period
    if not period:
        months = sorted({d[:7] for d, _ in load_series([args.product]).get(args.product, [])})
        assert len(months) > 1, f"no price series for {args.product}: fix knowledge/driver_series.yaml first"
        period = months[-2]  # the last month may be incomplete
    diag, incidents, not_ranked = run_diagnosis(args.metric, args.product, period)
    print(variance.report(diag, args.metric, args.product, incidents, not_ranked))

    if args.ask:
        step("4 agent")
        import agent
        answer, trace = agent.ask([], f"Pourquoi la marge brute du {args.product.upper()} a-t-elle bougé en {period} ? "
                                      f"Utilise diagnose_variance (metric {args.metric}, product {args.product}).")
        print(answer)
        print("\ntools:", [c["tool"] for c in trace])
    routes = ", ".join(f"{k}={s['location']} {s['incoterm']}" for k, s in CONFIG["series"].items())
    print(f"\nrouted to: {routes}")


if __name__ == "__main__":
    main()
