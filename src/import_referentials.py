"""Import countries and regions from the market-intel referential into the graph. Run after load_knowledge.py."""
import os

import psycopg
from neo4j import GraphDatabase

REGIONS_SQL = "select region_id, region_name from market_knowledge_data.ref_regions"
COUNTRIES_SQL = "select country_name, region_id from market_knowledge_data.ref_countries"


def human(name: str) -> str:
    return name.replace("_", " ").strip()


def main() -> None:
    with psycopg.connect(os.environ["MARKET_INTEL_DSN"]) as pg:
        regions = pg.execute(REGIONS_SQL).fetchall()
        countries = pg.execute(COUNTRIES_SQL).fetchall()
    region_ids = {rid: f"region_{name}" for rid, name in regions}

    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        s.run(
            "UNWIND $rows AS r CREATE (c:Concept:Region {id: r.id, kind: 'region', name: r.name, definition: 'Market region (market-intel referential).'}) "
            "CREATE (:Term {text: r.name})-[:REFERS_TO]->(c)",
            rows=[{"id": region_ids[rid], "name": human(name)} for rid, name in regions],
        )
        s.run(
            "UNWIND $rows AS r CREATE (c:Concept:Country {id: r.id, kind: 'country', name: r.name, definition: 'Country (market-intel referential).'}) "
            "CREATE (:Term {text: r.name})-[:REFERS_TO]->(c) "
            "WITH c, r MATCH (g:Region {id: r.region}) CREATE (c)-[:IN_REGION]->(g)",
            rows=[{"id": f"country_{name}", "name": human(name), "region": region_ids.get(rid)} for name, rid in countries],
        )
    driver.close()
    print(f"imported {len(regions)} regions, {len(countries)} countries")


if __name__ == "__main__":
    main()
