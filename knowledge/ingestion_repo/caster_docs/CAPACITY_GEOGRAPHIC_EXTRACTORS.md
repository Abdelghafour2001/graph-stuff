# README: Flat Geographic Extractors (Regional Aggregation Pattern)

**Files:**
- `specialty_phosphates_market_outlook_DATE_database_amended__pwa_tpa_capacity.py` — S&P specialty phosphates data sheets (capacity, production, demand, imports, exports)
- `plantlist_caster.py` — S&P plant list extractor (asset list by region/country)

**Pattern:** Flat geographic hierarchy (Region/Subregion → Country) with NO company/site entities  
**Data Sources:** S&P (PIEC) specialty phosphates analytics  
**Supported Products:** PWA TPA, tMAP, P4, LFP/LMFP, STPP, SPA, APP, DCP, MCP-MDCP  
**Status:** ⚠️ Inactive (commented in sheets_extractors.yaml) — Reference implementations available

---

## Overview

This documentation covers **2 extractors** that share a **flat geographic pattern**: both normalize region/country-level aggregated capacity and production data WITHOUT creating company or site entities. They handle regional total rows, metric type variants, and forecast vs. realized scenarios.

### Shared Features

- **Flat geographic entities**: Only Region → Subregion → Country (RegionCreate, CountryCreate, NO EntityCreate for geography)
- **No company/site entities**: Metrics are at regional/country level, not facility level
- **Aggregate row handling**: Rows ending with "Total" are REGION/SUBREGION nodes (not separate entities)
- **Metric type variants**: Multiple metrics per sheet (Capacity, Production, Demand, Imports, Exports, Trade)
- **Scenario detection**: Forecast vs. release based on year vs. publication date
- **Referential integration**: Load country/region/product aliases from YAML
- **Product group safety**: Members-first pattern (DAP before DAP+MAP group to avoid repository conflicts)

---

## Architecture (Unified Pattern)

```
Flat Geographic Aggregation Extractor
│
├─ Input: Excel sheet with Region|SubRegion|Country + Metric Columns + Years
│  └─ Rows with "Total" suffix → Regional aggregate nodes
│
├─ Stage 1: Document Context
│  ├─ Create DocumentCreate (publication date from filename)
│  ├─ Infer source code: sp or argus
│  ├─ Infer default product: from document name
│  └─ Confirm sheet type (Capacity, Production, Demand, etc.)
│
├─ Stage 2: Header Detection
│  ├─ Row 0-2 scan for "Region" or "Country" keyword
│  ├─ Build column map: region → col_idx, subregion → col_idx, country → col_idx
│  ├─ Extract year columns (numeric-only 4-digit headers)
│  ├─ Detect metric type from sheet name context (Capacity, Production, Demand, etc.)
│  └─ Optional: Detect product from sheet/preamble
│
├─ Stage 3: Data Processing (Single-Pass)
│  ├─ For each row:
│  │  ├─ Extract Region, Subregion, Country names
│  │  ├─ Check if row ends with "Total" → REGIONAL AGGREGATE
│  │  │  ├─ If YES: Strip "Total", emit as region/subregion node ONLY (no row metrics)
│  │  │  └─ If NO: Emit as country detail row with metrics
│  │  ├─ Normalize geographies via referential
│  │  ├─ Create RegionCreate, CountryCreate (dedup)
│  │  ├─ For each year column:
│  │  │  ├─ Extract numeric value
│  │  │  ├─ Determine scenario: year ≥ pub_year → forecast; else → release
│  │  │  ├─ Build metric_name: {metric_type}_{forecast|release}
│  │  │  ├─ Emit MetricCreate at country level
│  │  │  └─ Scope includes: region, subregion, country, metric_type
│  │  └─ NO site/plant entities emitted (only geo)
│  └─ NO dedup of companies (none created)
│
├─ Stage 4: Product Group Safety (If Multi-Product Per Sheet)
│  ├─ For product groups (e.g., DAP+MAP):
│  │  ├─ Determine members (DAP, MAP) from preamble/config
│  │  ├─ Emit DAP metrics first, then create DAP product
│  │  ├─ Emit MAP metrics next, then create MAP product
│  │  ├─ THEN emit group product (dag_map) if needed
│  │  └─ Prevents MetricRepository constraint violations
│  └─ Safe staging ensures products exist before group references them
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Products (2-8 per sheet)
   ├─ Regions (regional aggregates only)
   ├─ Countries (mapped to regions)
   ├─ Entities (EMPTY - no companies/sites)
   └─ Metrics (capacity/production/demand by country-year)
```

