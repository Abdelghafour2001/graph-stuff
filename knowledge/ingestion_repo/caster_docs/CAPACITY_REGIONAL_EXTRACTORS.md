# README: Regional Totals Caster

**File:** `regional_totals_caster.py` (624 lines)  
**Pattern:** Template-driven extraction (Caster pattern)  
**Supported Data:** Regional aggregate sheets from Argus, S&P, CRU analytics

---

## Overview

The **Regional Totals Caster** is a unified extractor for "Total …" sheets with a fixed **Region | Country | Year** layout. It normalizes geographic totals across six different analytics sources into a standardized schema.

### Supported Sources

| Source | Products | Example Sheets |
|--------|----------|-----------------|
| **Argus Ammonia Analytics** | ammonia | Total Gross Capacity, Total Merchant Production |
| **Argus Phosphate Rock** | phosphate_rock | Total Capacity, Total Production, Total Consumption |
| **Argus Potash Analytics** | potash | Total MOP Capacity, Total MOP Exports |
| **Argus Urea Analytics** | urea | Total Capacity, Total Production |
| **S&P Processed Phosphates** | wpa, dap, map, tsp | PA Total Capacity, DAP Total Production |
| **NPK Analytics (CRU/Argus)** | npk | NPK Total Capacity, NPK Total Imports |

---

## Architecture

```
Regional Totals Extractor Workflow
│
├─ Input: Excel sheet with Region | Country | Year columns
│
├─ Stage 1: Product Detection
│  ├─ Strategy A: Sheet name prefix (PA, DAP, MAP, TSP, NPK) → S&P/CRU style
│  └─ Strategy B: Document/file name regex (Argus style fallback)
│
├─ Stage 2: Header & Unit Detection
│  ├─ Find "Region" & "Country" column indices
│  └─ Extract unit from preamble ("Data in 000 tonnes")
│
├─ Stage 3: Row Processing
│  ├─ Clean geographic names (standardize, normalize aliases)
│  ├─ Apply whitelist/blocklist (locked subregions, forbidden keywords)
│  └─ Emit Region, Country, Metric schemas
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Products (detected product)
   ├─ Regions (deduplicated region list)
   ├─ Countries (deduplicated country list)
   └─ Metrics (capacity/production/consumption by region-country-year)
```

### Key Components

#### 1. **Product Detection (Two-Pass Strategy)**

```python
# Pass 1: Sheet name prefix (fast, deterministic)
"PA Total Capacity"     → (wpa, phosphoric_acid)
"DAP Total Exports"     → (dap, np_fertilizer)
"NPK Total Production"  → (npk, npk_fertilizer)

# Pass 2: Document name regex (fallback for Argus)
"Argus Ammonia Analytics - 1Q 2025.xlsx"  → (ammonia, n_fertilizer)
"Potash Analytics - May 2024.xlsx"        → (potash, k_fertilizer)
```

#### 2. **Layout Detection**

Fixed header pattern search (rows 0-20):
```
├─ Row 8:  "Region | Country | 2022 | 2023 | 2024 | 2025"
├─ Region column: normalized to allowed regions or kept as-is
└─ Country column: deduplicated, blocklist-filtered
```

#### 3. **Geographic Normalization**

Three-level normalization pipeline:
```python
Raw: "Eastern_Europe"
  ↓
Clean: Remove "Total" suffix: "Eastern_Europe"
  ↓
Standardize: Lowercase + underscores: "eastern_europe"
  ↓
Apply aliases: From referential.yaml:
   "eastern_europe" → "eastern_europe" (kept)
   "russian_federation" → "russia" (aliased)
  ↓
Whitelist check: Is in allowed_regions? Yes → Keep
```

**Whitelist/Blocklist Logic:**

```python
LOCKED_SUBREGIONS = {
    "world", "global", "total", "all_countries", ...
}

FORBIDDEN_KEYWORDS = ["total", "global", "world", "all_", ...]

BLOCKED_COUNTRIES = {"western_sahara"}  # Disputed territories
```

**Action:**
- Rows with region/country in locked_subregions → **Skip** (aggregates)
- Rows with forbidden keywords → **Skip**
- Rows with blocked countries → **Skip**
- Otherwise → **Emit** region/country schemas

#### 4. **Metric Generation**

Metric name: `{base_metric}_{suffix}`

