"""Injected-shock evaluation of diagnose_variance (docs/08-variance-diagnosis.md, "Evaluation: injected shocks").

A shock of known size and onset is added to one driver in one month; the diagnosis should rank that driver first.
Reports Top-1, Top-3 and MRR, overall and by driver, shock size and onset, against two simple baselines.

  python scripts/eval_variance.py               # synthetic market: linked price series, shocks propagate downstream
  python scripts/eval_variance.py --graph       # real Argus series from Neo4j (knowledge/driver_series.yaml), level shifts

The synthetic market is a test bench, not a model of OCP's costs: its pass-through coefficients and lags are made up so that
a sulfur shock reaches sulfuric acid two weeks later, phosphoric acid three weeks after that, and DAP after that.
Writes data/variance_eval_lag<N>.json.
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
import variance as v  # noqa: E402

DRIVERS = ["dap", "phosphoric_acid", "sulfuric_acid", "sulfur", "ammonia", "phosphate_rock"]
START, END = date(2023, 1, 2), date(2026, 9, 30)
SIZES = [0.08, 0.15, 0.30]   # shock as a share of the driver's price level
ONSETS = [3, 10]             # day of the month the shock starts
BASELINE_N = 3


def simulate(seed: int, shock: tuple[str, date, float] | None = None) -> dict:
    """Daily prices with lagged pass-through; observed on Mondays and Thursdays with 0.5% measurement noise.
    shock = (driver, onset, share): from onset the driver's own level is multiplied by (1 + share)."""
    rnd = random.Random(seed)
    days = (END - START).days + 1
    walk = {d: [0.0] * days for d in DRIVERS}
    vol = {"sulfur": 0.006, "ammonia": 0.006, "phosphate_rock": 0.002, "sulfuric_acid": 0.004, "phosphoric_acid": 0.003, "dap": 0.003}
    for d in DRIVERS:
        for t in range(1, days):
            walk[d][t] = walk[d][t - 1] + rnd.gauss(0, vol[d])
    bump = lambda d, t: 1 + (shock[2] if shock and shock[0] == d and START + timedelta(t) >= shock[1] else 0.0)
    lag = lambda series, t, n: series[max(0, t - n)]
    p = {d: [0.0] * days for d in DRIVERS}
    for t in range(days):
        p["sulfur"][t] = 150 * (1 + walk["sulfur"][t]) * bump("sulfur", t)
        p["ammonia"][t] = 420 * (1 + walk["ammonia"][t]) * bump("ammonia", t)
        p["phosphate_rock"][t] = 150 * (1 + walk["phosphate_rock"][t]) * bump("phosphate_rock", t)
        p["sulfuric_acid"][t] = (30 + 0.9 * lag(p["sulfur"], t, 14)) * (1 + walk["sulfuric_acid"][t]) * bump("sulfuric_acid", t)
        p["phosphoric_acid"][t] = (350 + 1.2 * lag(p["phosphate_rock"], t, 21) + 2.6 * lag(p["sulfuric_acid"], t, 21)) \
            * (1 + walk["phosphoric_acid"][t]) * bump("phosphoric_acid", t)
        p["dap"][t] = (150 + 0.6 * lag(p["phosphoric_acid"], t, 21) + 0.22 * lag(p["ammonia"], t, 14)) \
            * (1 + walk["dap"][t]) * bump("dap", t)
    out = {}
    for d in DRIVERS:
        out[d] = [((START + timedelta(t)).isoformat(), round(p[d][t] * (1 + rnd.gauss(0, 0.005)), 2))
                  for t in range(days) if (START + timedelta(t)).weekday() in (0, 3)]
    return out


def shift(series: dict, driver: str, onset: str, share: float) -> dict:
    """Real-data variant: a level shift on one driver from onset, no propagation."""
    return {d: [(t, x * (1 + share) if d == driver and t >= onset else x) for t, x in pts] for d, pts in series.items()}


def still_transmitting(case: dict, downstream: list[str], threshold: float = 0.02) -> bool:
    """True when the shock changes a downstream product's month-on-month move by more than threshold in the diagnosed month."""
    shocked = simulate(case["seed"], (case["driver"], date.fromisoformat(f"{case['shock_month']}-{case['onset']:02d}"), case["size"]))
    clean = simulate(case["seed"])
    prev = v.previous_months(case["period"], 1)
    move = lambda pts: fmean(v.in_months(pts, [case["period"]])) / fmean(v.in_months(pts, prev)) - 1
    return any(abs(move(shocked[d]) - move(clean[d])) > threshold for d in downstream)


def naive_rank(series: dict, period: str) -> list[str]:
    """Baseline: largest absolute % change of the monthly mean vs the previous month."""
    prev = v.previous_months(period, 1)[0]
    change = {}
    for d, pts in series.items():
        now, before = v.in_months(pts, [period]), v.in_months(pts, [prev])
        if now and before:
            change[d] = abs(fmean(now) / fmean(before) - 1)
    return sorted(change, key=lambda d: -change[d])


def score(ranking: list[str], truth: str) -> dict:
    r = ranking.index(truth) + 1 if truth in ranking else None
    return {"top1": r == 1, "top3": r is not None and r <= 3, "rr": 1 / r if r else 0.0, "rank": r}


