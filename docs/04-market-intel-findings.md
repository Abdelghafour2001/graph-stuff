# Market Intel Data: Findings and Graph-Agent Design

*Explored on 2026-09-25 from the "GenAI for Market Intel" project (`Desktop/MERGEF/dev/corporate-geni-strategy-intel`, ingestion in `MERGEF/devdata/genai-corporate-data-ingestion`).*

## 1. What exists

### Postgres (`postgres` DB, container `mi-postgres`, port 5432)

| Schema.table | Rows | What it is |
|---|---|---|
| `corporate_data.argus_news` | 37,627 | Argus news, 2017-09 → 2026-06-29. Headline, full text, region/sector ids |
| `corporate_data.sp_documents` | 45,936 | S&P documents |
| `corporate_data.yahoo_finance` | 182 | Market quotes |
| `market_knowledge_data.documents` | 58 | Ingested Excel workbooks (providers: SP, ARGUS, CRU, MIXED) |
| `market_knowledge_data.document_sheets` | 1,080 | Sheets of those workbooks |
| `market_knowledge_data.metrics` | 5,833,952 | Normalized long-format values (entity, country, region, product, variant, dates, metric name, unit, value) |
| `v_prices` / `v_supply` / `v_demand` / `v_trades` / `v_costs` | 352k / 1.99M / 590k / 1.23M / 53k | Materialized views on `metrics` |
| `ref_entities` | 13,059 | Companies, sites, mines, plants, ports, vessels… (16 types) |
| `ref_products` / `ref_countries` / `ref_regions` | 110 / 284 / 128 | Referentials |

The referential already contains **OCP sites** (e.g. `ocp_jorf_lasfar_phosphate_hub`, `ocp_safi_phosphate_hub`, `ocp_phosboucraa`, `ocp_imacid`, `ocp_emaphos`, `ocp_prayon`, `ocp_pak_maroc_phosphore`, `ocp_jorf_fertilizers_company`) and competitors (Maaden, Mosaic, …). There are capacity, cost-at-capacity, conversion-cost and cost-to-FOB metrics per site.

### MinIO (container `mi-minio`, port 9000/9001)

The volume holds `ingestion-file-bucket` (excel_ingestion/, ingestion/ with about 1,061 objects, newsletters/) and `a-bucket`. **The S3 API reports no buckets**, so bucket metadata looks broken or lost. The objects are on disk (`xl.meta`) but not reachable through the API. The raw Excels are also in the ingestion repo at `src/excel_ingestion/tests/fixtures/sample_files/last/` (40 workbooks), and that is what was profiled.

### Current Excel pipeline

There are **56 hand-written "caster" scripts** (`extractors/implementation/*.py`), routed by sheet name through `sheets_extractors.yaml` (1,309 lines), plus `referential.yaml` (2,190 lines) for canonicalization. Each new layout means writing new code.

The DB shows the cost of this approach:
- 875 of 1,080 sheets are marked `completed` with `skip_reason = no_extractor_match`. Some are cover, contents or dashboard sheets, but not all.
- Only 588 of 1,080 sheets produced metrics.

## 2. How complex the Excels are (40 workbooks, 739 sheets)

Profiler: `scripts/profile_excels.py` → `data/excel_profile.json`

| Trait | Sheets | Why it hurts |
|---|---|---|
| Header not on row 1 | 587 (79%) | Legal notices, logos and titles sit on top |
| Header on row ≥ 5 | 410 (55%) | |
| Multi-row headers (depth ≥ 2) | 345 (47%) | e.g. unit row + product row + incoterm row |
| ≥ 3 table blocks in the first 300 rows | 297 (40%) | Several tables stacked in one sheet |
| Contain formulas | 441 (60%) | Rollups (`SUMIF` totals), dashboards, `#VALUE!` cells |
| Merged ranges | 180 (28 with ≥ 10) | |
| No detectable header | 132 | Dashboards, charts, pivots |
| > 100 columns | 41 | Wide product × location × incoterm grids |
| Time in columns (wide) | ≥ 55 (heuristic lower bound) | Years or months across columns |
| > 10,000 rows | 10 | |
| Contents/Index/Readme sheets | 32 | **Useful:** they describe the other sheets |

