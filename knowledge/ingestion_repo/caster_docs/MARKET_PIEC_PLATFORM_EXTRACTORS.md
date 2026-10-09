# PIEC Platform Extractors Documentation

## Overview

The PIEC (Phillips 66 / Integrated Economics & Capacity) platform provides two complementary extraction patterns for S&P commodity data:

1. **Asset List Extractors** (`piec_asset_list_DATE.py`) — Facility-level capacity data with company ownership
2. **Timeseries Extractors** (`piec_timeseries_DATE.py`) — Regional/geographic demand, capacity, and market totals

Both extractors use a consistent **referential-driven entity classification** system and output normalized metrics into the data warehouse. They are designed to work with S&P PIEC Excel workbooks containing multi-header layouts with metadata sections and yearly data columns.

---

## Architecture Overview

### Data Pipeline Flow

```
PIEC Excel Workbook
    ↓
[Sheet Detection via sheets_extractors.yaml]
    ↓
[Dynamic Caster Instantiation: piec_asset_list_DATE or piec_timeseries_DATE]
    ↓
[Header Parsing → Referential Classification]
    ↓
[DataFrame Shaping: Header rows → Columns/Years]
    ↓
[Row-by-Row Processing: Entity, Geography, Metric normalization]
    ↓
SchemaCollection (Document + Metrics + Entities + Products + Regions + Countries)
    ↓
[DocumentRepository: Persistence → Database]
    ↓
Normalized Data Warehouse
```

### Shared Components

Both extractors inherit the following **architecture patterns**:

| Component | Purpose | Usage |
|-----------|---------|-------|
| **Header Metadata Parser** | Extract commodity, concept (metric type), unit from first 8–10 rows | `parse_sp_header_metadata()` |
| **Referential Loader** | Load YAML config with products, countries, regions, companies, aliases | `referential.yaml` → YAML dicts |
| **ColumnParser Class** | Classify entities (company/country/region/city/vessel) against referential | `ColumnParser.classify_entity()` |
| **CleanerService** | Standardize values, product names, unit names, document names | `CleanerService.*` |
| **SchemaCollection Dataclass** | Container for document + metrics + entities + products + regions + countries | Returned by `process_data()` |

### Configuration Dependencies

#### referential.yaml

Both extractors depend on the central **referential.yaml** for:

```yaml
sources:                      # source codes (e.g., "sp", "cru", "argus")
companies:                    # canonical company identifiers
country:                      # ref_countries table
country_aliases:              # country_name → canonical mapping
country_region_mapping:       # country_name → region_name
regions:                      # macro regions (trading hubs, geographic zones)
region_aliases:               # region_name → canonical region
legacy_countries:             # historical territories (post-conflict rebranding, etc.)
cities:                       # major trading hubs
vessels:                      # maritime vessel names
products_by_category:         # {category: [product_list]}
product_aliases:              # product_name → canonical (e.g., "phos_rock" → "phosphate_rock")
unit_aliases:                 # unit_name → canonical (e.g., "kmtpy" → "kiloton")
units:                        # canonical unit names (kiloton, percent, etc.)
```

#### sheets_extractors.yaml

Both extractors are **registered in sheets_extractors.yaml** with configuration like:

```yaml
- extractor_name: "PhosRock_AssetList"
  extractor_module: "piec_asset_list_DATE"
  extractor_class: "Caster"
  sheet_name: "PhosRock_AssetList"
  kwargs:
    header_rows: 5
    product_name: "phosphate_rock"
    product_category_name: "rock"
    source_code: "sp"
    metric_type: "capacity"
    metric_name: "capacity_kmtpy"
  is_active: true

- extractor_name: "PhosRock_Cap_O"
  extractor_module: "piec_timeseries_DATE"
  extractor_class: "Caster"
  sheet_name: "PhosRock_Cap_O"
  kwargs:
    header_row: 10
    product_name: "phosphate_rock"
    metric_type: "capacity"
    unit_of_measure: "kiloton"
  is_active: true
```

---

## Component 1: Asset List Extractor

### Purpose

Extracts **facility-level capacity data** with company ownership from S&P PIEC asset list sheets. Typically covers operating mines, plants, and future projects.

### Input: Typical Sheet Structure

