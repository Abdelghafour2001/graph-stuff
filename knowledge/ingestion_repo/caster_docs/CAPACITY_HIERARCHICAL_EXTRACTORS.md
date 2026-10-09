# README: Hierarchical Capacity Extractors (Unified Pattern)

**Files:**
- `cru_capacity_database_caster.py` — CRU unified capacity database (ammonia, phosphate rock, phosphate fert, NPK, sulphur)
- `cru_cost_service_caster.py` — CRU cost service flat database (phosphate fertilizer + phosphate rock commodities)
- `specialty_phosphates_market_outlook_DATE_database_amended__pwa_tpa_capacity_list.py` — S&P specialty phosphates capacity list
- `argus_potash_analytics_1q_DATE_capacity_by_plant.py` — Argus potash analytics capacity by plant

**Pattern:** Hierarchical (Company → Site/Plant) with parent-child entity model  
**Data Sources:** CRU, S&P (PIEC), Argus analytics databases  
**Supported Products:** 12+ (ammonia, phosphate rock, DAP, MAP, TSP, WPA, NPK, sulphur, potash, phosphoric acid, etc.)  
**Status:** ⚠️ Inactive (commented in sheets_extractors.yaml) — Reference implementations available

---

## Overview

This documentation covers **4 specialized extractors** that share an **identical hierarchical entity pattern**: all normalize plant/site-level capacity, cost, or asset data from production facilities. They follow a uniform two-entity model (Company parent → Site child) while handling diverse input formats, metadata, and commodity types.

### Shared Features

- **Hierarchical entities**: Company (entity_type="company") → Site/Plant (entity_type="site", parent_entity=company)
- **Parent-child deduplication**: Prevent duplicate companies; create sites only if new
- **Site naming collision avoidance**: Composite site_key = company_plant_location_unit (with optional parts)
- **Rich metadata in scope**: All metadata (status, technology, feedstock, PGS scoring, etc.) stored in metric.scope
- **JSON safety**: Strip Inf/NaN values before Postgres JSON insertion
- **Referential integration**: Load country/region/product aliases from YAML
- **Scenario detection**: Forecast vs. release/realized based on year vs. publication date

---

## Architecture (Unified Pattern)

```
Hierarchical Capacity Extractor
│
├─ Input: Excel sheet with Region|Country|Company|Site/Plant|... + Year columns
│  └─ Optional: Product, Status, Technology, PGS Scoring, Location, Unit columns
│
├─ Stage 1: Document Context
│  ├─ Create DocumentCreate (publication date from filename or preamble)
│  ├─ Infer source code: cru, sp, or argus
│  ├─ Infer default product: from document name or file metadata
│  └─ Confirm sheet type (Capacity Forecasts, Database, Projects, Cost Data, etc.)
│
├─ Stage 2: Header Detection
│  ├─ Scan first 20-30 rows for row with "country" AND ("region" OR "company")
│  ├─ Build column map: country → col_idx, company → col_idx, site → col_idx, etc.
│  ├─ Extract year columns (numeric-only 4-digit headers)
│  └─ Detect capacity_type from sheet name: "Gross", "Merchant", "Net" (optional)
│
├─ Stage 3: PRE-PASS (Entity Collection)
│  ├─ Scan all rows for Region, Country, Company nodes
│  ├─ Normalize geographies via referential
│  ├─ Create RegionCreate, CountryCreate, CompanyCreate (dedup by entity_name)
│  └─ Build company index for site parent lookups
│
├─ Stage 4: MAIN-PASS (Metrics + Site Entity Generation)
│  ├─ For each row:
│  │  ├─ Normalize Country → Region (via referential)
│  │  ├─ Extract Company + Site/Plant names
│  │  ├─ Build composite site_key (company_site_location_unit)
│  │  ├─ Create Site entity with parent_entity=company
│  │  ├─ Detect Product (column OR document default)
│  │  ├─ Detect Metrics (all numeric year columns)
│  │  ├─ For each year value:
│  │  │  ├─ Determine scenario: year ≥ pub_year → forecast; else → release
│  │  │  ├─ Build metric_name (e.g., capacity_forecast, cost_release)
│  │  │  ├─ Enrich scope with all metadata (status, tech, feedstock, unit, etc.)
│  │  │  └─ Create MetricCreate with rich scope
│  │  └─ Emit Site + all metrics
│  └─ Skip aggregate rows (totals, world, global keywords)
│
├─ Stage 5: JSON Safety
│  ├─ Strip Inf/NaN from all numeric values
│  ├─ Validate scope dict has no Inf/-Inf/-0.0
│  ├─ Clean string values (remove unprintables)
│  └─ Prevent Postgres JSON column violations
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Products (1-5 per file)
   ├─ Regions (normalized)
   ├─ Countries (mapped to regions)
   ├─ Entities (companies + sites with parent hierarchy)
   └─ Metrics (capacity/cost by site-year with rich scope)
```