```python
Base metric (from sheet name):
  "Total Gross Capacity"        → "total_gross_capacity"
  "Achievable MOP Production"   → "achievable_mop_production"

Suffix (from publication year):
  If year >= pub_year: "forecast"
  If year < pub_year:  "release"

Example:
  Sheet: "Total MOP Capacity"
  Year:  2024 (in file from 2025-03)
  → Metric: "total_mop_capacity_release"
```

#### 5. **Unit Detection**

Scans rows 0-header_idx for unit indicators:
```python
# Cell: "Data in 000 tonnes"      → "000_tonnes"
# Cell: "Data in 000t P2O5"      → "kiloton_p2o5"
# Default (if not found)          → "000_tonnes"
```

---

## Data Processing Flow

### Row Processing Logic

```python
For each row in sheet (after header):
  1. Extract region & country values
  2. Parse geographic names:
     - Remove "Total" suffix
     - Standardize (lowercase, underscores)
     - Apply referential aliases (& → and, etc.)
     - Query: Is region/country in referential?
  
  3. Whitelist checks:
     - Skip if region & country both not in allowed set
     - Skip if forbidden keywords found
     - Skip if explicitly blocked
  
  4. Emit schemas:
     - Region (if allowed or not in locked subregions)
     - Country (if allowed, otherwise region)
  
  5. For each year column:
     - Parse numeric value
     - Skip aggregates (country == region → already counted)
     - Create metric with scope { region, country, unit, type }
```

### Example: Processing a Row

**Input Row:**
```
| Region         | Country        | 2022  | 2023  | 2024  |
| Eastern Europe | Poland         | 450.5 | 465.2 | 478.9 |
```

**Processing:**

```
Region:   "Eastern Europe"
  ├─ Clean:      "Eastern Europe" (no "Total" suffix)
  ├─ Standardize: "eastern_europe"
  ├─ Normalize:   "eastern_europe" (from aliases)
  ├─ Check:       In allowed_regions? YES → OK
  └─ Emit:        RegionCreate(region_name="eastern_europe")

Country:  "Poland"
  ├─ Standardize: "poland"
  ├─ Aliases:     "poland" → "poland" (no alias)
  ├─ Check:       In allowed_regions? NO
  ├─ Check:       In locked_subregions? NO
  ├─ Check:       In blocked list? NO
  └─ Emit:        CountryCreate(country_name="poland", region_name="eastern_europe")

Metrics (for year 2022, 2023, 2024):
  ├─ Value: 450.5 (2022)
  ├─ Type:  "capacity" (from sheet name)
  ├─ Metric name: "total_gross_capacity_release"
  ├─ Scope: { region: "eastern_europe", country: "poland", unit: "000_tonnes" }
  └─ MetricCreate(...)
```

---

## Schema Data Structures

### SchemaCollection (Output)

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate             # File metadata
    metrics: List[MetricCreate]          # Capacity/production/etc values by region-country-year
    entities: List[EntityCreate]         # Empty (regional_totals has no entity-level data)
    products: List[ProductCreate]        # Detected product (ammonia, potash, etc.)
    regions: List[RegionCreate]          # Deduplicated regions
    countries: List[CountryCreate]       # Deduplicated countries
```

### DocumentCreate

```python
DocumentCreate(
    document_name="Argus Ammonia Analytics - 1Q 2025.xlsx",
    document_path="/path/to/file",
    source_code="Argus Ammonia Analytics",  # From _SOURCE_CODE_MAP
    publication_date=date(2025, 3, 15),    # Extracted from filename
    ingestion_date=date(2025, 3, 20),      # Current date
    effective_start_date=None,
    effective_end_date=None,
    is_archived=False,
)
```

### MetricCreate

```python
MetricCreate(
    product_name="ammonia",
    metric_name="total_gross_capacity_release",
    metric_type="capacity",                    # Derived from sheet name
    value="1234500",                           # Numeric value as string
    unit_of_measure="000_tonnes",              # Detected from preamble
    year=2022,
    start_date_effect=date(2022, 1, 1),
    end_date_effect=date(2022, 12, 31),
    date_publication=date(2025, 3, 15),
    document_name="Argus Ammonia Analytics - 1Q 2025.xlsx",
    sheet_name="Total Gross Capacity",
    region_name="eastern_europe",
    country_name="poland",
    scope={
        "region": "eastern_europe",
        "country": "poland",
        "unit": "000_tonnes",
        "type": "capacity"
    }
)
```

### RegionCreate / CountryCreate

```python
RegionCreate(
    region_name="eastern_europe"
)

