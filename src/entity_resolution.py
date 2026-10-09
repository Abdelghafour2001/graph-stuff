"""Entity specialist, first job: resolve the ~150 OCP-related records of the market-intel referential into canonical assets.

  python entity_resolution.py propose   # LLM (strong model) proposes clusters -> data/entity_resolution_ocp.json (costs money)
  python entity_resolution.py load      # deterministic: validate the proposal and load it into the graph (run by the loader)

Graph: (:SourceEntity {id, name, type, country, products, metrics})-[:SAME_AS {status}]->(:Asset {id, name, kind, confidence, reason})
       (:Asset)-[:LOCATED_AT]->(site Concept), (:Asset)-[:PART_OF]->(:Concept {id: 'ocp_group'}) for OCP-controlled assets.
Merges stay status 'proposed' until a human approves them.
"""
import json
import os
import sys
from pathlib import Path

import psycopg

from graph import driver

PROPOSAL = Path(__file__).parent.parent / "data" / "entity_resolution_ocp.json"
SITES = ["khouribga", "benguerir", "youssoufia", "boucraa", "jorf_lasfar", "safi"]
KINDS = ["company", "joint_venture", "mine", "chemical_platform", "plant", "production_line", "project", "other"]
SQL = r"""
select e.entity_id, e.entity_name, t.type_name, coalesce(c.country_name, ''), coalesce(p.entity_name, ''),
  coalesce((select string_agg(distinct rp.product_name, ',') from market_knowledge_data.metrics m
            join market_knowledge_data.ref_products rp using (product_id) where m.entity_id = e.entity_id), ''),
  (select count(*) from market_knowledge_data.metrics m where m.entity_id = e.entity_id)
from market_knowledge_data.ref_entities e join market_knowledge_data.ref_entity_types t using (entity_type_id)
left join market_knowledge_data.ref_countries c using (country_id)
left join market_knowledge_data.ref_entities p on p.entity_id = e.parent_entity_id
where e.entity_name like 'ocp%' or e.entity_name like '%\_ocp%' order by e.entity_name
"""
PROMPT = f"""You resolve duplicate records of OCP Group assets coming from several market-intelligence providers (CRU, Argus, S&P).
Each input line is: id | name | type | country | parent | products | number of metrics.
Group records that denote the SAME real-world asset (same company, JV, mine, chemical platform, plant or production line).
Keep different production lines separate only if they are clearly distinct units (e.g. JFC I vs JFC II); group spelling variants
(laayoune / layoune / la_youne), provider prefixes (ocp_sa_ocp_-_, morocco_ocp_, ocp_ocp_) and site/plant naming variants.
Return JSON {{"assets": [{{"canonical_id": "snake_case", "name": "readable name", "kind": one of {KINDS},
"site": one of {SITES} or null, "country": "snake_case country", "ocp_controlled": true|false,
"members": [record ids], "confidence": "high|medium|low", "reason": "one sentence"}}]}}.
Every record id must appear in exactly one asset. Singletons are fine."""


def fetch() -> list[tuple]:
    with psycopg.connect(os.environ["MARKET_INTEL_DSN"]) as pg:
        return pg.execute(SQL).fetchall()


def propose() -> None:
    import llm  # only this step needs LLM credentials

    records = fetch()
    lines = "\n".join(" | ".join(str(v) for v in r) for r in records)
    proposal = llm.json_completion(PROMPT, lines, "AZURE_OPENAI_AGENT_DEPLOYMENT")
    assigned = {m for a in proposal["assets"] for m in a["members"]}
    missing = [r for r in records if r[0] not in assigned]  # records the model left out become singletons flagged for review
    proposal["assets"] += [{"canonical_id": f"unassigned_{r[0]}", "name": r[1], "kind": "other", "site": None, "country": r[3] or "unknown",
                            "ocp_controlled": False, "members": [r[0]], "confidence": "low", "reason": "Not assigned by the model; review manually."}
                           for r in missing]
    PROPOSAL.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"proposal for {len(records)} records written to {PROPOSAL} ({len(missing)} left unassigned by the model)")


def load() -> None:
    records = {r[0]: r for r in fetch()}
    assets = json.loads(PROPOSAL.read_text(encoding="utf-8"))["assets"]
    members = [m for a in assets for m in a["members"]]
    assert sorted(members) == sorted(records), f"every record exactly once: missing {set(records) - set(members)}, duplicated {len(members) - len(set(members))}, unknown {set(members) - set(records)}"
    assert all(a["kind"] in KINDS and a["site"] in [*SITES, None] for a in assets), "unknown kind or site in proposal"
    with driver.session() as s:
        s.run("MATCH (n) WHERE n:SourceEntity OR n:Asset DETACH DELETE n")
        s.run(
            "UNWIND $rows AS r CREATE (:SourceEntity {id: r[0], name: r[1], type: r[2], country: r[3], parent: r[4], products: r[5], metrics: r[6]})",
            rows=[list(r) for r in records.values()],
        )
        s.run(
            "UNWIND $assets AS a CREATE (x:Asset {id: 'asset_' + a.canonical_id, name: a.name, kind: a.kind, country: a.country, "
            "confidence: a.confidence, reason: a.reason, ocp_controlled: a.ocp_controlled}) "
            "WITH x, a UNWIND a.members AS m MATCH (e:SourceEntity {id: m}) CREATE (e)-[:SAME_AS {status: 'proposed'}]->(x) "
            "WITH DISTINCT x, a OPTIONAL MATCH (site:Concept {id: a.site}) FOREACH (_ IN CASE WHEN site IS NULL THEN [] ELSE [1] END | CREATE (x)-[:LOCATED_AT]->(site)) "
            "WITH x, a MATCH (g:Concept {id: 'ocp_group'}) FOREACH (_ IN CASE WHEN a.ocp_controlled THEN [1] ELSE [] END | CREATE (x)-[:PART_OF]->(g))",
            assets=assets,
        )
    merged = sum(1 for a in assets if len(a["members"]) > 1)
    print(f"{len(records)} records -> {len(assets)} assets ({merged} merges of 2+ records)")


if __name__ == "__main__":
    {"propose": propose, "load": load}[sys.argv[1]]()