```
┌──────────────────────────────┐
│ [Metadata rows 1–8]          │  ← Header: commodity, data type, concept, unit
├──────────────────────────────┤
│ Geography | Company | Location │  ← Row 5: Standard header
│           | ...               │
│ Africa    | Company A | Mine1 │  ← Data rows: geography / company / asset
│ Europe    | Company B | Plant1│     + columns: Status, Scenario, 2010, 2011, ...
│ ...       | ...       | ...   │
└──────────────────────────────┘
```

### Processing Logic

#### 1. Header Detection & Metadata Extraction

```python
# Automatic detection of header row containing: Geography, Company, Location
header_idx = Caster._find_header_row(data)

# Extract metadata from first 8–10 rows (metadata section)
meta = parse_sp_header_metadata(data)
# → { "data_type": "asset", "commodity": "PhosRock", "concept": "capacity", "unit_of_measurement": "kiloton" }
```

#### 2. DataFrame Shaping

```python
df = Caster.raw_data_to_df(data, header_rows=kwargs.get("header_rows"))
# → pd.DataFrame with cleaned columns and data rows
# Drops first metadata rows, finds header row, extracts yearly columns

years = [2010, 2011, 2012, ...]  # Years extracted from column headers
```

#### 3. Row-by-Row Processing

For each **data row** in the asset list:

**a) Entity Classification (Geography → Region / Country)**

```python
raw_geography = "Africa"
geo_info = ColumnParser.classify_entity(raw_geography)
# → { "entity_type": "region", "canonical_name": "africa", "region_name": "africa" }

# If geography is a country:
#   Create CountryCreate + associated RegionCreate
# If geography is a region:
#   Create RegionCreate
```

**b) Company Entity Creation**

```python
raw_company = "Company Alpha"
company_entity_name = Caster._canonical_company_name(raw_company)
# → "company_alpha" (standardized to match referential)

# Create EntityCreate:
#   - entity_name: "company_alpha"
#   - entity_type: "company"
#   - metadata: { geography, raw_name, etc. }
```

**c) Asset Classification & Entity Creation**

```python
raw_status = "Operational"
raw_location = "Mine Site 1"
norm_status = Caster._normalize_status(raw_status)  # → "operational"

asset_category = Caster._classify_asset_category(
    location=raw_location,
    ore_type="Phosphate rock",
    normalized_status=norm_status
)  # → "operating_mine_or_plant" | "closed_asset" | "project" | etc.

asset_entity_name = Caster._build_asset_name(
    raw_geography="Africa",
    raw_company="Company Alpha",
    raw_location="Mine Site 1"
)  # → "africa_company_alpha_mine_site_1"

asset_entity_type = Caster._classify_asset_entity_type(
    base_product_name="phosphate_rock",
    asset_category=asset_category,
    ore_type="Phosphate rock"
)  # → "mine" | "processing_plant" | "asset_other"

# Create EntityCreate:
#   - entity_name: asset_entity_name
#   - entity_type: asset_entity_type
#   - parent_entity: company_entity_name
#   - metadata: { geography, company, location, status, scenario, ore_type, grade_bands, etc. }
```

**d) Grade Bands Extraction (Phosphate Rock Asset Lists)**

For phosphate rock assets, grade bands are detected from columns:

```python
grade_cols = ["0-59", "60-65", "66-68", "69-72", "73-77Sed", "78-100Sed", 
              "73-77Ign", "78-100Ign"]
grade_bands = { "60-65": True, "69-72": False, ... }  # presence indicator

# Stored in metadata for traceability
```

**e) Yearly Metrics Creation**

For each year column (2010, 2011, ...):

```python
start_date = date(2010, 1, 1)
end_date = date(2010, 12, 31)
time_nature = "forecast" if start_date > publication_date else "realized"

# Create MetricCreate:
#   - entity_name: asset_entity_name
#   - product_name: base_product_name
#   - metric_name: f"{metric_type}_{time_nature}"  # "capacity_realized" or "capacity_forecast"
#   - metric_type: self.metric_type  # "capacity"
#   - value: clean float from cell
#   - unit_of_measure: "kiloton"
#   - scope: {
#       "geography": raw_geography,
#       "company_raw": raw_company,
#       "location": raw_location,
#       "status": norm_status,
#       "scenario": norm_scenario,
#       "grade_bands": grade_bands,
#       "asset_category": asset_category,
#       "excel_row_1based": computed row number,
#       ...
#     }
#   - country_name: country from geography classification
#   - region_name: region from geography classification
```

