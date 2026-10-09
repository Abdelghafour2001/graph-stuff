"""ocp_exposure: which world events reached OCP in a period, and through which link (design: docs/11-exposure.md).

Walks the graph, no LLM:
  event -[AFFECTS]-> route / country / product
      -> lane (supply: what OCP buys and from where; export: where OCP sells; competitor: who else sells OCP's products)
      -> the item it carries -> the OCP products that need it (MADE_FROM) -> the sites making them (PRODUCED_AT)
and states the effect for OCP: a headwind (cost, availability, sales) or a tailwind (less competing supply, higher selling
price), with the item's market price move over the period when a price series exists.

It does NOT size anything in $: the graph has no OCP volumes or results. Lanes are public knowledge until OCP confirms them.
"""
from collections import Counter, defaultdict

IMPAIRED, EASED = {"disrupted", "down"}, {"restored", "up"}

# role of the lane, what happened on it -> effect for OCP and why
LANE_EFFECT = {
    ("supply", "impaired"): ("headwind", "less {item} reaching OCP from {origin}: availability risk and a higher {item} cost"),
    ("supply", "eased"): ("tailwind", "{item} supply from {origin} back to normal: lower cost pressure"),
    ("export", "impaired"): ("headwind", "OCP {item} shipments to {destination} delayed or costlier (freight, longer route, duties)"),
    ("export", "eased"): ("tailwind", "OCP {item} shipments to {destination} easier"),
    ("competitor", "impaired"): ("tailwind", "less competing {item} from {origin} on the market: support for the price OCP gets"),
    ("competitor", "eased"): ("headwind", "more competing {item} from {origin}: pressure on the price OCP gets"),
}


def lane_state(direction: str | None) -> str:
    return "impaired" if direction in IMPAIRED else "eased" if direction in EASED else "unclear"


def downstream(item: str, made_from: list[tuple[str, str]], ocp_products: set[str]) -> list[str]:
    """OCP products that need the item, directly or through intermediates (MADE_FROM is product -> input)."""
    users, seen, todo = [], {item}, [item]
    while todo:
        x = todo.pop()
        for product, inp in made_from:
            if inp == x and product not in seen:
                seen.add(product)
                todo.append(product)
                if product in ocp_products:
                    users.append(product)
    return sorted(users)


def price_move(monthly: dict[str, float] | None) -> dict | None:
    """First and last month averages of the period and the change, computed here (not by the LLM)."""
    if not monthly or len(monthly) < 2:
        return None
    months = sorted(monthly)
    a, b = monthly[months[0]], monthly[months[-1]]
    hi = max(months, key=monthly.get)
    return {"from": months[0], "from_avg": round(a, 1), "to": months[-1], "to_avg": round(b, 1),
            "change_pct": round(100 * (b - a) / a, 1) if a else None, "peak": hi, "peak_avg": round(monthly[hi], 1)}


