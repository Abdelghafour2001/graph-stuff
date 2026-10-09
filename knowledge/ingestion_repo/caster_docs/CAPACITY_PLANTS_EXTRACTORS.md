# README: Plant Capacity Caster

**File:** `plant_capacity_caster.py`  
**Pattern:** Plant-level capacity extraction (Caster pattern)  
**Data Sources:** Argus, S&P (PIEC), CRU multi-source analytics databases  
**Entity Model:** Hierarchical (Company → Site/Plant) with optional unit/location tracking  
**Supported Products:** Ammonia, Phosphate Rock, Potash, Urea, Sulphur, NPK, Phosphate Fertilizers  
**Status:** ✅ Active - Production-grade unified extractor

---

## Overview

The **Plant Capacity Caster** is a sophisticated unified extractor that normalizes plant-level capacity data across multiple vendors (Argus, S&P, CRU) and products. It handles dynamic column detection, variant resolution (gross/merchant/net capacity, physical forms, grades), and multi-year time series with scenario detection (forecast vs. release).

### Key Features

- **Multi-vendor support**: Argus, S&P (PIEC), CRU analytics files
- **11+ products**: Ammonia, phosphate rock, potash, urea, sulphur, NPK, phosphate fertilizers
- **Hierarchical entities**: Company (parent) → Site/Plant (child) with unit/location tracking
- **Dynamic column detection**: Auto-detects region, country, company, plant, product, type, grade, UOM columns
- **Variant resolution**: Type (gross/merchant/net), physical form (granular/prilled), grade, feedstock
- **Scenario detection**: Forecast vs. release based on year vs. publication date
- **Geographic normalization**: Country → region via referential mapping
- **Two-pass processing**: Pre-pass for entities, main-pass for metrics

---

## Architecture

```
Plant Capacity Extractor
│
├─ Input: Excel sheet with Region|Country|Company|Plant|City|Status|... + Year columns
│  └─ Optional: Product, Type, Grade, UOM, Technology, PGS Scoring columns
│
├─ Stage 1: Document Context
│  ├─ Create DocumentCreate (publication date from filename: 1Q2025, March-2025, etc.)
│  ├─ Infer source code: argus, sp, or cru
│  ├─ Infer default product: from document name pattern
│  └─ Confirm sheet type: "Capacity by Plant", "Capacity Forecasts", etc.
│
├─ Stage 2: Header Detection
│  ├─ Scan first 30 rows for row with "country" AND ("region" OR "company")
│  ├─ Build column map: country → col_idx, company → col_idx, product → col_idx, etc.
│  ├─ Extract year columns: numeric-only 4-digit column headers (2020, 2021, etc.)
│  └─ Detect capacity_type from sheet name: "Gross", "Merchant", "Net"
│
├─ Stage 3: PRE-PASS (Entity Collection)
│  ├─ Scan all rows for Region, Country, Company nodes
│  ├─ Normalize geographies via referential
│  ├─ Create RegionCreate, CountryCreate, CompanyCreate (without metrics)
│  └─ Build lookup index: {company_name → EntityCreate}
│
├─ Stage 4: MAIN-PASS (Metrics Generation)
│  ├─ For each row:
│  │  ├─ Normalize Country → Region (via referential)
│  │  ├─ Extract Company + Plant/Site names
│  │  ├─ Create Site entity (Company → Site parent hierarchy)
│  │  ├─ Detect Product (column OR document default)
│  │  ├─ Detect Capacity Type (sheet OR column: gross/merchant/net)
│  │  ├─ Detect Variant: Type, Physical Form (granular/prilled/liquid), Grade
│  │  ├─ Detect Feedstock (Sulphur only: oil/gas/sand)
│  │  ├─ Detect Unit (column OR default: kiloton)
│  │  ├─ For each Year column:
│  │  │  ├─ Extract numeric value
│  │  │  ├─ Determine scenario: year ≥ pub_year → forecast; else → release
│  │  │  ├─ Build metric name: capacity_{feedstock}_{type}_{scenario}
│  │  │  ├─ Enrich scope with: type, physical_form, grade_display, feedstock, unit
│  │  │  └─ Create MetricCreate
│  │  └─ Emit Site entity + all Metrics
│  └─ Prevent row skips: totals, world, aggregates, global
│
├─ Stage 5: Variant Resolution
│  ├─ Metric scope keys → MetricRepository._resolve_or_create_variant()
│  ├─ Scope keys that trigger variant creation:
│  │  ├─ "type" → ref_product_variants.type (gross, merchant, net)
│  │  ├─ "physical_form" → ref_product_variants.physical_form (granular, prilled, liquid)
│  │  ├─ "product_grade_display" → ref_product_variants.grade_display
│  │  ├─ "feedstock_category" → custom sulphur feedstock tracking
│  │  └─ "product_qualifier" → (technical, net, etc.)
│  └─ All variants linked back to base product via MetricRepository
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Products (ammonia, phosphate_rock, etc. — 1-11 products per file)
   ├─ Regions (normalized from country_region_mapping)
   ├─ Countries (mapped to regions)
   ├─ Entities (companies + sites with parent hierarchy)
   └─ Metrics (capacity by site-year with rich variant scope)
```