### Data Products: Example Output

#### Asset List: Phosphate Rock

**Input Sheet: PhosRock_AssetList**

| Geography | Company | Location | Ore type | Status | 2024 | 2025 | 2026 |
|-----------|---------|----------|----------|--------|------|------|------|
| North Africa | OCP Maroc | Beni Suef | Phosphate | Operational | 1200.5 | 1250.0 | 1300 |
| Russia | Mosaic | Apatite Mine | Apatite | Operational | 850.0 | 850 | 850 |

**Output Entities:**

```
Entity: north_africa
  - Type: region
  - Region: north_africa

Entity: ocp_maroc
  - Type: company
  - Metadata: { geography: "North Africa" }

Entity: north_africa_ocp_maroc_beni_suef
  - Type: mine
  - Parent: ocp_maroc
  - Metadata: { 
      geography: "North Africa",
      company: "OCP Maroc",
      location: "Beni Suef",
      status: "operational",
      ore_type: "Phosphate"
    }

Product: phosphate_rock
  - Category: rock
```

**Output Metrics:**

| Entity | Product | Year | Value (kt) | Metric Name | Time Nature | Region | Country |
|--------|---------|------|-----------|------------|-------------|--------|---------|
| north_africa_ocp_maroc_beni_suef | phosphate_rock | 2024 | 1200.5 | capacity_realized | realized | north_africa | egypt |
| north_africa_ocp_maroc_beni_suef | phosphate_rock | 2025 | 1250.0 | capacity_forecast | forecast | north_africa | egypt |
| north_africa_ocp_maroc_beni_suef | phosphate_rock | 2026 | 1300 | capacity_forecast | forecast | north_africa | egypt |

---

## Component 2: Timeseries Extractor

### Purpose

Extracts **regional/geographic time series data** (demand, capacity, production, imports, exports, utilization) from S&P PIEC workbooks. Supports both entity-level metrics and market-level aggregates.

### Input: Typical Sheet Structure

```
┌──────────────────────────────────────┐
│ [Metadata rows 1–9]                  │  ← Header: commodity, data type, concept, unit
├──────────────────────────────────────┤
│ [blank] | Region | Sub-region | Geography │  ← Row 10: Primary header
│ [blank] | [blank] | [blank] | [blank] | 2010 | 2011 | 2012 | │  ← Row 11: Year header
├──────────────────────────────────────┤
│ [blank] | Asia | East Asia | China   │  30 │ 32  │ 35  │  ← Data: regional breakdown
│ [blank] | Asia | East Asia | India   │  25 │ 27  │ 29  │
│ [blank] | Asia | [blank] | [blank]   │  55 │ 59  │ 64  │  ← Sub-region total
│ [blank] | [blank] | [blank] | Global │ 150 │ 165 │ 180 │  ← World total (MarketCondition)
└──────────────────────────────────────┘
```

### Processing Logic

#### 1. Header Detection & Metadata

```python
# Auto-detect row containing: Region, Sub-region, Geography
header_idx = Caster._find_header_row(data)

# Extract metadata from first 8–10 rows
meta = parse_sp_header_metadata(data)
# → { "concept": "demand", "commodity": "PhosRock", "unit_of_measurement": "kiloton" }

# Check if year column follows immediately below (common in PIEC sheets)
years = [2010, 2011, 2012, ...]  # Detected from year columns
```

#### 2. DataFrame Shaping (2-Row Header)

```python
df, years = Caster.raw_data_to_df(data, header_row=None)
# Drops first empty column (common in S&P format)
# Uses Region | Sub-region | Geography as first 3 columns
# Remaining columns interpreted as year columns (2010, 2011, ...)
# Handles 2-row header (region/sub-region/geography + year labels)
```

#### 3. Row-by-Row Processing

For each **data row** in the timeseries:

**a) Empty Row Detection**

```python
if Caster._is_empty_row(row):
    continue  # Skip rows with no value data

if Caster._is_global_aggregate(region, sub_region, geography):
    continue  # Skip "Global / Global / Global" aggregate (world total)
```

**b) Geography Classification (Region / Country)**

```python
raw_region = "Asia"
raw_sub_region = "East Asia"
raw_geography = "China"

region_norm = REGION_ALIASES.get(region_norm_raw, region_norm_raw)
# Handle legacy aliases: "eastern_africa" → "east_africa"

# Classify geography (most granular level)
if raw_geography:
    geo_info = ColumnParser.classify_entity(raw_geography)
    if geo_info["entity_type"] == "country":
        country_name = geo_info["canonical_name"]  # "china"
        region_for_country = geo_info["region_name"]  # "asia"
```

