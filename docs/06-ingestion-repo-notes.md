# Notes on the Market-Intel Ingestion Repo (`MERGEF/proddata/genai-corporate-data-ingestion`)

*Read on 2026-09-25. `src/excel_ingestion` is identical in code between `proddata` and `devdata`. Prod has more commits, e.g. `change/fix-duplicates` and an hourly/2h scheduled ingestion DAG.*

## What is useful to us

| Asset | What it holds | How we use it |
|---|---|---|
| `config/referential.yaml` (2,190 lines) | 135 companies, 249 countries, **111 country aliases**, **251 country → region mappings**, 51 regions, **444 region aliases** (incl. garbage → `world`: `total`, `unidentified`, `nan`…), cities, a hub (`us_gulf_tampa` with aliases), 64 vessels, 19 product categories, **57 product aliases**, **113 unit aliases**, metric-type natures | **Imported into the graph** (`src/import_referential_yaml.py`, snapshot at `knowledge/market_intel_referential.yaml`). Terms went from 577 to 1,147; regions from 128 to 139; 134 Company concepts; `IN_REGION` edges from the mapping |
| `extractors/Readme_casters/*.md` (15 docs, ~13k lines) | Per-family documentation of the 47 casters (trade, price, capacity, CRU databases, PIEC, freight, vessels, green/blue ammonia, NPK tenders): supported sheets, layouts, outputs, design decisions | **Layout knowledge for the agent.** These can become per-family hints (a "layout memory", like SheetCompass's expert memory) given to the agent when it inspects a matching workbook |
| `extractors/sheets_extractors.yaml` | Routing: sheet name / file regex → caster | Tells us which sheets were *meant* to be covered; useful to explain the "no_extractor_match" sheets |
| `extractors/implementation/argus_phosrock_trade.py` | Argus trade matrices | Confirms our orientation rule: when the corner cell is `Importers\Exporters`, **rows = importer, columns = exporter** (line ~757). It also strips the word "total" from names |
| `data_model/views/*.sql`, `docs/SQL_VIEWS_WIKI.md` | Definitions of `v_prices`, `v_supply`, `v_demand`, `v_trades`, `v_costs`, `v_market_economics` | Ground truth to compare against, and where the view quirks noticed earlier come from (`document_name = src`, frequency labels) |
| `config/taxonomy.py` | Units and metric types (price, volume, capacity, production, consumption, trade, forecast) | Candidate controlled vocabulary for `metric_type` in our specs |

## Things to know

- `config/canonical_mapper.py` is **empty** (0 lines), and the technical wiki says `referential_matcher` is missing from the repo. Canonicalization lives in `referential.yaml` plus `CleanerService` / `ColumnParser.classify_entity` inside casters.
- The referential maps `other middle east` to a **country** alias. That is probably a referential bug, and the graph now inherits it.
- Some Argus region labels are still unknown after the import: `E Europe, C Asia`, `East and SE Asia`. They should go through `propose_term` and review.
- The Argus DAP TM sheets of *Processed Phosphates Analytics 4Q 2025* have **0 metrics** in the DB, even though `sheets_extractors.yaml` routes `DAP TM 20xx` to `argus_phosrock_trade.py`. The routing exists but the run produced nothing, which is worth flagging to that team.

## Next ideas from this repo

1. **Layout memory:** index the caster READMEs by workbook family, and have `describe_sheet` attach the matching section ("how the old pipeline read this family") as a hint to the agent.
2. **Unit aliases:** feed the 113 `unit_aliases` into the `unit_evidence` check instead of our hand-written regex list.
3. **Differential test:** for sheets the old casters did extract, compare approved-spec output with the `metrics` rows (same sheet) to measure agreement.