CountryCreate(
    country_name="poland",
    region_name="eastern_europe",
    is_active=True,
)
```

---

## Configuration (sheets_extractors.yaml)

```yaml
- name: regional_totals
  description: >
    Unified caster for all "Total ..." sheets with Region|Country|Years layout.
    Supports Argus, S&P, and CRU sources.  Product auto-detected.
  
  extractor_code: regional_totals_caster.py
  
  matches:
    exact:
      # Ammonia (Argus)
      - value: "Total Gross Capacity"
        data_provider: "argus"
      - value: "Total Merchant Production"
        data_provider: "argus"
      # ... 50+ sheet patterns ...
      
      # Processed Phosphates (S&P)
      - value: "PA Total Capacity"
        data_provider: "sp"
      - value: "DAP Total Production"
        data_provider: "sp"
      # ... more patterns ...
```

---

## Referential Integration

### Country Aliases
```yaml
# referential.yaml
country_aliases:
  ussr: soviet_union
  russian_federation: russia
  united_states: usa
  united_kingdom: uk
```

### Region Aliases
```yaml
region_aliases:
  eastern_&_asia: eastern_and_asia
  middle_&_near_east: middle_and_near_east
```

### Region Allowlist
```yaml
regions:
  - eastern_europe
  - western_europe
  - southern_europe
  - northern_europe
  - north_america
  - south_america
  - middle_east
  - sub-saharan_africa
  # ... more regions ...
```

### Product Categories
```yaml
products_by_category:
  n_fertilizer:
    - ammonia
    - urea
    - an
  p_fertilizer:
    - phosphate_rock
    - phosphoric_acid
  npk_fertilizer:
    - npk