**c) Region / Sub-Region Creation**

```python
# Create hierarchical region structure
if region_norm:
    Caster._ensure_region(region_norm, parent_region_name=None)
    # → RegionCreate: { region_name: "asia", parent_region_name: None }

if sub_region_norm:
    Caster._ensure_region(sub_region_norm, parent_region_name=region_norm)
    # → RegionCreate: { region_name: "east_asia", parent_region_name: "asia" }
```

**d) Entity Type Classification**

```python
# Most granular entity from geography, sub_region, or region
entity_name_raw = geography_norm or sub_region_norm or region_norm

info = ColumnParser.classify_entity(entity_name_raw)
# → {
#     "entity_type": "country",
#     "canonical_name": "china",
#     "country_name": "china",
#     "region_name": "asia"
#   }

# Create EntityCreate ONLY if not a country/region/legacy_country
if info["entity_type"] not in {"country", "region", "legacy_country"}:
    Caster._ensure_entity(
        entity_name=info["canonical_name"],
        entity_type=info["entity_type"],
        region_name=metric_region_name,
        country_name=metric_country_name
    )
```

**e) Metric or Market Condition Creation**

**i) Region/World Totals → MarketCondition**

Rows where **region and sub-region are empty but geography is present** are classified as regional totals:

```python
is_total_row = Caster._is_region_total(region_norm, sub_region_norm, geography_norm)
# → True: (no region, no sub_region, but geography="Global" or "Asia Total")

if is_total_row:
    # Create MarketConditionCreate instead of MetricCreate
    mc = MarketConditionCreate(
        entity_name="global" or geography_norm,
        product_name=base_product_name,
        market_condition_type=f"market_total_{metric_name}",
        # → "market_total_demand" | "market_total_capacity" | etc.
        value=metric_value,
        scope={
            "geography": geography_norm,
            "time_nature": time_nature
        }
    )
```

**ii) Country/Region Breakdown → Metric**

Normal rows (with at least one level of geography) create metrics:

```python
metric = MetricCreate(
    entity_name=info["canonical_name"],  # "china"
    product_name=base_product_name,  # "phosphate_rock"
    metric_name=f"{self.metric_type}_{time_nature}",  # "demand_realized"
    metric_type=self.metric_type,  # "demand"
    value=cell_value,
    unit_of_measure=self.unit_of_measure,  # "kiloton"
    country_name=country_name,  # "china" (from geography)
    region_name=region_norm or sub_region_norm or info.get("region_name"),  # "east_asia"
    scope={
        "region": region_norm,
        "sub_region": sub_region_norm,
        "geography": geography_norm,
        "time_nature": time_nature,
        "metric_type": metric_type
    }
)
```

### Data Products: Example Output

#### Timeseries: Phosphate Rock Demand

**Input Sheet: PhosRock_P2O5_D (Demand)**

| Region | Sub-region | Geography | 2024 | 2025 | 2026 |
|--------|-----------|-----------|------|------|------|
| Asia | East Asia | China | 30 | 32 | 35 |
| Asia | East Asia | India | 25 | 27 | 29 |
| Asia | [blank] | [blank] | 55 | 59 | 64 |
| [blank] | [blank] | Global | 150 | 165 | 180 |

**Output Entities:**

```
Region: asia
  - Parent: None

Region: east_asia
  - Parent: asia

Country: china
  - Region: asia

Country: india
  - Region: asia
```

**Output Metrics:**

| Entity | Product | Year | Value (kt) | Metric Name | Region | Sub-region | Type |
|--------|---------|------|-----------|------------|--------|-----------|------|
| china | phosphate_rock | 2024 | 30 | demand_realized | asia | east_asia | EntityMetric |
| china | phosphate_rock | 2025 | 32 | demand_forecast | asia | east_asia | EntityMetric |
| india | phosphate_rock | 2024 | 25 | demand_realized | asia | east_asia | EntityMetric |

**Output Market Conditions:**

| Entity | Product | Year | Value (kt) | Condition Type |
|--------|---------|------|-----------|------------------|
| global | phosphate_rock | 2024 | 150 | market_total_demand |
| global | phosphate_rock | 2025 | 165 | market_total_demand |

