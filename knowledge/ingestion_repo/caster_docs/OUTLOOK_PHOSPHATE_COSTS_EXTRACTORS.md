# README: Phosphate Outlook Cost/Capacity Data Caster

**File:** `phosphateoutlook_2024m10_datafile_costsprices__costdata.py` (875 lines)  
**Pattern:** Template-driven extraction (Caster pattern)  
**Data Source:** S&P Phosphate Outlook - Cost Data & Representative Capacity sheets  
**Sheet Type:** Plant-level cost/capacity time-series with product grades

---

## Overview

The **Phosphate Outlook Cost Data Caster** extracts plant-level production cost and capacity data from S&P Phosphate Outlook Excel files. It normalizes unstructured cost/capacity sheets with product specifications into standardized metric schemas.

### Key Features

- **Plant-level entities** with geographic hierarchies (Country → Region)
- **Product grades** extracted from variable names (DAP 18:46, MAP 15:15:15, etc.)
- **Cost metrics**: Cash cost, cost at capacity, total cost (US$/tonne)
- **Capacity metrics**: Representative capacity in kilotonnes
- **Quarter-based time series**: 2010Q1, 2014Q3, etc.
- **Scenario tracking**: Realized (historical) vs. Forecast (forward-looking)
- **Product groups**: DAP/MAP auto-detection from sheet titles

---

## Architecture

```
Phosphate Outlook Cost Data Extractor
│
├─ Input: Excel sheet with Plant / Geography / Region / Variable / Quarter columns
│
├─ Stage 1: Sheet Context Detection
│  ├─ Find title row: "DAP/MAP cost data (US$/t) and representative capacity (kt product/year)"
│  ├─ Infer units: US$/t → usd_per_ton, kt/year → kiloton
│  └─ Infer product group: DAP/MAP, DAP only, or MAP only
│
├─ Stage 2: Header Detection
│  ├─ Scan rows 0-80 for "Plant ID", "Geography", "Region", "Variable"
│  └─ Detect quarter columns (YYYYQ1-Q4 pattern)
│
├─ Stage 3: Product Staging (Group Members First)
│  ├─ If group is DAP_MAP: create DAP product, then MAP product, then DAP_MAP group
│  └─ Ensures parent group finds members in database
│
├─ Stage 4: Row Processing
│  ├─ Parse plant ID (split on ' - ' for Company/Plant)
│  ├─ Normalize geography (Country | Region)
│  ├─ Map country → region via referential
│  ├─ Extract product/grade from variable (e.g., "Cost as DAP 18:46")
│  ├─ Iteration per quarter column:
│  │  ├─ Parse numeric value
│  │  ├─ Determine scenario (realized vs. forecast)
│  │  └─ Create metric with product grade in scope
│  │
│  └─ Emit Entity (plant), Region, Country, Product, Metric
│
└─ Output: SchemaCollection
   ├─ Document (file metadata + date range)
   ├─ Products (DAP, MAP, DAP_MAP group)
   ├─ Regions (extracted + normalized)
   ├─ Countries (extracted + normalized)
   ├─ Entities (plants)
   └─ Metrics (cost/capacity by plant-quarter-product)
```

---

## Data Processing Flow

### 1. **Sheet Context Detection**

```python
Title line: "DAP/MAP cost data (US$/t) and representative capacity (kt product/year)"
                        ↓
infer_units_from_title() → { "cost": "usd_per_ton", "capacity": "kiloton" }
infer_product_group_from_title() → "dap_map"
```

**Priority:** Cost rules must come **BEFORE** capacity rules in metric detection

---

### 2. **Header Detection**

Scans first 80 rows for marker row containing:
```
Plant ID | Geography | Region | Variable | 2010Q1 | 2011Q1 | ... | 2025Q4
```

Example header row positioning:
```
Row 0-5:    Title metadata
Row 6-8:    Empty/formatting
Row 9:      "Plant ID | Geography | Region | Variable | 2010Q1 | 2011Q1 ..."
Row 10+:    Data rows
```

---

### 3. **Product Group Staging (Members-First Pattern)**

**Why:** ProductRepository requires member products exist before group.

**Process:**
```python
Group: "dap_map"
  ↓ infer_group_members() → ["dap", "map"]
  
1. Create ProductCreate(product_name="dap", is_group=False)
2. Create ProductCreate(product_name="map", is_group=False)
3. Create ProductCreate(product_name="dap_map", is_group=True)
   └─ Category inherited from members if group is "unclassified"
```