---

## Data Sources & Product Coverage

| Source | File Pattern | Products | Capacity Types | Sheets |
|--------|---|-------------|---|---|
| **Argus** | Ammonia/Potash/Phosphate Rock/Urea Analytics | ammonia, potash, phosphate_rock, urea | Gross, Merchant (ammonia); standard (others) | "Capacity by Plant", "Gross Capacity by Plant", "Merchant Capacity by Plant" |
| **S&P (PIEC)** | Ammonia/Phosphate Outlook; Processed Phosphates Analytics | ammonia, wpa, dap, map, tsp, npk | Gross, Merchant | "Capacity by plant" |
| **CRU** | Ammonia/Sulphur/Phosphate Rock/Phosphate Fert Market Outlook | ammonia, sulphur, phosphate_rock, npk | Standard/project-specific | "Capacity Forecasts", "Projects", "Capacity List" |

---

## Processing Flow

### Two-Pass Architecture

**Pre-Pass:**
```
For each data row:
  1. Extract country, region, company
  2. Normalize country name via COUNTRY_ALIASES
  3. Lookup country → region via COUNTRY_REGION_MAP
  4. Emit Region, Country, Company entities (no metrics yet)
  5. Build company index for Site parent lookups
```

**Main-Pass:**
```
For each data row:
  1. Skip total/aggregate rows (keyword check)
  2. Normalize geography (same as pre-pass)
  3. Extract plant/site name
  4. Detect product: column → document → default
  5. Detect capacity type: column → sheet name
  6. Detect variant: type, physical_form, grade, feedstock
  7. Detect unit: column → default (kiloton)
  8. Emit Company (if not already present)
  9. Emit Site (Company → Site parent chain)
  10. For each year column:
      a. Extract numeric value (safe_float)
      b. Determine scenario (forecast vs. release)
      c. Build metric_name
      d. Create MetricCreate with rich scope
      e. MetricRepository will handle variant creation later
```

### Dynamic Column Detection

```python
Header row scan identifies columns by keyword matching:

Geographic:
  - "country" → col_map["country"]
  - "region" (no "sub") → col_map["region"]
  - "sub" + "region" → col_map["sub_region"]

Entity:
  - "company", "owner", "operator", "operating company" → col_map["company"]
  - "plant", "plant name", "refinery", "site" → col_map["plant"]
  - "location", "city", "field location" → col_map["location"]

Metadata:
  - "status" → col_map["status"]
  - "pgs" (PGS scoring) → col_map["pgs_scoring"]
  - "technology" → col_map["technology"]

Optional variants:
  - "product" → col_map["product"]
  - "type" → col_map["type"]  (e.g., "Gross", "Merchant")
  - "grade" → col_map["grade"]
  - "uom" or "unit of measure" → col_map["uom"]
  - "unit" → col_map["unit_col"]

Year columns:
  - Numeric-only 4-digit headers (1950 ≤ year ≤ 2100)
  - Stored in col_map["_year_cols"] as list of column indices
```

### Publication Date Extraction

Filename patterns supported:
- **Quarter format**: "1Q 2025", "4q_2023", "2025_3Q" → date(year, quarter_month, 1)
- **Month format**: "March 2025", "may-2025" → date(year, month, 1)
- **Year only**: "2025" → date(2025, 1, 1)
- **Fallback**: Current date

---

## Data Structures

### SchemaCollection (Output)

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate
    metrics: List[MetricCreate]
    entities: List[EntityCreate]        # Companies + Sites
    products: List[ProductCreate]
    regions: List[RegionCreate]
    countries: List[CountryCreate]