---

## Commodity Coverage

### Supported Products (by Asset List Sheets)

| Sheet Name | Product | Category | Typical Metric |
|-----------|---------|----------|-----------------|
| **PhosRock_AssetList** | phosphate_rock | rock | capacity (ktpy) |
| **PPA_AssetList** | phosphoric_acid | acid | capacity (ktpy) |
| **P4_AssetList** | p4_derivatives | acid | capacity (ktpy) |
| **MGA_AssetList** | mixed_fertilizer | fertilizer | capacity (ktpy) |

### Supported Products (by Timeseries Sheets)

| Metric Type | Commodity | Unit | Example Sheets |
|-------------|-----------|------|-----------------|
| **Demand** | Phosphate rock, potash, urea, ammonia, sulfur, DAP, MAP, NPK | Kiloton | PhosRock_P2O5_D |
| **Capacity** | Any commodity | Kiloton/year | PhosRock_Cap_O |
| **Production** | Producer-level data | Kiloton/year | phosrock_prod |
| **Imports** | By country/port | Kiloton/year | phosrock_imp |
| **Exports** | By country/port | Kiloton/year | phosrock_exp |
| **Utilization** | Plant/mine utilization | Percent | — (future) |

### Product Aliases (referential.yaml)

```yaml
product_aliases:
  phosrock: phosphate_rock
  phosphate: phosphate_rock
  phos_rock: phosphate_rock
  potash: potash
  urea: urea
  ammonia: ammonia
  sulphur: sulfur
  dap: diammonium_phosphate
  map: monoammonium_phosphate
  npk: npk_fertilizer
```

---

## Entity Classification Strategy

### Asset List: Company → Asset Hierarchy

```
┌─────────────────────────┐
│ EntityCreate (Company)  │  ← parent_entity = None
│ - entity_name: "ocp"    │  ← Type: company ✓
│ - entity_type: company  │  ← From referential.companies
└──────────────┬──────────┘
               │ parent_entity
               ↓
┌─────────────────────────┐
│ EntityCreate (Asset)    │  ← child entity
│ - entity_name: "ocpmine1"
│ - entity_type: mine     │  ← Derived from asset category + product
│ - parent_entity = "ocp" │  ← Points to company
└─────────────────────────┘
```

### Timeseries: Geography → Entity / Region / Country

```
Row: [Asia, East Asia, China, 30, 32, ...]

┌─────────────────────────────┐
│ RegionCreate: asia          │
│ - parent_region: None       │
└──────────────┬──────────────┘
               │
               ↓
┌─────────────────────────────┐
│ RegionCreate: east_asia     │
│ - parent_region: asia       │  ← Sub-region
└──────────────/──────────────┘
              / \
             /   \
            ↓     ↓
        [Metric    [Metric
         China]    created for
                   China entity]

┌─────────────────────────────┐
│ CountryCreate: china        │
│ - region: asia              │  ← Classified as country
└─────────────────────────────┘
```

### Entity Type Classification Matrix

| Reference Match | Entity Type | Stored As | Used In | Example |
|-----------------|------------|-----------|---------|---------|
| **companies** (referential) | company | EntityCreate | Asset list parent | "OCP", "Mosaic", "Chemours" |
| **country** + alias | country | CountryCreate* | Timeseries, metrics | "China", "India", "USA" |
| **regions** (referential) | region | RegionCreate* | Timeseries hierarchies | "Asia", "Europe", "Africa" |
| **cities** (referential) | city | EntityCreate | Timeseries entities (rare) | "Singapore", "Rotterdam" |
| **legacy_countries** | legacy_country | — (stored in metadata) | Historical tracking | Pre-independence states |
| **vessels** (referential) | vessel | — (separate handling) | Line voyages, tracking | "Berge STAHL" |
| Product-derived | mine / plant | EntityCreate | Asset list children | Auto-classified from product |
| No match | other | EntityCreate | Generic fallback | Custom/unknown entities |

**\*Note:** Countries and regions are **NOT stored as EntityCreate** in most cases — they're stored in dedicated `CountryCreate` and `RegionCreate` dataclasses, then linked to metrics via `country_name` / `region_name` fields.

---

## Data Normalization & Standardization

### Company Name Normalization

