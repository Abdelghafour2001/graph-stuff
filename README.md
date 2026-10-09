# OCP P&L Graph Agent: POC

The goal is agentic P&L computation across OCP branches and BUs on top of a Neo4j graph, with every number traceable to its source and every change explainable.

## Docs

- [Vision and architecture](docs/01-vision.md)
- [Research notes](docs/02-research-notes.md) (SheetCompass, agentic reasoning graphs, Graph-PReFLexOR)
- [Roadmap, status, open questions](docs/03-roadmap.md)
- [Market-intel data findings + DAP/US–Iran war design](docs/04-market-intel-findings.md)
- [Prior art sweep (papers + repos) and decisions](docs/05-prior-art.md)
- [Notes on the market-intel ingestion repo (referential, caster docs)](docs/06-ingestion-repo-notes.md)
- [Sub-agents: orchestrator + impact, workbook and news specialists (built), market/entity/business (proposed)](docs/07-subagents.md)
- [Sample files review (Argus, CRU, S&P, vessel tracker)](docs/09-sample-files-review.md)
- [P&L agent: branch submissions without templates, structure discovery, P&L engine (design + prototype)](docs/10-pnl-agent.md); try `python scripts/sample_branch.py /tmp/b.xlsx && python scripts/discover_submission.py /tmp/b.xlsx`
- [Variance diagnosis: why a margin moved (design, with animated architecture)](docs/08-variance-diagnosis.md)
- [From world events to OCP: the exposure walk ("OCP lost a lot this year, why?")](docs/11-exposure.md): events → routes and countries → what OCP buys, sells and competes with → products and sites; lanes in `knowledge/supply_chain.yaml`
- Architecture figures (French, SVG importable into Figma): [agentic architecture](docs/figures/01-architecture-agentique.svg), [data flows](docs/figures/02-flux-de-donnees.svg), [graph creation process](docs/figures/03-creation-du-graphe.svg), [branch submission discovery and P&L](docs/figures/04-decouverte-pnl.svg); regenerate with `python docs/figures/build_figures.py`
- UI design: [DESIGN.md](DESIGN.md) (IBM Carbon tokens adapted to a data product; theme in `.streamlit/config.toml`). Skills in `.claude/skills/`: `web-design-guidelines` (review UI changes for accessibility and UX, rules vendored from Vercel Labs) and `taste-skill` (for docs pages and redesigns, not for data tables). Source style: [docs/design/ibm-carbon.DESIGN.md](docs/design/ibm-carbon.DESIGN.md) from VoltAgent/awesome-design-md

Core rule: **the LLM never computes or invents numbers.** Agents maintain structure and a deterministic engine does the math.

## Layout

```
knowledge/ontology.yaml   business concepts, terms (synonyms), relations: the file domain experts edit
knowledge/proposals.jsonl terms the agent did not know and proposed (human review queue)
src/load_knowledge.py     validates the ontology and loads it into Neo4j
src/agent.py              Claude agent with graph tools
src/excel_tools.py        find_sheets / describe_sheet / read_range / propose_extraction_spec
src/workbook_graph.py     Workbook -> Sheet -> Concept graph from the Excel profile
src/variance.py           why a metric moved: ranked drivers, deterministic (tools in src/variance_tools.py)
scripts/eval_variance.py  injected-shock evaluation of the variance diagnosis
scripts/profile_excels.py layout profiler (headers, blocks, formulas, merged cells)
```

The graph model is:

- `(:Concept:<OrgUnit|Site|Product|Input|Metric|Unit> {id, name, definition})`
- `(:Term {text})-[:REFERS_TO]->(:Concept)`: every word people use for the concept
- `PART_OF`, `PRODUCED_AT`, `MADE_FROM`, `DEPENDS_ON`, `MEASURED_IN`

The agent has four tools. `lookup_term`, `describe_concept` and `run_cypher` are read-only, which is enforced by a Neo4j read transaction. `propose_term` writes only to the review queue.

## Run (containers, recommended)

```bash
podman compose up -d --build     # neo4j, market-intel-db (existing volume), loader (one-shot graph load), api, ui
```

- **UI:** http://localhost:8501. Tabs: chat with the agent (with its tool calls), variance diagnosis with its review queue, workbook explorer (sheets by concept, skeleton, cell ranges), spec review (checks, sample rows with source cells, approve), eval results.
- **API:** http://localhost:8010/docs (FastAPI Swagger).
- **Graph:** http://localhost:7474 (Neo4j Browser; neo4j / ocp-poc-password).
- `.env` must define `EXCEL_DIR` (host folder of the market-intel workbooks), the LLM provider settings, and the rest of `.env.example`.
- **Azure OpenAI check:** `python scripts/check_azure.py` (or `podman compose run --rm api python /app/scripts/check_azure.py` to test from inside the container) checks DNS, the key, both deployment names and tool calling. `AZURE_OPENAI_DEPLOYMENT` and `AZURE_OPENAI_AGENT_DEPLOYMENT` are deployment names from Azure AI Foundry, not model names.
- **LLM provider:** `LLM_PROVIDER=azure_openai`, `bifrost` (Qwen behind the Bifrost gateway; check it first with `python scripts/check_gateway.py` on the office network) or anything else for the Claude API.
- The market-intel Postgres volume `corporate-geni-strategy-intel_postgresql` is reused as-is (external volume). Don't run the market-intel project's own Postgres at the same time.

## Run (local Python, for development)

```bash
podman compose up -d        # or: podman run -d --name ocp-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/ocp-poc-password docker.io/library/neo4j:5-community
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
# put the variables from .env.example in .env (loaded automatically). LLM_PROVIDER=azure_openai uses AZURE_OPENAI_*; anything else uses Claude (ANTHROPIC_API_KEY)
.venv/Scripts/python src/load_knowledge.py
.venv/Scripts/python src/import_referentials.py        # needs market-intel Postgres (MARKET_INTEL_DSN)
.venv/Scripts/python src/import_referential_yaml.py    # aliases from the ingestion referential
.venv/Scripts/python scripts/profile_excels.py "$EXCEL_DIR"
.venv/Scripts/python src/workbook_graph.py
.venv/Scripts/python src/agent.py
```

The Neo4j browser is at http://localhost:7474 (neo4j / ocp-poc-password).

Try these questions:

- "C'est quoi l'ACP et à partir de quoi on le fabrique ?"
- "Which purchased inputs drive the cost of DAP, end to end?"
- "Si le prix du soufre monte, quelles marges sont touchées ?"
- "What does PCI mean and why does it matter for group consolidation?"
- An unknown term, e.g. "What is the BL of Khouribga?", should make the agent say it does not know and queue a proposal.
- "Pourquoi la marge DAP a baissé en août 2026 ?" runs the variance playbook (diagnose_variance, then submit_diagnosis).

Tests: `python -m pytest tests` (no database needed). Variance diagnosis on the real graph: `python scripts/smoke_variance.py` (see [docs/08](docs/08-variance-diagnosis.md#running-it-on-the-real-graph)).

## Before showing to finance

The org units, sites and definitions in `ontology.yaml` are an **illustrative seed**. BU controllers need to validate them and add their real jargon. Adding a term means one line in YAML followed by a reload.