```

---

## Worked Examples

### Example 1: Ammonia Regional Capacity (Argus)

**File:** `Argus Ammonia Analytics - 1Q 2025.xlsx`  
**Sheet:** `Total Gross Capacity`

**Input Data:**
```
Region              Country             2023    2024    2025(F)
Asia-Pacific        India               1200    1250    1300
Asia-Pacific        China               2800    2850    2900
Eastern Europe      Russia              1500    1500    1500
Eastern Europe      Poland              450     465     480
World Total         World Total         12000   12200   12500
```

**Output Metrics:**
```json
[
  {
    "product_name": "ammonia",
    "metric_name": "total_gross_capacity_release",
    "year": 2023,
    "value": "1200",
    "region_name": "asia-pacific",
    "country_name": "india",
    "unit_of_measure": "000_tonnes"
  },
  {
    "product_name": "ammonia",
    "metric_name": "total_gross_capacity_release",
    "year": 2024,
    "value": "1250",
    "region_name": "asia-pacific",
    "country_name": "india",
    "unit_of_measure": "000_tonnes"
  },
  {
    "product_name": "ammonia",
    "metric_name": "total_gross_capacity_forecast",
    "year": 2025,
    "value": "1300",
    "region_name": "asia-pacific",
    "country_name": "india",
    "unit_of_measure": "000_tonnes"
  }
]
```

**Note:** "World Total" row **skipped** (in locked_subregions)

---

### Example 2: S&P Processed Phosphates (DAP)

**File:** `S&P Processed Phosphates March 2025.xlsx`  
**Sheet:** `DAP Total Exports`

**Input Data:**
```
Region              Country             2023    2024
North America       United States       450     420
North America       Canada              80      85
South America       Brazil              200     220
Middle East         Saudi Arabia        150     160
```

**Output Metrics:**
```json
[
  {
    "product_name": "dap",
    "metric_name": "dap_total_exports_release",
    "metric_type": "exports",
    "year": 2023,
    "value": "450",
    "region_name": "north_america",
    "country_name": "united_states",
    "scope": {
      "region": "north_america",
      "country": "united_states",
      "unit": "000_tonnes",
      "type": "exports"
    }
  }
]
```

---

### Example 3: NPK Total Consumption (Multi-Source)

**File:** `NPK Analytics - 1Q 2025.xlsx`  
**Sheet:** `Total NPK Consumption`

**Input Data:**
```
Region              Country             2022    2023    2024
South America       Brazil              500     530     560
South America       Argentina           150     155     160
Africa              Nigeria             80      90      100
Africa              Egypt               200     210     220
```

**Output:**
```json
[
  {
    "product_name": "npk",
    "metric_name": "total_npk_consumption_release",
    "metric_type": "consumption",
    "year": 2023,
    "value": "530",
    "region_name": "south_america",
    "country_name": "brazil",
    "unit_of_measure": "000_tonnes"
  }
]
```

---

## Design Rationale

### 1. **Two-Pass Product Detection**
- **Why:** Different sources encode product differently
  - S&P: Prefix in sheet name (PA, DAP, MAP, TSP)
  - Argus: In document filename (Ammonia Analytics, Potash Analytics)
- **Benefit:** Zero configuration needed; auto-detects across all sources

### 2. **Whitelist/Blocklist Geographic Filtering**
- **Why:** Regional aggregate sheets contain implicit "totals" (World Total, EU Total, etc.)
- **Benefit:** Prevents double-counting (metrics only at country level, not aggregates)

### 3. **Region as Parent, Country as Child**
- **Why:** All sheets use Region|Country structure
- **Benefit:** Easy geographic hierarchy; supports continent→country lookups

### 4. **Forecast/Release Suffix**
- **Why:** Distinguish historical (release) from forward-looking (forecast) data
- **Benefit:** Downstream systems can filter by data type

### 5. **Scope as Metadata Container**
- **Why:** Flexibility for future geographic rollups or filtering
- **Benefit:** No schema changes needed if new geographic groupings emerge

---

## Comparison: Regional Totals vs. Flat Database Caster

| Aspect | Regional Totals | CRU Flat Database |
|--------|-----------------|-------------------|
| **Layouts** | 1 fixed (Region\|Country\|Years) | 4 types (prefixed, multi_col, single_col, plant) |
| **Metadata** | Minimal (unit only) | Extensive (Commodity, Unit, Variant, Concept) |
| **Metric Detection** | Simple (from sheet name) | 30+ keyword patterns |
| **Entity Levels** | Region, Country | Region, Country, Plant, Company |
| **Use Case** | Regional aggregates | Flat database with multiple layouts |
| **Complexity** | ~600 lines | ~1400 lines |

**When to use Regional Totals:**
- Simple regional/country-level aggregates
- Single layout across all sheets
- Sheet names encode the metric type

**When to use Flat Database:**
- Multiple geographic layouts in same file
- Detailed metadata in preamble
- Plant or company-level entities
- Specialized metrics (production, utilization, demand)

---

## Troubleshooting

### Issue 1: Header Row Not Found

**Symptom:** Warning "Header row not found in sheet"

**Cause:** The extractor searched rows 0-20 for "Region" and "Country" keywords, but didn't find both.

**Solution:**
1. Check the sheet manually:
   - Does column A contain "Region"?
   - Does column B or C contain "Country"?
   - Are they in the first 20 rows?
2. If not, the file may not match regional_totals pattern → skip it
3. If they exist but are misspelled (e.g., "Region Name", "Nation"), update sheets_extractors.yaml to mark sheet as skip

**Debug Code:**
```python
import pandas as pd
df = pd.read_excel("file.xlsx", sheet_name="Total Gross Capacity")
for i in range(min(20, len(df))):
    row_str = " ".join(str(v).lower() for v in df.iloc[i].values)
    if "region" in row_str:
        print(f"Row {i}: {row_str}")
```

---

### Issue 2: Product Not Detected

**Symptom:** `product_name = "unknown"` in output

**Cause:** Sheet name doesn't start with PA/DAP/MAP/TSP/NPK, and document name doesn't match product regex patterns.

**Solution:**
1. Check sheet name:
   - Starts with product token? (DAP Total Capacity → YES)
   - Update _SHEET_PREFIX_MAP if missing
2. Check document name:
   - Contains "ammonia", "potash", "phosphate_rock", "urea"?
   - Update _DOC_NAME_PATTERNS if document uses different naming

**Fix in Code:**
```python
# Add to _DOC_NAME_PATTERNS if needed
(re.compile(r"my_custom_product", re.I), "custom_product_name", "category")
```

---

### Issue 3: Geographic Names Not Recognized

**Symptom:** Country created with `region_name=None` or empty

**Cause:** Region name contains forbidden keywords or is in locked_subregions

**Solution:**
1. Check referential.yaml for region aliases:
   ```yaml
   region_aliases:
     my_region_old_name: my_region_new_name
   ```
2. Check allowed_regions list includes your region
3. If region is an aggregate (EU Total, World Total), it should be skipped (expected behavior)

---

### Issue 4: Year Columns Not Detected

**Symptom:** No metrics generated; years ignored

**Cause:** Year columns not in YYYY format (e.g., "2022.0", "Q1 2022", "Year 2022")

**Solution:**
1. Check Excel column headers:
   - Should be exactly "2022", "2023", etc.
   - Remove ".0" suffixes in header
2. If column has formula results, ensure they display as integers
3. Validate regex: `r"^\d{4}$"` matches exactly 4 digits

**Debug:**
```python
df.columns = df.iloc[header_idx]
for i, col in enumerate(df.columns):
    col_str = str(col).replace(".0", "").strip()
    if re.match(r"^\d{4}$", col_str):
        print(f"Column {i}: {col_str} → detected as year")