### Typical layouts seen

- **Argus "Price Forecast":** each column is a *price series* whose header packs product + origin + incoterm + unit (`DAP Morocco fob`, `DAP US Gulf barge fob ($/st)`, `Phosacid India cfr`), and time runs down the rows.
- **CRU trade matrices:** rows form a geography hierarchy (Continent | Sub-region | Country) and columns are years. **Total rows are formulas** (`=SUMIF(...)`, `=D5+D56+...`) mixed in with the leaf rows, so reading everything double-counts.
- **CRU flat databases:** `Table of Contents`, formula-driven `Data Dashboard` / `Trade Dashboard` with drop-down inputs (not data), then the real data sheets (`Stats Data`, `Trade Data`, `WPA Capacity`, …).
- **S&P futures forecasts, plant lists and cost services:** each has its own layout. The existing caster header documents 4 different geography-column variants for "flat database" files alone.

### Data-quality issues spotted in the normalized output

These are the kinds of issues a graph and reflector layer should catch:
- `ref_products` has duplicates and noise: `ammonia` / `Ammonia`, `sulphur` / `sulfur`, `phosphate_rock` / `rock` / `phosrock`, the typo `phospahte`, `19` / `04`, many combo codes (`map_np_dap`).
- `v_prices`: the ARGUS weekly-looking DAP series is labeled `frequency = annual`; "Quarterly Price Forecast" rows have `unit = kt` on a price; `document_name` shows `src` instead of the file name.
- `metrics` repeats identical rows for a site/product/date (e.g. Jorf Lasfar phosphoric acid capacity), probably one per line or scope, which is not visible without reading `scope`.

## 3. News and the US–Iran war

- The Argus text dates the start as *"Israeli-US strikes on Iran at the turn of the month"* (end of February / start of March 2026). The latest item (2026-06-29) reads *"Iran, US agree to pause attacks, renew talks"*.
- Headlines mentioning Iran or Hormuz: 40 in 2026-02, then **298 in 2026-03**, 211 in April, 147 in May, 159 in June.
- Argus publishes **daily market reports** ("Phosphates: Phosphate fertilizers", "Overview", …), about 100 per month. They contain **price assessments in text**, e.g. *"DAP prices are unchanged at $695-720/t fob"* (China), Moroccan DAP at $740/t cfr East Africa, Romania in the $860s/t fca.
- Co-mentions: sulphur + Hormuz goes from 0 (Jan) to 124 (Mar); Maaden + Hormuz from 0 to 46 (Mar). OCP is mentioned in 1,219 articles in total, 282 of them since March 2026.

**Key gap:** the structured `v_prices` rows for Feb–Jun 2026 are all **forecasts published before the war** (2025 publication dates). **Actual war-period prices exist only in news text.** That is useful: the pre-war forecast works as the counterfactual baseline, and the news provides the realized prices.

## 4. How a graph agent answers: "How was the DAP price affected by the US–Iran war?"

### Step 1: Rewrite and resolve (Explorer)
- "DAP" resolves to `dap`. "US–Iran war" resolves to an **Event cluster** node (start about 2026-03-01, pause 2026-06-29), built from news, not assumed.
- The question is expanded into sub-questions:
  1. DAP price level before vs during the war, by origin (Morocco, Saudi Arabia, China, Russia, US Gulf) and destination (India, Brazil, Europe, SE Asia, East Africa).
  2. Through which channels did the war act?
  3. How does this affect OCP specifically?