---

## Extractors in This Group

### 1. CRU Capacity Database Caster

**File:** `cru_capacity_database_caster.py` (835 lines)  
**Coverage:** 5 CRU capacity files (ammonia, phosphate rock, phosphate fert, NPK, sulphur)  
**Sheet Types:** "Capacity Forecasts", "Projects", "Net Capacity Forecasts", "Capacity Forecasts-Base Case"

**Key Features:**
- **Multi-product per file**: DAP, MAP, TSP, WPA, NPK detected from sheet names
- **Composite entity naming**: "{company}_{plant}" as entity_name
- **Extensive metadata scope**: Includes plant_capex, train_capex, epc, rock_grade, bpl, technology, feedstock, PGS scoring
- **Scope structure**:
  ```python
  scope = {
    "region": region,
    "sub_region": sub_region,
    "country": country,
    "plant_name": plant,
    "short_plant_name": short_plant_name,
    "operating_company": company,
    "location": location,
    "technology": technology,
    "feedstock": feedstock,
    "status": status,
    "pgs_scoring": pgs_scoring,
    "product": product,
    "plant_capex": capex_value,
    # ... 20+ metadata fields
  }
  ```
- **Entity hierarchy**: Company parent with full plant metadata in Site child

---

### 2. CRU Cost Service Caster

**File:** `cru_cost_service_caster.py` (845 lines)  
**Coverage:** 2 CRU cost service files (phosphate fertilizer + phosphate rock)  
**Sheet Types:** "Database" sheets only

**Key Features:**
- **Multi-commodity support**: DAP, MAP, TSP, Phosphoric acid, Sulphuric acid (auto-detected from column)
- **Cost-specific metrics**: Data Types include vcp, cash costs, capex, etc.
- **Calculation types**: capacity, production, demand, cost_of_goods_sold, etc.
- **Scope includes**:
  ```python
  scope = {
    "region": region,
    "country": country,
    "company": company,
    "site_name": site_name,
    "status": status,
    "commodity": commodity,
    "data_category": data_category,
    "data_type": data_type,
    "calculation_type": calculation_type,
    "data_type_id": data_type_id,
    "site_or_business": site_or_business,
    "scenario": "forecast" or "realized"
  }
  ```
- **Entity**: {company}_{site_name} composite

---

### 3. Specialty Phosphates Capacity List Caster

**File:** `specialty_phosphates_market_outlook_DATE_database_amended__pwa_tpa_capacity_list.py`  
**Coverage:** S&P specialty phosphates capacity list sheets  
**Products:** PWA TPA, tMAP, P4, LFP/LMFP, STPP, SPA, APP, DCP, MCP-MDCP

**Key Features:**
- **Product group detection**: From sheet name pattern ("PWA TPA Capacity list", "MCP-MDCP Capacity list", etc.)
- **Specific product overrides**: PWA TPA and MCP-MDCP have dedicated patterns before generic fallback
- **Header row 3**: Includes columns for Region, Country, Company, Site, Product, Status, PGS Scoring, year columns
- **Scope**:
  ```python
  scope = {
    "region": region,
    "country": country,
    "company": company,
    "site_name": site_name,
    "product": product,
    "status": status,
    "pgs_scoring": pgs_scoring,
    "location": location
  }
  ```
- **Entity naming**: Handles product groups safely (staging: members first, then group)

---

### 4. Argus Potash Analytics Caster

**File:** `argus_potash_analytics_1q_DATE_capacity_by_plant.py`  
**Coverage:** Argus Potash Analytics files  
**Sheet Types:** "NPK Capacity List" (with "argus" in filename filter)  
**Product:** potash (MOP)

**Key Features:**
- **Single product (Potash)**: Detected from file pattern
- **Header detection**: Standard (country + region/company)
- **Year columns**: Auto-detected 4-digit numeric
- **Scope**: Similar to plant_capacity_caster (city, status, technology, unit)
- **Entity naming**: company_plant_location_unit composite

---

## Key Processing Differences

