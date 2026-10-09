"""Load knowledge/ontology.yaml into Neo4j. Wipes the knowledge layer and reloads it (idempotent)."""
import os
from pathlib import Path

import yaml
from neo4j import GraphDatabase

LABELS = {
    "org_unit": "OrgUnit",
    "site": "Site",
    "product": "Product",
    "input": "Input",
    "metric": "Metric",
    "unit": "Unit",
    "incoterm": "Incoterm",
    "route": "Route",
    "country": "Country",
    "region": "Region",
}
RELATIONS = {"PART_OF", "PRODUCED_AT", "MADE_FROM", "DEPENDS_ON", "MEASURED_IN", "TRANSITS", "IN_REGION"}
ONTOLOGY = Path(__file__).parent.parent / "knowledge" / "ontology.yaml"


def load_ontology() -> dict:
    data = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
    ids = [c["id"] for c in data["concepts"]]
    assert len(ids) == len(set(ids)), "duplicate concept id"
    for c in data["concepts"]:
        assert c["kind"] in LABELS, f"unknown kind {c['kind']} on {c['id']}"
        assert c["name"] and c["definition"] and c["terms"], f"incomplete concept {c['id']}"
    for src, rel, dst in data["relations"]:
        assert rel in RELATIONS, f"unknown relation {rel}"
        assert src in ids and dst in ids, f"dangling relation {src} {rel} {dst}"
    return data


def main() -> None:
    data = load_ontology()
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        s.run("CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE")
        s.run("MATCH (n) WHERE n:Concept OR n:Term DETACH DELETE n")
        for c in data["concepts"]:
            s.run(
                f"CREATE (c:Concept:{LABELS[c['kind']]} {{id: $id, kind: $kind, name: $name, definition: $definition}}) "
                "WITH c UNWIND $terms AS term CREATE (:Term {text: term})-[:REFERS_TO]->(c)",
                id=c["id"], kind=c["kind"], name=c["name"], definition=c["definition"], terms=c["terms"],
            )
        for src, rel, dst in data["relations"]:
            s.run(f"MATCH (a:Concept {{id: $src}}), (b:Concept {{id: $dst}}) CREATE (a)-[:{rel}]->(b)", src=src, dst=dst)
    driver.close()
    print(f"loaded {len(data['concepts'])} concepts, {len(data['relations'])} relations")


if __name__ == "__main__":
    main()