---

### 4. **Row Processing**

For each data row:

```python
Plant ID:    "Prayon - Engis"
  ↓ split on " - "
  ├─ Company: "Prayon"
  └─ Plant: "Engis"

Geography:   "Belgium"
  ↓ normalize_country()
  → "belgium"

Region:      "Western Europe"
  ↓ normalize_region()
  → "western_europe"

Variable:    "Cash Cost as DAP 18:46 (US$/tonne)"
  ↓ parse_variable_to_metric_product()
  ├─ Product: "dap"
  ├─ Grade: ProductGrade(display="18:46", phosphate=18.0, ...)
  ├─ Metric: "cash_cost"
  ├─ Family: "cost"
  └─ Unit: "usd_per_ton"
```

---

### 5. **Metric Generation per Quarter**

For each quarter column (2010Q1, 2011Q1, ...):

```python
Column:      "2015Q3"
  ↓
Quarter date: 2015-07-01 (start of Q3)
End date:     2015-09-30 (end of Q3)

Value:       1250.5

Doc publish: 2024-10-01
Quarter:     2015 < 2024 → scenario = "realized"

Metric name: "cash_cost_realized" (scenario suffix added if in version 2+)

Scope:
{
  "region": "western_europe",
  "country": "belgium",
  "product_group": "dap_map",
  "company": "prayon",
  "plant": "engis",
  "scenario": "realized",
  "product_grade_display": "18:46",
  "variable_raw": "Cash Cost as DAP 18:46 (US$/tonne)"
}
```

---

## Data Structures

### SchemaCollection (Output)

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate             # File metadata + date range
    metrics: List[MetricCreate]          # Cost & capacity values by quarter
    entities: List[EntityCreate]         # Plants (geography in metadata_)
    products: List[ProductCreate]        # DAP, MAP, DAP_MAP group
    regions: List[RegionCreate]          # Extracted regions
    countries: List[CountryCreate]       # Extracted countries
```

### DocumentCreate

```python
DocumentCreate(
    document_name="phosphateoutlook_2024m10_datafile_costsprices__costdata",
    document_path="/path/to/file.xlsx",
    source_code="sp",                           # Data provider
    publication_date=date(2024, 10, 1),        # Extracted from YYYYMnn
    ingestion_date=date(2024, 10, 15),         # Today's date
    effective_start_date=date(2010, 1, 1),     # Min quarter from data
    effective_end_date=date(2025, 12, 31),     # Max quarter from data
    is_archived=False,
)
```

### EntityCreate (Plant)

```python
EntityCreate(
    entity_name="engis",
    entity_type="plant",
    description=None,
    parent_entity=None,
    metadata_={
        "entity_level": "plant",
        "country_name": "belgium",
        "region_name": "western_europe",
        "original_plant_raw": "Prayon - Engis",
    },
    is_active=True,
)
```

### ProductCreate

```python
# Member product
ProductCreate(
    product_name="dap",
    product_category_name="np_fertilizer",
    product_category_id=None,
    description="auto-created member of group dap_map",
    is_active=True,
    is_group=False,
)

# Group product
ProductCreate(
    product_name="dap_map",
    product_category_name="np_fertilizer",
    product_category_id=None,
    description="auto-created product group from sheet title context",
    is_active=True,
    is_group=True,
)
```

### MetricCreate

```python
MetricCreate(
    entity_name="engis",
    country_name="belgium",
    region_name="western_europe",
    product_name="dap",                             # Or group name
    metric_name="cash_cost_realized",
    metric_type="cost",
    value="1250.5",
    unit_of_measure="usd_per_ton",
    year=2015,
    start_date_effect=date(2015, 7, 1),            # Q3 start
    end_date_effect=date(2015, 9, 30),             # Q3 end
    date_publication=date(2024, 10, 1),
    document_name="phosphateoutlook_2024m10...",
    sheet_name="CostData",
    region_name="western_europe",
    country_name="belgium",
    scope={
        "region": "western_europe",
        "country": "belgium",
        "product_group": "dap_map",
        "company": "prayon",
        "plant": "engis",
        "scenario": "realized",
        "product_grade_display": "18:46",
        "variable_raw": "Cash Cost as DAP 18:46 (US$/tonne)",
    }
)
```

### ProductGrade

```python
ProductGrade(
    display_value="18:46",          # How it displays in Excel
    nitrogen=0.0,
    phosphate=18.0,
    potash=46.0,
    sulfur=0.0,
)
```

---

## Configuration (sheets_extractors.yaml)

```yaml
- name: phosphateoutlook_costdata
  description: >
    Phosphate outlook – CostData sheets with plant-level cost & capacity data.
    Product group (DAP/MAP) auto-detected from title.
    Quarter columns (YYYYQ1-Q4) for time-series.
  
  extractor_code: phosphateoutlook_2024m10_datafile_costsprices__costdata.py
  
  matches:
    exact:
      - value: "CostData"
        data_provider: "sp"
        params:
          header_rows: 6  # Optional hint for UI
