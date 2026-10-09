#!/bin/sh
# One-shot graph load for compose: wait for Neo4j, then ontology -> referentials -> workbook graph.
set -e
cd /app/src
until python -c "from graph import driver; driver.verify_connectivity()" 2>/dev/null; do echo "waiting for neo4j"; sleep 3; done
python load_knowledge.py --dry-run   # log what the reload changes
python load_knowledge.py
python import_referentials.py
python import_referential_yaml.py
python load_term_additions.py
python load_supply_chain.py       # lanes: what OCP buys, sells, competes with, and the routes between
python workbook_graph.py
python import_caster_knowledge.py
python news_graph.py
python news_extract.py load        # LLM step is manual: python news_extract.py extract
python entity_resolution.py load    # LLM step is manual: python entity_resolution.py propose
