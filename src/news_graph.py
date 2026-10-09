"""News subgraph, deterministic part: every Argus article becomes (:Article) linked to the concepts it mentions.

Matching uses the graph's own Terms (same vocabulary as the workbook graph), on the headline and the start of the text.
Article text stays in Postgres; tools fetch it on demand.
"""
import os
import re
from collections import Counter, defaultdict

import psycopg

from graph import driver

SQL = """
select "NewsId", "Headline", left("PublicationDate", 10), "LANGUAGE_Name", left("Text", 3000)
from corporate_data.argus_news where "Headline" is not null
"""
BATCH = 2000


def term_matcher(session) -> tuple[re.Pattern, dict[str, set[str]]]:
    """One alternation regex over all terms (longest first) plus term -> concept ids."""
    concepts = defaultdict(set)
    for r in session.run("MATCH (t:Term)-[:REFERS_TO]->(c:Concept) RETURN t.text AS text, c.id AS id").data():
        if len(r["text"]) >= 3:
            concepts[r["text"].lower()].add(r["id"])
    alternation = "|".join(re.escape(t) for t in sorted(concepts, key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z0-9])(" + alternation + r")(?![A-Za-z0-9])", re.IGNORECASE), concepts


def main() -> None:
    with psycopg.connect(os.environ["MARKET_INTEL_DSN"]) as pg:
        articles = pg.execute(SQL).fetchall()
    with driver.session() as s:
        s.run("CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE")
        s.run("CREATE INDEX article_date IF NOT EXISTS FOR (a:Article) ON (a.published_at)")
        s.run("MATCH (a:Article) CALL (a) { DETACH DELETE a } IN TRANSACTIONS OF 5000 ROWS")
        pattern, concepts = term_matcher(s)
        links = 0
        for i in range(0, len(articles), BATCH):
            rows = []
            for news_id, headline, date, language, text in articles[i:i + BATCH]:
                counts = Counter(cid for m in pattern.findall(f"{headline}\n{text or ''}") for cid in concepts[m.lower()])
                rows.append({"id": news_id, "headline": headline, "date": date, "language": language,
                             "mentions": [{"id": cid, "n": n} for cid, n in counts.items()]})
                links += len(counts)
            s.run(
                "UNWIND $rows AS r CREATE (a:Article {id: r.id, headline: r.headline, published_at: r.date, language: r.language}) "
                "WITH a, r UNWIND r.mentions AS m MATCH (c:Concept {id: m.id}) CREATE (a)-[:MENTIONS {n: m.n}]->(c)",
                rows=rows,
            )
            print(f"{min(i + BATCH, len(articles))}/{len(articles)} articles", flush=True)
    print(f"loaded {len(articles)} articles, {links} concept links")


if __name__ == "__main__":
    main()