```

---

## Referential Integration

### Product Categories
```yaml
# referential.yaml
products_by_category:
  np_fertilizer:
    - dap
    - map
    - dap_map  # group
  physical_form:
    - granular
    - prills
    - solution
```

### Country Aliases
```yaml
country_aliases:
  republic_of_ireland: ireland
  united_kingdom: uk
  united_states: usa
```

### Country → Region Mapping
```yaml
country_region_mapping:
  belgium: western_europe
  france: western_europe
  united_states: north_america
  india: south_asia
```

---

## Grade Detection Priority

Product grades are extracted from variable names via regex patterns:

```
Priority order (highest → lowest):
1. BPL pattern:        "% BPL", "50% BPL", "46-48 BPL"
2. P2O5 pattern:       "46% P2O5", "52% P205"
3. Generic percent:    "15%", "46%"
4. 4-value (N:P:K:S):  "15:15:15:2"
5. 3-value (N:P:K|S):  "18:46:0", "15:15:15"
6. 2-value (N:P):      "18:46"

Example Extractions:
  "Cost as DAP 18:46"           → ProductGrade(phosphate=18, potash=46)
  "Capacity as MAP 15-15-15"    → ProductGrade(nitrogen=15, phosphate=15, potash=15)
  "Cash Cost 46% BPL"           → ProductGrade(display_value="46% BPL")
```

---

## Metric Type Detection

From variable name text:

```python
# Cost metrics (checked FIRST)
"cost at capacity" → "cost_at_capacity"
"cash cost"        → "cash_cost"
"total cost"       → "total_cost"
else               → "cost"

# Capacity metric
"capacity"         → "capacity"

# Default
else               → "unknown" (metric_family="other")
```

**Important:** Cost patterns checked **before** capacity patterns to avoid misclassification

---

## Scenario Detection

Compares quarter date with document publication date:

```python
Publication date: 2024-10-01

2015Q3 (2015-07-01) < 2024-10-01  → scenario = "realized"
2025Q3 (2025-07-01) > 2024-10-01  → scenario = "forecast"

Metric name:
  If forecast and metric_name doesn't end with "_forecast":
    Add "_forecast" suffix
    
Example:
  "cash_cost" + forecast        → "cash_cost_forecast"
  "capacity" + realized         → "capacity"
