# Sub-Agents with Their Own Graphs: Design Proposal

*2026-09-25. Status: proposal. Today's code has one agent with Excel and graph tools; this is the target shape.*

## Idea

Instead of one agent that knows everything, we run **specialist agents, each owning a subgraph** (its own node types, tools, memory and review queue), plus an **orchestrator** that splits the question, calls the specialists, and assembles one cited answer.

The specialists do not share their internals. They share the **core concepts** (`dap`, `ammonia`, `country_morocco`, `hormuz`, `company_maaden`…). A concept id is the join key between subgraphs; call it the "concept bus". That is why the core ontology and vocabulary work matter: every specialist links into the same concepts.

```
                              ┌──────────────┐
            question ───────► │ Orchestrator │ ── decompose, route, merge, Reflector (every claim cites a node)
                              └──────┬───────┘
          ┌──────────────┬───────────┼─────────────┬──────────────────┐
          ▼              ▼           ▼             ▼                  ▼
   Workbook agent   Market agent  News agent   Entity agent     Business/P&L agent
   Workbook/Sheet/  Series/       Article/     SourceEntity →   core ontology,
   Caster/Spec      Forecast      Event        Plant/Company    formula DAG
          └──────────────┴────── shared (:Concept) nodes ─────┴──────────────────┘
```

## The specialists

| Agent | Owns (subgraph) | Tools | Status |
|---|---|---|---|
| **Workbook agent** | `Workbook`, `Sheet`, `Caster` (old-pipeline layout memory), `Spec` | `find_sheets`, `describe_sheet`, `read_range`, `propose_extraction_spec` (+ executor, Reflector checks, DB diff) | **Built** |
| **Market agent** | `Series {product, location, incoterm, unit, freq, source}` → values in Postgres; `Forecast {model, as_of}` | `find_series(concepts)`, `get_series(id, from, to)` (deterministic), `compare_periods` | Next. `v_prices` / `v_supply` / `v_trades` already hold the values |
| **News agent** | `Article` (37.6k), `Event` (757), `PriceAssessment` (2.8k), `AFFECTS {direction, channel}` → Concept | `search_articles`, `read_article`, `event_timeline`, `price_routes`, `price_monthly`, `price_assessments` (all "as of" date_to) | **Built** (2026-09-26); event dedup (Graphiti) later |
| **Entity agent** | `SourceEntity` (149 OCP-related records so far) → `SAME_AS {status}` → `Asset` → `LOCATED_AT` site | `resolve_entity`, `ocp_assets` | **Built for OCP** (2026-09-26): 61 assets, 36 merges, human approval in UI. Next: competitors (Maaden, Mosaic…) |
| **Business / P&L agent** | Core ontology, org tree, `Formula` DAG, `Observation` | `lookup_term`, `describe_concept`, `compute(metric, period)` (deterministic) | Core built; P&L later |

## Rules that make this safe

1. **Specialists return claims plus evidence ids**, never free text alone: `{claim, evidence: [node ids, cells, article ids], confidence}`. The orchestrator's Reflector drops any claim without evidence.
2. **Numbers come only from deterministic tools** (series queries, the spec executor, computations). LLMs choose, explain and structure.
3. **Writes to any subgraph go through review queues** (terms, specs, merges, event links), with auto-accept only for low-impact items.
4. **Time discipline:** every query can be "as of" a publication date (avoids look-ahead leakage; see prior-art doc).
5. **One Neo4j database, namespaced by label.** Community edition has one user database, and the shared concepts must be joinable anyway. "Own graph" means own labels, tools, memory and review queue, not a separate DB.

## How the DAP / US–Iran war question flows

1. **Orchestrator** resolves `dap`, the war event cluster and `hormuz`, and plans three sub-questions.
2. **News agent** returns the event timeline (war start ~2026-03-01, pause 2026-06-29) and events that `AFFECTS` sulphur / ammonia / Saudi DAP exports through `hormuz`, with article ids. It also returns **price assessments extracted from Argus daily reports**, each with its quote.
3. **Market agent** returns pre-war DAP forecasts (Argus Price Forecast, the sheet whose spec already matches the DB) as the baseline, and computes realized vs baseline deltas per route.
4. **Workbook agent** is only called if a needed series is not in the DB yet: it finds the sheet and proposes a spec (e.g. `DAP Trade Balance`, with export/import sections now handled by `subtitle`).
5. **Entity agent** maps Maaden and OCP plants for the competitive angle (OCP exports FOB Morocco, outside Hormuz).
6. **Business agent** links the result to OCP concepts (sulphur and ammonia → cash cost → margin).
7. The **Orchestrator** merges everything, the Reflector checks citations, and the answer is stored as a reasoning trace (`Question → Step → evidence`).

## Implementation pattern

- **Agent-as-tool:** each specialist is a function `ask_<agent>(question) -> {claims}` with its own system prompt and a **subset** of tools. The orchestrator sees the specialists as tools. This keeps our current simple loop; no framework needed.
- Specialists can run **in parallel** and on a **cheaper model**; the orchestrator uses the strongest model available.
- **Memory per specialist:** successful traces (e.g. approved specs per workbook family, useful Cypher queries) are stored in its subgraph and fed back as hints. This is SheetCompass's "experience memory" and generalizes the `Caster` hints we just added.

## Suggested build order

1. **News agent** (data ready: 37k articles, war period well covered). It gives the most visible value for the DAP/war demo.
2. **Market agent** over the existing views, starting with Argus Price Forecast and other specs the DB diff confirms.
3. **Orchestrator** with two specialists (news + market) plus the existing workbook agent.
4. **Entity agent** (OCP plant dedup).
5. Business / P&L agent computations.