def summarize(rows: list[dict], method: str) -> dict:
    s = [r[method] for r in rows]
    return {"n": len(s), "top1": round(fmean(x["top1"] for x in s), 3), "top3": round(fmean(x["top3"] for x in s), 3),
            "mrr": round(fmean(x["rr"] for x in s), 3)}


def run(cases, cands, get_series) -> list[dict]:
    rows = []
    for case in cases:
        series = get_series(case)
        period = case["period"]
        months = sorted({d[:7] for pts in series.values() for d, _ in pts})
        episodes = v.library(cands, series, [m for m in months if m < period and v.previous_months(m, BASELINE_N)[0] >= months[0]], BASELINE_N)
        full = v.diagnose(cands, series, period, BASELINE_N, episodes=episodes)
        no_analogs = v.diagnose(cands, series, period, BASELINE_N, episodes=[])
        month_only = sorted(full["ranking"], key=lambda r: -r["score"])
        rows.append({**{k: case[k] for k in ("driver", "period", "size", "onset", "seed")},
                     "full": score([r["id"] for r in full["ranking"]], case["driver"]),
                     "no_analogs": score([r["id"] for r in no_analogs["ranking"]], case["driver"]),
                     "no_weekly_vote": score([r["id"] for r in month_only], case["driver"]),
                     "naive_pct_change": score(naive_rank({c["id"]: series.get(c["id"], []) for c in cands}, period), case["driver"]),
                     "top3": [r["id"] for r in full["ranking"][:3]]})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", action="store_true", help="use real series from Neo4j instead of the synthetic market")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--lag", type=int, default=0, help="diagnose N months after the shock month (the cause started earlier)")
    args = ap.parse_args()

    ontology = yaml.safe_load((ROOT / "knowledge" / "ontology.yaml").read_text(encoding="utf-8"))
    edges = [tuple(r) for r in ontology["relations"]]
    cands = v.candidates(edges, "gross_margin", "dap", set(DRIVERS))
    methods = ["full", "no_analogs", "no_weekly_vote", "naive_pct_change"]

    if args.graph:
        import variance_tools
        real = variance_tools.load_series(DRIVERS)
        months = sorted({d[:7] for pts in real.values() for d, _ in pts})
        periods = [m for m in months[BASELINE_N + 6:] if all(v.in_months(real.get(d, []), [m]) for d in DRIVERS)]
        cases = [{"driver": d, "period": m, "size": s, "onset": o, "seed": 0} for d in DRIVERS for m in periods for s in SIZES for o in ONSETS]
        get = lambda c: shift(real, c["driver"], f"{c['period']}-{c['onset']:02d}", c["size"])
    else:
        periods = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]
        cases = [{"driver": d, "period": m, "shock_month": v.previous_months(m, args.lag)[0] if args.lag else m, "size": s, "onset": o, "seed": seed}
                 for seed in range(args.seeds) for d in DRIVERS for m in periods[seed::args.seeds] for s in SIZES for o in ONSETS]
        get = lambda c: simulate(c["seed"], (c["driver"], date.fromisoformat(f"{c['shock_month']}-{c['onset']:02d}"), c["size"]))

    if args.lag and not args.graph:
        # keep only well-posed cases: the shock must still be moving a downstream product in the diagnosed month
        # (compared with the same simulation without the shock); otherwise there is nothing left to explain
        downstream = {c["id"]: c["downstream"] for c in cands}
        cases = [c for c in cases if still_transmitting(c, downstream[c["driver"]])]
        print(f"{len(cases)} well-posed cases (shock still reaching a downstream product in the diagnosed month)")
    rows = run(cases, cands, get)
    report = {"source": "graph" if args.graph else "synthetic", "lag_months": args.lag, "cases": len(rows),
              "overall": {m: summarize(rows, m) for m in methods}, "by": {}}
    for key in ("driver", "size", "onset"):
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        report["by"][key] = {str(k): {m: summarize(g, m) for m in ("full", "naive_pct_change")} for k, g in sorted(groups.items())}
    confusions = defaultdict(int)
    for r in rows:
        if not r["full"]["top1"]:
            confusions[f"{r['driver']} -> {r['top3'][0]}"] += 1
    report["top_confusions"] = dict(sorted(confusions.items(), key=lambda x: -x[1])[:8])

    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / f"variance_eval_lag{args.lag}.json").write_text(json.dumps({**report, "rows": rows}, indent=1), encoding="utf-8")
    print(f"{report['cases']} injected shocks ({report['source']}, diagnosed {args.lag} month(s) after the shock month)")
    print(f"{'method':<18}{'top1':>7}{'top3':>7}{'mrr':>7}")
    for m in methods:
        o = report["overall"][m]
        print(f"{m:<18}{o['top1']:>7}{o['top3']:>7}{o['mrr']:>7}")
    for key, groups in report["by"].items():
        print(f"\nby {key} (full / naive top1)")
        for k, g in groups.items():
            print(f"  {k:<18}{g['full']['top1']:>7}{g['naive_pct_change']['top1']:>7}  (n={g['full']['n']})")
    print("\nmost frequent misses:", report["top_confusions"])


if __name__ == "__main__":
    main()