### Step 2: Channels from the graph (the multi-hop part)
The graph holds routes and dependencies:
```
(Event: US–Iran war)─DISRUPTS─►(Route: Strait of Hormuz)
(Route: Hormuz)─CARRIES─►(Flow: Saudi DAP exports / Gulf sulphur / Gulf ammonia & urea)
(dap)─MADE_FROM─►(phosphoric_acid)─MADE_FROM─►(sulfuric_acid)─MADE_FROM─►(sulfur)
(dap)─MADE_FROM─►(ammonia)
(maaden)─COMPETES_WITH─►(ocp) ; (maaden sites)─EXPORTS_VIA─►(Hormuz)
```
Two channels come out of this: a **supply channel** (Gulf DAP exports constrained) and a **cost channel** (sulphur and ammonia prices up, which pushes DAP replacement cost up), plus freight and insurance. Each channel is a *hypothesis*, confirmed only when news evidence links to it (for example the "Saudi DAP cargo transits strait of Hormuz" and sulphur-vessel headlines).

### Step 3: Numbers (Analyst; deterministic tools only)
- **Baseline:** pre-war DAP forecasts (Argus Price Forecast Sep 2025, S&P monthly forecasts) and the last pre-war actuals.
- **Realized:** price points **extracted from the daily reports**. Each extraction stores `{product, origin/destination, incoterm, low, high, unit, date, article_id, quote}`. A validator checks that the number literally appears in the quoted text. The LLM extracts; it does not invent.
- Deltas (realized vs pre-war level, realized vs pre-war forecast) are computed in code, per route.

### Step 4: Link to OCP (graph)
- OCP's DAP ships FOB Morocco, **outside Hormuz**, while competitor Maaden's exports **depend on Hormuz**, a possible relative market-share and price advantage.
- OCP's inputs (sulphur, ammonia) have Gulf exposure, a possible cost headwind. The hypothesis needs checking against OCP sourcing data, which we don't have yet.
- OCP sites and capacities come from `ref_entities` and `v_supply`.

### Step 5: Reflect and answer
The Reflector drops claims without citations and checks units ($/t vs $/st, fob vs cfr). The answer comes back in the user's language, with a chart per route and links to the articles. The trace is stored.

## 5. What the graph adds over the current pipeline

| Today | With the graph agent |
|---|---|
| 56 hand-coded casters routed by sheet name | A workbook graph (Workbook → Sheet → Block → Header/Column) with **header tokens linked to concepts** (product, location, incoterm, unit). The agent proposes the extraction spec and a human approves it once. Contents sheets are used as documentation. |
| Formula totals mixed with leaf rows | Formulas parsed into `AGGREGATES` edges, so totals are recognized and never double-counted, and can be used as checksums. |
| Duplicate product codes | Canonical concept plus alias terms, merged in the graph (`phosrock` → `phosphate_rock`). |
| News is only searchable text | News becomes Events linked to concepts and routes, and price assessments extracted with quotes become realized series. |
| No link between news and Excel data | Both hang off the same concepts, so one traversal reaches forecasts, actuals, events and OCP sites. |

## 6. Notes and risks

- **Secrets in the repo:** the market-intel `docker-compose.yml` contains plaintext Azure AD client secrets and OAuth secrets. They should be rotated and moved to env/secret storage.
- **Licensing:** Argus, CRU and S&P content is licensed. Using it inside OCP tooling is presumably covered by the existing project, but confirm before sending it to any new external LLM endpoint. The existing project uses Azure OpenAI; our POC uses the Claude API (open question 6 in the roadmap).
- MinIO bucket metadata needs repair before the stored originals can be served through the S3 API.

## 7. Phase 2a results so far (2026-09-25)