```

---

## Worked Examples

### Example 1: DAP Cost at Capacity (Prayon - Engis)

**Sheet Fragment:**
```
| Plant ID          | Geography | Region          | Variable                           | 2023Q4 | 2024Q1 | 2025Q1(F) |
|-------------------|-----------|-----------------|--------------------------------------|--------|--------|-----------|
| Prayon - Engis    | Belgium   | Western Europe  | Cost at Capacity as DAP 18:46      | 285    | 310    | 325       |
| Prayon - Engis    | Belgium   | Western Europe  | Capacity Representative DAP        | 450    | 450    | 450       |
```

**Processing:**

Plant: Prayon - Engis
  ├─ Company: Prayon
  └─ Plant: Engis

Variable 1: "Cost at Capacity as DAP 18:46"
  ├─ Product: DAP
  ├─ Grade: 18:46 (Phosphate=18, Potash=46)
  ├─ Metric: cost_at_capacity
  ├─ Unit: usd_per_ton
  └─ Metrics:
    - 2023Q4 (realized): 285 USD/t
    - 2024Q1 (realized): 310 USD/t
    - 2025Q1 (forecast): 325 USD/t

Variable 2: "Capacity Representative DAP"
  ├─ Product: DAP
  ├─ Metric: capacity
  ├─ Unit: kiloton
  └─ Metrics:
    - 2023Q4 (realized): 450 kt/year
    - All quarters: 450 kt/year (constant)

**Output Metrics:**
```json
[
  {
    "entity_name": "engis",
    "product_name": "dap",
    "metric_name": "cost_at_capacity_realized",
    "metric_type": "cost",
    "value": "285",
    "unit_of_measure": "usd_per_ton",
    "year": 2023,
    "start_date_effect": "2023-10-01",
    "end_date_effect": "2023-12-31",
    "scope": {
      "region": "western_europe",
      "country": "belgium",
      "product_group": "dap_map",
      "company": "prayon",
      "plant": "engis",
      "scenario": "realized",
      "product_grade_display": "18:46"
    }
  }
]
```

---

### Example 2: MAP Cash Cost (Multi-Plant)

**Sheet Fragment:**
```
| Plant ID              | Geography  | Region       | Variable                     | 2023Q2 | 2024Q2 | 2025Q2(F) |
|----------------------|------------|--------------|------------------------------|--------|--------|-----------|
| Mosaic - Gafsa       | Tunisia    | North Africa | Cash Cost as MAP 15:15:15   | 198    | 215    | 220       |
| CF Industries - Gulf | USA        | North America| Cash Cost as MAP 10:26:26   | 220    | 245    | 260       |
| Yonker - Chennai     | India      | South Asia   | Cash Cost as MAP 12:52:00   | 185    | 195    | 205       |
```

**Output:**

3 plants × 3 quarters × 1 metric = 9 metrics
  - Mosaic (Tunisia): 3 metrics
  - CF Industries (USA): 3 metrics
  - Yonker (India): 3 metrics

```json
[
  {
    "entity_name": "gafsa",
    "country_name": "tunisia",
    "product_name": "map",
    "metric_name": "cash_cost_realized",
    "value": "198",
    "scope": {
      "region": "north_africa",
      "country": "tunisia",
      "product_group": "dap_map",
      "company": "mosaic",
      "plant": "gafsa",
      "scenario": "realized",
      "product_grade_display": "15:15:15"
    }
  },
  {
    "entity_name": "gulf",
    "country_name": "united_states",
    "product_name": "map",
    "metric_name": "cash_cost_realized",
    "value": "220",
    "scope": {
      "region": "north_america",
      "country": "united_states",
      "product_group": "dap_map",
      "company": "cf_industries",
      "plant": "gulf",
      "scenario": "realized",
      "product_grade_display": "10:26:26"
    }
  }
]
```

---

### Example 3: Forecast Scenario (2025 Q2)

**Quarter: 2025Q2 vs. Publication: 2024-10-01**

```python
2025-04-01 > 2024-10-01 → scenario = "forecast"

Metric: "cash_cost" + forecast → "cash_cost_forecast"

