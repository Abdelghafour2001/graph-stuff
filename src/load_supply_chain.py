"""Load knowledge/supply_chain.yaml into Neo4j as (:Lane) nodes. Run after load_knowledge.py and import_referentials.py
(lanes hang on concepts and countries, which those reloads recreate).

  (:Lane {id, role, status, share, basis})-[:CARRIES]->(item) -[:FROM]->(origin country) -[:TO]->(OCP site or destination country)
  (:Lane)-[:VIA {order}]->(route)

  python load_supply_chain.py            # reload
  python load_supply_chain.py --check    # validate the file only (no Neo4j)
"""
import sys
from pathlib import Path

import yaml

FILE = Path(__file__).parent.parent / "knowledge" / "supply_chain.yaml"
ONTOLOGY = Path(__file__).parent.parent / "knowledge" / "ontology.yaml"
ROLES = {"supply", "export", "competitor"}
STATUSES = {"public", "confirmed"}


def load_lanes() -> list[dict]:
    """Lanes with ids, validated against the ontology (items, routes, sites); countries are checked at load time."""
    onto = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
    kinds = {c["id"]: c["kind"] for c in onto["concepts"]}
    lanes = yaml.safe_load(FILE.read_text(encoding="utf-8"))["lanes"]
    for i, lane in enumerate(lanes):
        where = f"lane {i + 1} ({lane.get('item')} {lane.get('role')})"
        assert lane["role"] in ROLES, f"{where}: role must be one of {ROLES}"
        assert lane.get("status") in STATUSES, f"{where}: status must be one of {STATUSES}"
        assert kinds.get(lane["item"]) in {"product", "input"}, f"{where}: item {lane['item']} is not a product or input concept"
        for r in lane.get("via") or []:
            assert kinds.get(r) == "route", f"{where}: {r} is not a route concept in ontology.yaml"
        assert lane["origin"].startswith("country_"), f"{where}: origin must be a country id"
        if lane["role"] == "supply":
            assert kinds.get(lane.get("to")) == "site", f"{where}: a supply lane goes to an OCP site (to: jorf_lasfar, ...)"
        elif lane["role"] == "export":
            assert str(lane.get("destination", "")).startswith("country_"), f"{where}: an export lane needs a destination country"
        share = lane.get("share")
        assert share is None or (lane["status"] == "confirmed" and 0 <= share <= 1), f"{where}: share only for confirmed lanes, 0..1"
        lane["id"] = f"lane:{lane['role']}:{lane['item']}:{lane['origin']}:{lane.get('to') or lane.get('destination') or 'world'}"
        lane["via"] = lane.get("via") or []
    ids = [lane["id"] for lane in lanes]
    assert len(ids) == len(set(ids)), "duplicate lane"
    return lanes


def main() -> None:
    lanes = load_lanes()
    if "--check" in sys.argv:
        print(f"{len(lanes)} lanes ok")
        return
    from graph import driver
    with driver.session() as s:
        countries = {lane["origin"] for lane in lanes} | {lane["destination"] for lane in lanes if lane.get("destination")}
        found = {r["id"] for r in s.run("MATCH (c:Concept) WHERE c.id IN $ids RETURN c.id AS id", ids=list(countries)).data()}
        missing = sorted(countries - found)
        if missing:
            print(f"warning: countries not in the graph (run import_referentials.py first?): {missing}; their edges are skipped")
        s.run("MATCH (l:Lane) DETACH DELETE l")
        s.run(
            "UNWIND $lanes AS l CREATE (n:Lane {id: l.id, role: l.role, status: l.status, share: l.share, basis: l.basis}) "
            "WITH n, l MATCH (item:Concept {id: l.item}) CREATE (n)-[:CARRIES]->(item) "
            "WITH n, l OPTIONAL MATCH (o:Concept {id: l.origin}) FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | CREATE (n)-[:FROM]->(o)) "
            "WITH n, l OPTIONAL MATCH (d:Concept {id: coalesce(l.to, l.destination)}) FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END | CREATE (n)-[:TO]->(d)) "
            "WITH n, l UNWIND range(0, size(l.via) - 1) AS k MATCH (r:Concept {id: l.via[k]}) CREATE (n)-[:VIA {order: k}]->(r)",
            lanes=[{**lane, "to": lane.get("to"), "destination": lane.get("destination"), "share": lane.get("share"),
                    "basis": lane.get("basis", "")} for lane in lanes],
        )
        n = s.run("MATCH (l:Lane) RETURN count(l) AS n").single()["n"]
    print(f"loaded {n} lanes ({sum(lane['status'] == 'confirmed' for lane in lanes)} confirmed by OCP)")


if __name__ == "__main__":
    main()
