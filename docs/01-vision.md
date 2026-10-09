# Vision: OCP World-Model Graph + Agents

*Status: working draft, 2026-09-25. Origin: discussion with the tech lead on using agentic AI with Neo4j.*

## Problem

OCP Group has many branches and business units, each with its own products and processes. Prices, costs and volumes are highly volatile and depend on many numbers coming from many sources: Excels that cannot be normalized into one format, structured databases, market feeds and news. That makes computing Profit & Loss slow, hard to trace, and hard to explain.

## Goal

The system is a graph-based "world model" of OCP, with agents on top that can:

1. **Understand the business**: plants, products, processes, countries, markets, and the vocabulary people actually use (French, English, internal abbreviations).
2. **Answer questions by retrieving relations**: which products are made in which plants and countries, what each product is made from, current prices, forecasts, and the latest news and events that affect them.
3. **Explain changes**: why a margin or cost moved between two periods, with every step traceable to a source.
4. **Compute P&L eventually**, using a dependency graph of formulas that adapts as sources and processes change.

## Non-negotiable rules

- **The LLM never computes or invents numbers.** Agents maintain structure (mappings, formulas, links) and pick tools. Deterministic code does arithmetic, aggregation and forecasting.
- **Every claim cites evidence**: a graph node, a series value, or an article. A claim without evidence is dropped.
- **The curated core changes only through review.** Agents propose; humans (finance / BU controllers) approve.
- **History is never overwritten.** New values and versions supersede old ones and are linked to them.

## Architecture

```
                 ┌──────────── CORE (curated, reviewed) ─────────────┐
 Country ◄─LOCATED_IN─ Site ◄─PRODUCED_AT─ Product ─MADE_FROM─► Input
    ▲                   │                    │                  │
    │                PART_OF              SOLD_TO             PRICED_BY
    │                   ▼                    ▼                  ▼
    │                 OrgUnit              Market            (:Series)──► Postgres/Timescale
    │                                                           ▲            (prices, volumes)
    │                                                   (:Forecast)─FORECASTS┘
    │
 ┌──┴───────── EVENTS (self-growing, confidence-scored) ──────────────┐
 (:Article {url, date, text, embedding})─REPORTS─►(:Event {type, date, summary})
                              (:Event)─AFFECTS {direction, channel, confidence}─► any core node
                              (:Event)─FOLLOWED_BY_MOVE {series, pct, window}─► (:Series)   ← computed, not guessed
 └────────────────────────────────────────────────────────────────────┘

 ┌───────────── TRACES (reasoning graph, audit + reuse) ──────────────┐
 (:Question)─STEP─►(:Step {tool, query})─USED─►(any evidence node)
 └────────────────────────────────────────────────────────────────────┘
```

### Layer 1: Core (curated)

This layer holds the org tree, sites, products, inputs, metrics, units and glossary terms. It is implemented in phase 1 (`knowledge/ontology.yaml`) and will be extended with Country, Market, plant capacity, process steps and competitors. Relations that change over time (capacity, ownership, trade routes) carry `valid_from` / `valid_to`.

### Layer 2: Prices, volumes, forecasts

Time series do not live in Neo4j. The graph holds a `(:Series {id, source, unit, currency, freq})` node linked to its concept; the values live in Postgres/Timescale. Forecasts are produced by deterministic statistical models, not the LLM, and are stored as `(:Forecast {model, as_of, horizon})` so the agent can cite "forecast by model X as of date Y".

### Layer 3: News and events (historical + live)

- **Backfill.** Run event extraction once over the historical news archive (the Batch API halves the cost). Each article becomes one or more `Event`s with a fixed type (export restriction, plant outage, gas price shock, tender, sanction, weather, …), linked to core nodes with `AFFECTS`.
- **Market reaction.** For each event, deterministic code measures the price move over a fixed window on the linked series and stores it as `FOLLOWED_BY_MOVE`.
- **Analogs.** A graph query combined with vector search over event summaries answers questions like "the last three times ammonia spiked because of gas, what happened to the DAP margin?". The Neo4j 5 native vector index is enough for the POC.
- **Live feed.** A background "news curator" agent extracts events continuously. It auto-accepts low-impact links and sends links that touch prices or margins to the review queue.
- **Licensing.** Argus, CRU and Fertilizer Week content is paid and restricted. Confirm what OCP market intel is allowed to store. Internal market reports and public press releases are the safe starting point.

### Layer 4: Reasoning traces

Every answer is stored as a small reasoning graph (question → steps → tool calls → evidence). This gives controllers an audit trail from each sentence back to its evidence, and lets successful paths be promoted to reusable templates.

## Agent roles

| Role | Job | Writes |
|---|---|---|
| Explorer | Resolve terms, find the relevant subgraph | none |
| Analyst | Pull series, deltas and forecasts through deterministic tools; rank drivers | none |
| Reflector | Check every claim cites evidence; check units, currency and period consistency | none |
| News curator (background) | Extract events from articles, link to core, score confidence | proposals / low-impact auto-accept |
| Ingestor (phase 4) | Map messy Excel tables/columns to concepts | proposals |
| Calculator (phase 5) | **Not an LLM.** Evaluate the formula DAG | values |

## Worked example

Question: *"Pourquoi la marge DAP de Jorf a baissé en août, et que prévoir pour Q4 ?"*

1. The Explorer resolves "DAP" → `dap` and "Jorf" → `jorf_lasfar`, walks `MADE_FROM` to `ammonia` and `sulfur`, and finds their `Series`.
2. The Analyst gets month-over-month deltas from tools (computed in code) and ranks the drivers.
3. It pulls the Events that `AFFECTS` ammonia or sulfur in that window, with their precomputed market reactions.
4. It reads the latest `Forecast` nodes for Q4.
5. The Reflector drops any claim without a cited node, series or article.
6. The agent answers in French with citations and stores the trace.

## Traps specific to OCP

- **Intercompany flows** (rock from Mining to Nutricrops, acid between platforms) must be modeled explicitly with transfer prices and eliminated in group consolidation.
- **Units**: product tonnes vs t P2O5, BPL grade, kt/Mt. **Currency**: USD vs MAD, with the FX rate of the right date. Every value carries a unit and currency, and the Reflector rejects mismatches.
- **Governance**: per-branch access control, audit trail, and human approval on formula and ontology changes.
- **Management vs statutory reporting**: the answer changes how much autonomy the agents can have.