Output scope:
{
  "scenario": "forecast",
  "variable_raw": "Cash Cost as MAP 15:15:15"
}
```

---

## Design Rationale

### 1. **Members-First Product Group Registration**
- **Why:** Database requires member products before group
- **Benefit:** Eliminates "Member products not found" errors
- **Implementation:** `_stage_group_products_members_first()` creates members before group

### 2. **Plant Parsing: "Company - Plant" Format**
- **Why:** S&P data encodes both company & plant in single Plant ID column
- **Benefit:** Enables company-level filtering and hierarchies
- **Split Logic:** `plant_raw.split(' - ')` → [Company, Plant Name]

### 3. **Geography in Metadata (vs. Separate Fields)**
- **Why:** Consistency with other casters; Plant ≠ Geography composite
- **Benefit:** Plants can move geographies; metadata preserves original mapping
- **Fields:** `Country_name`, `Region_name` stored in `EntityCreate.metadata_`

### 4. **Product Grade in Scope (vs. Separate Schema)**
- **Why:** Grades vary by product/cost type; not fixed entity property
- **Benefit:** Flexible grade tracking without schema changes
- **Storage:** `scope["product_grade_display"]`, `extra_scope["product_grade_*"]`

### 5. **Scenario-Based Metric Naming**
- **Why:** Distinguish historical from forecasted data downstream
- **Benefit:** Filtering systems can select realized vs. forecast metrics
- **Logic:** If `quarter_date > publication_date`: add "_forecast" suffix

### 6. **Title-Based Unit Inference**
- **Why:** Reduces configuration; units often in title text
- **Benefit:** Auto-detects US$/t, kt/year, etc. without manual mapping
- **Patterns:** `"US$/t"`, `"kt/year"`, `"kt product/year"`

---

## Referential Dependencies

This caster requires referential.yaml to define:

1. **Sources** - Data providers (sp, cru, argus, etc.)
2. **Countries / Countries** - Allowed country names
3. **Country Aliases** - Map variations to canonical (united_states → usa)
4. **Country → Region Mapping** - Geography hierarchy
5. **Regions** - Allowed region names
6. **Region Aliases** - Map variations (eastern_&_asia → eastern_and_asia)
7. **Products by Category** - Product→category mapping
8. **Units** - Standard unit names

---

## Troubleshooting

### Issue 1: Header Row Not Found

**Symptom:** ValueError "Could not find body header row (Plant ID / Geography / Region / Variable)"

**Cause:** Extractor scanned first 80 rows but didn't find all 4 required columns

**Solution:**
1. Check sheet manually: Does it contain Plant ID, Geography, Region, Variable columns?
2. Are they all in the first 80 rows?
3. If headers are misspelled (e.g., "Plant Name" instead of "Plant ID"), the sheet doesn't match pattern
4. Mark sheet as skip in sheets_extractors.yaml

**Debug Code:**
```python
import pandas as pd
data = np.array(...)  # Your sheet data
caster = Caster()
df = caster.raw_data_to_df(data)  # Will raise ValueError if header not found
```

---

### Issue 2: No Quarter Columns Detected

**Symptom:** Metrics created but values are empty or zero

**Cause:** Quarter columns not in YYYYQ1-YYYYQ4 format (e.g., "Q1 2024", "2024-Q1")

**Solution:**
1. Verify Excel column headers: Should be exactly "2010Q1", "2011Q1", etc.
2. Check for formatting: Dates formatted as text "2024-01-01" won't match `^\d{4}Q[1-4]$`
3. If columns are in different format, rename them or mark sheet as skip

**Regex Check:**
```python
import re
col = "2015Q3"
if re.match(r"^\d{4}Q[1-4]$", col.strip().upper()):
    print("✓ Detected as quarter column")
