# Roadmap and Status

*Last updated: 2026-09-25 (after market-intel exploration)*

| Phase | Scope | Status |
|---|---|---|
| 1 | Business understanding: ontology (org, sites, products, inputs, metrics, units, FR/EN terms), Neo4j loader, Claude agent with read-only graph tools + term proposal queue | **Done** (tools verified; LLM loop not yet run, no API key set on the machine) |
| 2a | **Excel understanding on real market-intel workbooks** (40 files, 739 sheets): workbook graph (Workbook → Sheet → Block → Header), sheet-role classification, formula → `AGGREGATES` edges, header tokens → concepts, agent-proposed extraction specs checked against the existing 5.8M `metrics` rows. See [findings](04-market-intel-findings.md) | **In progress**: workbook graph, agent tools, executor + Reflector checks, eval (6/8 strict pass on gpt-4.1-mini; DB diff agrees on Price Forecast), layout memory, referential units, subtitle op, API + UI + compose done. News specialist sub-agent built (37.6k articles, 2.8k verified price assessments, 757 events, UI tab). gpt-5.4 agents + citation/number Reflector + incidents; entity agent (OCP assets). Next: market agent, competitor entities |
| 2b | News → Events + price assessments extracted from Argus daily reports (with quotes); demo question: DAP price vs US–Iran war, linked to OCP | Planned |
| 1b | Extend core: Country, Market, plant capacity, competitors, routes (e.g. Hormuz); import market-intel referentials (`ref_entities` incl. OCP sites, `ref_countries`, `ref_products` with alias merge) | Planned (feeds 2a) |
| 2 | Prices + forecasts: Series store (Postgres/Timescale), `get_series` tool, baseline deterministic forecast, `Forecast` nodes | Planned |
| 3 | Events/news: historical backfill (batch extraction), `Event`/`Article` nodes, computed `FOLLOWED_BY_MOVE`, vector search for analogs, news-curator agent with review queue | Planned |
| 4 | Messy Excel ingestion (SheetCompass pattern): table/column graph, column → concept mapping, constrained extraction code, Reflector checklist, reusable templates | Planned |
| 5 | P&L computation: versioned formula DAG, deterministic evaluator, bitemporal observations, period-diff explanations | Planned |
| — | Reasoning traces stored as graph (cross-cutting, starts with phase 2) | Planned |

## Demo target (end of phase 3)

> "Pourquoi la marge DAP de Jorf a baissé en août, et que prévoir pour Q4 ?"

The answer should give ranked drivers with computed deltas, related events with their past market reactions, a forecast with its source model and date, and a citation for every claim.

## Demo data policy

Until real feeds are available, price series and events will be **synthetic and clearly labeled as such** (roughly 30 hand-written sample events), so no one mistakes invented numbers for OCP data. The ontology seed is also illustrative and needs validation by finance/BU controllers.

## Open questions (for tech lead / finance)

1. Granularity: monthly close, or near-real-time price moves?
2. Sources: can we reach SAP/BW, or only Excels at first?
3. News: which sources does OCP market intel already license (Argus, CRU, Fertilizer Week, Reuters, internal reports)? What may we store?
4. Who approves ontology, mapping and formula changes? Finance controllers per BU?
5. Management reporting (flexible) or statutory (strict)?
6. Hosting constraints: can data leave the network for the Claude API, or do we need a local or on-prem model option?

## Running the POC

See the [README](../README.md).