**Built:**
- `scripts/profile_excels.py`: per-sheet layout features, preamble, multi-row header cells, row labels, formula-total rows.
- `src/import_referentials.py`: 284 countries and 128 regions from the market-intel referential, linked with `IN_REGION`.
- Ontology extended with urea, potash, SSP, 6 incoterms, the Hormuz route (`TRANSITS`), and product aliases (`phosrock`, `phosacid`, `WPA`, `sulphur`…).
- `src/workbook_graph.py`: 40 `Workbook` and 739 `Sheet` nodes (role, layout features, description) with `MENTIONS {where: header|rows|context, n}` edges to concepts. **262 sheet descriptions were taken from the workbooks' own Contents/Index sheets.**
- `src/excel_tools.py`: agent tools `find_sheets`, `describe_sheet` (features + skeleton), `read_range`, and `propose_extraction_spec` (YAML, Auto-Tables operators only, written to a review queue).

**Checks:**
- `find_sheets(dap, country_morocco, fob)` returns 12 sheets. The top hits are the Fertilizer Week price averages, the S&P yearly/quarterly price forecasts, and Argus "Price Forecast" ("Global phosphates price forecasts - 12 month outlook"), which are the right places.
- Sheet roles compared with what the existing pipeline extracted (on sheets that could be matched by name):
  - `data`: 339 extracted, **172 never extracted**
  - `dashboard`: 15 extracted, 20 not
  - `other`: 37 extracted, 51 not
  - `contents`: 0 extracted
  - About 87% of extracted sheets are ones we classify as data, so the role heuristic is decent and needs an LLM pass for the rest.
- **Sheets the current pipeline never extracted** include `DAP Trade Balance`, `Phosphoric Acid Trade Balance`, `Ammonia Production Costs`, `New Capacity`, `Energy prices` and `Statistical forecast`. These are directly useful for the DAP/war question, and they are the obvious first targets for agent-proposed specs.

**Layout lessons from real sheets:**
- *Argus Price Forecast*: a **3-level header**. Row 4 has Argus series codes, row 5 the series name (`DAP Morocco fob`) spanning two columns, row 6 `Low`/`High`, then monthly dates down the rows. The spec is: ffill row 5 → combine rows 4–6 into the series key → wide_to_long on date.
- *Argus DAP Trade Balance*: **region subtotal rows are typed-in values, not formulas** (`Export total`, `West Europe`, `Africa`…), mixed with countries (`Morocco` 420 / 445 / 430 kt). No formula reveals them, but the graph does: `Morocco IN_REGION Africa`, so an `Africa` row followed by African countries is a subtotal. It can also serve as a checksum (children should sum to the region). Columns mix months and quarters (`2025-10-01`… `1Q25`, `2Q26`) in one header row.
- The OCP referential has about 130 `ocp_*` entities with duplicates (`ocp_laayoune` / `ocp_layoune` / `ocp_la_youne`; `ocp_jfc_i` / `ocp_jorf_fertilizer_company_i` / `ocp_sa_ocp_-_jfc_i`). This is a clear **entity-resolution** task for the graph: canonical plant plus aliases.

**Blocked:** the LLM part (the agent reading skeletons and proposing specs) needs `ANTHROPIC_API_KEY` on this machine.

**Next (no LLM needed):**
- A deterministic **spec executor** that replays an approved YAML spec into long rows.
- A **checker** that compares those rows with the existing `metrics` / `v_prices` rows for the same sheet.

## 8. First agent run on Azure OpenAI gpt-4.1-mini (2026-09-25)

The agent is now provider-switchable (`LLM_PROVIDER=azure_openai|anthropic`, same tools).

**Business question (FR):** "C'est quoi l'ACP, à partir de quoi on le fabrique, et quels produits passent par Ormuz ?" The agent called `lookup_term` twice and `run_cypher` once, and gave a correct answer with cited concept ids.

**Excel task:** "find DAP trade balance by country, inspect the layout, propose a spec." The agent chose `Argus Processed Phosphates Analytics - 4Q 2025.xlsx :: DAP TM 2024` (a valid choice), looked at it with `describe_sheet` and `read_range`, and wrote a spec. Reviewing that spec by hand against the sheet:

| Point | Agent said | Truth | Verdict |
|---|---|---|---|
| Structure | 2024 trade matrix, header on row 6 | Correct | ok |
| Orientation | rows = exporters, columns = importers | Header cell is `Importers\Exporters`: **rows = importers, columns = exporters** (the Morocco column sums to 3,937 kt of exports) | **wrong, trade direction flipped** |
| Total row | skip rows matching "total" | Row 7 is an **unlabeled** per-exporter total row, which the skip rule misses and so double-counts | **wrong** |
| Total column | "can be used for checks or skipped" | Column B `Total` must be excluded from values | partial |
| Unit | `tonne`, "confirm if ×1000" | Preamble row 5: `Data in 000 tonnes product` means **kt product** | **wrong** |
| Labels | not mentioned | Country names carry trailing spaces (`Argentina `) | missed |

**Lesson:** a small model plus a single pass produces plausible but wrong specs. The errors are exactly the kind the planned **Reflector** must catch, and most are checkable **deterministically**:
- **Checksum test.** Summing a column's leaf cells equal to the value in an unlabeled row means that row is a total row. Summing across a row equal to the `Total` column means that column is a total.
- **Orientation test.** Parse `A\B` corner headers. Cross-check against known facts from the graph or DB (e.g. Morocco is a major DAP *exporter*, so its column total should be large).
- **Unit test.** The unit must match a unit phrase found in the preamble or header (`000 tonnes` → kt).
- **Ground truth.** The old pipeline already extracted TM sheets into `v_trades` (with exporter/importer), so the executor's output can be diffed against it.

**Next:** deterministic spec executor → the checks above → a Reflector pass that feeds failures back to the agent → evaluation on a batch of sheets against the DB. It is also worth trying a stronger Azure deployment (the market-intel project uses gpt-4.1 and gpt-5.4) or Claude when a key is available.

## 9. Executor, Reflector checks and eval (2026-09-25)

`src/spec_executor.py` replays a YAML spec deterministically (ffill + stack are executable; the other Auto-Tables ops are accepted in the vocabulary but rejected as "not executable yet"). Every output row keeps its **source cell** (`cell: J45`) for provenance.

**Checks, fed back to the agent inside `propose_extraction_spec` (the Reflector loop):**

| Check | Catches |
|---|---|
| `values_parse` | wrong range or header rows (text where numbers should be) |
| `covers_whole_table` | truncated ranges: non-empty cells right below or right of the range |
| `unit_evidence` | unit not supported by preamble/header text; the most specific mass scale wins (`000 tonnes` → kt, not t) |
| `corner_orientation` | `Importers\Exporters` corner cell vs row/column dimension names |
| `no_total_rows` / `no_total_columns` | checksums over **all** numeric columns (dropped ones included) |
| `dropped_columns_are_totals_or_empty` / `dropped_rows_are_totals_or_empty` | "cheating" by dropping real data to make checksums pass |
| `no_subtotal_labels` | **graph-driven:** the most specific label column mixes regions and countries (region subtotals), or rows labelled "total". The fix is `skip_label_kinds: [region]`, resolved through `IN_REGION` / Term lookups |

The first gpt-4.1-mini spec for DAP TM 2024 had four errors, and the checks now flag all four. The agent's v2 spec "passed" by dropping column J (Honduras, a real exporter) instead of the `Total` column B, which exposed a gap. Checksums now use all columns, and dropped columns and rows must be justified.

**Eval v2 (8 sheets, gpt-4.1-mini, before the last check fixes):** 4/8 passed the checks, 2 of them only after a retry (the Reflector loop works). 2 produced no spec, because the model gave up after validation errors (header rows outside the range, which is now a clear validation message). **Known check gaps:**
- Regions missing from the vocabulary (`E Europe, C Asia`, `Latin America`) slip through the subtotal check. The fix is to grow the vocabulary through `propose_term`.
- Derived rows like `Balance`.
- **Stacked sections** (an export block followed by an import block in one sheet) need the Auto-Tables `subtitle` operator, which is not executable yet.