---

## Extractors in This Group

### 1. Specialty Phosphates Data Sheets Caster

**File:** `specialty_phosphates_market_outlook_DATE_database_amended__pwa_tpa_capacity.py`  
**Coverage:** S&P specialty phosphates data sheets  
**Sheet Types:** Capacity, Production, Demand, Imports, Exports sheets

**Key Features:**
- **Multi-product per sheet**: PWA TPA, tMAP, P4, LFP, STPP, SPA, APP, DCP, MCP-MDCP (auto-detected from sheet name)
- **Multi-metric support**: Product group + (Capacity|Production|Demand|Imports|Exports) per sheet
- **Product group variants**:
  ```yaml
  # From sheet patterns:
  - "PWA TPA Capacity" → product="pwa_tpa", metric="capacity"
  - "MCP-MDCP Production" → product="mcp_mdcp", metric="production"
  - "LFP P2O5 Demand" → product="lfp_lmfp", metric="demand"  (special case)
  - "tMAP Imports" → product="tmap", metric="imports"
  ```
- **Header row 2**: Region|Subregion|Country + Year1|Year2|...
- **Scope**:
  ```python
  scope = {
    "region": region,
    "sub_region": subregion,
    "country": country,
    "product_group": product_group,
    "metric_type": metric_type,
  }
  ```
- **Metric naming**: "{metric_type}_{forecast|release}" (e.g., "capacity_forecast", "production_release")

**Sheet Pattern Matching:**
```yaml
# Specific product group overrides (processed FIRST):
- pattern: "^PWA TPA (Capacity|Production|Demand|Imports|Exports)$"
  params: { product_group: "pwa_tpa" }

- pattern: "^MCP[-_]MDCP (Capacity|Production|Demand|Imports|Exports)$"
  params: { product_group: "mcp_mdcp" }

- pattern: "^LFP P2O5 Demand$"
  params: { product_group: "lfp_lmfp", metric_type_override: "demand" }

# Generic fallback (for all other sheets):
- pattern: "^(PWA TPA|tMAP|P4|LFP|STPP|SPA|APP|DCP|MCP[-_]MDCP) (Capacity|Production|Demand|Imports|Exports)$"
  params: { product_group: "{captured_group}" }
```

---

### 2. Plant List Caster

**File:** `plantlist_caster.py`  
**Coverage:** S&P plant list (asset list by region/country)  
**Sheet Types:** "PlantList" with optional product specificity

**Key Features:**
- **Asset listing**: Region|Subregion|Country + Plant name columns (no hierarchical entities)
- **No year columns**: Static asset list, not time-series
- **Metric emission**: Asset status / capacity snapshot per plant
- **Scope**:
  ```python
  scope = {
    "region": region,
    "sub_region": subregion,
    "country": country,
    "plant_name": plant_name,
    "status": status,
    "capacity_type": capacity_type_detected,
  }
  ```
- **Entity level**: Country aggregates only (NO company/site entities)

---

## Key Processing Differences

| Aspect | Specialty Phosphates | Plant List |
|--------|---|---|
| **Data Type** | Time-series metrics (Capacity, Production, Demand, etc.) | Static asset list |
| **Year Columns** | Yes (2020-2030+) | No |
| **Metric Types** | 5+ per file (Capacity, Production, Demand, Imports, Exports) | Single (plant asset status) |
| **Row Filtering** | Strip "Total" rows (regional aggregates) | Keep all rows (asset list) |
| **Scope** | 5-6 fields (geo + metric type) | 5-6 fields (geo + status/type) |
| **Header Row** | Row 2 (fixed) | Variable (0-5) |
| **Product Detection** | Sheet name pattern | Document name or column |

---

## Data Structures

### SchemaCollection (Output)

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate
    metrics: List[MetricCreate]         # Empty for plantlist, populated for data sheets
    entities: List[EntityCreate]        # EMPTY - no companies/sites
    products: List[ProductCreate]       # 2-8 products
    regions: List[RegionCreate]         # Regional nodes
    countries: List[CountryCreate]      # Country nodes