def exposure(lanes: list[dict], made_from: list[tuple[str, str]], sites: dict[str, list[str]], events: list[dict],
             prices: dict[str, dict[str, float]], scope: str | None = None, aliases: dict[str, list[str]] | None = None,
             price_sources: dict[str, str] | None = None) -> dict:
    """lanes: [{id, role, item, origin, destination, via, status, share}]; sites: {OCP product: [sites]};
    events: [{incident, date, type, summary, concept, direction, channel, article_ids}]; prices: {item: {YYYY-MM: avg}}.
    scope: an OCP product id to keep only what reaches it, or None for all of OCP.
    aliases: {route: [region ids]} whose events count as events on the route."""
    ocp_products = set(sites)
    bought = {inp for _, inp in made_from} - ocp_products

    def reaches(item: str) -> list[str]:
        own = [item] if item in ocp_products else []
        return sorted(set(own + downstream(item, made_from, ocp_products)))

    by_touch = defaultdict(list)
    alias_of = {a: route for route, names in (aliases or {}).items() for a in names}  # region_red_sea -> bab_el_mandeb
    for e in events:
        by_touch[alias_of.get(e["concept"], e["concept"])].append(e)

    links = defaultdict(lambda: {"events": {}, "lanes": set(), "status": set(), "why": set()})
    for lane in lanes:
        # an export lane starts in Morocco, i.e. at OCP itself: news that mentions Morocco is not news about the lane
        origin = None if lane["role"] == "export" else lane.get("origin")
        touches = [origin, *lane.get("via", []), lane.get("destination")]
        for t in filter(None, touches):
            for e in by_touch.get(t, []):
                state = lane_state(e["direction"])
                effect, why = LANE_EFFECT.get((lane["role"], state), ("unclear", "direction of the effect unclear"))
                key = (effect, lane["role"], lane["item"])
                link = links[key]
                link["events"].setdefault(e["incident"], {**e, "touch": t, "touch_kind": "origin" if t == lane.get("origin") else "destination" if t == lane.get("destination") else "route"})
                link["lanes"].add(f"{lane['origin']} -> {' -> '.join(lane.get('via') or ['direct'])} -> {lane.get('destination') or lane.get('to') or 'world market'}")
                link["status"].add(lane.get("status", "public"))
                link["why"].add(why.format(item=lane["item"], origin=lane.get("origin", ""), destination=lane.get("destination", "")))

    # events on the item itself (e.g. "sulphur prices jump", "China halts phosphate exports" tagged on dap)
    for item in bought | ocp_products:
        for e in by_touch.get(item, []):
            d = e["direction"]
            if item in bought:
                effect = "headwind" if d in {"up", "disrupted"} else "tailwind" if d in {"down", "restored"} else "unclear"
                why = f"{item} market {'tighter or dearer' if effect == 'headwind' else 'easier or cheaper' if effect == 'tailwind' else 'moved'}: OCP buys it"
                role = "input market"
            else:
                effect = "tailwind" if d == "up" else "headwind" if d == "down" else "unclear"
                why = f"{item} market {'price up' if d == 'up' else 'price down' if d == 'down' else d or 'moved'}: OCP sells it"
                role = "product market"
            link = links[(effect, role, item)]
            link["events"].setdefault(e["incident"], {**e, "touch": item, "touch_kind": "item"})
            link["status"].add("graph")
            link["why"].add(why)

    # events at OCP's own sites (outage, strike, accident, restart)
    for site in sorted({s for ss in sites.values() for s in ss}):
        for e in by_touch.get(site, []):
            d = e["direction"]
            effect = "headwind" if d in IMPAIRED else "tailwind" if d in EASED else "unclear"
            link = links[(effect, "OCP site", site)]
            link["events"].setdefault(e["incident"], {**e, "touch": site, "touch_kind": "site"})
            link["status"].add("graph")
            link["why"].add(f"event at OCP site {site}: production of what it makes may be affected")

    out = {"headwind": [], "tailwind": [], "unclear": []}
    for (effect, role, item), link in links.items():
        reached = sorted(p for p, ss in sites.items() if item in ss) if role == "OCP site" else reaches(item)
        if scope and scope not in reached:
            continue
        evs = sorted(link["events"].values(), key=lambda e: e["date"])
        out[effect].append({
            "item": item, "link": role, "why": sorted(link["why"]), "lanes": sorted(link["lanes"]),
            "reaches_ocp_products": reached, "sites": sorted({s for p in reached for s in sites.get(p, [])}),
            "lane_status": "public knowledge, not confirmed by OCP" if link["status"] <= {"public"} else sorted(link["status"]),
            "incidents": len(evs), "first": evs[0]["date"], "last": evs[-1]["date"],
            "events": [{k: e.get(k) for k in ("date", "type", "summary", "touch", "direction", "channel", "article_ids")} for e in evs[:8]],
            "price": (lambda m: m and {**m, "series": (price_sources or {}).get(item)})(price_move(prices.get(item))),
        })
    for effect in out:
        out[effect].sort(key=lambda x: (-x["incidents"], x["item"]))
    touched = {i for xs in out.values() for c in xs for i in [c["item"], *c["reaches_ocp_products"]]}
    return {
        "scope": scope or "ocp_group",
        **out,
        "no_event_found_for": sorted((bought | ocp_products) - touched) if not scope else [],
        "cannot_size": "The graph has no OCP volumes, costs or results: this shows which links were hit and how market prices "
                       "moved, not how many $ OCP lost or gained. Headwinds and tailwinds can offset each other.",
    }


def dominant(events: list[dict]) -> list[dict]:
    """One row per (incident, concept): the most frequent direction and channel among its reports."""
    groups = defaultdict(list)
    for e in events:
        groups[(e["incident"], e["concept"])].append(e)
    rows = []
    for (_, _), es in groups.items():
        direction = Counter(e["direction"] for e in es).most_common(1)[0][0]
        channel = Counter(e["channel"] for e in es).most_common(1)[0][0]
        ids = sorted({a for e in es for a in e.get("article_ids") or []})[:3]
        rows.append({**es[0], "direction": direction, "channel": channel, "article_ids": ids})
    return rows
