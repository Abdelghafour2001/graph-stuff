# README: Sulphur Market Outlook Capacity Database Caster

**File:** `sulphur_market_outlook_capacity_list_caster.py` (Planned/Template Implementation)  
**Pattern:** Capacity database extraction (Caster pattern)  
**Data Source:** CRU Sulphur Market Outlook - Capacity Forecasts & Projects sheets  
**Entity Model:** Hierarchical (Company → Plant) with full geographic + metadata tracking  
**Status:** ⚠️ Template - Currently referenced in sheets_extractors.yaml comments; implementation follows Phosphate Capacity Database pattern

---

## Overview

The **Sulphur Market Outlook Capacity Database Caster** extracts plant-level capacity forecasts and project timelines from CRU sulphur capacity database sheets. It normalizes geographic hierarchies and capacity values across multiple years, following the same **two-phase entity creation** pattern as the phosphate capacity database.

### Key Features

- **Hierarchical entities**: Company (parent) → Plant (child)
- **Geographic resolution**: Country → Region mapping via referential
- **Zero-NULL geographic fields**: Enforced referential mapping prevents NULL regions
- **Capacity types**: Total (auto-detected from sheet context)
- **Detailed metadata**: Location, technology, status, capacity grades
- **Forecast/Release distinction**: Based on publication year
- **Multi-year time series**: Year columns auto-detected
- **Sheet pattern matching**: "Capacity Forecasts" & "Projects" sheets

---

## Architecture

Identical to [README_PHOSPHATE_CAPACITY_DATABASE.md](README_PHOSPHATE_CAPACITY_DATABASE.md) with **Product = Sulphur** instead of Phosphate Rock:

```
Sulphur Capacity Database Extractor
│
├─ Input: Excel sheet with Region/Country/Company/Plant/Location/... columns + Year columns
│
├─ Stage 1: Document Context
│  ├─ Create DocumentCreate (publication date from document or referential)
│  └─ Identify sheet type: "Capacity Forecasts" or "Projects"
│
├─ Stage 2: Header Detection
│  ├─ Scan first 20 rows for marker keywords: "region", "country", "location"
│  ├─ Build column map: country → col_idx, entity → col_idx, plant → col_idx, etc.
│  └─ Detect year columns (numeric-only col headers)
│
├─ Stage 3: Data Qualification
│  ├─ Filter rows: Skip aggregates (total, world, other keyword checks)
│  ├─ Skip rows: Missing country, missing operating company
│  └─ Keep only rows with plant_name + operating_company + country
│
├─ Stage 4: Geographic Resolution (Zero-NULL Pattern)
│  ├─ Normalize country name
│  ├─ Look up country → region in referential
│  ├─ Fallback: Use sheet region → normalize
│  ├─ Final fallback: Default to "unknown_region"
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
│  ├─ Metric name: capacity_{scenario}  (no type suffix for sulphur)
│  └─ Include rich metadata in scope (location, technology, status)
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Products (sulphur or elemental_sulphur)
   ├─ Regions (normalized, zero NULL)
   ├─ Countries (mapped to regions, referential-backed)
   ├─ Entities (companies + plants with parent hierarchy)
   └─ Metrics (capacity by plant-year with metadata)
```

---

## Key Differences from Phosphate Pattern

| Aspect | Phosphate | Sulphur |
|--------|-----------|---------|
| **Product Name** | phosphate_rock | elemental_sulphur or sulphur |
| **Capacity Types** | Gross, Merchant | Total (or untyped) |
| **Metric Suffix** | capacity_{type}_{scenario} | capacity_{scenario} |
| **Metadata** | PGS Scoring, Technology | Production method, grade |
| **Geographic Scope** | Global (mostly Africa/Asia) | Global (oil refining regions) |
| **File Naming** | phosphate_fertilizer_market_outlook_* | sulphur_market_outlook_* |
| **Reference Sheets** | Capacity Forecasts, Projects | Capacity Forecasts, Projects |

---

## Data Processing Flow

### Geographic Resolution (Zero-NULL Guarantee)