```

### RegionCreate

```python
RegionCreate(
    region_name="western_europe",
    is_active=True,
)
```

### CountryCreate

```python
CountryCreate(
    country_name="netherlands",
    region_name="western_europe",
    is_active=True,
)
```

### MetricCreate (Data Sheets Only)

```python
MetricCreate(
    metric_name="capacity_forecast",
    metric_type="capacity",
    value="120",
    unit_of_measure="kiloton",
    year=2025,
    start_date_effect=date(2025, 1, 1),
    end_date_effect=date(2025, 12, 31),
    date_publication=date(2025, 1, 1),
    country_name="netherlands",
    region_name="western_europe",
    entity_name=None,                    # NO entity for geo-level metrics
    product_name="pwa_tpa",
    sheet_name="PWA TPA Capacity",
    document_name="specialty_phosphates_market_outlook_2025_data_sheets",
    scope={
        "region": "western_europe",
        "sub_region": None,
        "country": "netherlands",
        "product_group": "pwa_tpa",
        "metric_type": "capacity",
    }
)
```

---

## Total Row Handling (Regional Aggregates)

**Pattern Recognition:**
```python
def _is_total_row(row_text: str) -> bool:
    """Check if row ends with Total, represents an aggregate."""
    low = row_text.lower().strip()
    return low.endswith("total") or "total" in low.split()[-1]

# Examples:
#   "Western Europe Total"    → YES (regional aggregate)
#   "Europe Sub-Total"        → YES
#   "European Region"         → NO
#   "Total Capacity"          → NO (sheet header, not data)
```

**Processing:**
- If total row: Extract region/subregion name (strip "Total"), emit as **regional node ONLY**
  - No metrics for total rows at region level
  - Only country-level rows emit metrics
- If detail row: Normal processing (emit country metrics)

**Example:**
```
| Region | Sub Region | Country | 2024 | 2025F |
|--------|-----------|---------|------|-------|
| US   | East | Total       |  500 |  550  |  ← Total row: emit region "east", NO metrics
| US   | East | New York    |  250 |  275  |  ← Detail: emit metrics
| US   | East | New Jersey  |  250 |  275  |  ← Detail: emit metrics
```

---

## Metric Naming Convention

All extractors follow a consistent pattern:

```python
metric_name = f"{metric_type}_{scenario}"

# Examples:
#   capacity_release  (2024 ≤ pub_date.year)
#   capacity_forecast (2025 > pub_date.year)
#   production_release
#   demand_forecast
#   imports_release
#   exports_forecast
```

---

## Product Group Safety Pattern

**Problem:** If products share the same hierarchy (e.g., DAP, MAP, DAP+MAP group), metrics must point to products that already exist.

**Solution:** Emit in safe order (members first, then group):

```python
# Order for DAP/MAP scenario:
1. Emit all DAP metrics
2. Create DAP product
3. Emit all MAP metrics
4. Create MAP product
5. Emit all DAP+MAP (group) metrics
6. Create DAP+MAP product

# Prevents MetricRepository:
#   Error: metric.product_name="dap" but product DNE
```

---

## Referential Integration

### Required Mappings

```yaml
# referential.yaml
country_region_mapping:
  netherlands: western_europe
  germany: western_europe
  united_states: north_america
  # ... all countries in data sheets

region_aliases:
  # ... optional regional aliases

product_aliases:
  "pwa": "pwa_tpa"
  "tmap": "tmap"
  "lfp": "lfp_lmfp"
  # ... product standardization
```

---

## Configuration (sheets_extractors.yaml)

```yaml
# Example: Specialty Phosphates Data Sheets (currently commented)
# - name: specialty_phosphates_capacity
#   description: >
#     Data sheets (capacity/production/demand/imports/exports) from specialty
#     phosphates market outlook database.
#   extractor_code: specialty_phosphates_market_outlook_DATE_database_amended__pwa_tpa_capacity.py
#   matches:
#     regex:
#       - pattern: "^PWA TPA (Capacity|Production|Demand|Imports|Exports)$"
#         params: { product_group: "pwa_tpa" }
#       - pattern: "^MCP[-_]MDCP (Capacity|Production|Demand|Imports|Exports)$"
#         params: { product_group: "mcp_mdcp" }
#       - pattern: "^LFP P2O5 Demand$"
#         params: { product_group: "lfp_lmfp", metric_override: "demand" }