```

### DocumentCreate

```python
DocumentCreate(
    document_name="argus_ammonia_analytics_1q_2025",
    document_path="/path/to/file.xlsx",
    source_code="argus",                # Inferred from filename
    publication_date=date(2025, 3, 1),  # Extracted: 1Q2025
    ingestion_date=date.today(),
    is_archived=False,
)
```

### ProductCreate

```python
ProductCreate(
    product_name="ammonia",
    product_category_name="primary_chemical",
    is_active=True,
)
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
    entity_name="shell_port_arthur_refinery",  # company_plant_location_unit (optional parts)
    entity_type="site",
    parent_entity="shell",                      # FK to company
    country_name="united_states",
    region_name="north_america",
    metadata_={
        "city": "Port Arthur, Texas",
        "status": "Operating",
        "technology": "Steam Reforming",
    },
    is_active=True,
)
```

### MetricCreate

```python
MetricCreate(
    metric_name="capacity_gross_forecast",  # or "capacity_oil_gross_forecast" (sulphur)
    metric_type="capacity",
    value="500",                            # kilotons
    unit_of_measure="kiloton",
    year=2025,
    start_date_effect=date(2025, 1, 1),
    end_date_effect=date(2025, 12, 31),
    date_publication=date(2025, 3, 1),
    country_name="united_states",
    region_name="north_america",
    entity_name="shell_port_arthur_refinery",
    product_name="ammonia",
    sheet_name="Gross Capacity by Plant",
    document_name="argus_ammonia_analytics_1q_2025",
    scope={
        "region": "north_america",
        "sub_region": "gulf_coast",
        "country": "united_states",
        "company": "shell",
        "operating_name": "port_arthur",
        "city": "Port Arthur, Texas",
        "unit_of_measure": "kiloton",
        "unit": "1",
        "status": "Operating",
        "pgs_scoring": None,
        "technology": "Steam Reforming",
        "type": "gross",
        "physical_form": None,
        "product_grade_display": None,
        "feedstock_category": None,
    }
)
```

---

## Configuration (sheets_extractors.yaml)

```yaml
- name: plant_capacity
  description: >
    Unified caster for plant-level capacity sheets (Company→Site + year cols).
    Argus sources only. Product/type/grade auto-detected.
    (CRU & S&P entries moved to capacity_database above)
  extractor_code: plant_capacity_caster.py

  matches:
    exact:
      # ---------- Argus Ammonia Analytics ----------
      - value: "Gross Capacity by Plant"
        data_provider: "argus"
      - value: "Merchant Capacity by Plant"
        data_provider: "argus"

      # ---------- Argus Phosphate Rock / Potash / Urea / NPK ----------
      - value: "Capacity by Plant"
        data_provider: "argus"
```

---

## Referential Integration

### Required Mappings

```yaml
# referential.yaml
country_aliases:
  usa: united_states
  us: united_states
  uae: united_arab_emirates
  sa: saudi_arabia

country_region_mapping:
  united_states: north_america
  canada: north_america
  saudi_arabia: middle_east
  netherlands: western_europe
  # ... [11+ other capacity-relevant countries]

region_aliases:
  middle_east: mea
  north_america: na

unit_aliases:
  "kt": "kiloton"
  "kton": "kiloton"
  "thousands tonnes": "kiloton"