```python
For each row:
  Country: "China" → "china"
  
  # Step 1: Lookup in referential
  referential.country_region_mapping.get("china") → "east_asia"
  
  # Step 2: Or use sheet region
  if not found:
      region_from_sheet = "East Asia" → "east_asia"
  
  # Step 3: Final assignment
  final_region = "east_asia"  # Never NULL, guaranteed
```

---

### Entity Hierarchy Creation

**Same 2-phase approach as Phosphate:**

**Phase 1: Create Companies**
```python
Company("shell")    → entity_type="company"
Company("bp")       → entity_type="company"
Company("chevron")  → entity_type="company"
```

**Phase 2: Create Plants (with parent reference)**
```python
Plant("port_arthur")   → parent_entity="shell"
Plant("hamburg")       → parent_entity="bp"
Plant("grand prairie") → parent_entity="shell"
```

---

### Metric Generation

```python
Year: 2024, Publication: 2025-Q1
  2024 < 2025 → scenario = "release"
  Metric: "capacity_release"

Year: 2025, Publication: 2025-Q1
  2025 >= 2025 → scenario = "forecast"
  Metric: "capacity_forecast"

Value: 750 (thousand tonnes)
Unit: kiloton

Scope includes all metadata:
  {
    "region": "middle_east",
    "country": "saudi_arabia",
    "plant_name": "Yanbu",
    "operating_company": "saudi_aramco",
    "location": "Saudi Arabia (Eastern Province)",
    "technology": "Oil Refining",
    "status": "Operating",
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
    products: List[ProductCreate]        # elemental_sulphur
    regions: List[RegionCreate]          # Extracted + mapped
    countries: List[CountryCreate]       # Mapped to regions
```

### DocumentCreate

```python
DocumentCreate(
    document_name="sulphur_market_outlook_DATE_capacity_database",
    document_path="/path/to/file.xlsx",
    source_code="cru",
    publication_date=date(2025, Q1),     # Inferred from file date
    ingestion_date=date.today(),
    is_archived=False,
)
```

### ProductCreate

```python
ProductCreate(
    product_name="elemental_sulphur",  # or "sulphur"
    product_category_name="elemental",
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

### EntityCreate (Plant)

```python
EntityCreate(
    entity_name="port_arthur",
    entity_type="plant",
    parent_entity="shell",
    country_name="united_states",
    region_name="north_america",
    is_active=True,
)
```

### MetricCreate

```python
MetricCreate(
    metric_name="capacity_release",
    metric_type="capacity",
    value="750",
    unit_of_measure="kiloton",
    year=2024,
    start_date_effect=date(2024, 1, 1),
    end_date_effect=date(2024, 12, 31),
    date_publication=date(2025, 3, 1),
    country_name="united_states",
    region_name="north_america",
    entity_name="port_arthur",
    product_name="elemental_sulphur",
    sheet_name="Capacity Forecasts",
    document_name="sulphur_market_outlook_DATE_capacity_database",
    scope={
        "region": "north_america",
        "country": "united_states",
        "plant_name": "Port Arthur",
        "operating_company": "Shell",
        "location": "Port Arthur, Texas",
        "technology": "Oil Refining",
        "status": "Operating",
        "unit": "kiloton"
    }
)
```

---

## Configuration (sheets_extractors.yaml)

```yaml
- name: sulphur_market_outlook_capacity_database
  description: >
    Sulphur market outlook – Capacity Forecasts & Projects sheets.
    Plant-level capacity with company hierarchy.
  
  extractor_code: sulphur_market_outlook_capacity_list_caster.py
  
  matches:
    exact:
      - value: "Capacity Forecasts"
        data_provider: "cru"
        file_regex: "sulphur"
      - value: "Projects"
        data_provider: "cru"
        file_regex: "sulphur"
```

---

## Referential Integration

### Required Mappings

```yaml
# referential.yaml
countries:
  - saudi_arabia
  - united_states
  - canada
  - ... (all sulphur-producing countries)

country_region_mapping:
  saudi_arabia: middle_east
  united_states: north_america
  canada: north_america
  china: east_asia
  india: south_asia
  vietnam: southeast_asia
  netherlands: western_europe
  # ... comprehensive mapping

