"""ocp_exposure walk on the real ontology and supply-chain lanes, with made-up events. No Neo4j, no LLM."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
import exposure as x  # noqa: E402
import load_supply_chain  # noqa: E402

ONTO = yaml.safe_load((ROOT / "knowledge" / "ontology.yaml").read_text(encoding="utf-8"))
REL = [tuple(r) for r in ONTO["relations"]]
MADE_FROM = [(a, b) for a, r, b in REL if r == "MADE_FROM"]
SITES = {}
for a, r, b in REL:
    if r == "PRODUCED_AT":
        SITES.setdefault(a, []).append(b)
LANES = load_supply_chain.load_lanes()


def ev(incident, date, concept, direction, summary="", channel="supply"):
    return {"incident": incident, "date": date, "type": "shipping_disruption", "summary": summary, "concept": concept,
            "direction": direction, "channel": channel, "article_ids": [1000000 + len(incident)]}


EVENTS = [
    ev("i-hormuz", "2026-03-02", "hormuz", "disrupted", "Hormuz transits halted"),
    ev("i-redsea", "2026-02-10", "bab_el_mandeb", "disrupted", "Red Sea attacks, ships divert to the Cape"),
    ev("i-china", "2026-05-01", "country_china", "down", "China suspends phosphate fertilizer exports", "policy"),
    ev("i-sulfur", "2026-03-15", "sulfur", "up", "Middle East sulphur prices jump", "price"),
    ev("i-dap", "2026-04-01", "dap", "up", "DAP prices climb", "price"),
    ev("i-jorf", "2026-06-01", "jorf_lasfar", "disrupted", "Unplanned outage at a Jorf Lasfar line"),
]
PRICES = {"sulfur": {"2026-01": 160.0, "2026-03": 260.0, "2026-06": 240.0}, "dap": {"2026-01": 600.0, "2026-06": 690.0}}


def find(report, effect, link, item):
    return next(c for c in report[effect] if c["link"] == link and c["item"] == item)


def test_one_event_two_sides():
    r = x.exposure(LANES, MADE_FROM, SITES, EVENTS, PRICES)
    sulfur = find(r, "headwind", "supply", "sulfur")
    assert "hormuz" in {e["touch"] for e in sulfur["events"]} and "bab_el_mandeb" in {e["touch"] for e in sulfur["events"]}
    assert {"dap", "map", "tsp", "phosphoric_acid", "sulfuric_acid"} <= set(sulfur["reaches_ocp_products"])
    assert "jorf_lasfar" in sulfur["sites"] and sulfur["lane_status"] == "public knowledge, not confirmed by OCP"
    assert sulfur["price"] == {"from": "2026-01", "from_avg": 160.0, "to": "2026-06", "to_avg": 240.0, "change_pct": 50.0,
                               "peak": "2026-03", "peak_avg": 260.0}
    # the same Hormuz closure takes Saudi DAP off the market: a tailwind for OCP
    saudi = find(r, "tailwind", "competitor", "dap")
    assert {e["touch"] for e in saudi["events"]} >= {"hormuz", "country_china"}
    assert find(r, "headwind", "supply", "ammonia")["incidents"] == 2  # Hormuz + Red Sea on the Saudi ammonia lane


def test_exports_markets_and_sites():
    r = x.exposure(LANES, MADE_FROM, SITES, EVENTS, PRICES)
    india = find(r, "headwind", "export", "dap")
    assert any("country_india" in lane for lane in india["lanes"]) and india["events"][0]["touch"] == "bab_el_mandeb"
    assert find(r, "headwind", "input market", "sulfur")["events"][0]["summary"] == "Middle East sulphur prices jump"
    assert find(r, "tailwind", "product market", "dap")["price"]["change_pct"] == 15.0
    jorf = find(r, "headwind", "OCP site", "jorf_lasfar")
    assert "dap" in jorf["reaches_ocp_products"] and "phosphate_rock" not in jorf["reaches_ocp_products"]
    rock = find(r, "tailwind", "competitor", "phosphate_rock")  # Jordan's rock leaves Aqaba through the Red Sea
    assert rock["lanes"] == ["country_jordan -> bab_el_mandeb -> world market"]
    assert "cannot_size" in r and r["no_event_found_for"] == ["potash"]


def test_scope_keeps_only_what_reaches_the_product():
    r = x.exposure(LANES, MADE_FROM, SITES, EVENTS, PRICES, scope="tsp")
    items = {(c["link"], c["item"]) for effect in ("headwind", "tailwind") for c in r[effect]}
    assert ("supply", "sulfur") in items  # tsp is made from phosphoric acid, made with sulphuric acid from sulphur
    assert ("competitor", "dap") not in items and ("supply", "ammonia") not in items


def test_no_events_no_claims():
    r = x.exposure(LANES, MADE_FROM, SITES, [], {})
    assert r["headwind"] == r["tailwind"] == r["unclear"] == []


def test_dominant_direction_per_incident():
    rows = [ev("i1", "2026-03-02", "hormuz", "disrupted"), ev("i1", "2026-03-02", "hormuz", "disrupted"), ev("i1", "2026-03-03", "hormuz", "unclear")]
    (one,) = x.dominant(rows)
    assert one["direction"] == "disrupted"