Passing the checks is necessary but not sufficient, so human review stays in the loop.

**Eval v4, with all checks** (8 sheets, gpt-4.1-mini; results in `data/eval_results.json`, earlier runs kept as `_v2` / `_v3`):

| Sheet | Attempts | Result |
|---|---|---|
| Argus DAP TM 2024 | 2 | passed. Spec is now correct: rows = importers, row 7 and column B dropped as totals, kt |
| Argus DAP Trade Balance | 2 | passed (region subtotals dropped via the graph) |
| Argus Price Forecast (3-row header) | 1 | passed |
| Argus Ammonia Production Costs | 1 | passed |
| Argus Phosphoric Acid Trade Balance | 4 | rejected: `covers_whole_table` |
| Argus New Capacity | 2 | rejected: `values_parse` (text columns mixed with numbers) |
| CRU phosphate rock trade matrix "Imports" | 3 | rejected: `covers_whole_table`. The agent keeps missing the last data row (211 "Unidentified"), which is a real miss |
| S&P Yearly Price Forecast | 3 | rejected: `unit_evidence` (no $ unit stated near the table) |

**4/8 pass strict checks, and every rejection is a real, explained issue.** Rejected specs can still be approved by a human in the UI (reviewer override). A stronger model, the `subtitle` operator, and vocabulary growth are the next levers.

## 10. Containers, API, UI (2026-09-25)

`compose.yaml` (podman compose) runs everything:
- `neo4j`
- `market-intel-db` (the market-intel Postgres volume, mounted as external)
- `loader` (one-shot: ontology → referentials → workbook graph)
- `api` (FastAPI, :8010, `/docs`)
- `ui` (Streamlit, :8501)

The UI has four tabs:
- **Ask the agent:** chat, with the tool-call trace for every answer.
- **Workbooks:** type words, see how they resolve to concepts, see the matching sheets; pick one for layout features, skeleton, linked concepts and any cell range.
- **Spec review:** spec YAML, checks, sample rows with source cells, and Approve.
- **Eval:** the table above.

Neo4j Browser (:7474) stays the place for visual graph exploration; the sidebar has sample queries.

## 11. Layout memory, referential units, `subtitle`, DB diff (2026-09-25)