regions:
  - middle_east
  - north_america
  - east_asia
  - south_asia
  - southeast_asia
  - western_europe
  - southern_africa
  # ... major sulphur-producing regions

products_by_category:
  elemental:
    - elemental_sulphur
    - sulphur
```

---

## Worked Examples

### Example 1: Saudi Aramco Refinery (Saudi Arabia)

**Sheet Fragment (Capacity Forecasts):**
```
| Region | Country | Plant Name | Operating Company | Location | Technology | Status | 2024 | 2025(F) | 2026(F) |
|--------|---------|------------|-------------------|----------|-----------|--------|------|---------|---------|
| ME     | SA      | Yanbu      | Saudi Aramco      | Yanbu R  | Oil Refin. | Operat | 500  | 550     | 550     |
| ME     | SA      | Ras Tanura | Saudi Aramco      | E Prov   | Oil Refin. | Operat | 700  | 700     | 700     |
```

**Processing:**

Row 1:
  - Country: "SA" → "saudi_arabia"
  - Region lookup: saudi_arabia → "middle_east" (from referential)
  - Company: "Saudi Aramco" → "saudi_aramco"
  - Plant: "Yanbu" → "yanbu"

**Output:**
- Company: `EntityCreate(entity_name="saudi_aramco", entity_type="company", ...)`
- Plants:
  - `EntityCreate(entity_name="yanbu", parent_entity="saudi_aramco", entity_type="plant", ...)`
  - `EntityCreate(entity_name="ras_tanura", parent_entity="saudi_aramco", entity_type="plant", ...)`
- Metrics (6 total: 2 plants × 3 years):
  - yanbu 2024: 500kt (release)
  - yanbu 2025: 550kt (forecast)
  - yanbu 2026: 550kt (forecast)
  - ras_tanura 2024: 700kt (release)
  - ras_tanura 2025: 700kt (forecast)
  - ras_tanura 2026: 700kt (forecast)

---

### Example 2: Multi-Region Capex Projects

**Sheet Fragment (Projects):**
```
| Region | Country | Plant Name | Operating Company | Location | Technology | Status | 2024 | 2025(F) | 2026(F) | 2027(F) |
|--------|---------|------------|-------------------|----------|-----------|--------|------|---------|---------|---------|
| NA     | USA     | Beaumont   | Valero            | Texas    | Coker      | Under  | 0    | 200     | 400     | 450     |
| NA     | CAN     | Upgrader   | Suncor            | Alberta  | Upgrade   | Plan   | 0    | 0       | 300     | 600     |
```

**Processing:**

Rows show future capacity additions (under construction / planned):
  - Beaumont: Ramping up 2025-2027
  - Upgrader: Ramping up 2026-2027

All share:
  - region_name: "north_america"
  - All marked as forecast (future years)

---

## Design Rationale

### 1. **Same Architecture as Phosphate (Proven Pattern)**
- **Why:** Both are capacity databases with company-plant hierarchies
- **Benefit:** Consistent code path; easier to maintain
- **Implementation:** Switch product_name from "phosphate_rock" to "elemental_sulphur"

### 2. **2-Phase Entity Creation**
- **Why:** Database FK constraints
- **Benefit:** Prevents "Parent entity not found" errors
- **Implementation:** Create all companies first, then plants with parent_entity references

### 3. **Zero-NULL Region Fields**
- **Why:** Prevents FK violations  in region_name columns
- **Implementation:** Referential mapping + fallback chain
- **Guarantee:** final_region never None

### 4. **Omit Capacity Type Suffix (Unlike Phosphate)**
- **Why:** Sulphur capacity is typically untyped (no gross/merchant distinction)
- **Metric Naming:** "capacity_release" vs "capacity_forecast" (not "capacity_gross_release")
- **Flexibility:** Can add type suffix later if data requires it

---

## Implementation Checklist

When implementing `sulphur_market_outlook_capacity_list_caster.py`:

- [ ] Clone phosphate_fertilizer_market_outlook_DATE_npk_capacity_database.py
- [ ] Replace product_name: "phosphate_rock" → "elemental_sulphur"
- [ ] Remove capacity_type detection (or make optional)
- [ ] Update metric naming: capacity_{type}_{scenario} → capacity_{scenario}
- [ ] Update logger names: "sulphur_capacity_caster"
- [ ] Update sheet filtering: file_regex "sulphur" instead of "fertilizer"
- [ ] Test with sample sulphur capacity data
- [ ] Update referential.yaml with sulphur country/region mappings
- [ ] Add configuration to sheets_extractors.yaml (uncomment and enable)

---

## Referential Sulphur Mappings

**Required country_region_mapping entries:**

```yaml
country_region_mapping:
  # Oil refining (MAJOR source)
  saudi_arabia: middle_east
  kuwait: middle_east
  united_arab_emirates: middle_east
  iraq: middle_east
  iran: middle_east
  bahrain: middle_east
  qatar: middle_east
  oman: middle_east
  yemen: middle_east
  
  # North America
  united_states: north_america
  canada: north_america
  mexico: north_america
  
  # Europe
  netherlands: western_europe
  france: western_europe
  norway: northern_europe
  russia: eastern_europe
  
  # Asia-Pacific
  china: east_asia
  india: south_asia
  japan: east_asia
  south_korea: east_asia
  australia: oceania
  
  # Africa
  south_africa: southern_africa
  egypt: north_africa
  algeria: north_africa
