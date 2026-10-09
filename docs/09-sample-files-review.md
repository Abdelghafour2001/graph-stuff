# Sample Files Review (2026-10-09)

Five sample files we will receive, checked with the repo's own tools (`scripts/profile_excels.py`, `spec_executor.py`) and small read-only scripts. No Neo4j was available, so region-subtotal detection through the graph was off when specs were replayed.

| File | Provider | Shape | What it gives the graph |
|---|---|---|---|
| Argus Monthly Phosphates Outlook – Sep 2025 | Argus | 7 sheets, small (0.1 MB) | **Monthly prices 2014→2026** (10 series: DAP Morocco fob, DAP India cfr, phosacid India cfr, phosrock Morocco fob, …), trade balances (rock, acid, DAP, MAP) |
| Argus Monthly Ammonia Outlook – Oct 2025 | Argus | 9 sheets | **Monthly ammonia prices 2015→2027** (8 routes incl. Middle East fob, Morocco cfr), production costs, new capacity, monthly historical balance by country |
| Ammonia Outlook Data File – Feb 2025 | S&P Global (Fertecon) | 54 sheets, 9 MB | Long-term price forecast (nominal and real), cost curves, **capacity by plant** (company, feedstock, status, start, closure), supply/demand by end use, trade matrices 2021–2023 |
| ammonia-market-outlook-march-2025-flat-database | CRU | 14 sheets | **Monthly ammonia prices since 2000** (8 routes), annual/quarterly forecasts, consumption/production/capacity/trade by country, gas and coal price forecasts, CBAM metrics |
| Fertecon Vessel Tracker 04-03-2026 | S&P Global (Fertecon) | 9 sheets, one row per voyage | **Shipments**: vessel, shipper/supplier, loadport, disport, sailed/ETA dates, volume, sometimes price and incoterm; ammonia, phosphates, sulphur, sulphuric acid, urea, potash, nitrates |

## Findings that change the design

### 1. Forecasts are marked only by cell format
In both Argus price sheets the months from **Oct-2025** carry the number format `mmm-yy "f"`. The value is a plain date, so a reader of values (openpyxl `data_only`, pandas, our executor) cannot tell forecast from history. Phosphates rows from Oct-2022 to Sep-2025 are also italic, which probably marks another status; this needs confirming with Argus documentation.

**Consequence:** the variance diagnosis and every "as of" query would read Argus forecasts as realised prices, which is look-ahead leakage. **Action:** the executor must read the number format of the date column and emit `status: forecast | actual` on each row; specs need a `forecast_marker` rule.

### 2. Layouts drift between editions
Three specs that passed their checks when written (`DAP Trade Balance`, `Phosphoric Acid Trade Balance`, `Price Forecast`, Sep 2025 phosphates) **fail** on this copy of the same-named file. Here the header is on row 5, not row 6, so the header row now points at data (periods came out as `1769.87`). The `header_is_text` check caught all three.

Shifted up by one row, they pass again: `DAP Trade Balance` and `Price Forecast` pass every check, and `Phosphoric Acid Trade Balance` fails only `covers_whole_table` (its range needs extending).

**Action:** anchor specs on content (the header cell text, e.g. `'000t` in column A, or the first label `Export total`) instead of absolute row numbers, and re-run checks on every new file before loading it. An approved spec is approved for a layout, not for a file name.

### 3. "No market" is written three ways
- CRU uses `NM`, but also **`0`** (Baltic fob: 54 zero months) and a blank string `' '`.
- S&P uses `0` (e.g. Mediterranean cfr 2010).
- Argus ammonia uses `n/a` (Pivdenny, after the 2022 war).

A zero price is never a price. **Action:** treat 0, `NM`, `n/a` and blank strings as missing in price series, per provider.

### 4. Vessel tracker needs its own extractor
It is record-shaped (one voyage per row), not a cross-table, so the spec executor does not apply. Quality issues:

| Sheet | Voyages | Issues |
|---|---|---|
| Ammonia | 1,113 (2006–2026) | 39 without volume, 132 cells with stray spaces |
| Phosphates | 1,892 | 589 without volume, `TBC` volumes, dates in 1900 (Excel serial typos), `At port` as a date, product spelled `Phosphates` / `Phosphate` / `DAP` …, 129 rows with a price (84 CFR) |
| Sulfur | 366 | no volume column, only DWT (some as text `61,630 `) |
| Urea, Potash, Nitrates | 811 / 348 / 54 | dates as text in mixed formats (`30/6/25`, `26/04/2025`), volume ranges (`15,000-16,000`) |

Value for us: 129 ammonia, 140 phosphates, 193 sulphur and 311 urea loadings are in Gulf countries (Hormuz transit), and 727 phosphate rows are OCP shipments. That is the measured exposure the TRANSITS edges currently only assume.

### 5. Smaller source errors to flag, not fix
- DAP Trade Balance (Argus Sep 2025) column headers read `1Q25 | 2Q26 | 3Q26`; the first is almost certainly `1Q26`.
- Argus phosphates dates from Apr-2026 drift by a day per month (`2026-04-02`, `05-03`, `06-04`, …); Argus ammonia has three `2022-0x-22` dates. Normalise monthly dates to the 1st.
- S&P `LT Price Fcst` is titled "February 2024" in the Feb 2025 file.
- CRU `Price History` says "January 2000 – November 2024" but runs to Mar-2025: the last months are probably estimates.
- CRU `Annual Prices` has a stray backtick (`` ` ``) as the 2000 Black Sea value.
- Sheet dimensions are bloated (`Historical Balance` reports 1,048,576 rows, two tracker sheets 16,384 columns), so profiling must stop at the last non-empty row.
- S&P `Capacity by plant` interleaves country subtotal rows (`Austria Total`) with plants.

## What this means for the variance diagnosis
`knowledge/driver_series.yaml` currently points at Argus news price assessments (irregular, extracted by an LLM). These files give **regular monthly series straight from the providers**:

| Driver | Best series in these files |
|---|---|
| DAP | Argus DAP Morocco fob, monthly since 2014 |
| Phosphoric acid | Argus phosacid India cfr |
| Phosphate rock | Argus phosrock Morocco fob |
| Ammonia | Argus Middle East fob (since 2015) or CRU FOB Middle East (since 2000) |
| Sulphur | **not in these files**; still news assessments |

Once forecast rows are flagged (finding 1), these should replace the news-based series for those drivers.

## Next steps
1. Executor: read the date-column number format, emit `status`, and exclude forecasts from history and "as of" queries.
2. Specs: content anchors instead of absolute rows; re-check every new file before load.
3. Provider rules for missing values (0, NM, n/a, blank).
4. A record extractor for the vessel tracker (normalised dates, ports to countries, Gulf / Hormuz flag, OCP shipments).
5. Load S&P plant capacity into the entity graph (competitor plants, status, start/closure).