```

### Product Detection Priority

1. **Column detection**: If "Product" column exists, use cell value
2. **Document name**: Parse filename for product pattern (ammonia, potash, etc.)
3. **Fallback**: Based on source_code and file pattern

---

## Worked Examples

### Example 1: Argus Ammonia (US Gulf Coast)

**File:** `Argus_Ammonia_Analytics_1Q_2025.xlsx`  
**Sheet:** "Gross Capacity by Plant"

**Input Data (excerpt):**
```
| Region | Country | Operating Company | Plant Name | Location | City | Status | 2024 | 2025F |
|--------|---------|-------------------|-----------|----------|------|--------|------|-------|
| NA     | USA     | Shell             | Port Arthur| Refinery | TX   | Operat | 500  | 500   |
| NA     | USA     | Valero            | Beaumont  | Refinery | TX   | Operat | 450  | 450   |
| NA     | USA     | CF Industries     | Donaldson | Plant    | LA   | Operat | 800  | 800   |
```

**Processing:**

Row 1 (Port Arthur):
- Country: "USA" → "united_states"
- Region lookup: united_states → "north_america"
- Company: "Shell" → "shell"
- Plant: "Port Arthur" → "port_arthur"
- Site key: "shell_port_arthur_refinery_tx"
- Product: default → "ammonia" (from doc name)
- Capacity type: "Gross" (from sheet name)
- Unit: "kiloton" (default)

**Output (2 metrics per plant):**
- Metric 2024: capacity_gross_release (2024 < 2025 publication year)
- Metric 2025: capacity_gross_forecast (2025 ≥ 2025 publication year)

**Entities Created:**
- Region: north_america
- Country: united_states
- Companies: shell, valero, cf_industries
- Sites: shell_port_arthur_refinery_tx, valero_beaumont_refinery_tx, cf_industries_donaldson_plant_la

---

### Example 2: S&P Processed Phosphates (Global WPA)

**File:** `S_P_Processed_Phosphates_Analytics_May_2025.xlsx`  
**Sheet:** "WPA Capacity by Plant"

**Input Data (excerpt):**
```
| Region | Sub-Region | Country | Company | Plant Name | Grade | Status | Unit | Tech | 2024 | 2025F |
|--------|-----------|---------|---------|-----------|-------|--------|------|------|------|-------|
| Europe | W. Europe | Netherlands | Prayon | Engis  | 46% P2O5 | Operat | 1 | Acid | 120  | 120   |
| Levant | MENA | Saudi Arabia | SCPP | Safaniyah | 46% P2O5 | Operat | 1 | Acid | 500  | 520   |
| Africa | N. Africa | Morocco | OCP    | Arradeya L1 | 30% P2O5 | Operat | 1 | Acid | 1200 | 1200  |
```

**Processing:**

Row 1 (Prayon Engis):
- Country: "Netherlands" → "netherlands"
- Region: netherlands → "western_europe"
- Company: "Prayon" → "prayon"
- Plant: "Engis" → "engis"
- Location: "Engis" (implicit from plant name)
- Site key: "prayon_engis"
- Product: "wpa" (from sheet prefix OR column)
- Capacity type: default (not in sheet name)
- Grade: "46% P2O5" → scope["product_grade_display"] = "46_p2o5"
- Unit: "1" (from Unit column) → interpreted as kiloton
- Technology: "Acid" → scope["technology"]

**Output:**
- Metric 2024: capacity_release, value=120, unit=kiloton_p2o5
- Metric 2025: capacity_forecast, value=120, unit=kiloton_p2o5

**Variant Creation:**
- MetricRepository reads scope["product_grade_display"] → creates or links to `wpa_46_p2o5` variant

---

### Example 3: CRU Sulphur (Multi-Feedstock)

**File:** `Sulphur_Market_Outlook_2025_1Q.xlsx`  
**Sheet:** "S-Capacity by plant Oil"

**Input Data (excerpt):**
```
| Region | Country | Operating Company | Plant Name | Location | Feedstock | Status | 2024 | 2025F | 2026F |
|--------|---------|-------------------|-----------|----------|-----------|--------|------|-------|-------|
| MENA   | Saudi   | Saudi Aramco      | Yanbu     | Yanbu R   | Oil/Gas   | Operat | 500  | 550   | 550   |
| MENA   | Kuwait  | KNPC              | Mina Al   | Coastal   | Oil/Gas   | Operat | 350  | 350   | 350   |
| Africa | Morocco | OCP               | Jorf      | Coastal   | Mined     | Plan   | 0    | 300   | 400   |
```

**Processing:**

Row 1 (Yanbu):
- Country: "Saudi" → "saudi_arabia"
- Region: saudi_arabia → "middle_east"
- Company: "saudi_aramco"
- Plant: "yanbu"
- Site key: "saudi_aramco_yanbu"
- Product: "sulphur" (default from doc name)
- Feedstock detection:
  - From sheet name "S-Capacity by plant Oil" → feedstock="oil"
  - OR from Feedstock column → scope["feedstock_category"]="oil" (overrides sheet)
- Capacity type: default (not sheet-derived for sulphur)
- Unit: "kiloton" (default for sulphur)

**Metric Naming:**
- capacity_oil_release (2024 < 2025 pub)
- capacity_oil_forecast (2025 ≥ 2025 pub)
- capacity_oil_forecast (2026 ≥ 2025 pub)

**Variant Creation:**
- MetricRepository reads scope["feedstock_category"]="oil"
- Links to `sulphur_oil` variant (or creates if not exists)

---

## Column Mapping Reference

| Semantic Meaning | Column Keywords (fuzzy match) | col_map Key |
|---|---|---|
| **Geographic** | "country" | country |
| | "region" (not "sub") | region |
| | "sub" + "region" | sub_region |
| **Entity** | "company", "owner", "operator" | company |
| | "plant", "plant name", "refinery", "site" | plant |
| | "location", "city" | location |
| **Metadata** | "status" | status |
| | "pgs", "pgs scoring" | pgs_scoring |
| | "technology" | technology |
| **Variant** | "product" | product |
| | "type" | type |
| | "grade" | grade |
| | "uom", "unit of measure" | uom |
| | "unit" (only if "uom" absent) | unit_col |
| **Year** | 4-digit number (1950-2100) | _year_cols (list) |

---

## Design Rationale

### 1. **Two-Pass Processing**
- **Why:** Ensures all parent entities (companies) exist before creating child entities (sites)
- **Benefit:** Clean entity hierarchy without "Parent not found" errors
- **Implementation:** Pre-pass collects geo + companies; main-pass creates sites + metrics

### 2. **Dynamic Column Detection**
- **Why:** Different vendors use different column layouts
- **Benefit:** Single extractor handles 11+ products × 3 vendors
- **Implementation:** Keyword-based fuzzy matching on row 0-30

### 3. **Scenario Detection (Forecast vs. Release)**
- **Why:** Separate forward projections from historical data
- **Benefit:** Analytics can query "capacity forecasts for 2026" vs. "actual 2024 capacity"
- **Implementation:** year >= pub_date.year → "forecast"; else → "release"

### 4. **Variant Scope Storage**
- **Why:** Variants (gross/merchant, granular/prilled, oil/gas) are product-specific attributes
- **Benefit:** MetricRepository handles variant creation; Caster just emits scope dict
- **Implementation:** Store type, physical_form, grade_display, feedstock in scope; MetricRepository reads later

### 5. **Skip Row Detection**
- **Why:** Avoid double-counting total rows
- **Implementation:** Keyword check: "total", "grand total", "world", "average", "global"

### 6. **Multi-Source Harmony**
- **Why:** Argus, S&P, CRU often have incompatible column orders
- **Benefit:** Unified processing pipeline reduces maintenance
- **Implementation:** Generic column mapping engine works for all vendors

---

## Troubleshooting

### Issue 1: Header Row Not Found

**Symptom:** No metrics generated; log shows "No header row found"

**Root Cause:** Header row doesn't contain both "country" AND ("region" OR "company")

**Solution:**
1. Check first 30 rows of sheet
2. Manually verify header row exists and contains required keywords
3. If keywords different, add aliases to referential (e.g., "territory" → region equivalent)

**Example fix in referential:**
```yaml
region_aliases:
  territory: region
  sub_territory: sub_region