**Added:**
- **Layout memory from the old pipeline** (`src/import_caster_knowledge.py`): 43 casters (38 with docs from `Readme_casters`), 780 `(:Sheet)-[:ROUTED_TO]->(:Caster {code, doc})` edges covering 573 of 739 sheets. `describe_sheet` returns up to 2 `old_pipeline_hints` (the caster's doc section) to the agent.
- **Units from the ingestion referential:** `value_unit` must be a referential unit or alias (`kiloton`, `kt_product`, `usd_per_short_ton`, `$/t`…). Evidence uses the 113 aliases, and a more specific unit wins (`000 tonnes` → kiloton, so `t` is rejected).
- **`subtitle` operator** (Auto-Tables): `{dimension: flow, rows: {6: export, 26: import}}` splits stacked sections. Total checks are now **section-aware**. A dropped row is justified if it is empty, labelled "total", or matches a checksum of its section (kept rows or region-subtotal rows). Unlabeled total rows must pass a checksum.
- **Reviewed vocabulary file** `knowledge/term_additions.yaml`, loaded last. This is where approved `propose_term` proposals land. First entries: `E Europe, C Asia` / `EECA` → `region_europe_cis`, `East and SE Asia` → `region_asia`.
- **Two more sanity checks:** `header_is_text` (header rows must not be data rows) and `labels_present` (the label column must hold labels).
- **Differential test vs the old pipeline** (`src/diff_vs_db.py`, API `/specs/{status}/{name}/compare`, UI button, eval column): rounded value multisets vs `metrics` rows of the same sheet.

**Eval v5 (gpt-4.1-mini): 6/8 pass the checks.** Where the old pipeline has data, the diff is decisive:
- **Argus Price Forecast** (3-row header): the agent's spec **agrees** with the hand-coded caster. 100% of our values are in the DB, and 99.3% of the DB's are in ours.
- **S&P Yearly Price Forecast** "passed" checks v5 but **disagreed** with the DB. Two causes:
  1. The agent's spec was wrong (`header_rows` pointed at a data row, and the label column was empty). The new checks now reject it.
  2. **The old pipeline stored serialized pandas objects as values**, e.g. `'dap|dap cfr india 459.90…\nname: 0, dtype: object'`. **10,440 corrupted values across all 4 S&P "Yearly Price Forecast" sheets**, plus 162,054 `'nan'` value rows in `metrics`. Report this to the market-intel team. A corrected spec recovers 2,288 values and contains 85% of the DB's parseable ones.
- 4 of the passing sheets have **no DB rows at all** (the old pipeline never extracted them). These are net new data: DAP TM 2024, DAP Trade Balance, Phosphoric Acid Trade Balance, Ammonia Production Costs.

## 12. News specialist sub-agent (2026-09-26)

**News subgraph:**
- `src/news_graph.py`: all **37,627 Argus articles** become `(:Article)`, with **285k `MENTIONS` links** to concepts (deterministic, same vocabulary). Text stays in Postgres.
- `src/news_extract.py extract` (LLM, gpt-4.1-mini, 8 parallel workers): 645 Argus daily phosphate reports (2026) give price assessments; 272 war-and-fertilizer articles (2026) give events. Raw outputs are cached in `data/news_extractions.jsonl`, so reloads never re-call the LLM.
- `src/news_extract.py load` (deterministic, run by the loader) keeps only verified items:
  - the quote is found verbatim in the article
  - both prices appear in the quote, and 0 < low ≤ high
  - no price is more than 2× away from the median of its product/location/incoterm series
- **Result: 2,837 `PriceAssessment` and 757 `Event` nodes.** 468 unverifiable items and 28 outliers were rejected. Event types: shipping_disruption 133, capacity_change 132, policy 80, shipping_restored 51, export_restriction 49, military_action 45, plant_outage 44, ceasefire_or_talks 42…
- New reviewed terms: `Mainland China`, `China Domestic`, `Nola`, `US Nola`, `Tampa`.

**Realized DAP prices** (monthly average of verified assessments, $/t, computed by Neo4j):

| Route | Jan | Feb | Mar | Apr | May | Jun | Feb → Jun |
|---|---|---|---|---|---|---|---|
| China fob | 687 | 705 | 736 | 820 | 894 | 897 | +27% |
| India cfr | 672 | 689 | 772 | 855 | 930 | 933 | +35% |
| Morocco fob (thin: 1–8 points/month) | 720 | 746 | 813 | 860 | 948 | 925 | ≈ +24% |

The first extracted events (2026-02-28): "The US and Israel attacked Iran, leading Iran to claim it has closed the Strait of Hormuz", and "blocking exports from Saudi Arabia", from article 2795774, *Global DAP/MAP offers dry up, market watching Hormuz*.

**Sub-agent wiring (agent-as-tool):**
- The orchestrator (`agent.SYSTEM`, workbook and graph tools) has `ask_news_agent`.
- The news specialist (`NEWS_SYSTEM`) has its own tools: `search_articles`, `read_article`, `event_timeline`, `price_routes`, `price_monthly`, `price_assessments`, all "as of" `date_to`.
- The orchestrator's prompt includes an **impact playbook**: MADE_FROM/TRANSITS channels → one precise delegated question → timeline + per-route before/during table + OCP implications split into evidence and hypotheses.

**End-to-end test** ("Comment le prix du DAP a-t-il été affecté par la guerre US-Iran…"): the orchestrator delegated one question. The specialist ran `event_timeline` plus `price_monthly` on Morocco, China and India, and the answer gave a dated timeline and the three routes' rises. **Remaining weaknesses on gpt-4.1-mini:**
- No article ids cited.
- Input prices were queried at the wrong place (Morocco instead of Gulf sulphur/ammonia).
- OCP implications stayed generic. It even hedged about OCP's dependence on Hormuz, which does not match the graph (OCP exports FOB Morocco).

**Next levers:** an orchestrator Reflector that rejects answers without evidence ids; a stronger model; input-price routes (sulphur Middle East fob, ammonia) in the playbook; event deduplication across articles (Graphiti-style).

**UI:** new **News & prices** tab: per-route monthly price chart for any product, plus the event table for chosen concepts.

## 13. gpt-5.4, Reflector, incidents, entity agent (2026-09-26)

**Models:** the same Azure key serves `gpt-5.4` and `gpt-5.4-mini` (the deployment named `gpt-4o` actually serves gpt-5.1; `gpt-4.1` is not deployed). Agents (orchestrator and specialists) now use `AZURE_OPENAI_AGENT_DEPLOYMENT=gpt-5.4`. Bulk extraction keeps `AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini`.

**Citation / number Reflector** (`agent.reflect`, deterministic, applied to every agent run, orchestrator and specialists):
- Every number ≥ 10 in an answer (years excepted) must appear in a tool result of that run, within 1%.
- If tools returned article ids, the answer must cite at least one.
- On failure, the problems go back to the model (2 rounds), then any unresolved issues are appended to the answer.
- New `calc` tool so that derived numbers (differences, percentages) come from code.

**Incidents:** events reported by several articles (same type, date and affected concepts) are grouped into `(:Incident {reports})`: 538 incidents from 757 events. `event_timeline` returns incidents with up to 5 article ids. Invalid LLM dates (e.g. 2026-02-29) fall back to the article date.

**DAP / US–Iran war question on gpt-5.4** (`data/demo_dap_war_gpt54.json`). The orchestrator called the news specialist twice, plus 12 `calc` calls; the specialist called `price_routes`, `price_monthly` ×5, `price_assessments` ×5 and `event_timeline`. **The Reflector caught one unsupported number (50,000), which the model removed.** The answer includes:
- a dated incident timeline with article ids
- a Mar/Apr/May table per route with `calc`-computed changes (DAP Morocco fob 813.1 → 948.3, China fob 735.6 → 893.7, India cfr 771.5 → 929.6)
- quoted transmission channels, e.g. article 2803651: *"higher sulphur costs as a result of supply disruptions from the Middle East"*
- correct OCP facts from the graph (DAP produced at Jorf Lasfar; Hormuz not on OCP export routes)
- implications split into evidence and hypotheses

**Entity agent (first job): OCP asset resolution** (`src/entity_resolution.py`):
- gpt-5.4 proposed clusters for the **149 OCP-related source records**. Code validation found **3 records the model left out**; they are added as low-confidence singletons for review.
- **Result: 61 canonical `Asset` nodes, 36 of them merges** (26 high, 20 medium, 15 low confidence). Examples: 6 Laayoune spellings → *Laayoune Plant* (Boucraa); 4 Maroc Chimie variants → *Maroc Chimie Safi*; 3 → *OCP-ADNOC JV Ruwais*. Numbered Jorf Lasfar hub sub-sites are grouped at medium confidence, which needs review.
- Graph: `(:SourceEntity)-[:SAME_AS {status: proposed|approved}]->(:Asset)-[:LOCATED_AT]->(site)`, `-[:PART_OF]->(ocp_group)`.
- Orchestrator tools: `resolve_entity`, `ocp_assets`. UI tab **Entities** with Approve.
