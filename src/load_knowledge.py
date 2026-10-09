"""Load knowledge/ontology.yaml into Neo4j. Wipes the knowledge layer and reloads it (idempotent).

  python load_knowledge.py            # reload
  python load_knowledge.py --dry-run  # only show what the reload would change in the ontology part of the graph, and what it would orphan

Ontology nodes and relations carry source: 'ontology' so the dry run can tell them apart from referential imports.
"""
import os
import sys
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
TERM_ADDITIONS = Path(__file__).parent.parent / "knowledge" / "term_additions.yaml"
# Edges other loaders hang on concepts; the reload drops them for a removed concept and the later loaders cannot rebuild them.
DEPENDENT_EDGES = "MATCH (c:Concept {id: id})<-[r]-(x) WHERE NOT x:Term AND coalesce(r.source, '') <> 'ontology' RETURN id, labels(x)[0] AS from, type(r) AS rel, count(*) AS n"


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


def plan(data: dict, session) -> list[str]:
    """Differences between ontology.yaml and the ontology currently in the graph, plus what removed concepts would orphan."""
    new_concepts = {c["id"]: c for c in data["concepts"]}
    old_concepts = {r["id"]: r for r in session.run(
        "MATCH (c:Concept {source: 'ontology'}) RETURN c.id AS id, c.kind AS kind, c.name AS name, c.definition AS definition").data()}
    new_terms = {(t, c["id"]) for c in data["concepts"] for t in c["terms"]}
    old_terms = {(r["text"], r["id"]) for r in session.run(
        "MATCH (t:Term {source: 'ontology'})-[:REFERS_TO]->(c:Concept) RETURN t.text AS text, c.id AS id").data()}
    new_rels = {tuple(r) for r in data["relations"]}
    old_rels = {(r["src"], r["rel"], r["dst"]) for r in session.run(
        "MATCH (a:Concept)-[r {source: 'ontology'}]->(b:Concept) RETURN a.id AS src, type(r) AS rel, b.id AS dst").data()}

    lines = []
    if not old_concepts:
        lines.append("note: no concept in the graph is tagged source='ontology' (never loaded with this version): everything shows as added")
    added, removed = sorted(new_concepts.keys() - old_concepts.keys()), sorted(old_concepts.keys() - new_concepts.keys())
    lines += [f"+ concept {i} ({new_concepts[i]['kind']})" for i in added]
    lines += [f"- concept {i} ({old_concepts[i]['kind']})" for i in removed]
    for i in sorted(new_concepts.keys() & old_concepts.keys()):
        changed = [k for k in ("kind", "name", "definition") if new_concepts[i][k] != old_concepts[i][k]]
        lines += [f"~ concept {i}.{k}: {old_concepts[i][k]!r} -> {new_concepts[i][k]!r}" for k in changed]
    lines += [f"+ term {t!r} -> {c}" for t, c in sorted(new_terms - old_terms)]
    lines += [f"- term {t!r} -> {c}" for t, c in sorted(old_terms - new_terms)]
    lines += [f"+ relation {a} {r} {b}" for a, r, b in sorted(new_rels - old_rels)]
    lines += [f"- relation {a} {r} {b}" for a, r, b in sorted(old_rels - new_rels)]

    if removed:
        for r in session.run("UNWIND $ids AS id " + DEPENDENT_EDGES, ids=removed).data():
            lines.append(f"! {r['id']}: {r['n']} {r['from']} -[{r['rel']}]-> edges will be lost")
    additions = yaml.safe_load(TERM_ADDITIONS.read_text(encoding="utf-8"))["terms"] if TERM_ADDITIONS.exists() else []
    lines += [f"! term_additions.yaml: {t['text']!r} points to removed concept {t['concept']} (load_term_additions.py will fail)"
              for t in additions if t["concept"] in removed]
    return lines


def main() -> None:
    data = load_ontology()
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    if "--dry-run" in sys.argv:
        with driver.session() as s:
            lines = plan(data, s)
        driver.close()
        print("\n".join(lines) if lines else "no change")
        return
    with driver.session() as s:
        s.run("CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE")
        s.run("MATCH (n) WHERE n:Concept OR n:Term DETACH DELETE n")
        for c in data["concepts"]:
            s.run(
                f"CREATE (c:Concept:{LABELS[c['kind']]} {{id: $id, kind: $kind, name: $name, definition: $definition, source: 'ontology'}}) "
                "WITH c UNWIND $terms AS term CREATE (:Term {text: term, source: 'ontology'})-[:REFERS_TO]->(c)",
                id=c["id"], kind=c["kind"], name=c["name"], definition=c["definition"], terms=c["terms"],
            )
        for src, rel, dst in data["relations"]:
            s.run(f"MATCH (a:Concept {{id: $src}}), (b:Concept {{id: $dst}}) CREATE (a)-[:{rel} {{source: 'ontology'}}]->(b)", src=src, dst=dst)
    driver.close()
    print(f"loaded {len(data['concepts'])} concepts, {len(data['relations'])} relations")


if __name__ == "__main__":
    main()
