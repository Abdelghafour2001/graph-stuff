"""Check the routes in knowledge/driver_series.yaml against the price assessments actually in the graph.

For each driver it prints the configured route (product, location, incoterm) with its number of assessments and date range,
and the best-covered route for that product. A configured route with no data, or with far fewer assessments than the
best one, is flagged.

  python scripts/check_driver_series.py           # report only
  python scripts/check_driver_series.py --write   # also switch flagged drivers to their best-covered route
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from variance_tools import CONFIG, read_all  # noqa: E402

PATH = ROOT / "knowledge" / "driver_series.yaml"
MIN_SHARE = 1 / 3  # flag a configured route with less than a third of the best route's assessments
ROUTES = (
    "MATCH (p:PriceAssessment)-[:OF]->(:Concept {id: $product}), (p)-[:AT]->(l:Concept), (p)-[:BASIS]->(i:Concept) "
    "RETURN l.id AS location, i.id AS incoterm, count(*) AS n, count(DISTINCT substring(p.date, 0, 7)) AS months, "
    "min(p.date) AS first, max(p.date) AS last ORDER BY months DESC, n DESC"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    text = PATH.read_text(encoding="utf-8")
    changes = 0
    for cid, spec in CONFIG["series"].items():
        routes = read_all(ROUTES, product=spec["product"])
        configured = next((r for r in routes if r["location"] == spec["location"] and r["incoterm"] == spec["incoterm"]), None)
        best = routes[0] if routes else None
        show = lambda r: f"{r['location']} {r['incoterm']}: {r['n']} assessments over {r['months']} months ({r['first']} .. {r['last']})"
        print(f"\n{cid}")
        print(f"  configured  {spec['location']} {spec['incoterm']}: " + (show(configured).split(': ', 1)[1] if configured else "NO DATA"))
        if not best:
            print(f"  no price assessments at all for product '{spec['product']}': the driver cannot be ranked")
            continue
        print(f"  best route  {show(best)}")
        for r in routes[1:4]:
            print(f"  also        {show(r)}")
        weak = not configured or configured["months"] < MIN_SHARE * best["months"]
        if weak and (best["location"], best["incoterm"]) != (spec["location"], spec["incoterm"]):
            print("  FLAG: configured route has little or no data")
            if args.write:
                line = re.compile(rf"^(\s*{re.escape(cid)}:\s*\{{product: {re.escape(spec['product'])}, )location: [^,]+, incoterm: [^}}]+\}}", re.M)
                text, n = line.subn(rf"\g<1>location: {best['location']}, incoterm: {best['incoterm']}}}", text)
                changes += n
    if args.write and changes:
        PATH.write_text(text, encoding="utf-8")
        yaml.safe_load(text)  # still valid
        print(f"\nupdated {changes} route(s) in {PATH.relative_to(ROOT)}; review the diff before committing")


if __name__ == "__main__":
    main()
