# README: Phosphate Fertilizer Capacity Database Caster

**File:** `phosphate_fertilizer_market_outlook_DATE_npk_capacity_database.py` (513 lines)  
**Pattern:** Capacity database extraction (Caster pattern)  
**Data Source:** CRU Phosphate Fertilizer Market Outlook - Capacity Forecasts & Projects sheets  
**Entity Model:** Hierarchical (Company → Plant) with full geographic + metadata tracking

---

## Overview

The **Phosphate Fertilizer Capacity Database Caster** extracts plant-level capacity forecasts and project timelines from CRU capacity database sheets. It normalizes geographic hierarchies (Region, Country, Company, Plant) with capacity values across multiple years.

### Key Features

- **Hierarchical entities**: Company (parent) → Plant (child)
- **Geographic resolution**: Country → Region mapping via referential
- **Zero-NULL geographic fields**: Enforced referential mapping prevents NULL regions
- **Capacity types**: Gross, Merchant (detected from sheet name)
- **Detailed metadata**: Location, technology, status, PGS scoring
- **Forecast/Release distinction**: Based on publication year
- **Multi-year time series**: Year columns auto-detected  
- **Sheet pattern matching**: "Capacity Forecasts" & "Projects" sheets

---

## Architecture

```
Phosphate Capacity Database Extractor
│
├─ Input: Excel sheet with Region/Country/Company/Plant/Location/... columns + Year columns
│
├─ Stage 1: Document Context
│  ├─ Create DocumentCreate (fixed publication date: 2025-03-28)
│  └─ Identify sheet type: "Capacity Forecasts" or "Projects"
│
├─ Stage 2: Header Detection
│  ├─ Scan first 20 rows for marker keywords: "region", "country", "location"
│  ├─ Build column map: country → col_idx, entity → col_idx, plant → col_idx, etc.
│  └─ Detect year columns (numeric-only col headers)
│
├─ Stage 3: Data Qualification
│  ├─ Filter rows: Skip aggregates (total, world, small producers keyword checks)
│  ├─ Skip rows: Missing country, missing operating company
│  └─ Keep only rows with plant_name + operating_company + country (hierarchy required)
│
├─ Stage 4: Geographic Resolution (Zero-NULL Pattern)
│  ├─ Normalize country name
│  ├─ Look up country → region in referential
│  ├─ If not found: Use sheet region column → normalize
│  ├─ If still None: Default to "unknown_region"
│  └─ Prevents NULL region_name in all entities/metrics
│
├─ Stage 5: Entity Creation (2-Phase)
│  ├─ Phase 1: Create all COMPANIES first (parent entities)
│  ├─ Phase 2: Create PLANTS with parent_entity reference to company
│  └─ Ensures parent-child referential integrity
│
├─ Stage 6: Metric Generation
│  ├─ For each year column: Extract numeric value
│  ├─ Determine scenario: year > pub_year → forecast; else → release
│  ├─ Capacity type: "gross" or "merchant" (from sheet name)
│  ├─ Metric name: capacity_{type}_{scenario}
│  └─ Include rich metadata in scope (location, technology, status, PGS scoring)
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Products (phosphate_rock)
   ├─ Regions (normalized, zero NULL)
   ├─ Countries (mapped to regions, referential-backed)
   ├─ Entities (companies + plants with parent hierarchy)
   └─ Metrics (capacity by plant-year-type with metadata)
```

---

## Data Processing Flow

### 1. **Sheet Selection**

Only processes sheets named exactly:
- "Capacity Forecasts"
- "Projects"

Other sheets are skipped (logged as "Sheet not handled").

---

### 2. **Header Detection**

Scans first 20 rows for any cell containing: "region", "country", or "location" (case-insensitive)

**Example:**
```
Row 0-2:   Blank/metadata
Row 3:     Capacity Database Header Row ← DETECTED
           Region | Sub Region | Country | Plant Name | Operating Company | Location | ...
Row 4+:    Data rows
```

---

### 3. **Column Mapping**

Dynamically maps column headers to semantic categories:

```python
Column Header           → Mapped To
───────────────────────────────────
"country"              → country
"region" (not sub)     → region
"sub region"           → sub_region
"operating company"    → entity (company)
"plant name"           → plant
"short plant name"     → short_plant
"location"             → location
"technology"           → technology
"status"               → status
"pgs scoring"          → pgs_scoring
```

If column header doesn't match any pattern, it's checked to see if it's numeric (YYYY) → year column.

---

### 4. **Row Filtering (Data Qualification)**

**Skip rows where:**
1. Country column is empty → `skipped_no_country`
2. Combined text contains: "total", "world", "other", "small producers" → `skipped_agg`
3. Operating Company is NA/null → `skipped_no_parent` (hierarchy enforcement)
4. Plant name is NA/empty after normalization → `skipped_no_plant`

**Kept rows are stored with normalized geographic + entity data for later phases.**

---

### 5. **Geographic Resolution (Zero-NULL Guarantee)**

For each kept row:

```python
Raw input:
  Country: "South Africa"
  Region: "Africa"
  
Step 1: Normalize country
  "South Africa" → "south_africa"

Step 2: Look up in referential.country_region_mapping
  country_region_mapping.get("south_africa") → "sub_saharan_africa"
  
Step 3: If found, use it; else fall back to sheet region:
  final_region = "sub_saharan_africa" (from mapping)
  
Step 4: Normalize region
  "sub_saharan_africa" → "sub_saharan_africa"
  
Step 5: Store normalized pairs for schemas
  country: "south_africa"
  region: "sub_saharan_africa"  ← Never NULL
```

**Key:** If country→region map missing AND sheet region is NA:
  ```python
  final_region = "unknown_region"  # Final fallback, never None
  ```

---

### 6. **Entity Creation (2-Phase)**

**Phase 1: Companies (Parent Entities)**
```python
For each unique operating_company in kept rows:
  ├─ If not yet emitted:
  │  └─ EntityCreate(
  │     entity_name="prayon",
  │     entity_type="company",
  │     country_name="belgium",
  │     region_name="western_europe",
  │     is_active=True
  │  )
  └─ Add to emitted set
```

**Phase 2: Plants (Child Entities)**
```python
For each unique plant_name in kept rows:
  ├─ If not yet emitted:
  │  └─ EntityCreate(
  │     entity_name="engis",
  │     parent_entity="prayon",           ← Links to company
  │     entity_type="plant",
  │     country_name="belgium",
  │     region_name="western_europe",
  │     is_active=True
  │  )
  └─ Add to emitted set
```

**Why 2 phases?** Database FK constraints require parent (company) to exist before child (plant).

---

### 7. **Metric Generation**

For each (plant, year) combination:

```python
Year: 2025, Publication Date: 2025-03-28
  2025 >= 2025 → scenario = "forecast"

Year: 2024, Publication Date: 2025-03-28
  2024 < 2025 → scenario = "release"

Sheet: "Capacity Forecasts"
  "Capacity Forecasts" contains "forecast" (ignored in type detection)
  Type detection: "Gross" in sheet name? → type = "gross"
  
Metric name: capacity_{type}_{scenario}
  → "capacity_gross_forecast" (2025)
  → "capacity_gross_release" (2024)

Scope enriches metric with all available metadata:
  {
    "region": "western_europe",
    "country": "belgium",
    "plant_name": "Engis",
    "operating_company": "Prayon",
    "location": "Jorf Lasfar",
    "technology": "Gafsa-Type",
    "status": "Operating",
    "pgs_scoring": "A1",
    "unit": "kiloton"
  }
```

---

## Data Structures

### SchemaCollection (Output)

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate             # File metadata
    metrics: List[MetricCreate]          # Capacity by plant-year
    entities: List[EntityCreate]         # Companies + Plants
    products: List[ProductCreate]        # phosphate_rock
    regions: List[RegionCreate]          # Extracted + mapped
    countries: List[CountryCreate]       # Mapped to regions