```

---

### Issue 3: Product Group Not Created

**Symptom:** Metrics reference product="dap_map" but group is missing from output

**Cause:** `_stage_group_products_members_first()` didn't run or failed silently

**Solution:**
1. Check logs for warnings during `start_casting_sequence()`
2. Verify product group name inferred from title:
   - Title must contain "DAP" or "MAP" or "dap" or "map"
   - e.g., "DAP/MAP cost data..." → group="dap_map" ✓
   - e.g., "Cost Data for DAP" → group="dap" (members-first still applies)
3. If title is ambiguous, add explicit group parameter in sheets_extractors.yaml kwargs

---

### Issue 4: Company/Plant Split Failing

**Symptom:** Metrics show plant_name empty; company contains full "Company - Plant" string

**Cause:** "Company - Plant" format not present in Plant ID column

**Solution:**
1. Check actual Plant ID format in data:
   - Expected: "Prayon - Engis"
   - Alternative: "Prayon", "Engis", "Prayon/Engis"?
2. If different format, debug:
   ```python
   plant_raw = "Prayon - Engis"
   if isinstance(plant_raw, str) and ' - ' in plant_raw:
       parts = plant_raw.split(' - ')
       company, plant = parts[0], parts[1]
   ```
3. If no separator, both company & plant remain unsplit (plant_name = full raw string)

---

### Issue 5: Geographic Normalization Failing

**Symptom:** Country/Region fields empty or mismatched in output

**Cause:** Referential doesn't contain aliases for country/region names in data

**Solution:**
1. Add to referential.yaml:
   ```yaml
   country_aliases:
     belgie: belgium
     royaume_uni: united_kingdom
   region_aliases:
     europe_occidentale: western_europe
   ```
2. Verify country_region_mapping includes your countries:
   ```yaml
   country_region_mapping:
     belgium: western_europe
   ```
3. Check allowed_regions list in referential includes your regions

---

### Issue 6: Grade Extraction Returns None

**Symptom:** product_grade_display missing from scope; grades not captured

**Cause:** Variable text doesn't match any grade extraction regex

**Solution:**
1. Check variable text format:
   - Expected patterns: "18:46", "15-15-15", "46% BPL", "52% P2O5"
   - Actual: Check in variable column for different format
2. If custom format (e.g., "DAP Grade A"), add to extraction priority:
   ```python
   # In extract_product_grade_from_colname():
   custom_match = re.search(r"Grade\s+([A-Z])", s)
   if custom_match:
       return ProductGrade(display_value=custom_match.group(1), ...)
   ```
3. If expected pattern exists but not matching, debug case sensitivity

---

### Issue 7: Date Publication Not Extracted

**Symptom:** publication_date defaults to effective_end_date or ingest_date (not actual doc date)

**Cause:** Document filename doesn't contain YYYYMnn pattern

**Solution:**
1. Rename file to include month designation:
   - Include: "phosphateoutlook_2024m10_..." → YYYYMnn extracted → 2024-10-01
   - Current: "phosphateoutlook_costsprices_..." → no YYYYMnn → fallback to today
2. Or set publication_date via kwargs:
   ```yaml
   params:
     publication_date: "2024-10-01"
   ```

---

## Best Practices

### 1. **File Naming Convention**
Include month indicator for publication date extraction:
```
✓ phosphateoutlook_2024m10_datafile_...xlsx   → 2024-10-01
✗ phosphateoutlook_october_2024_...xlsx       → Fallback to today
```

### 2. **Sheet Naming**
Use standardized sheet names for easy sheet matches:
```
✓ "CostData"
✓ "Cost Data"
✗ "Costs" or "Data" (ambiguous)
```

### 3. **Column Headers**
Ensure exact matching:
```
✓ "Plant ID", "Geography", "Region", "Variable"
✗ "Plant", "Geo", "Country", "Description" (won't match)
```

### 4. **Quarter Format**
Ensure columns are exactly YYYYQ#:
```
✓ 2010Q1, 2010Q2, 2010Q3, 2010Q4, 2011Q1
✗ Q1 2010, 2010-Q1, 2010/Q1 (won't be detected)
```

### 5. **Plant ID Format**
Use "Company - Plant" format for proper parsing:
```
✓ "Prayon - Engis", "Mosaic - Gafsa"
✗ "Prayon-Engis" (without spaces)
✗ "Engis (Prayon)" (reversed order)
```

### 6. **Referential Maintenance**
Keep referential.yaml updated with:
- New countries/regions
- Company names (for company field extraction)
- Product grades supported
- Unit variations

### 7. **Variable Naming**
Use consistent metric pattern in variable names:
```
✓ "Cost at Capacity as DAP 18:46"  → Parsed as: cost_at_capacity, DAP, 18:46
✓ "Cash Cost as MAP 15:15:15"      → Parsed as: cash_cost, MAP, 15:15:15
✗ "DAP Cost"                       → Grade not extracted
```

---

## Related Documentation

- [README_REGIONAL_TOTALS_CASTER.md](README_REGIONAL_TOTALS_CASTER.md) — Simple region|country|years layout
- [README_CRU_FLAT_DATABASE_CASTER.md](README_CRU_FLAT_DATABASE_CASTER.md) — Complex 4-layout flat database
- [README_TRADE_EXTRACTORS.md](README_TRADE_EXTRACTORS.md) — Trade matrix extractors
- [README_GREEN_BLUE_AMMONIA_PROJECTS.md](README_GREEN_BLUE_AMMONIA_PROJECTS.md) — Project database extraction
- **sheets_extractors.yaml** — Master template-to-extractor configuration
- **referential.yaml** — Centralized geographic and product normalization

---

## Key Files

- **Implementation:** `src/excel_ingestion/extractors/implementation/phosphateoutlook_2024m10_datafile_costsprices__costdata.py`
- **Configuration:** `src/excel_ingestion/extractors/sheets_extractors.yaml`
- **Referential:** `src/excel_ingestion/config/referential.yaml`
- **Schemas:** `src/excel_ingestion/persistence/schemas.py`
- **Utilities:** `src/excel_ingestion/extractors/utils.py`

---

## Implementation Checklist for New Data Files

When processing a new S&P Phosphate Outlook cost data file:

- [ ] Verify filename contains YYYYMnn for publication date
- [ ] Check sheet name is "CostData" (or add match in sheets_extractors.yaml)
- [ ] Confirm header row: Plant ID, Geography, Region, Variable
- [ ] Verify quarter columns in YYYYQ# format (2010Q1, 2011Q1, etc.)
- [ ] Check plant ID format: "Company - Plant" (space around dash)
- [ ] Validate country/region names against referential.yaml
- [ ] Ensure referential includes country→region mappings
- [ ] Verify product group inferred from title (DAP/MAP, DAP, or MAP)
- [ ] Test with small subset before full ingestion
- [ ] Monitor logs for warnings on header detection or product staging

---

**Version:** 1.0  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team