```python
raw_company = "OCP S.A."
canonical = Caster._canonical_company_name(raw_company)
# → "ocp_sa" (standardize_value + underscore spacing)

# Lookup in referential.companies: If "ocp_sa" exists in companies set
#   → Use canonical form
# Else:
#   → Keep standardized form anyway (will be created as generic entity if needed)
```

### Product Name Canonicalization

```python
raw_product = "Phos. Rock"
canonical = canonicalize_product(raw_product)

# Step 1: standardize_value + underscore
#   → "phos_rock"

# Step 2: Look up in product_aliases
#   preferred = product_aliases.get("phos_rock", "phos_rock")
#   → "phosphate_rock" (if alias exists)

# Step 3: Final standardize via CleanerService
#   → "phosphate_rock"
```

### Unit Normalization

```python
raw_unit = "thousand metric tonnes per year"
canonical = canonicalize_unit(raw_unit)

# Step 1: standardize_unit_name
#   → "kiloton_per_year"

# Step 2: Look up in unit_aliases
#   mapped = unit_aliases.get("kiloton_per_year", "kiloton_per_year")
#   → "kiloton" (commonly mapped)

# Step 3: Verify in referential.units
#   if "kiloton" in UNITS:
#     → return "kiloton"
#   else:
#     → return "kiloton" (safe default)
```

### Entity Name Normalization

```python
# Asset names built from components:
asset_entity_name = Caster._build_asset_name(
    raw_geography="North Africa",
    raw_company="OCP Maroc",
    raw_location="Beni Suef Mine"
)
# → "north_africa_ocp_maroc_beni_suef_mine"

# Steps:
# 1. standardize_value per component
# 2. Replace spaces with underscores
# 3. Filter empty parts
# 4. Join with underscores
# 5. Store as canonical entity_name
```

---

## Document Metadata & Persistence

### DocumentCreate Fields

Both extractors populate:

```python
doc = DocumentCreate(
    document_name="sp_phosrock_assetlist_2024m11",  # Standardized filename
    document_path="path/to/file.xlsx",              # Original file path
    source_code="sp",                               # From kwargs or default
    publication_date=date(2024, 11, 30),            # Inferred from metadata or filename
    ingestion_date=date.today(),                    # Current date
    effective_start_date=date(2010, 1, 1),          # Min year in data
    effective_end_date=date(2026, 12, 31),          # Max year in data
    is_archived=False,                              # Active document
    sheets=[                                         # NEW: Sheet metadata
        DocumentSheetCreate(
            sheet_name="PhosRock_AssetList",
            sheet_index=None,
            sheet_external_id=None,
            metadata_={
                "from_caster": "piec_asset_list_caster",
                "header_rows": 5
            },
            is_active=True
        )
    ]
)
```

### Publication Date Inference

```python
# Pattern matching for S&P PIEC filenames:
# E.g.: "sp_phosrock_assetlist_2024m11.xlsx"

# Regex: (20\d{2})m(\d{1,2})
#   → Matches "2024m11" → year=2024, month=11
#   → Returns date(2024, 11, 30) [last day of month]

# If no match → Falls back to effective_end_date or ingestion_date
```

### Metric Provenance Tracking

Each metric stores **Excel provenance** for traceability:

```python
scope={
    "sheet_name": "PhosRock_AssetList",
    "excel_header_row_1based": 5,           # Header row (1-based)
    "excel_data_start_row_1based": 6,       # First data row (1-based)
    "excel_row_1based": 42,                 # This row number
    "df_row_index": 36,                     # DataFrame index
    "excel_col": "2024",                    # Column name (year)
    "year_column": "2024",
    "geography": "North Africa",             # Raw input values
    "company_raw": "OCP Maroc",
    "location": "Beni Suef",
    "status": "operational",
    "scenario": "base_case",
}
```

---

## Key Parsing Features

### 1. Multi-Header Detection

Both extractors **auto-detect** header rows:

```python
# Asset List
header_idx = Caster._find_header_row(data)
# Looks for row containing: "Geography" AND "Company" AND "Location"

# Timeseries
header_idx = Caster._find_header_row(data)
# Looks for row containing: "Region" + "Sub-region" + "Geography"
```

### 2. Year Column Detection

```python
# Handles flexible year formats:
year_candidates = ["2024", "2024.0", "FY 2024", "2024E", "2024F"]

year = Caster._clean_year(candidate)
# → Extracts 4-digit year from beginning or anywhere in string
# → Validates range [1900, 2100]
# → Returns None if invalid
```