```

---

### Issue 5: Unit Not Detected

**Symptom:** `unit_of_measure = "000_tonnes"` (default) even if preamble specifies otherwise

**Cause:** Preamble row doesn't contain "Data in" or "000t" pattern

**Solution:**
1. Check rows above header for unit indicator:
   ```
   Row 1: "Data in 000 tonnes"    ← Detected
   Row 2: "In thousands of tonnes" ← NOT detected
   ```
2. Update _detect_unit_from_preamble() method if needed
3. Or add unit as parameter in sheets_extractors.yaml:
   ```yaml
   - value: "Total Capacity"
     params:
       unit: "kiloton_p2o5"
   ```

---

### Issue 6: Rows Incorrectly Skipped

**Symptom:** Expected metrics missing; rows skipped silently

**Cause:** Row contains forbidden keyword or country is in blocklist

**Solution:**
1. Check FORBIDDEN_KEYWORDS list for your region/country
2. Check BLOCKED_COUNTRIES list for disputed territories
3. Debug with logging:
   ```python
   logger.setLevel(logging.DEBUG)
   logger.debug(f"Row skipped: {region_std} / {country_std}")
   ```
4. If row should NOT be skipped, update:
   - LOCKED_SUBREGIONS
   - FORBIDDEN_KEYWORDS
   - BLOCKED_COUNTRIES

---

### Issue 7: Metrics Created for Regions Instead of Countries

**Symptom:** Metrics with `country_name="eastern_europe"` instead of specific country

**Cause:** Country value is actually a region name found in referential.allowed_regions

**Expected:** If country matches a known region, it's treated as RegionCreate, not CountryCreate

**Resolution:** This is correct behavior. Check if your sheet mixes region aggregates with country-level data. If intent is country metrics, ensure data is truly at country level.

---

## Best Practices

### 1. **File Naming**
Include publication quarter/month in filename for accurate date extraction:
```
✓ Argus Ammonia Analytics - 1Q 2025.xlsx
✓ S&P Processed Phosphates March 2025.xlsx
✗ Argus Ammonia Analytics.xlsx  ← No date; uses ingest date as fallback
```

### 2. **Sheet Naming**
Use consistent "Total" pattern:
```
✓ "Total Gross Capacity"
✓ "Total MOP Exports"
✓ "PA Total Production"
✗ "Gross Cap"           ← Not recognized
```

### 3. **Header Row**
Ensure exactly two geographic columns:
```
✓ Region | Country | 2022 | 2023 | ...
✓ Region | Country | Jan-22 | Jan-23 | ...
✗ Geography | 2022 | 2023  ← Missing Country column
```

### 4. **Referential Maintenance**
Keep referential.yaml updated with:
- New regions and region aliases
- Country additions/corrections
- Country→region mappings
- Data provider source codes

### 5. **Unit Consistency**
Use standard preamble format:
```
✓ Data in 000 tonnes
✓ Data in 000t P2O5
✗ Units: thousands  ← Not detected
```

---

## Related Documentation

- [README_CRU_FLAT_DATABASE_CASTER.md](README_CRU_FLAT_DATABASE_CASTER.md) — Complex 4-layout flat database extractor
- [README_TRADE_EXTRACTORS.md](README_TRADE_EXTRACTORS.md) — Trade matrix extractors
- [README_GREEN_BLUE_AMMONIA_PROJECTS.md](README_GREEN_BLUE_AMMONIA_PROJECTS.md) — Project database extraction
- **sheets_extractors.yaml** — Master template-to-extractor configuration (50+ regional_totals mappings)
- **referential.yaml** — Centralized geographic and product normalization

---

## Key Files

- **Implementation:** `src/excel_ingestion/extractors/implementation/regional_totals_caster.py`
- **Configuration:** `src/excel_ingestion/extractors/sheets_extractors.yaml`
- **Referential:** `src/excel_ingestion/config/referential.yaml`
- **Schemas:** `src/excel_ingestion/persistence/schemas.py`
- **Utilities:** `src/excel_ingestion/extractors/utils.py`

---

**Version:** 1.0  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team