```

### DocumentCreate

```python
DocumentCreate(
    document_name="phosphate_fertilizer_market_outlook_DATE_npk_capacity_database",
    document_path="/path/to/file.xlsx",
    source_code="cru",
    publication_date=date(2025, 3, 28),  # Fixed publication date
    ingestion_date=date(2025, 3, 20),    # Current date
    is_archived=False,
)
```

### EntityCreate (Company)

```python
EntityCreate(
    entity_name="prayon",
    entity_type="company",
    country_name="belgium",
    region_name="western_europe",
    is_active=True,
)
```

### EntityCreate (Plant)

```python
EntityCreate(
    entity_name="engis",
    entity_type="plant",
    parent_entity="prayon",              # Links to company
    country_name="belgium",
    region_name="western_europe",
    is_active=True,
)
```

### MetricCreate

```python
MetricCreate(
    metric_name="capacity_gross_release",
    metric_type="capacity",
    value="450",
    unit_of_measure="kiloton",
    year=2024,
    start_date_effect=date(2024, 1, 1),
    end_date_effect=date(2024, 12, 31),
    date_publication=date(2025, 3, 28),
    country_name="belgium",
    region_name="western_europe",
    entity_name="engis",
    product_name="phosphate_rock",
    sheet_name="Capacity Forecasts",
    document_name="phosphate_fertilizer_market_outlook_DATE_npk_capacity_database",
    scope={
        "region": "western_europe",
        "country": "belgium",
        "plant_name": "Engis",
        "operating_company": "Prayon",
        "location": "Jorf Lasfar",
        "technology": "Gafsa-Type",
        "status": "Operating",
        "pgs_scoring": "A1",
        "unit": "kiloton",
        "type": "gross"  # If capacity_type detected
    }
)
```

---

## Configuration (sheets_extractors.yaml)

```yaml
- name: phosphate_fertilizer_market_outlook_capacity_database
  description: >
    Phosphate fertilizer capacity database - Plant-level capacity forecasts
    and projects with company hierarchy.  Gross/Merchant capacity auto-detected.
  
  extractor_code: phosphate_fertilizer_market_outlook_DATE_npk_capacity_database.py
  
  matches:
    exact:
      - value: "Capacity Forecasts"
        data_provider: "cru"
        file_regex: "fertilizer"
      - value: "Projects"
        data_provider: "cru"
        file_regex: "fertilizer"
```

---

## Referential Integration

### Country → Region Mapping (Critical)

```yaml
# referential.yaml
country_region_mapping:
  south_africa: sub_saharan_africa
  morocco: north_africa
  egypt: north_africa
  tunisia: north_africa
  belgium: western_europe
  france: western_europe
  united_states: north_america
  china: east_asia
  india: south_asia
  # ... all countries must be mapped to prevent NULL
