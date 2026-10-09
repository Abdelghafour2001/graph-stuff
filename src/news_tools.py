"""Tools of the news specialist: Articles, Events and PriceAssessments in the graph; article text from Postgres.

Every tool is "as of" date_to: nothing published after it is returned (avoids look-ahead leakage).
"""
import json
import os

import psycopg
from anthropic import beta_tool

from graph import read_graph


@beta_tool
def search_articles(concept_ids: list[str], date_from: str, date_to: str) -> str:
    """Articles (Argus news) mentioning ALL given concepts, published between two dates, newest first (max 50).

    Args:
        concept_ids: Concept ids from lookup_term, e.g. ["dap", "hormuz"].
        date_from: Inclusive start date, YYYY-MM-DD.
        date_to: Inclusive end date, YYYY-MM-DD. Nothing published later is returned.
    """
    rows = read_graph(
        "MATCH (a:Article)-[:MENTIONS]->(c:Concept) WHERE c.id IN $ids AND a.published_at >= $from AND a.published_at <= $to "
        "WITH a, count(DISTINCT c) AS hit WHERE hit = size($ids) "
        "RETURN a.id AS article_id, a.published_at AS date, a.headline AS headline ORDER BY date DESC",
        ids=concept_ids, **{"from": date_from, "to": date_to},
    )
    return json.dumps(rows, ensure_ascii=False) if rows else "No article mentions all these concepts in that period."


@beta_tool
def read_article(article_id: int) -> str:
    """Full text of one article (first 6000 characters).

    Args:
        article_id: article_id returned by search_articles, event_timeline or price_assessments.
    """
    with psycopg.connect(os.environ["MARKET_INTEL_DSN"]) as pg:
        row = pg.execute('select "Headline", left("PublicationDate", 10), left("Text", 6000) from corporate_data.argus_news where "NewsId" = %s', (article_id,)).fetchone()
    assert row, f"unknown article {article_id}"
    return f"{row[1]} | {row[0]}\n\n{row[2]}"


@beta_tool
def event_timeline(concept_ids: list[str], date_from: str, date_to: str) -> str:
    """Incidents extracted from news (military action, shipping disruption, ceasefire, export restriction, ...) that affect ANY of the
    given concepts, in date order (max 50). An incident groups the same event reported by several articles (reports = count);
    each comes with a verbatim quote and the supporting article ids.

    Args:
        concept_ids: Concept ids, e.g. ["hormuz", "sulfur", "ammonia"].
        date_from: Inclusive start date, YYYY-MM-DD.
        date_to: Inclusive end date, YYYY-MM-DD.
    """
    rows = read_graph(
        "MATCH (i:Incident)-[:AFFECTS]->(c:Concept) WHERE c.id IN $ids AND i.date >= $from AND i.date <= $to "
        "MATCH (e:Event)-[:INSTANCE_OF]->(i), (e)-[:REPORTED_IN]->(a:Article) WHERE a.published_at <= $to "
        "WITH i, collect(DISTINCT c.id) AS affects, collect(DISTINCT a.id)[..5] AS article_ids, head(collect(e.quote)) AS quote "
        "RETURN i.date AS date, i.type AS type, i.summary AS summary, i.reports AS reports, affects, quote, article_ids "
        "ORDER BY date, reports DESC",
        ids=concept_ids, **{"from": date_from, "to": date_to},
    )
    return json.dumps(rows, ensure_ascii=False) if rows else "No extracted incident affects these concepts in that period."


@beta_tool
def price_routes(product_id: str) -> str:
    """Which routes (location concept + incoterm) have verified price assessments for a product, with counts and date range.
    Call this before price_monthly to pick routes that actually have data.

    Args:
        product_id: Product concept id, e.g. "dap".
    """
    rows = read_graph(
        "MATCH (p:PriceAssessment)-[:OF]->(:Concept {id: $product}), (p)-[:AT]->(l:Concept), (p)-[:BASIS]->(i:Concept) "
        "RETURN l.id AS location_id, i.id AS incoterm_id, count(*) AS n, min(p.date) AS first, max(p.date) AS last ORDER BY n DESC",
        product=product_id,
    )
    return json.dumps(rows) if rows else "No verified price assessments for this product."


@beta_tool
def price_monthly(product_id: str, location_id: str, incoterm_id: str, date_from: str, date_to: str) -> str:
    """Monthly statistics of price assessments extracted (quote-verified) from Argus daily reports: number of assessments,
    average midpoint, lowest low, highest high, in $/t. Numbers are computed by the database, not estimated.

    Args:
        product_id: Product concept id, e.g. "dap".
        location_id: Country/region concept id, e.g. "country_india" or "country_morocco".
        incoterm_id: Incoterm concept id: "fob", "cfr", "fca", "cpt_cip", "exw" or "cif".
        date_from: Inclusive start date, YYYY-MM-DD.
        date_to: Inclusive end date, YYYY-MM-DD.
    """
    rows = read_graph(
        "MATCH (p:PriceAssessment)-[:OF]->(:Concept {id: $product}), (p)-[:AT]->(:Concept {id: $location}), (p)-[:BASIS]->(:Concept {id: $incoterm}) "
        "WHERE p.date >= $from AND p.date <= $to "
        "RETURN substring(p.date, 0, 7) AS month, count(*) AS n, round(avg(p.mid), 1) AS avg_mid, min(p.low) AS min_low, max(p.high) AS max_high "
        "ORDER BY month",
        product=product_id, location=location_id, incoterm=incoterm_id, **{"from": date_from, "to": date_to},
    )
    return json.dumps(rows) if rows else "No verified price assessments for this product, location and incoterm in that period."


@beta_tool
def price_assessments(product_id: str, location_id: str, date_from: str, date_to: str) -> str:
    """Individual price assessments (with verbatim quote and article id) for a product at a location, by date (max 50).

    Args:
        product_id: Product concept id, e.g. "dap".
        location_id: Country/region concept id, e.g. "country_china".
        date_from: Inclusive start date, YYYY-MM-DD.
        date_to: Inclusive end date, YYYY-MM-DD.
    """
    rows = read_graph(
        "MATCH (p:PriceAssessment)-[:OF]->(:Concept {id: $product}), (p)-[:AT]->(:Concept {id: $location}), (p)-[:REPORTED_IN]->(a:Article) "
        "WHERE p.date >= $from AND p.date <= $to "
        "RETURN p.date AS date, p.incoterm AS incoterm, p.low AS low, p.high AS high, p.change AS change, p.quote AS quote, a.id AS article_id ORDER BY date",
        product=product_id, location=location_id, **{"from": date_from, "to": date_to},
    )
    return json.dumps(rows, ensure_ascii=False) if rows else "No verified price assessments for this product and location in that period."
