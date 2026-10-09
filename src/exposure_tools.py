"""Agent tool ocp_exposure: reads lanes, recipes, OCP sites, events and prices from the graph, then src/exposure.py does the walk."""
import json

from anthropic import beta_tool

from load_supply_chain import route_aliases

import exposure as x
from variance_tools import load_series, read_all

OCP_SITES = "MATCH (s:Site)-[:PART_OF*]->(:Concept {id: 'ocp_group'}) "


def graph_snapshot() -> tuple[list[dict], list[tuple[str, str]], dict[str, list[str]]]:
    lanes = read_all(
        "MATCH (l:Lane)-[:CARRIES]->(i:Concept) OPTIONAL MATCH (l)-[:FROM]->(o:Concept) OPTIONAL MATCH (l)-[:TO]->(d:Concept) "
        "OPTIONAL MATCH (l)-[v:VIA]->(r:Concept) WITH l, i, o, d, r, v ORDER BY v.order "
        "RETURN l.id AS id, l.role AS role, l.status AS status, l.share AS share, i.id AS item, o.id AS origin, "
        "CASE WHEN l.role = 'supply' THEN null ELSE d.id END AS destination, CASE WHEN l.role = 'supply' THEN d.id END AS to, "
        "[x IN collect(r.id) WHERE x IS NOT NULL] AS via")
    made_from = [(r["a"], r["b"]) for r in read_all("MATCH (a:Concept)-[:MADE_FROM]->(b:Concept) RETURN a.id AS a, b.id AS b")]
    sites = {}
    for r in read_all(OCP_SITES + "MATCH (p:Concept)-[:PRODUCED_AT]->(s) RETURN p.id AS p, collect(s.id) AS sites"):
        sites[r["p"]] = sorted(r["sites"])
    return lanes, made_from, sites


def events_on(concepts: list[str], date_from: str, date_to: str) -> list[dict]:
    rows = read_all(
        "MATCH (e:Event)-[a:AFFECTS]->(c:Concept) WHERE c.id IN $ids AND e.date >= $from AND e.date <= $to "
        "OPTIONAL MATCH (e)-[:INSTANCE_OF]->(i:Incident) OPTIONAL MATCH (e)-[:REPORTED_IN]->(art:Article) "
        "RETURN coalesce(i.id, e.id) AS incident, coalesce(i.date, e.date) AS date, e.type AS type, "
        "coalesce(i.summary, e.summary) AS summary, c.id AS concept, a.direction AS direction, a.channel AS channel, "
        "collect(DISTINCT art.id) AS article_ids",
        ids=concepts, **{"from": date_from, "to": date_to})
    return x.dominant(rows)


def monthly_prices(items: list[str], date_from: str, date_to: str) -> dict[str, dict[str, float]]:
    out = {}
    for item, points in load_series(items).items():
        by_month = {}
        for d, v in points:
            if date_from <= d <= date_to:
                by_month.setdefault(d[:7], []).append(v)
        out[item] = {m: sum(vs) / len(vs) for m, vs in by_month.items()}
    return out


def run_exposure(scope: str, date_from: str, date_to: str) -> dict:
    lanes, made_from, sites = graph_snapshot()
    if not lanes:
        return {"error": "No supply-chain lanes in the graph: run src/load_supply_chain.py (after import_referentials.py)."}
    items = sorted({lane["item"] for lane in lanes} | {b for _, b in made_from} | set(sites))
    aliases = route_aliases()
    touch = sorted({t for lane in lanes for t in [lane["origin"], lane.get("destination"), *lane["via"]] if t}
                   | set(items) | {s for ss in sites.values() for s in ss} | {a for names in aliases.values() for a in names})
    report = x.exposure(lanes, made_from, sites, events_on(touch, date_from, date_to),
                        monthly_prices(items, date_from, date_to), scope or None, aliases)
    report["period"] = [date_from, date_to]
    return report


@beta_tool
def ocp_exposure(scope: str, date_from: str, date_to: str) -> str:
    """Which world events reached OCP in a period and through which link, walked on the graph (no LLM): event -> route, country
    or market -> lane (what OCP buys and from where, where it sells, who competes with it) -> input or product -> OCP products and
    sites. Returns headwinds (cost, availability, sales) and tailwinds (less competing supply, higher selling price), each with
    its incidents (dates, article ids), the lanes involved, whether the lane is confirmed by OCP, and the market price move of the
    item over the period. It does not size anything in $: the graph has no OCP volumes or results.
    Use it for "why did OCP lose/earn ...", "what hit OCP this year", "how exposed is DAP to ...".

    Args:
        scope: An OCP product id to keep only what reaches it (e.g. "dap"), or "" for all of OCP.
        date_from: Inclusive start date, YYYY-MM-DD.
        date_to: Inclusive end date, YYYY-MM-DD.
    """
    return json.dumps(run_exposure(scope, date_from, date_to), ensure_ascii=False, default=str)
