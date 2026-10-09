"""News subgraph, LLM part: extract price assessments and events from targeted Argus articles, verify them against the text,
cache raw outputs in data/news_extractions.jsonl, then load the verified ones into the graph.

  python news_extract.py extract   # calls the LLM for articles not yet in the cache (costs money)
  python news_extract.py load      # deterministic: cache -> graph (run by the loader)
"""
import json
import os
from datetime import date as calendar_date
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import psycopg

from graph import driver

CACHE = Path(__file__).parent.parent / "data" / "news_extractions.jsonl"
TARGETS = {
    "prices": """select "NewsId", left("PublicationDate", 10), "Headline", "Text" from corporate_data.argus_news
                 where "PublicationDate" >= '2026-01-01' and "Headline" like 'Phosphates:%'""",
    "events": """select "NewsId", left("PublicationDate", 10), "Headline", "Text" from corporate_data.argus_news
                 where "PublicationDate" >= '2026-01-01' and "Headline" ~* '(iran|hormuz|israel|ceasefire|strait)'
                 and "Text" ~* '(dap|phosphat|sulphur|sulfur|ammonia|urea|fertili)'""",
}
EVENT_TYPES = ["military_action", "ceasefire_or_talks", "shipping_disruption", "shipping_restored", "sanction_or_tariff",
               "export_restriction", "plant_outage", "capacity_change", "tender_or_deal", "policy", "other"]
PROMPTS = {
    "prices": """You extract price assessments from an Argus fertilizer market report.
Return JSON {"assessments": [{"product": "DAP|MAP|TSP|NPK|phosphate rock|phosphoric acid|sulphur|sulphuric acid|ammonia|urea|other",
"location": "country, port or region exactly as written", "incoterm": "fob|cfr|cif|fca|cpt|cip|exw|unknown",
"low": number, "high": number (same as low for a single price), "unit": "as written, e.g. $/t", "change": "up|down|steady|unknown",
"quote": "the exact sentence from the text that contains the numbers, copied verbatim"}]}.
Only prices explicitly stated in the text, in US dollars. No calculations. At most 40.""",
    "events": f"""You extract market-relevant events from a news article about fertilizers and geopolitics.
Return JSON {{"events": [{{"type": one of {EVENT_TYPES}, "date": "YYYY-MM-DD when it happened, else the publication date",
"summary": "one factual sentence", "affects": [{{"term": "product, route, country or company exactly as written (e.g. urea, sulphur, Strait of Hormuz, Qatar)",
"direction": "up|down|disrupted|restored|unclear", "channel": "supply|demand|cost|freight|price|policy"}}],
"quote": "one sentence from the text supporting the event, copied verbatim"}}]}}.
Only events stated in the article. At most 5.""",
}
WORKERS = 8
lock = Lock()


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def extract() -> None:
    import llm  # imported here so `load` works without LLM credentials

    done = {(r["kind"], r["article_id"]) for r in map(json.loads, CACHE.read_text(encoding="utf-8").splitlines())} if CACHE.exists() else set()
    with psycopg.connect(os.environ["MARKET_INTEL_DSN"]) as pg:
        jobs = [(kind, row) for kind, sql in TARGETS.items() for row in pg.execute(sql).fetchall() if (kind, row[0]) not in done]
    print(f"{len(jobs)} articles to extract ({len(done)} cached)", flush=True)

    def run(job):
        kind, (news_id, date, headline, text) = job
        try:
            output = llm.json_completion(PROMPTS[kind], f"Publication date: {date}\nHeadline: {headline}\n\n{text[:12000]}", "AZURE_OPENAI_DEPLOYMENT")
        except Exception as e:  # one failed article must not stop the batch; it stays uncached and is retried next run
            print(f"failed {news_id}: {e}", flush=True)
            return
        with lock, CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "article_id": news_id, "date": date, "output": output}, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(WORKERS) as pool:
        for i, _ in enumerate(pool.map(run, jobs), start=1):
            if i % 50 == 0:
                print(f"{i}/{len(jobs)}", flush=True)


def valid_date(candidate, fallback: str) -> str:
    """The model's event date if it is a real calendar date, else the article's publication date."""
    try:
        return calendar_date.fromisoformat(str(candidate)).isoformat()
    except ValueError:
        return fallback


def number_in(value: float, quote: str) -> bool:
    return str(int(value)) in quote.replace(",", "")


