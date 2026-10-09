"""Import aliases and mappings from the market-intel ingestion referential (knowledge/market_intel_referential.yaml,
a snapshot of genai-corporate-data-ingestion/src/excel_ingestion/config/referential.yaml). Run after import_referentials.py.

Adds Terms for country/region/product aliases, country -> region IN_REGION edges, and Company concepts.
"""
from pathlib import Path

import yaml

from graph import driver

REFERENTIAL = Path(__file__).parent.parent / "knowledge" / "market_intel_referential.yaml"
PLACEHOLDERS = {"", "nan", "none", "null", "undefined"}


def human(name: str) -> str:
    return str(name).replace("_", " ").strip()


def main() -> None:
    ref = yaml.safe_load(REFERENTIAL.read_text(encoding="utf-8"))
    with driver.session() as s:
        regions = sorted(set(ref["regions"]) | set(ref["region_aliases"].values()) | set(ref["country_region_mapping"].values()))
        s.run(
            "UNWIND $rows AS r MERGE (c:Concept {id: r.id}) "
            "ON CREATE SET c:Region, c.kind = 'region', c.name = r.name, c.definition = 'Market region (ingestion referential).' "
            "MERGE (t:Term {text: r.name})-[:REFERS_TO]->(c)",
            rows=[{"id": f"region_{r}", "name": human(r)} for r in regions],
        )
        s.run(
            "UNWIND $rows AS r MATCH (c:Concept {id: r.target}) MERGE (t:Term {text: r.alias})-[:REFERS_TO]->(c)",
            rows=[{"alias": human(a), "target": f"region_{r}"} for a, r in ref["region_aliases"].items() if str(a).lower() not in PLACEHOLDERS]
            + [{"alias": human(a), "target": f"country_{c}"} for a, c in ref["country_aliases"].items()],
        )
        s.run(
            "UNWIND $rows AS r MATCH (c:Concept {id: r.country}), (g:Concept {id: r.region}) MERGE (c)-[:IN_REGION]->(g)",
            rows=[{"country": f"country_{c}", "region": f"region_{r}"} for c, r in ref["country_region_mapping"].items()],
        )
        s.run(
            "UNWIND $rows AS r MATCH (t0:Term)-[:REFERS_TO]->(c:Concept {kind: 'product'}) WHERE toLower(t0.text) = r.canonical "
            "WITH DISTINCT r, c MERGE (t:Term {text: r.alias})-[:REFERS_TO]->(c)",
            rows=[{"alias": human(a), "canonical": human(p).lower()} for a, p in ref["product_aliases"].items()],
        )
        s.run(
            "UNWIND $names AS n MERGE (c:Concept {id: 'company_' + n}) "
            "ON CREATE SET c:Company, c.kind = 'company', c.name = replace(n, '_', ' '), c.definition = 'Company (ingestion referential).' "
            "MERGE (t:Term {text: replace(n, '_', ' ')})-[:REFERS_TO]->(c)",
            names=ref["companies"],
        )
        counts = s.run("MATCH (c:Concept) RETURN c.kind AS kind, count(*) AS n ORDER BY n DESC").data()
    print("concepts by kind after referential import:", counts)


if __name__ == "__main__":
    main()