```

---

### Issue 2: All Rows Skipped

**Symptom:** Entities created but no metrics; log shows rows being skipped

**Root Cause:** 
- Missing company column → all rows fail "not company or not plant" check
- Rows matching _SKIP_KEYWORDS (total, world, etc.)

**Solution:**
1. Verify "company" or "operating company" column exists
2. For aggregate rows: add custom skip keywords or use "status" = "Aggregate"
3. Check row 1: Ensure it's not a total/summary row

---

### Issue 3: Unknown Region (Fallback)

**Symptom:** region_name = "unknown_region" in metrics

**Root Cause:** Country not found in country_region_mapping

**Solution:** Add country to referential.yaml
```yaml
country_region_mapping:
  new_country: target_region
```

---

### Issue 4: Product Not Recognized

**Symptom:** product_name = "unknown_product" or empty

**Root Cause:**
- Document name doesn't match _DOC_PRODUCT_PATTERNS
- Product column has unexpected value

**Solution:**
1. Add product aliases to referential.yaml
2. Add document pattern to _DOC_PRODUCT_PATTERNS (in caster code)
```yaml
product_aliases:
  "phos acid": "phosphoric_acid"
  "wpa": "wpa"
```

---

### Issue 5: Unit Misdetected

**Symptom:** unit_of_measure = "1" instead of "kiloton"

**Root Cause:**
- UOM column interpreted as a "Unit" identifier (refinery unit 1, 2, etc.) not unit of measure
- Confusion between "Unit" (identifier) and "UOM" (measurement)

**Solution:**
1. Use distinct column names: "Unit Number" for identifier, "UOM" for measurement
2. Update _build_column_map to prefer "uom" over "unit"
3. Or manually override: set default_unit when calling process_data()

---

### Issue 6: Duplicate Site Names

**Symptom:** Same site appears with multiple ID keys (company_plant vs. company_plant_location)

**Root Cause:** Site key construction includes optional parts: company_plant_location_unit

**Solution:**
1. Ensure Location and Unit columns are consistent (same site shouldn't have multiple unit identifiers)
2. Clean Location/Unit columns: remove duplicates, standardize formatting

---

## Implementation Checklist

When using plant_capacity_caster.py:

- [ ] Verify header row contains "country" + "region"/"company"
- [ ] Confirm year columns are 4-digit numeric only
- [ ] Check country names match referential.country_region_mapping entries
- [ ] Add missing countries to referential if "unknown_region" appears
- [ ] Ensure no aggregate/total rows mixed with detail rows (or filter them)
- [ ] Confirm product detection: column exists OR document name contains product keyword
- [ ] Validate unit_of_measure detection (kiloton vs. refinery unit identifier)
- [ ] Test with 5-10 rows manually to verify metric generation
- [ ] Check scope contains expected metadata (city, status, technology, etc.)
- [ ] Verify variant creation via MetricRepository (type, physical_form, grade, feedstock)

---

## Variant Detection Summary

| Scope Key | Source | MetricRepository Impact |
|---|---|---|
| `type` | Column "Type" OR Sheet name (Gross/Merchant) | Creates `{product}_{type}` variant |
| `physical_form` | Column "Grade" parsed for form keywords | Creates `{product}_{form}` variant |
| `product_grade_display` | Column "Grade" full text | Creates `{product}_{grade}` variant |
| `feedstock_category` | Sheet name (Oil/Gas/Sand) or Column | Creates `{product}_{feedstock}` variant |
| `product_qualifier` | Product alias expansion | Appends qualifier to product_name |

---

## Related Documentation

- [README_PHOSPHATE_CAPACITY_DATABASE.md](README_PHOSPHATE_CAPACITY_DATABASE.md) — Hierarchical capacity DB (company → plant)
- [README_SULPHUR_CAPACITY_DATABASE.md](README_SULPHUR_CAPACITY_DATABASE.md) — Sulphur-specific capacity template
- [README_CRU_FLAT_DATABASE_CASTER.md](README_CRU_FLAT_DATABASE_CASTER.md) — Regional/country aggregates (different layout)
- [README_REGIONAL_TOTALS_CASTER.md](README_REGIONAL_TOTALS_CASTER.md) — Simple totals layout (no plant detail)
- **sheets_extractors.yaml** — Master configuration (plant_capacity entries)
- **referential.yaml** — Geographic + product normalization

---

## Key Code Sections (Implementation Notes)

### Header Detection (`_find_header_row`)
```python
Scans rows 0-30 for row containing BOTH:
  - "country" keyword AND
  - "region" OR "company" keyword