```

**Enforcement:** If country not in mapping AND sheet region is NA:
  ```python
  final_region = "unknown_region"  # Ultimate fallback
  ```

---

## Worked Examples

### Example 1: Prayon - Engis (Belgium)

**Sheet Fragment (Capacity Forecasts):**
```
| Region | Sub Region | Country | Plant Name | Operating Company | Location | Technology | Status | PGS Scoring | 2024 | 2025(F) | 2026(F) |
|--------|------------|---------|------------|-------------------|----------|-----------|--------|------------|------|---------|---------|
| Europe | Western    | Belgium | Engis      | Prayon            | Jorf     | Gafsa-Type| Operat | A1         | 450  | 450     | 450     |
| Europe | Western    | Belgium | Azote      | Prayon            | Jorf     | Gafsa-Type| Operat | A2         | 350  | 350     | 350     |
```

**Processing:**

Row 1:
  - Country: "Belgium" → "belgium"
  - Region lookup: belgium → "western_europe" (from referential)
  - Company: "Prayon" → "prayon"
  - Plant: "Engis" → "engis"
  - Year 2024: scenario = release (2024 < 2025)
  - Year 2025: scenario = forecast (2025 >= 2025)

**Output Entities:**
1. Company: `EntityCreate(entity_name="prayon", entity_type="company", ...)`
2. Plant: `EntityCreate(entity_name="engis", parent_entity="prayon", entity_type="plant", ...)`

**Output Metrics:**
```json
[
  {
    "entity_name": "engis",
    "product_name": "phosphate_rock",
    "metric_name": "capacity_gross_release",
    "year": 2024,
    "value": "450",
    "region_name": "western_europe",
    "country_name": "belgium",
    "scope": {
      "region": "western_europe",
      "country": "belgium",
      "plant_name": "Engis",
      "operating_company": "Prayon",
      "location": "Jorf",
      "technology": "Gafsa-Type",
      "status": "Operat",
      "pgs_scoring": "A1",
      "type": "gross"
    }
  },
  {
    "entity_name": "engis",
    "metric_name": "capacity_gross_forecast",
    "year": 2025,
    "value": "450",
    ...
  }
]
```

---

### Example 2: Multiple Companies (Morocco)

**Sheet Fragment:**
```
| Region | Country | Plant Name | Operating Company | 2024 | 2025(F) | 2026(F) |
|--------|---------|------------|-------------------|------|---------|---------|
| Africa | Morocco | Safi       | OCP               | 1200 | 1200    | 1300    |
| Africa | Morocco | Jorf       | OCP               | 900  | 900     | 900     |
| Africa | Morocco | Khouribga  | Independent       | 300  | 350     | 400     |
```

**Entity Hierarchy Created:**

```
Company: OCP
  ├─ Plant: Safi (metrics: 1200kt 2024, 1200kt 2025, 1300kt 2026)
  └─ Plant: Jorf (metrics: 900kt 2024, 900kt 2025, 900kt 2026)

Company: Independent
  └─ Plant: Khouribga (metrics: 300kt 2024, 350kt 2025, 400kt 2026)