```

---

## Troubleshooting

### Issue 1: Header Row Not Found

**Solution:** [Same as Phosphate] Verify sheet contains "region", "country", or "location" in first 20 rows.

---

### Issue 2: All Rows Skipped (No Metrics)

**Solution:** [Same as Phosphate] Check country column is populated and detectable via column mapping.

---

### Issue 3: Parent Entity "Saudi Aramco" Not Found

**Solution:** [Same as Phosphate] Verify operating company column has data for all plants; check for data quality issues.

---

### Issue 4: Region Shows "unknown_region"

**Solution:** [Same as Phosphate] Add country → region mapping to referential.yaml.

---

## Comparison: Phosphate vs. Sulphur Capacity Casters

| Aspect | Phosphate | Sulphur |
|--------|-----------|---------|
| **File to implement** | ✓ Exists | ⚠️ Template (use phosphate as pattern) |
| **Product** | phosphate_rock | elemental_sulphur |
| **Entity types** | Company, Plant | Company, Plant |
| **Capacity types** | Gross, Merchant | Total (untyped) |
| **Geographic scope** | Global (Africa/Asia/ME) | Global (oil refining centers) |
| **Metadata** | PGS scoring, technology | Technology, grade |
| **Architecture** | 100% identical | 100% identical (swap product) |
| **Code reuse** | Reference implementation | Clone + customize |

---

## Related Documentation

- [README_PHOSPHATE_CAPACITY_DATABASE.md](README_PHOSPHATE_CAPACITY_DATABASE.md) — Reference implementation (phosphate)
- [README_CRU_FLAT_DATABASE_CASTER.md](README_CRU_FLAT_DATABASE_CASTER.md) — Flat database pattern (simpler)
- [README_REGIONAL_TOTALS_CASTER.md](README_REGIONAL_TOTALS_CASTER.md) — Regional aggregates (different pattern)
- **sheets_extractors.yaml** — Master configuration (sulphur entries currently commented)
- **referential.yaml** — Geographic normalization (requires sulphur country mappings)

---

## Key Files (When Implemented)

- **Implementation:** `src/excel_ingestion/extractors/implementation/sulphur_market_outlook_capacity_list_caster.py` (to create)
- **Configuration:** `src/excel_ingestion/extractors/sheets_extractors.yaml` (uncomment sulphur entries)
- **Referential:** `src/excel_ingestion/config/referential.yaml` (add sulphur mappings)
- **Schemas:** `src/excel_ingestion/persistence/schemas.py` (use existing)

---

**Version:** 1.0 (Template/Specification)  
**Status:** ⚠️ Pending Implementation  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team  
**Next Step:** Use README_PHOSPHATE_CAPACITY_DATABASE implementation as reference to build this caster