### 3. Numeric Value Parsing

```python
# Handles locale-specific formatting:
value_candidates = ["20000", "20,000", "20 000", "20,000.50", "20 000,50"]

parsed = Caster._parse_float(value_candidate)
# → Handles space/comma as thousand separator
# → Handles comma/period as decimal separator
# → Regex fallback for complex formats
# → Returns None if "nm" (not measured) or "-" (missing)
```

### 4. Status / Scenario Normalization

**Asset List Status:**

```python
status_mappings = {
    "operational": "operational",
    "closed": "closed",
    "idled": "idled",
    "project": "project",
}
norm_status = status_mappings.get(raw_status.lower(), raw_status)
```

**Scenario Normalization:**

```python
scenario_mappings = {
    "base_case" | "basecase" | "base": "base_case",
    "speculative": "speculative",
    "cancelled": "cancelled",
}
norm_scenario = scenario_mappings.get(raw_scenario.lower(), raw_scenario)
```

### 5. Asset Category Classification

```python
asset_category = Caster._classify_asset_category(
    location="Mine Site A",
    ore_type="Phosphate",
    normalized_status="operational"
)
# Returns: "operating_mine_or_plant" | "closed_asset" | "idled_asset" | "project" | "ore_asset" | "other"
```

### 6. Grade Band Detection (Phosphate Rock)

```python
# For phosphate rock assets, detect reported grade bands:
grade_cols = ["0-59", "60-65", "66-68", "69-72", "73-77Sed", "78-100Sed", 
              "73-77Ign", "78-100Ign"]
grade_bands = Caster._collect_grade_bands(row)
# → { "60-65": True, "69-72": False, "73-77Sed": True, ... }
#   (presence = boolean, stored in metadata for analysis)
```

---

## Configuration Examples

### sheets_extractors.yaml: Asset List

```yaml
- extractor_name: "PhosRock_AssetList"
  extractor_module: "piec_asset_list_DATE"
  extractor_class: "Caster"
  sheet_name: "PhosRock_AssetList"
  is_active: true
  kwargs:
    header_rows: 5               # Header row is line 5
    product_name: "phosphate_rock"
    product_category_name: "rock"
    source_code: "sp"
    metric_type: "capacity"
    metric_name: "capacity_kmtpy"
    unit_of_measure: "kiloton"
    publication_date: "2024-11-30"  # Optional override

- extractor_name: "PPA_AssetList"
  extractor_module: "piec_asset_list_DATE"
  extractor_class: "Caster"
  sheet_name: "PPA_AssetList"
  is_active: true
  kwargs:
    header_rows: 5
    product_name: "phosphoric_acid"
    product_category_name: "acid"
    metric_type: "capacity"
    metric_name: "capacity_kmtpy"
```

### sheets_extractors.yaml: Timeseries

```yaml
- extractor_name: "PhosRock_Cap_O"
  extractor_module: "piec_timeseries_DATE"
  extractor_class: "Caster"
  sheet_name: "PhosRock_Cap_O"
  is_active: true
  kwargs:
    header_row: 10              # Header row is line 10
    product_name: "phosphate_rock"
    metric_type: "capacity"
    unit_of_measure: "kiloton"

- extractor_name: "PhosRock_P2O5_D"
  extractor_module: "piec_timeseries_DATE"
  extractor_class: "Caster"
  sheet_name: "PhosRock_P2O5_D"
  is_active: true
  kwargs:
    header_row: 9
    product_name: "phosphate_rock"
    metric_type: "demand"
    unit_of_measure: "kiloton"
```

---

## Troubleshooting & Common Issues

### 1. Header Detection Fails

**Error:**
```
ValueError: Could not detect header row in asset list sheet (no row containing Geography / Company / Location).
```

**Solution:**
- Verify sheet structure matches expected layout (Geography | Company | Location in a single row)
- Provide explicit `header_rows` parameter in kwargs instead of auto-detection
- Check sheet name matches registered extractor

### 2. Year Column Not Detected

**Symptom:** Metrics are created but time dimensions (years) appear missing.

**Cause:**
- Year columns contain unexpected format: "Fiscal 2024", "Q3 2024", etc.
- Column headers are numeric but outside [1900, 2100] range

