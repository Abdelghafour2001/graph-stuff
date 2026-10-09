# CRU Flat Database Caster Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture & Data Flow](#architecture--data-flow)
3. [Supported File Types](#supported-file-types)
4. [Layout Detection & Parsing](#layout-detection--parsing)
5. [Core Components](#core-components)
6. [Classes & Object Design](#classes--object-design)
7. [Data Processing & Transformation](#data-processing--transformation)
8. [Design Decisions](#design-decisions)
9. [Geographic Layouts](#geographic-layouts)
10. [Examples](#examples)
11. [Troubleshooting](#troubleshooting)

---

## Overview

### Purpose

The **CRU Flat Database Caster** is a unified data ingestion pipeline designed to extract, parse, and normalize flat-database formats from commodity market analysis reports. The system handles diverse geographic layouts (Region/SubRegion/Country × Years) and automatically detects product types, metrics, and data structures, transforming raw spreadsheet data into structured database schemas.

### What is Flat Database Extraction?

Flat database extraction refers to the **automated extraction and structuring of time-series geographical data** from market research reports in tabular format:

- **Geographic hierarchies**: Region → SubRegion → Country rows
- **Temporal data**: Year columns spanning multiple decades
- **Metrics**: Capacity, Production, Consumption, Imports, Exports, etc.
- **Variants**: Grey/Green/Blue ammonia, different product grades
- **Commodities**: Ammonia, Phosphate Rock, Sulphur, NPK, Potash, Urea
- **Data providers**: CRU, S&P, Argus

### Key Capabilities

- **Multi-layout support**: Detects and parses 4 distinct geographic layouts
- **Flexible product detection**: Auto-detects products from document name, sheet name, or data preamble
- **Variant tracking**: Captures product variants (green ammonia, blue ammonia, etc.)
- **Dynamic metric extraction**: Identifies metrics from sheet names using keyword matching
- **Referential integration**: Normalizes countries and regions using centralized configuration
- **Plant-level data**: Special handling for company/plant hierarchies

### Overall Workflow

```
Excel File (CRU/S&P Market Report)
       ↓
[Sheet Detection] → Match against sheets_extractors.yaml
                    (Capacity, Production, Exports, etc.)
       ↓
[Load Extractor] → Load cru_flat_database_caster.py
       ↓
[Detect Layout] → Identify geographic structure:
                  - Prefixed (WPAAustria format)
                  - Multi-col (Region|SubRegion|Country)
                  - Single-col (state machine)
                  - Plant-level (Company|Plant × Years)
       ↓
[Find Headers] → Locate header row with year columns
       ↓
[Extract Metadata] → Parse preamble for:
                  - Product/Commodity
                  - Unit of measure
                  - Metric type
                  - Variants (grey/green/blue)
       ↓
[Parse Rows] → For each geographic row:
                - Extract country/region info
                - Parse year values
                - Create metrics
                - Classify entities (for plant-level)
       ↓
[Standards] → Using referential.yaml:
                  - Normalize country names
                  - Map to regions
                  - Standardize product names
                  - Resolve unit aliases
       ↓
[Database Ready] → SchemaCollection containing:
                   - Document metadata
                   - List of Metrics (geographic time series)
                   - List of Entities (plants, companies)
                   - List of Products
                   - List of Regions and Countries
       ↓
[Persistence]    → Loaded into PostgreSQL database
```

---

## Architecture & Data Flow

### Component Hierarchy

```
extractors/
├── loader.py                                    # Sheet matcher
├── utils.py                                     # Utilities
├── sheets_extractors.yaml                       # Configuration
└── implementation/
    └── cru_flat_database_caster.py              # Unified flat DB caster
        ├── Caster (main class)
        ├── Layout detection (4 types)
        ├── Geographic parsing (3+ methods)
        ├── Product/metric detection
        │ └── Keyword matching
        ├── Referential integration
        └── Entity management
```

### Data Flow Diagram

```
RawExcelData ──[Detect Layout]──→ [Find Header + Years]
                                          ↓
                    [Extract Preamble Metadata]
                    (Product, Unit, Variant, Metric)
                                          ↓
                    [For Each Data Row]
                    ├─→ Parse Geographic (layout-specific)
                    ├─→ Extract Year Values
                    ├─→ Normalize Country/Region
                    ├─→ Create Metric Records
                    └─→ Emit Entities (plant-level)
                                          ↓
                    SchemaCollection
                    ├── Document
                    ├── Metrics[]
                    ├── Entities[]
                    ├── Products[]
                    ├── Regions[]
                    └── Countries[]
```

---

## Supported File Types

### Ammonia Reports

| Filename Pattern | Layout | Product | Example Sheets |
|---|---|---|---|
| `ammonia-market-outlook-*-flat-database` | Multi-col (3) | ammonia | Capacity, Production, Exports |
| `Ammonia_Outlook_Data_File_*` | Multi-col (3+offset) | ammonia | Capacity by geography, Production |

**Product Variants Detected:**
- Grey ammonia (conventional)
- Green ammonia (renewable-based)
- Blue ammonia (carbon capture)
- Low carbon ammonia

### Phosphate Rock Reports

| Filename Pattern | Layout | Product | Example Sheets |
|---|---|---|---|
| `phosphate-rock-market-outlook-*-flat-database` | Multi-col (3) | phosphate_rock | Capacity, Utilization, Imports |
| `phosphate-rock-market-outlook-*-trade-matrices` | Multi-col (3) | phosphate_rock | Bilateral imports/exports |

### Phosphate Fertilizer Reports

| Filename Pattern | Layout | Product | Example Sheets |
|---|---|---|---|
| `phosphate-fertilizer-market-outlook-*-flat-database` | Prefixed (5) | wpa, dap, map, tsp | WPA Capacity, DAP Production |
| `phosphate-fertilizer-*-npk-flat-database` | Prefixed (5) | npk, np, pk | NPK Capacity, NP Exports |

**Row Format:**
```
WPA_Australia_values...
DAP_France_values...
MAP_Brazil_values...
```

### Sulphur Reports

| Filename Pattern | Layout | Product | Example Sheets |
|---|---|---|---|
| `sulphur-market-outlook-*-flat-database` | Single-col (state) | sulphur | B, B.1, B.2, C, C.1, C.2 |
| `Sulphur_Outlook_Data-*` | Multi-col (3+offset) | sulphur | Production, Demand, Exports |

**Sulphur Sheet Codes:**
- **B.x** = Consumption by use (Phosphoric Acid, Ammonium Sulphate, etc.)
- **C.x** = Production by source (Gas, Oil, Oil Sands, etc.)

### NPK Reports

| Filename Pattern | Layout | Product | Example Sheets |
|---|---|---|---|
| `phosphate-fertilizer-*-npk-flat-database` | Prefixed (5) | npk, np, pk | NPK Production, NP Imports |

---

## Layout Detection & Parsing

### Layout Types

#### 1. **Prefixed Layout** (5 columns)

Used by: Phosphate Fertilizer & NPK reports (CRU)

**Characteristic:** Product prefix embedded in col0 value

```
Row 1: [Header] PrefixCountry | [blank] | Continent | SubRegion | Country | 2020 | 2021 | ...
Row 2: WPA Australia        |         | Oceania   | Australia | Australia | 500  | 510  | ...
Row 3: DAP France           |         | Europe    | Western   | France    | 800  | 820  | ...
Row 4: MAP Argentina        |         | S. America| South     | Argentina | 200  | 210  | ...
```

**Detection:** Rows match pattern `^(WPA|DAP|MAP|TSP|...)(.+)$`

**Parsing Steps:**
1. Extract product prefix from col0 (e.g., "WPA")
2. Extract remaining columns (Continent, SubRegion, Country)
3. Match prefixed product to base product (WPA → wpa)
4. Create metrics with row_product override

#### 2. **Multi-Column Layout** (3 columns)

Used by: Ammonia/Phosphate reports (CRU/S&P)

**Characteristic:** Geographic hierarchy in columns 0-2

```
Row 1: [Header] Region/Continent | SubRegion    | Country  | 2020 | 2021 | ...
Row 2: Europe                     | Western      | France   | 1200 | 1250 | ...
Row 3: Europe                     | Eastern      | Poland   | 400  | 420  | ...
Row 4: Asia                       | East Asia    | China    | 8500 | 8800 | ...
```

**Variants:**
- **No offset**: Region in col0, SubRegion in col1, Country in col2
- **Offset=1**: Blank in col0, Region in col1, SubRegion in col2, Country in col3

**Detection:**
- Header row contains "Region" or "Continent" keyword
- Data rows have distinct values across geo columns
- Country values match referential countries

**Parsing Steps:**
1. Find header row containing "region" or "continent"
2. Detect column offset if col0 is consistently blank
3. Extract geographic hierarchy from appropriate columns
4. Normalize country via referential mapping

#### 3. **Single-Column Layout** (state machine)

Used by: Sulphur reports (CRU) with sheet codes (B, B.1, C, C.1, etc.)

**Characteristic:** Region/SubRegion/Country encoded in col0 using state machine

```
Row 1: [Years:] 2020 | 2021 | 2022 | 2023 | ...
Row 2: Europe        | (no data)
Row 3: Western Europe | (no data)
Row 4: France        | 150  | 155  | 158  | ...
Row 5: Germany       | 200  | 210  | 215  | ...
Row 6: (blank)       | (marker)
Row 7: Asia          | (no data)
Row 8: East Asia     | (no data)
Row 9: China         | 8000 | 8100 | 8200 | ...
```

**Detection:** Year columns start at col1 (not col0); col0 has text identifiers

**Parsing Steps:**
1. Identify region/country hierarchy through state machine transitions
2. When encountering indented text, classify as region/subregion/country
3. Track current region/subregion context
4. Apply context to data rows

#### 4. **Plant-Level Layout** (Company|Plant × Years)

Used by: S&P/Argus capacity-by-plant sheets

**Characteristic:** Header contains "Company" + year columns; rows are plant entities

```
Row 1: [Header] Company    | Plant Name      | Region    | 2020 | 2021 | ...
Row 2: Shell              | Condat Plant    | Europe    | 500  | 510  | ...
Row 3: Shell              | Amsterdam Plant | Europe    | 400  | 410  | ...
Row 4: CF Industries      | Donaldsonville  | N. America| 600  | 610  | ...
```

**Detection:** Header row contains "company" keyword + 3+ year columns

**Parsing Steps:**
1. Extract company and plant name
2. Build company→plant hierarchy
3. Create both company entity and plant entity
4. Link plant metrics to company parent

---

## Core Components

### Caster Class

Main processor for flat database extraction.

#### Key Methods:

**`process_data(data, document_name, sheet_name, **kwargs) → SchemaCollection`**
- Main entry point
- Auto-detects layout, headers, metadata
- Returns complete schema collection

**`_detect_layout(df) → str`**
- Identifies geographic structure
- Returns: "prefixed", "multi_col", "single_col", "plant_level", or "skip"

**`_find_header_and_years(df, layout) → (header_idx, year_cols)`**
- Locates header row and year column indices
- Scans first 15 rows for year patterns (YYYY format)

**`_extract_preamble(df, header_idx) → dict`**
- Extracts metadata from rows above header
- Returns: `{product, commodity, unit, variant, concept}`

**`_parse_data_rows(...)`**
- Main parsing loop
- Delegates to layout-specific row parsers

#### Layout-Specific Parsers:

- `_parse_prefixed_row(df, row_idx, product)` → geographic data
- `_parse_multi_col_row(df, row_idx)` → geographic data
- `_parse_single_col_row(df, row_idx, region, subregion)` → geographic data + state
- `_parse_plant_row(df, row_idx, col_map)` → plant entity + geographic data

---

## Classes & Object Design

### SchemaCollection

Container for all extracted data:

```python
@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate]      # File metadata
    metrics: List[MetricCreate]             # Geographic time-series records
    entities: List[EntityCreate]            # Plants, companies (if plant-level)
    products: List[ProductCreate]           # Commodities
    regions: List[RegionCreate]             # Geographic regions
    countries: List[CountryCreate]          # Country records
```

### DocumentCreate

File metadata:

```python
@dataclass
class DocumentCreate:
    document_name: str                      # Standardized filename
    document_path: str                      # Full file path
    source_code: str                        # "cru", "sp", "argus"
    publication_date: Optional[date]        # Publication date (detected from name)
    ingestion_date: date                    # Extraction date
    is_archived: bool                       # Archive flag
```

### MetricCreate

Individual geographic time-series record:

```python
@dataclass
class MetricCreate:
    metric_id: Optional[str]                # Unique ID
    entity_name: str                        # Geographic location (country/region)
                                            # OR plant/company name (plant-level)
    country_name: Optional[str]             # Country of record
    region_name: Optional[str]              # Region assignment
    product_name: str                       # Product (ammonia, phosphate_rock, etc.)
    metric_type: str                        # "geographical" or "plant"
    metric_name: str                        # e.g., "capacity_forecast"
    start_date_effect: Optional[date]       # Validity start
    end_date_effect: Optional[date]         # Validity end
    date_publication: Optional[date]        # Document publication date
    date_insertion: date                    # Extraction date
    document_name: str                      # Source document
    unit_of_measure: str                    # Unit (kiloton, percent, etc.)
    value: float                            # Time-series value
    sheet_name: Optional[str]               # Source sheet name
    scope: Dict[str, Any]                   # Additional metadata:
                                            # - variant (green/blue/etc.)
                                            # - forecast_release (forecast/release)
                                            # - year (year integer)
                                            # - parent_entity (plant-level)
```

### EntityCreate (Plant-Level)

Company/plant entity (only for plant-level layouts):

```python
@dataclass
class EntityCreate:
    entity_name: str                        # Plant name or company name
    entity_type: str                        # "company", "plant"
    parent_entity: Optional[str]            # Parent company (if plant)
    country_name: Optional[str]             # Entity location
    region_name: Optional[str]              # Entity region
```

### ProductCreate

Commodity product:

```python
@dataclass
class ProductCreate:
    product_name: str                       # e.g., "ammonia"
    product_category_name: str              # Category (from referential)
    description: Optional[str]              # Description
    is_active: bool                         # Activity flag
```

### RegionCreate & CountryCreate

Geographic entities with hierarchy:

```python
@dataclass
class RegionCreate:
    region_name: str                        # e.g., "Europe"
    parent_region_name: Optional[str]       # Parent region
    description: Optional[str]

@dataclass
class CountryCreate:
    country_name: str                       # e.g., "France"
    country_code: Optional[str]             # ISO code
    region_name: Optional[str]              # Region assignment
    description: Optional[str]
```

---

## Data Processing & Transformation

### Product Detection (Priority Order)

1. **Preamble Commodity** (top rows above header)
   - If "Commodity: Ammonia" found → use "ammonia"
2. **Sheet Name Prefix** (WPA Capacity, DAP Production)
   - Extract and normalize: WPA → wpa
3. **Document Name Pattern** (via regex)
   - Match: "phosphate-rock" → "phosphate_rock"
4. **Fallback** to "unknown"

### Metric Detection (Keyword Matching)

Sheet names matched against keyword patterns:

| Pattern | Metric Base |
|---|---|
| `capacity`* | capacity |
| `production`* | production |
| `consumption\|apparent demand` | apparent_consumption |
| `import` | imports |
| `export` | exports |
| `operating rate\|utilization` | operating_rate |
| `B` (sheet code) | total_sulphur_consumption |
| `C.1` (sheet code) | gas_based_sulphur_production |
| `NH3 for Steel` | ammonia_for_steel |
| `S-Production Oil` | production_oil |

### Unit Normalization

Units standardized via `unit_aliases` from referential:

```yaml
unit_aliases:
  "'000 t": "kiloton"
  "kt": "kiloton"
  "million tonnes": "million_ton"
  "%": "percent"
```

### Geographic Normalization

**Country Resolution:**
1. Exact match against referential countries
2. Try country aliases (e.g., "USA" → "United States")
3. If not found, log and skip

**Region Assignment:**
1. Use country→region mapping from referential
2. Fallback to "world" if not found
3. Skip if resolves to aggregate region ("undefined", "world", etc.)

### Publication Date Detection

Parsed from document name patterns:

| Pattern | Example →  Date |
|---|---|
| Month+Year | "March-2025" → 2025-03-01 |
| Quarter+Year | "1Q 2024" → 2024-01-01 |
| Bare year | "2024" → 2024-01-01 |

Fallback: Current date

### Variant Extraction

Product variants stored in metric scope:

```python
variant_mapping = {
    "grey_ammonia": "grey",
    "green_ammonia": "green",
    "blue_ammonia": "blue",
    "low_carbon_ammonia": "low_carbon",
    "elemental_sulphur": "elemental",
}
# Stored in scope["variant"] = detected_variant
```

---

## Design Decisions

### 1. **Unified Caster for Multiple Layouts**

Rather than separate extractors per layout, unified detection handles all:
- **Advantage**: Single maintenance point, consistent data model
- **Advantage**: Easy to extend with new layouts
- **Challenge**: More complex detection logic

### 2. **Referential-Backed Normalization**

All country/region/product mappings from `referential.yaml`:
- **Advantage**: Centralized source of truth
- **Advantage**: Changes propagate to all extractors
- **Advantage**: Consistent across data sources

### 3. **Metadata in Preamble**

Product/Unit/Variant extracted from rows above header:
- **Advantage**: More reliable product detection than sheet name alone
- **Advantage**: Captures variant information (green/blue)
- **Advantage**: Explains "Unit of Measure" when present

### 4. **Layout Auto-Detection**

No parameter needed; detected from data structure:
- **Advantage**: No user configuration required
- **Advantage**: Handles format variations
- **Challenge**: Detection can fail on unusual formats

### 5. **Variants in Scope, Not Separate Products**

Green/Blue ammonia stored as variants in metric scope:
- **Advantage**: Simpler product hierarchy
- **Advantage**: Easier to compare variants
- **Disadvantage**: Requires scope parsing for variant queries

### 6. **State Machine for Single-Column**

Sulphur reports use state machine for region/country tracking:
- **Advantage**: Handles implicit geographic hierarchy
- **Advantage**: Works with indentation patterns
- **Challenge**: Sensitive to row ordering

---

## Geographic Layouts

### Layout Comparison

| Aspect | Prefixed | Multi-col | Single-col | Plant-level |
|---|---|---|---|---|
| Geo Columns | 5 | 3 | 1 | 3+ |
| Product Source | col0 prefix | sheet/doc | doc | header |
| Header Contains | Year | Year | Year | Company + Year |
| Hierarchy | Explicit (cols) | Explicit (cols) | Implicit (state) | Explicit (cols) |
| Entity Type | Geographic | Geographic | Geographic | Plant |
| Example | WPA data | S&P Ammonia | CRU Sulphur | Argus capacity |

### Example: Multi-Column (3) with Offset

```
Row 0: [blank] | Continent | SubRegion | Country | 2020 | 2021 | 2022
Row 1: [blank] | Europe    | Western   | France  | 1200 | 1250 | 1300
Row 2: [blank] | Europe    | Eastern   | Poland  | 400  | 420  | 440
Row 3: [blank] | Asia      | East      | China   | 8500 | 8800 | 9100
```

**Offset detected:** Column 0 is blank → offset = 1
**Parsing:** Region from col1, SubRegion from col2, Country from col3

---

## Examples

### Example 1: Ammonia Capacity (Multi-col, 3 columns)

**File:** `ammonia-market-outlook-october-2024-flat-database.xlsx`
**Sheet:** "Capacity by geography"

```
Row 1: [Header] Region/Continent | SubRegion      | Country  | 2020 | 2021 | 2022
Row 2: Europe                     | Western Europe | France   | 1200 | 1250 | 1300
Row 3: Europe                     | Western Europe | Germany  | 800  | 820  | 840
Row 4: Europe                     | Eastern Europe | Poland   | 400  | 420  | 440
Row 5: Asia                       | East Asia      | China    | 8500 | 8800 | 9100
```

**Output Metrics:**
```
- France 2020: capacity, value=1200, unit=kiloton
- France 2021: capacity, value=1250, unit=kiloton
- Germany 2020: capacity, value=800, unit=kiloton
- China 2022: capacity, value=9100, unit=kiloton
```

### Example 2: Phosphate Fertilizer (Prefixed, 5 columns)

**File:** `phosphate-fertilizer-market-outlook-september-2024-flat-database.xlsx`
**Sheet:** "WPA Capacity"

```
Row 0: [Preamble] Commodity: Phosphate (WPA)
Row 1: WPA Prefecture | [blank] | Continent | SubRegion | Country | 2020 | 2021
Row 2: WAA Australia  |         | Oceania   | Australia | Australia | 500  | 520
Row 3: WPA Brazil     |         | S. America| South     | Brazil    | 300  | 310
Row 4: WPA Morocco    |         | Africa    | North     | Morocco   | 400  | 420
```

**Product Detection:** "WPA" prefix → product="wpa"
**Parsing:**
- Extract "WPA" prefix
- Extract remainder "Australia" → country
- Map to geographic hierarchy

**Output Metrics:**
```
- Australia: product=wpa, metric=capacity, value=500 (2020)
- Brazil: product=wpa, metric=capacity, value=300 (2020)
- Morocco: product=wpa, metric=capacity, value=400 (2020)
```

### Example 3: Sulphur (Single-col with codes)

**File:** `sulphur-market-outlook-march-2025-flat-database.xlsx`
**Sheet:** "B"

```
Row 0: [Preamble] Concept: Total Consumption
Row 1: [Years] 2020 | 2021 | 2022 | 2023
Row 2: Europe |
Row 3: France | 150 | 155 | 158 | 160
Row 4: Germany| 200 | 210 | 215 | 220
Row 5: [blank]|
Row 6: Asia |
Row 7: China | 8000 | 8100 | 8200 | 8300
```

**Sheet code "B"** → metric = "total_sulphur_consumption"
**State machine tracks:**
- "Europe" marker → set current_region = "Europe"
- "France" data row → create metric (country=France, region=Europe)
- "Asia" marker → set current_region = "Asia"

**Output:**
```
- France: consumption, value=150 (2020), region=Europe
- Germany: consumption, value=200 (2020), region=Europe
- China: consumption, value=8000 (2020), region=Asia
```

### Example 4: Plant-Level (S&P Capacity by Plant)

**File:** `argus-ammonia-analytics-november-2024.xlsx`
**Sheet:** "Capacity by Plant"

```
Row 1: [Header] Company      | Plant Name       | Region    | 2020 | 2021 | 2022
Row 2: Shell                 | Condat Plant     | Europe    | 500  | 510  | 520
Row 3: Shell                 | Amsterdam Plant  | Europe    | 400  | 410  | 420
Row 4: CF Industries         | Donaldsonville   | N. America| 600  | 610  | 620
```

**Entities Created:**
- Shell (company)
  - Condat Plant (plant, parent=Shell)
    - Metrics: capacity=500, 510, 520 (2020-2022)
  - Amsterdam Plant (plant, parent=Shell)
    - Metrics: capacity=400, 410, 420 (2020-2022)
- CF Industries (company)
  - Donaldsonville (plant, parent=CF Industries)
    - Metrics: capacity=600, 610, 620 (2020-2022)

---

## Troubleshooting

### Common Issues & Solutions

#### **Issue 1: Layout Not Detected**

**Symptom**: `Finished sheet: 0 metrics created`

**Possible Causes:**
- Geographic data structure doesn't match expected patterns
- Header row not found (no year columns detected)
- Empty DataFrame

**Solution:**
1. Verify file has year columns (YYYY format)
2. Check first 15 rows for header markers:
   - Multi-col: "Region" or "Continent" keyword
   - Plant-level: "Company" keyword
   - Single-col: Years in row 1, not column 1
3. Review logs for layout detection attempts

---

#### **Issue 2: Country Not Recognized**

**Symptom**: Metrics not created: `Skip if country resolves to non-country`

**Possible Causes:**
- Country name not in referential
- Typo in country name
- Row is aggregate/total row

**Solution:**
```yaml
# Update referential.yaml
country:
  - "France"
  - "Germany"
  - "Your_New_Country"

# Or add alias
country_aliases:
  "old_name": "france"
```

---

#### **Issue 3: Product Not Detected**

**Symptom**: Product="unknown" in metrics

**Possible Causes:**
- Document name doesn't match patterns
- Sheet name doesn't start with product prefix (WPA, DAP, etc.)
- Preamble commodity not recognized

**Solution:**
1. Add document name to `_DOC_PRODUCT_PATTERNS` (if new document type)
2. Verify preamble format: ``Commodity: Ammonia`` or similar
3. Check sheet name starts with product: "WPA Capacity", "NPK Production"

---

#### **Issue 4: Unit Not Normalized**

**Symptom**: unit_of_measure contains raw text like "'000 tonnes"

**Possible Causes:**
- Unit not in `unit_aliases`
- Preamble unit parsing failed
- Unit extraction skipped

**Solution:**
```yaml
# Update referential.yaml
unit_aliases:
  "'000 t": "kiloton"
  "'000 tonnes": "kiloton"
  "millions": "million_ton"
```

---

#### **Issue 5: Wrong Metric Detected**

**Symptom**: Sheet "Capacity - Total" creates metric_name="capacity_total" instead of "capacity"

**Possible Causes:**
- Sheet name matches non-base pattern
- Keyword matching too specific

**Solution:**
Order matters in `_METRIC_KEYWORDS`. More specific patterns should come first:
```python
# WRONG order:
(re.compile(r"capacity", re.I), "capacity"),           # catches "Capacity - Total"
(re.compile(r"capacity\s*-\s*total", re.I), "capacity"),

# CORRECT order:
(re.compile(r"capacity\s*-\s*total", re.I), "capacity"),
(re.compile(r"capacity", re.I), "capacity"),
```

---

#### **Issue 6: Offset Detection Failed**

**Symptom**: Multi-col (3 offset) data parsed as multi-col (3 no-offset): regions/countries misaligned

**Possible Causes:**
- Column 0 not consistently blank (has some data)
- Offset detection looks at data rows, not header

**Solution:**
1. Manually verify if layout has blank col0
2. Check that "region" keyword appears in correct column
3. Monitor logs for offset detection: `geo_offset=1` should appear

---

#### **Issue 7: Publication Date Not Found**

**Symptom**: publication_date is current date instead of file date

**Possible Causes:**
- Document name doesn't match date patterns
- No date in TOC

**Solution:**
Add date to filename in one of these formats:
- Month-Year: `october-2024`, `november_2024`
- Quarter-Year: `1Q 2024`, `2024 Q3`
- Bare year: `2024` (uses January 1)

---

### Debug Flags

Enable detailed logging:

```python
import logging

logger = logging.getLogger("cru_flat_database_caster")
logger.setLevel(logging.DEBUG)

# Will output:
# [Layout detection] Checking for prefixed pattern...
# [Product detection] From doc: "ammonia"
# [Header found] Row 5, year columns: [3, 4, 5, ...]
# [Parsing] France 2020: 1200
```

---

### Manual Testing

```python
from src.excel_ingestion.extractors.implementation.cru_flat_database_caster import Caster
import pandas as pd

# Load file
df = pd.read_excel("ammonia-market-outlook.xlsx", sheet_name="Capacity by geography", header=None)

# Create caster
caster = Caster()

# Process
result = caster.process_data(
    data=df,
    document_name="ammonia-market-outlook-october-2024.xlsx",
    sheet_name="Capacity by geography"
)

# Check output
print(f"Metrics: {len(result.metrics)}")
print(f"Countries: {len(result.countries)}")
print(f"Products: {result.products[0].product_name if result.products else 'None'}")
```

---

## Best Practices

### For Users

1. **Naming conventions**: Use standard document names (includes year/month)
2. **Geographic hierarchy**: Maintain consistent region/country structure
3. **Year columns**: Use YYYY format (2024, not "2024.0" or "24")
4. **Headers**: Include header row with year values
5. **Test with preamble**: If possible, include Commodity/Unit/Concept rows

### For Developers

1. **Update referential first**: Add new countries before processing
2. **Test all 4 layouts**: Create test files for each layout type
3. **Log extensively**: Help diagnose parsing issues
4. **Handle edge cases**: Blank rows, total rows, special characters
5. **Monitor detect_layout**: Ensure correct layout identification

### For Maintainers

1. **Monitor product patterns**: Extend as new commodities appear
2. **Review sheet metrics**: Add new metric keywords to keyword list
3. **Track date formats**: Extend date parsing for new patterns
4. **Profile performance**: Optimize for large files (10k+ rows)
5. **Keep referential current**: Regular updates for new countries

---

## Related Documentation

- [Price Extractors README](README_PRICE_EXTRACTORS.md)
- [Trade Extractors README](README_TRADE_EXTRACTORS.md)
- [Vessel Trackers README](README_VESSEL_TRACKERS.md)
- [Green/Blue Ammonia README](README_GREEN_BLUE_AMMONIA_PROJECTS.md)
- [Main Data Ingestion README](../Data_Acquisition_All_README.md)
- Referential Configuration: `config/referential.yaml`
- Extractor Configuration: `sheets_extractors.yaml`

---

## Version History

- **v1.0** (2024-Q4): Initial unified flat database caster documentation
  - Documented 4 geographic layouts
  - Added product/metric detection details
  - Provided comprehensive troubleshooting

---

## Support & Feedback

For issues, questions, or feature requests:
- Check troubleshooting section above
- Review debug logs for layout/detection issues
- Test with sample files from each data provider
- Contact data engineering team for schema extensions