Returns first matching row index, or None
```

### Column Mapping (`_build_column_map`)
```python
Builds dict: semantic_name → column_index
Priority: later keywords override earlier ones
Year detection: 4-digit numeric cells → col_map["_year_cols"]
```

### Row Filtering (`_should_skip`)
```python
Skip if combined row text contains any of:
  "total", "grand total", "subtotal", "world", "global", "aggregate"
```

### Entity Hierarchy (`_ensure_entity`)
```python
Pre-pass: Emit Company (entity_type="company")
Main-pass: Emit Site (entity_type="site", parent_entity=company)
Dedup: Each entity only emitted once via _emitted_entities set
```

### Metric Name Building (`_build_metric_name`)
```python
metric_name = "capacity" + 
              (_feedstock if feedstock) + 
              (_type if capacity_type) + 
              (forecast|release)

Examples:
  - "capacity_forecast" (simple: ammonia, no type)
  - "capacity_gross_forecast" (ammonia with gross/merchant)
  - "capacity_oil_forecast" (sulphur with feedstock)
```

---

## File Locations

- **Implementation:** [src/excel_ingestion/extractors/implementation/plant_capacity_caster.py](src/excel_ingestion/extractors/implementation/plant_capacity_caster.py)
- **Configuration:** [src/excel_ingestion/extractors/sheets_extractors.yaml](src/excel_ingestion/extractors/sheets_extractors.yaml) (search for "plant_capacity")
- **Schemas:** [src/excel_ingestion/persistence/schemas.py](src/excel_ingestion/persistence/schemas.py)
- **Referential:** [src/excel_ingestion/config/referential.yaml](src/excel_ingestion/config/referential.yaml)

---

**Version:** 2.0 (Production)  
**Status:** ✅ Active  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team  
**Next Step:** Reference for documenting other capacity extractors (regional_totals, flat_database)