| Aspect | CRU Capacity | CRU Cost Service | Specialty Phosphates | Argus Potash |
|--------|---|---|---|---|
| **Products** | Multi (sheet-dependent) | Multi (column-dependent) | Multi (pattern-dependent) | Single (potash) |
| **Commodity Col** | Optional | Yes (Commodity) | Optional | No |
| **Metric Type** | capacity + scenario | cost + calc_type | capacity + scenario | capacity + scenario |
| **Scope Fields** | 20+ (capex, grades, etc.) | 10+ (cost-specific) | 7+ (basic) | 8+ (basic + status) |
| **Header Row** | Variable (scan 0-30) | Variable (scan 0-30) | Row 3 (fixed) | Variable (scan 0-30) |
| **Aggregate Skip** | Yes (total keywords) | Yes | Yes | Yes |

---

## Data Structures (Unified)

### SchemaCollection (Output)

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate             # File metadata
    metrics: List[MetricCreate]          # Capacity/cost by site-year
    entities: List[EntityCreate]         # Companies + Sites
    products: List[ProductCreate]        # 1-5 products per file
    regions: List[RegionCreate]
    countries: List[CountryCreate]
```

### EntityCreate (Company)

```python
EntityCreate(
    entity_name="shell",
    entity_type="company",
    country_name="netherlands",
    region_name="western_europe",
    is_active=True,
)
```

### EntityCreate (Site)

```python
EntityCreate(
    entity_name="shell_port_arthur_refinery_1",  # composite: company_plant_location_unit
    entity_type="site",
    parent_entity="shell",                       # FK reference
    country_name="united_states",
    region_name="north_america",
    metadata_={
        "city": "Port Arthur, Texas",
        "status": "Operating",
        "technology": "Steam Reforming",
        "unit": "1",
    },
    is_active=True,
)
```

### MetricCreate (Example)

```python
MetricCreate(
    metric_name="capacity_forecast",
    metric_type="capacity",
    value="500",
    unit_of_measure="kiloton",
    year=2025,
    start_date_effect=date(2025, 1, 1),
    end_date_effect=date(2025, 12, 31),
    date_publication=date(2025, 3, 1),
    country_name="united_states",
    region_name="north_america",
    entity_name="shell_port_arthur_refinery_1",
    product_name="ammonia",
    sheet_name="Capacity Forecasts",
    document_name="cru_ammonia_market_outlook_1q_2025",
    scope={
        "region": "north_america",
        "country": "united_states",
        "plant_name": "Port Arthur",
        "operating_company": "shell",
        "location": "Port Arthur, Texas",
        "status": "Operating",
        "technology": "Steam Reforming",
        "feedstock": "natural_gas",
        # ... 15+ additional fields per extractor
    }
)
```

---

## Site Naming Collision Avoidance

**Problem:** Same plant name can exist in different companies/locations.  
**Solution:** Composite site_key with optional collision-resolving parts.

```python
site_key_parts = [company, plant]
if location:
    site_key_parts.append(location_clean)
if unit_identifier:
    site_key_parts.append(unit_clean)
site_key = "_".join(site_key_parts)

# Examples:
#   "shell_port_arthur"                (basic: company + plant)
#   "shell_port_arthur_texas"         (+ location)
#   "shell_port_arthur_texas_1"       (+ unit identifier)
```

---

## JSON Safety Pattern

All extractors strip Inf/-Inf/NaN before emitting metrics:

```python
# In _safe_float:
def _safe_float(v) -> Optional[float]:
    try:
        f = float(v)
        if math.isinf(f) or math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None

# In scope emission:
scope = {k: v for k, v in scope.items() 
         if not (isinstance(v, float) and (math.isinf(v) or math.isnan(v)))}
```

---

## Referential Integration

### Required Mappings

```yaml
# referential.yaml
country_region_mapping:
  shell_parent_country: region_name
  # ... comprehensive mapping for all vendors' countries

product_aliases:
  "phosphoric_acid": "phosphoric_acid"
  "sulf_acid": "sulphuric_acid"
  # ... product standardization

unit_aliases:
  "kt": "kiloton"
  "'000 tonnes": "kiloton"
  # ... unit standardization
```

---

## Configuration (sheets_extractors.yaml)

```yaml
# Example: CRU Capacity Database (currently commented)
# - name: capacity_database
#   extractor_code: cru_capacity_database_caster.py
#   matches:
#     exact:
#       - value: "Capacity Forecasts"
#         data_provider: "cru"
#       - value: "Projects"
#         data_provider: "cru"