# Example: Plant List (currently commented)
# - name: sp_plant_list
#   description: Extracteur plantlist sp datafile
#   extractor_code: plantlist_caster.py
#   matches:
#     exact:
#       - value: "PlantList"
#         data_provider: "sp"
#         file_regex: "Plant|plants?_List|plant list"
```

---

## Worked Examples

### Example 1: Specialty Phosphates Capacity Sheets

**File:** `Specialty_Phosphates_Market_Outlook_2025_Data.xlsx`  
**Sheet:** "PWA TPA Capacity"

**Input (excerpt):**
```
| Region | Sub-Region | Country | 2024 | 2025F | 2026F |
|--------|-----------|---------|------|-------|-------|
| Europe | W. Europe | Netherlands | 120 | 120 | 120 |
| Europe | W. Europe | Total     | 180 | 185 | 185 |  ← Total row
| Europe | S. Europe | Total     | 40 | 45 | 45 |    ← Total row
| Europe | Total     | South    | 20 | 25 | 25 |     ← Different layout
```

**Processing:**

Row 1 (Detail):
- Region="europe", Subregion="w_europe", Country="netherlands"
- Product="pwa_tpa", Metric type="capacity"
- Metrics: 2024→release(120), 2025→forecast(120), 2026→forecast(120)

Row 2 (Total row):
- Strip "Total": Region="europe", Subregion="w_europe"
- NO metrics emitted (regional aggregate only)

---

### Example 2: Plant List Asset Listing

**File:** `S_P_Plant_List_2025.xlsx`  
**Sheet:** "PlantList"

**Input (excerpt):**
```
| Region | Sub-Region | Country | Plant Name | Status | Capacity |
|--------|-----------|---------|-----------|--------|----------|
| NA | Gulf | USA | Port Arthur | Operating | 500 |
| NA | Gulf | Mexico | Veracruz | Operating | 350 |
| ME | Persian G | Iran | Isfahan | Operating | 1500 |
```

**Processing:**
- Region="na" (north_america), Country="usa", Plant="port_arthur"
- NO metrics (static asset list)
- Create Region, Country nodes
- Scope includes: plant_name, status, capacity_type

---

## Troubleshooting

### Issue 1: Total Rows Not Filtered

**Symptom:** Duplicate metrics (same country appears twice: once alone, once in Total)

**Root Cause:** Total row detection regex doesn't match format used in data

**Solution:** Expand total row keywords:
```python
_TOTAL_KEYWORDS = frozenset({
    "total", "grand total", "sub-total", "subtotal",
    "africa total", "region total", "summary",
})
```

---

### Issue 2: Product Not Found (Before Metrics)

**Symptom:** MetricRepository error: "product_name='dap' but product DNE"

**Root Cause:** Metrics emitted before product creation; product group ordering violated

**Solution:** Ensure members-first emission:
```
1. Collect all DAP metrics
2. Create ProductCreate("dap")
3. Collect all MAP metrics
4. Create ProductCreate("map")
5. Collect DAP+MAP metrics
6. Create ProductCreate("dap_map")
```

---

### Issue 3: Country Not in Referential

**Symptom:** region_name="unknown_region" for all country rows

**Root Cause:** Missing country→region mapping

**Solution:** Add to referential.yaml:
```yaml
country_region_mapping:
  new_country: target_region
```

---

## Implementation Checklist

When adapting these extractors to new data sources:

- [ ] Verify header row contains "country" (+ "region" or "sub_region")
- [ ] Confirm year columns are 4-digit numeric
- [ ] Add new countries to referential.country_region_mapping
- [ ] Implement total row detection (strip "Total" pattern match)
- [ ] Test metric naming: {metric_type}_{forecast|release}
- [ ] Verify product group safe-staging (members first)
- [ ] Validate no Inf/NaN in numeric values
- [ ] Check scope contains NO company/site entities (only geo)
- [ ] Confirm scenario detection (year ≥ pub_year = forecast)

---

## Related Documentation

- [README_HIERARCHICAL_CAPACITY_EXTRACTORS.md](README_HIERARCHICAL_CAPACITY_EXTRACTORS.md) — Company→Site (different pattern)
- [README_PLANT_CAPACITY_CASTER.md](README_PLANT_CAPACITY_CASTER.md) — Unified hierarchical extractors
- [README_FREIGHT_TRADE_EXTRACTOR.md](README_FREIGHT_TRADE_EXTRACTOR.md) — Trade/route-based extraction
- **sheets_extractors.yaml** — Master configuration (currently commented)
- **referential.yaml** — Geographic + product normalization

---

**Version:** 1.0 (Group Documentation)  
**Status:** ⚠️ Inactive/Reference  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team  
**Next Step:** Enable in sheets_extractors.yaml when ready to ingest S&P specialty phosphates data