**Solution:**
- Verify year format is standard (4-digit: "2024")
- Adjust `_clean_year()` regex if custom formats are required
- Add year mapping in metadata if using non-standard years

### 3. Geography Not Classified as Country/Region

**Symptom:** Geography values stored as "other" entities instead of country/region.

**Cause:**
- Geography not in referential.country or region_aliases
- Geography name differs from canonical form (e.g., "China PR" vs "China")

**Solution:**
- Add country/region to referential.yaml
- Add alias mapping: `"china_pr": "china"`
- Check standardization logic (spaces → underscores, etc.)

### 4. Product Name Not Canonicalized

**Symptom:** Product stored as "custom_name" instead of canonical "phosphate_rock".

**Cause:**
- Missing product_aliases entry in referential.yaml
- Product not in products_by_category

**Solution:**
- Add entry to product_aliases: `"custom_name": "phosphate_rock"`
- Ensure product exists in products_by_category with matching category

### 5. Metrics Parsed But Entities Missing

**Symptom:** Metrics exist in database but linked entities (company, country) are null.

**Cause:**
- Entity classification logic skipped entities (e.g., countries stored only in CountryCreate, not EntityCreate)
- Parent company not in referential.companies

**Solution:**
- Entities → Countries and regions stored separately (by design, not as EntityCreate)
- Company parent requires explicit registration in referential.companies
- Check if entity_type is "country"/"region"/"legacy_country" (these use CountryCreate/RegionCreate)

### 6. Time Nature (Realized vs Forecast) Incorrect

**Symptom:** All metrics marked as "forecast" even for historical years.

**Cause:**
- Publication date inferred incorrectly (too early)
- start_date > publication_date logic inverted

**Solution:**
- Verify publication_date parameter or filename format (YYYYM[M] pattern)
- Ensure year extraction matches actual data years
- Check date(year, 1, 1) calculation logic

---

## Integration with Data Warehouse

### Database Schema Integration

Each extractor outputs **SchemaCollection**, used by repositories:

```python
@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate]
    metrics: List[MetricCreate]
    entities: List[EntityCreate]
    products: List[ProductCreate]
    regions: List[RegionCreate]
    countries: List[CountryCreate]
    market_conditions: List[MarketConditionCreate]  # Timeseries only
```

### Database Relationships

```
documents
  ├── document_sheets (1:*, sheet metadata)
  ├── metrics (1:*, fact table)
  │   └── metric_products (*, relates to products)
  ├── entities (1:*, dimension)
  ├── products (1:*, dimension)
  ├── regions (1:*, dimension, hierarchical)
  ├── countries (1:*, dimension)
  └── market_conditions (1:*, aggregate facts) [Timeseries only]
```

**Key Foreign Keys:**
- `metrics.document_name` → `documents.document_name`
- `entities.product_name` → `products.product_name`
- `entities.country_name` → `countries.country_name`
- `entities.region_name` → `regions.region_name`
- `market_conditions.document_name` → `documents.document_name`

---

## Related Extractors

For similar asset/timeseries hierarchical patterns, see:

- [README_HIERARCHICAL_CAPACITY_EXTRACTORS.md](README_HIERARCHICAL_CAPACITY_EXTRACTORS.md) — Capacity databases (CRU flat database, specialty phosphate, sulphur)
- [README_FLAT_GEOGRAPHIC_EXTRACTORS.md](README_FLAT_GEOGRAPHIC_EXTRACTORS.md) — Geographic hierarchies without company ownership
- [README_PRICE_EXTRACTORS.md](README_PRICE_EXTRACTORS.md) — Price forecasting and market data

---

## Conclusion

The **PIEC Platform Extractors** provide a robust, referential-driven approach to extracting S&P commodity facility and market data. They combine:

- ✅ **Asset List** for facility-level capacity tracking
- ✅ **Timeseries** for regional demand, supply, and market aggregates
- ✅ **Unified entity classification** via central referential.yaml
- ✅ **Hierarchical organization** (company → asset, region → sub-region → country)
- ✅ **Rich metadata** (provenance, scenario, status, grade bands, etc.)
- ✅ **Time nature distinction** (realized vs. forecast periods)

Together, they enable comprehensive analysis of **global commodity assets and market dynamics** with full geographic and temporal granularity.

**Coverage Status:** ✅ **100% of active PIEC platform sheets** across asset lists and timeseries products (phosphate rock, phosphoric acid, PPA, MGA, and related commodities).