# Example: CRU Cost Service (currently commented)
# - name: cost_service_database
#   extractor_code: cru_cost_service_caster.py
#   matches:
#     exact:
#       - value: "Database"
#         data_provider: "cru"
```

---

## Worked Examples

### Example 1: CRU Ammonia Capacity Database

**File:** `ammonia-market-outlook-2025-1Q-capacity-database.xlsx`  
**Sheet:** "Capacity Forecasts"

**Input (excerpt):**
```
| Region | Sub Region | Country | Plant Name | Company | Status | Technology | 2024 | 2025F |
|--------|-----------|---------|-----------|---------|--------|-----------|------|-------|
| Me.E   | Persian G | Iran    | Isfahan   | NIOC    | Operat | Steam  | 1500 | 1500  |
| N Am   | Gulf      | USA     | Port Art  | Shell   | Operat | Steam  | 500  | 500   |
```

**Processing:**
- Entity 1: Company("nioc", country="iran", region="middle_east")
- Entity 2: Site("nioc_isfahan", parent="nioc", location="Isfahan")
- Metric 1: capacity_release, 2024, value=1500kt
- Metric 2: capacity_forecast, 2025, value=1500kt
- Scope includes: region, country, technology, status

---

### Example 2: CRU Cost Service (Multi-Commodity)

**File:** `phosphate-fertilizer-cost-service-Q1-2025-flat-database.xlsx`  
**Sheet:** "Database"

**Input (excerpt):**
```
| Company | Site | Country | Commodity | Data Type | Calculation Type | Unit | 2024 | 2025(F) |
|---------|------|---------|-----------|-----------|--|------|------|---------|
| Prayon  | Engis | Belgium | DAP | Cash Cost | Production | $/t | 285 | 295 |
| OCP     | Laayoune | Morocco | MAP | VCP | Capacity | kiloton | 2500 | 2500 |
```

**Processing:**
- Extract company="prayon", site="engis"
- Entity 1: Company("prayon", country="belgium")
- Entity 2: Site("prayon_engis", parent="prayon")
- Product: DAP (from Commodity column)
- Metric: cash_cost_release (2024) and cash_cost_forecast (2025)
- Scope includes: commodity, data_type, calculation_type, scenario

---

## Troubleshooting

### Issue 1: Parent-Child Deduplication Fails

**Symptom:** Same company appears multiple times; sites have orphaned parent

**Root Cause:** Pre-pass didn't emit all companies before main-pass

**Solution:** Ensure pre-pass runs BEFORE main-pass; both scan same filtered rows

---

### Issue 2: Site Key Collision Unresolved

**Symptom:** Two different sites have same entity_name

**Root Cause:** Plant name identical; location/unit not available to differentiate

**Solution:** Add location or unit column to source sheet; update site_key construction logic

---

### Issue 3: JSON Scope Contains Inf/-Inf

**Symptom:** Postgres error: "Infinity is not valid JSON"

**Root Cause:** Numeric value not validated before scope insertion

**Solution:** Call _safe_float() on ALL numeric conversions; strip Inf before scope dict construction

---

## Implementation Checklist

When adapting these extractors to new data sources:

- [ ] Verify header row contains "country" + "company"/"region"
- [ ] Confirm year columns are 4-digit numeric
- [ ] Add new countries to referential.country_region_mapping
- [ ] Test parent-child entity dedup (same company, different plants)
- [ ] Validate site_key uniqueness (no collisions across all plants)
- [ ] Check metric values for Inf/NaN before metric emission
- [ ] Verify scope dict has NO Inf/-Inf/-0.0 values
- [ ] Test forecast vs. release scenario detection
- [ ] Confirm product detection (column → document → default priority)

---

## Related Documentation

- [README_PLANT_CAPACITY_CASTER.md](README_PLANT_CAPACITY_CASTER.md) — Similar hierarchical patterns (Argus/S&P/CRU)
- [README_PHOSPHATE_CAPACITY_DATABASE.md](README_PHOSPHATE_CAPACITY_DATABASE.md) — Specific phosphate capacity patterns
- [README_FLAT_GEOGRAPHIC_EXTRACTORS.md](README_FLAT_GEOGRAPHIC_EXTRACTORS.md) — Alternative flat (non-hierarchical) pattern
- [README_FREIGHT_TRADE_EXTRACTOR.md](README_FREIGHT_TRADE_EXTRACTOR.md) — Trade/route-based extraction
- **sheets_extractors.yaml** — Master configuration (currently all commented)
- **referential.yaml** — Normalization database

---

**Version:** 1.0 (Group Documentation)  
**Status:** ⚠️ Inactive/Reference  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team  
**Next Step:** Enable in sheets_extractors.yaml when ready to ingest these data sources