def load() -> None:
    records = [json.loads(line) for line in CACHE.read_text(encoding="utf-8").splitlines()]
    with psycopg.connect(os.environ["MARKET_INTEL_DSN"]) as pg:
        texts = dict(pg.execute('select "NewsId", "Text" from corporate_data.argus_news where "NewsId" = any(%s)', ([r["article_id"] for r in records],)).fetchall())
    prices, events, rejected = [], [], 0
    for r in records:
        text = squash(texts[r["article_id"]])
        items = r["output"].get("assessments" if r["kind"] == "prices" else "events", [])
        for i, item in enumerate(items):
            quote = squash(str(item.get("quote", "")))
            verified = bool(quote) and quote in text
            if r["kind"] == "prices":
                verified = verified and isinstance(item.get("low"), (int, float)) and isinstance(item.get("high"), (int, float)) \
                    and 0 < item["low"] <= item["high"] and number_in(item["low"], quote) and number_in(item["high"], quote)
                if verified:
                    prices.append({"id": f"{r['article_id']}-p{i}", "article": r["article_id"], "date": r["date"], **{k: item[k] for k in ("product", "location", "incoterm", "low", "high", "unit", "change", "quote")}})
            elif verified and item.get("type") in EVENT_TYPES:
                events.append({"id": f"{r['article_id']}-e{i}", "article": r["article_id"], "date": valid_date(item.get("date"), r["date"]),
                               "type": item["type"], "summary": item.get("summary", ""), "quote": item["quote"], "affects": item.get("affects", [])})
            rejected += not verified
    # Outlier guard: a price more than 2x away from the median of its own series (product, location, incoterm) is a misread
    # (e.g. "up $1/t" taken as a price). Deterministic, so every rejection is reproducible.
    series = {}
    for x in prices:
        series.setdefault((x["product"].lower(), x["location"].lower(), x["incoterm"]), []).append((x["low"] + x["high"]) / 2)
    medians = {k: sorted(v)[len(v) // 2] for k, v in series.items()}
    kept = [x for x in prices if 0.5 <= ((x["low"] + x["high"]) / 2) / medians[(x["product"].lower(), x["location"].lower(), x["incoterm"])] <= 2]
    outliers = len(prices) - len(kept)
    prices = kept
    with driver.session() as s:
        s.run("MATCH (n) WHERE n:PriceAssessment OR n:Event OR n:Incident DETACH DELETE n")
        resolve = "OPTIONAL MATCH (t:Term)-[:REFERS_TO]->(c:Concept) WHERE toLower(t.text) = toLower(trim({text})) WITH {var}, collect(DISTINCT c)[0] AS {out}"
        s.run(
            "UNWIND $rows AS r MATCH (a:Article {id: r.article}) "
            "CREATE (p:PriceAssessment {id: r.id, date: r.date, product: r.product, location: r.location, incoterm: r.incoterm, "
            "low: toFloat(r.low), high: toFloat(r.high), mid: (toFloat(r.low) + toFloat(r.high)) / 2, unit: r.unit, change: r.change, quote: r.quote})-[:REPORTED_IN]->(a) "
            "WITH p, r " + resolve.format(text="r.product", var="p, r", out="prod") + " FOREACH (_ IN CASE WHEN prod IS NULL THEN [] ELSE [1] END | CREATE (p)-[:OF]->(prod)) "
            "WITH p, r " + resolve.format(text="r.location", var="p, r", out="loc") + " FOREACH (_ IN CASE WHEN loc IS NULL THEN [] ELSE [1] END | CREATE (p)-[:AT]->(loc)) "
            "WITH p, r " + resolve.format(text="r.incoterm", var="p, r", out="inc") + " FOREACH (_ IN CASE WHEN inc IS NULL THEN [] ELSE [1] END | CREATE (p)-[:BASIS]->(inc))",
            rows=prices,
        )
        s.run(
            "UNWIND $rows AS r MATCH (a:Article {id: r.article}) "
            "CREATE (e:Event {id: r.id, date: r.date, type: r.type, summary: r.summary, quote: r.quote})-[:REPORTED_IN]->(a) "
            "WITH e, r UNWIND r.affects AS x " + resolve.format(text="x.term", var="e, x", out="c") +
            " WHERE c IS NOT NULL CREATE (e)-[:AFFECTS {direction: x.direction, channel: x.channel, term: x.term}]->(c)",
            rows=events,
        )
        # Dedup: events with the same type, date and affected concepts, reported by several articles, form one Incident.
        groups = {}
        for e in s.run("MATCH (e:Event) OPTIONAL MATCH (e)-[:AFFECTS]->(c:Concept) RETURN e.id AS id, e.type AS type, e.date AS date, e.summary AS summary, collect(DISTINCT c.id) AS concepts").data():
            groups.setdefault((e["type"], e["date"], tuple(sorted(e["concepts"]))), []).append(e)
        s.run(
            "UNWIND $rows AS r CREATE (i:Incident {id: r.id, type: r.type, date: r.date, summary: r.summary, reports: size(r.events)}) "
            "WITH i, r UNWIND r.events AS eid MATCH (e:Event {id: eid}) CREATE (e)-[:INSTANCE_OF]->(i) "
            "WITH DISTINCT i, r UNWIND r.concepts AS cid MATCH (c:Concept {id: cid}) CREATE (i)-[:AFFECTS]->(c)",
            rows=[{"id": f"incident-{n}", "type": k[0], "date": k[1], "concepts": list(k[2]), "summary": g[0]["summary"], "events": [e["id"] for e in g]}
                  for n, (k, g) in enumerate(groups.items())],
        )
    print(f"{len(groups)} incidents from {len(events)} events")
    print(f"loaded {len(prices)} price assessments, {len(events)} events; rejected {rejected} unverifiable items (quote or numbers not in text) and {outliers} price outliers")


if __name__ == "__main__":
    {"extract": extract, "load": load}[sys.argv[1]]()