```

All share:
  - region_name: "north_africa" (from country_region_mapping)
  - country_name: "morocco"

---

## Design Rationale

### 1. **Zero-NULL Geographic Fields**
- **Why:** NULLs in region_name cause FK errors in repositories
- **Implementation:** Fallback chain: country_region_map → sheet region → "unknown_region"
- **Benefit:** No query failures; all records persist

### 2. **2-Phase Entity Creation (Company → Plant)**
- **Why:** Database FK enforces parent existence before child
- **Benefit:** Prevents "Parent entity not found" errors
- **Pattern:** Emit all companies, then all plants

### 3. **Column Auto-Detection**
- **Why:** Excel column names vary; schema needs flexibility
- **Implementation:** Fuzzy regex matching on header names
- **Benefit:** Reduces configuration; handles minor naming variations

### 4. **Aggregate Row Filtering**
- **Why:** Sheets often contain "World Total", "Other", "Small Producers" rows
- **Benefit:** Prevents inflated capacity metrics; keeps only plant-level data

### 5. **Metadata in Scope (Not Separate Fields)**
- **Why:** Plants have many optional metadata fields (location, technology, status, PGS scoring)
- **Implementation:** Store all metadata in scope dict, not on metric entity
- **Benefit:** Flexible expansion; no schema changes needed for new metadata fields

### 6. **Fixed Publication Date**
- **Why:** CRU capacity databases released on fixed schedule (2025-03-28)
- **Implementation:** Hardcoded in caster; not extracted from filename
- **Benefit:** Consistency; avoids date parsing errors
- **Note:** Should be configurable per data release if this changes

---

## Logging & Monitoring

The caster uses extensive logging for operational visibility:

```python
logger.warning("Caster initialized | referential_countries=%s", len(...))
logger.warning("Header detection | header_idx=%s", header_idx)
logger.warning("Row scan summary | kept=%s | skipped_no_country=%s | skipped_agg=%s", ...)
logger.warning("Companies created | count=%s", len(...))
logger.warning("Plants created | count=%s", len(...))
logger.warning("Metrics created | count=%s | skipped_null_values=%s", ...)
```

**Log Levels:**
- **WARNING**: Key processing milestones (header found, entities created, metrics done)
- **DEBUG**: Detailed row/column processing (skip reasons, normalization steps)
- **ERROR**: Processing failures (invalid data, missing referential)

---

## Troubleshooting

### Issue 1: "Header row not found"

**Symptom:** Processing skipped; logging shows "Header row not found"

**Cause:** Scanned first 20 rows but didn't find "region", "country", or "location"

**Solution:**
1. Check sheet structure manually
2. Verify headers in first 20 rows contain at least one marker word
3. If headers are different (e.g., "Region Code", "Country Name"), mark sheet as skip

---

### Issue 2: All rows skipped ("skipped_no_country" high)

**Symptom:** Document created but 0 metrics generated

**Cause:** Country column empty or not found via column mapping

**Solution:**
1. Verify column header contains "country" (case-insensitive)
2. Check data: Are country cells actually filled?
3. Debug column map: Add logging to see what columns were detected

---

### Issue 3: "missing operating company" rows skipped

**Symptom:** Some plants missing; entities incomplete

**Cause:** Row has country/plant but company column is NA/null

**Solution:**
1. Verify company column has data for all plants
2. If some plants truly have no company, discuss data quality with source
3. Consider optional company (remove enforcement) if needed

---

### Issue 4: Region showing "unknown_region" instead of expected region

**Symptom:** All metrics have region_name="unknown_region"

**Cause:** Country not in referential.country_region_mapping AND sheet region column is empty/NA

**Solution:**
1. Add country → region mapping to referential.yaml:
   ```yaml
   country_region_mapping:
     my_country: my_region
   ```
2. Or populate region column in data
3. Or update sheet region column with correct region

---

### Issue 5: Capacity type not detected (metric_name = "capacity_forecast" instead of "capacity_gross_forecast")

**Symptom:** Metric doesn't distinguish gross vs. merchant

**Cause:** Sheet name doesn't contain "gross" or "merchant" keywords

**Solution:**
1. Check sheet name: Should be "Capacity Forecasts - Gross" or similar
2. If not, update detection logic:
   ```python
   if "gross" in sheet_name.lower():
       capacity_type = "gross"
   elif "merchant" in sheet_name.lower():
       capacity_type = "merchant"
   ```
3. Or mark metric_name manually in config

---

## Best Practices

### 1. **Referential Maintenance**
Keep referential.yaml updated with:
- All countries in data
- Country → region mappings (NO NULLs)
- Company names if needed

### 2. **Sheet Naming Convention**
Use consistent naming:
```
✓ "Capacity Forecasts" or "Capacity Forecasts - Gross"
✓ "Projects"
✗ "Capac" or "Forecasts" (ambiguous)
```

### 3. **Column Headers**
Ensure headers contain semantic keywords:
```
✓ "Country", "Region", "Plant Name", "Operating Company", "Location"
✗ "Col A", "Geo", "Entity" (no semantic meaning)
```

### 4. **Data Cleaning**
Remove aggregate rows before or during ingestion:
- Remove "World Total" rows
- Remove "Other" / "Small Producers" rows
- Keep only plant-level entities

### 5. **Company-Plant Hierarchy**
Verify every plant has a parent company in data:
```
✓ Operating Company: "Prayon", Plant: "Engis"
✓ All plants linked to companies
✗ Missing company values
```

---

## Related Documentation

- [README_REGIONAL_TOTALS_CASTER.md](README_REGIONAL_TOTALS_CASTER.md) — Simple region|country|years
- [README_CRU_FLAT_DATABASE_CASTER.md](README_CRU_FLAT_DATABASE_CASTER.md) — Complex 4-layout flat database
- [README_PHOSPHATEOUTLOOK_COSTDATA.md](README_PHOSPHATEOUTLOOK_COSTDATA.md) — Cost & capacity data (S&P)
- **sheets_extractors.yaml** — Master configuration
- **referential.yaml** — Geographic normalization

---

## Key Files

- **Implementation:** `src/excel_ingestion/extractors/implementation/phosphate_fertilizer_market_outlook_DATE_npk_capacity_database.py`
- **Configuration:** `src/excel_ingestion/extractors/sheets_extractors.yaml`
- **Referential:** `src/excel_ingestion/config/referential.yaml`
- **Schemas:** `src/excel_ingestion/persistence/schemas.py`

---

**Version:** 1.0  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team
