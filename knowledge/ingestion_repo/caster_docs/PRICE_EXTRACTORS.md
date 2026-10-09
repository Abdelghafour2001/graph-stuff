# Price Sheet Extractors Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture & Data Flow](#architecture--data-flow)
3. [Extractors Logic](#extractors-logic)
4. [Functions Explanation](#functions-explanation)
5. [Classes Explanation](#classes-explanation)
6. [Processing Logic](#processing-logic)
7. [Design Decisions](#design-decisions)
8. [How to Extend](#how-to-extend)
9. [Examples](#examples)

---

## Overview

### Purpose

The **Price Sheet Extractors** system is a template-driven data ingestion pipeline designed to extract, normalize, and transform price data from Excel files into structured database schemas. The system handles various fertilizer, commodity, and chemical price data sources including Argus, CRU, and other market data providers.

### What is "Price Sheet Extraction"?

Price sheet extraction refers to the automated process of:
- **Reading** multi-header Excel templates with complex layouts (product columns, entity rows, multiple data periods)
- **Parsing** column headers to extract product, entity, metric type, and pricing dimension information
- **Normalizing** product names, units, entities, regions, and countries against a centralized referential YAML configuration
- **Classifying** entities (companies, countries, regions, cities, vessels) from user-provided text
- **Structuring** the data into first-normal-form database records (Metrics, Products, Entities, Regions, Countries)

### Overall Workflow

```
Excel File (Raw)
       ↓
    [Sheet Detection] → Match sheet name against templates in sheets_extractors.yaml
       ↓
 [Load Extractor] → Dynamically load the appropriate Caster from implementation/
       ↓
[Parse Headers] → Extract product names, metrics, entities from multi-row headers
       ↓
[Process Rows] → For each data row:
    - Parse date column
    - For each metric column:
        - Extract grade, physical form, unit, metric type
        - Classify entity (country, region, city, etc.)
        - Normalize product name against referential
        - Create Metric, Product, Entity, Region, Country records
       ↓
[Database Ready] → SchemaCollection containing:
    - Document metadata
    - List of Metrics (price points)
    - List of Products (with categories)
    - List of Entities (companies, trading hubs)
    - List of Regions
    - List of Countries (with region assignments)
       ↓
    [Repository] → Persisted to database
```

---

## Architecture & Data Flow

### Component Hierarchy

```
extractors/
├── loader.py                          # Sheet matcher & extractor resolver
├── utils.py                           # Dynamic loading, standardization utilities
├── sheets_extractors.yaml             # Configuration: sheet name → extractor mapping
└── implementation/
    ├── prices.py                      # Base/generic price extractor
    ├── ammonia_prices.py              # Ammonia-specific price extractor
    ├── potash_prices.py               # Potash-specific price extractor
    ├── urea_prices.py                 # Urea-specific price extractor
    ├── npk_prices.py                  # NPK blend price extractor
    ├── phosrock_prices.py             # Phosphate rock price extractor
    ├── weekly_prices.py               # Weekly fertilizer prices extractor
    ├── ammonia_sulphure_prices_flatdatabase.py
    ├── argus_ammo_phos_prices.py
    ├── praw_yearly_quarterly_prices.py
    ├── ann_quar_prices.py
    ├── monthly_phos_forecast_prices.py
    ├── ammended_prices.py
    ├── sulphure_outlook_data_prices.py
    ├── st_prices_ammonia_data.py
    └── ... (other specialized extractors)
```

### Data Classification Hierarchy

```
RawExcelData ──[Caster]──> SchemaCollection
                            ├── Document (1 per file)
                            │   └── publication_date, effective_start/end_date
                            ├── Metrics[] (multiple per file)
                            │   ├── product_name (base)
                            │   ├── entity_name
                            │   ├── price value
                            │   ├── unit of measure
                            │   └── scope (contains variant info: physical_form, grade)
                            ├── Products[] (unique base products)
                            ├── Entities[] (unique entity names)
                            ├── Regions[] (unique regions)
                            └── Countries[] (unique countries)
```

### Key Flow Points

1. **Sheet Name Matching** (`loader.py::resolve_extractor`)
   - Uses exact or regex patterns defined in `sheets_extractors.yaml`
   - Returns `MatchResult` with extractor implementation and parameters

2. **Dynamic Extractor Loading** (`utils.py::get_generated_caster`)
   - Dynamically imports the Python module specified in `MatchResult.extractor_implementation`
   - Instantiates the `Caster` class from that module

3. **Data Extraction** (`Caster::process_data`)
   - Main entry point for extraction
   - Converts raw numpy array to DataFrame
   - Iterates through rows, parsing dates and metric values
   - Returns populated `SchemaCollection`

4. **Entity Extraction** (`Caster::_process_row`)
   - Parses each column header to extract metric metadata
   - Classifies entities using referential data
   - Creates region/country relationships
   - Generates Metric records with scope information

5. **Normalization** (throughout)
   - Product names: standardized via `CleanerService` + `PRODUCT_ALIASES` from referential
   - Units: matched against `UNITS` list with `UNIT_ALIASES` fallback
   - Entities: classified as company, country, region, city, vessel, or "other"

---

## Extractors Logic

### Price Extractor Variants

All price extractors follow a **consistent template** but handle different input formats and commodity types.

#### 1. **prices.py** (Generic/Base Price Extractor)
   - **Purpose**: Generic implementation for mixed commodity price data
   - **Template Structure**:
     - Row 0-3: Headers (products, metrics, units, empty)
     - Row 4+: Data rows with year/date in column 0, prices in columns 1+
   - **Input Format**: Excel XLSX with multi-header layout
   - **Commodity Focus**: Multi-commodity (ammonia, phosphate, potash, etc.)
   - **Parsing Strategy**:
     - Combines multi-row headers into column names
     - Extracts product name, entity, metric type, price type from column header
     - Special handling for price units like "$/t (metric)"
     - Extracts and validates grade/BPL info
     - Extracts physical form (granular, prills, liquid, etc.)

#### 2. **ammonia_prices.py** (Ammonia Specialist)
   - **Purpose**: Extract ammonia price data from Argus reports
   - **Template Structure**: Similar multi-header but specialized for ammonia entities
   - **Input Format**: Excel with ammonia-specific columns
   - **Commodity Focus**: Ammonia only
   - **Key Features**:
     - Recognizes ammonia trading hubs (e.g., "Baltic", "Black Sea", "US Gulf")
     - Handles various ammonia price types (FOB, CFR, truck, pipeline)
     - Supports min/max price extraction for volatility analysis
     - Canonical unit handling for ammonia (e.g., "$/t" → "usd_per_ton_metric")

#### 3. **potash_prices.py** (Potash Specialist)
   - **Purpose**: Extract potash (MOP, SOP) prices from market reports
   - **Template Structure**: Multi-header with potash-specific entity columns
   - **Input Format**: Excel with potash market data
   - **Commodity Focus**: Potash (MOP), SOP, KCl
   - **Key Features**:
     - Potash-specific entities (mining regions, export hubs)
     - Handles "FOB Nominal Contract", "CFR", "CIF" pricing types
     - Supports various potash grades (standard, enhanced, etc.)

#### 4. **urea_prices.py** (Urea Specialist)
   - **Purpose**: Extract urea fertilizer prices
   - **Template Structure**: Multi-header similar to ammonia/potash
   - **Input Format**: Excel with urea market data
   - **Commodity Focus**: Urea (various grades)
   - **Key Features**:
     - Urea-specific delivery modes (FOB, CFR, CIF)
     - Import parity pricing
     - Regional price spreads

#### 5. **npk_prices.py** (NPK Blend Specialist)
   - **Purpose**: Extract NPK blend fertilizer prices
   - **Template Structure**: Multi-header with complex NPK grading
   - **Input Format**: Excel with NPK forecast data
   - **Commodity Focus**: NPK blends (e.g., 15:15:15, 16:20:0, etc.)
   - **Key Features**:
     - Complex grade parsing: N:P:K or N:P:K:S format
     - Supports multiple grades per metric column
     - Regional blend variations

#### 6. **phosrock_prices.py** (Phosphate Rock Specialist)
   - **Purpose**: Extract phosphate rock (PRAW) prices
   - **Template Structure**: Multi-header with BPL grade specification
   - **Input Format**: Excel with phosphate rock data
   - **Commodity Focus**: Phosphate rock (PRAW)
   - **Key Features**:
     - BPL (Bone Phosphate of Lime) grade extraction (e.g., "68-70% BPL")
     - Trend annotations handling
     - Annual/quarterly/monthly historical prices

#### 7. **weekly_prices.py** (Fertilizer Weekly Historical Prices)
   - **Purpose**: Extract historical weekly fertilizer price averages
   - **Template Structure**: 
     - Fixed first 4 columns: Year, Quarter, Month, Price Date
     - Variable metric columns starting at column 5
   - **Input Format**: CSV/Excel with "All_W", "All_M", "All_Q", "All_A" sheets
   - **Commodity Focus**: Multi-commodity (DAP, MAP, MOP, TSP, etc.)
   - **Parsing Strategy**:
     - Handles multiple frequency variations in same file
     - Extracts publication date from filename (DD-MM-YYYY format)
     - Supports date parsing in YYYY, YYYYMnn, and quarter formats

#### 8. **ammonia_sulphure_prices_flatdatabase.py** (Multi-Commodity Flat Database)
   - **Purpose**: Extract ammonia/sulfur/phosphate rock prices from flat database export
   - **Template Structure**: Complex multi-header with min/max/average columns
   - **Input Format**: Excel flat database export
   - **Commodity Focus**: Ammonia, Sulfur, Phosphate Rock
   - **Key Features**:
     - Min/max/average price extraction per period
     - Hub-based pricing (FOB, CFR)
     - Currency and index handling

#### 9. **argus_ammo_phos_prices.py** (Argus Min/Max Prices)
   - **Purpose**: Extract ammonia and phosphate minimum and maximum prices
   - **Template Structure**: Multi-header with explicit min/max columns
   - **Input Format**: Excel with min/max price data
   - **Commodity Focus**: Ammonia, Phosphate, Phosphate Rock
   - **Key Features**:
     - Separate min and max metric extraction
     - Volatility analysis support
     - Trading hub price premiums/discounts

#### 10. **praw_yearly_quarterly_prices.py** (Phosphate Rock Outlook Yearly/Quarterly)
   - **Purpose**: Extract annual and quarterly phosphate rock (PRAW) price forecasts
   - **Template Structure**: Multi-header with forecast year columns (e.g., 2024, 2025, 2026)
   - **Input Format**: Excel with annual/quarterly forecasts (header_rows: 11)
   - **Commodity Focus**: Phosphate Rock (PRAW)
   - **Key Features**:
     - Year-over-year price forecasts
     - Quarterly forecast breakdown within annual periods
     - Multiple forecast scenarios (base, bull, bear)
     - BPL grade specification handling

#### 11. **ann_quar_prices.py** (Ammonia Market Outlook Annual/Quarterly Prices)
   - **Purpose**: Extract annual and quarterly ammonia price forecasts from market outlook reports
   - **Template Structure**: Multi-header with year columns and quarterly sub-columns
   - **Input Format**: Excel with annual/quarterly ammonia forecast sheets
   - **Commodity Focus**: Ammonia forecasts
   - **Key Features**:
     - Annual price averages
     - Quarterly forecasts within each year
     - Hub-based pricing (FOB origins, CFR destinations)
     - Long-term price trend analysis

#### 12. **monthly_phos_forecast_prices.py** (Monthly Phosphate Forecast Prices)
   - **Purpose**: Extract monthly phosphate price forecasts and trends
   - **Template Structure**: Month-indexed rows with product/metric columns
   - **Input Format**: Excel with "Prices" sheet (file_regex: "forecast")
   - **Commodity Focus**: Phosphate products (DAP, MAP, TSP, PRAW)
   - **Key Features**:
     - Monthly granularity (vs. annual/quarterly)
     - Trend annotations (↑, ↓, →)
     - Multiple market origins (Brazil, Morocco, China)
     - Forecast vs. realized price comparison

#### 13. **ammended_prices.py** (Specialty Phosphate Amended Prices)
   - **Purpose**: Extract amended/adjusted specialty phosphate product prices
   - **Template Structure**: Specialty phosphate product rows with market columns
   - **Input Format**: Excel specialty phosphates file (file_regex: "specialty")
   - **Commodity Focus**: Specialty phosphates (PWA, tMAP, DCP, MCP, STPP, P4, SPA, LFP)
   - **Key Features**:
     - Specification pricing (product amendments, blends)
     - Specialty grade premiums
     - Niche market pricing (industrial applications)
     - Multi-region sourcing

#### 14. **sulphure_outlook_data_prices.py** (Sulphur Outlook Price Forecasts)
   - **Purpose**: Extract sulphur price forecasts from market outlook reports
   - **Template Structure**: Annual/quarterly forecast layout specific to sulphur
   - **Input Format**: Excel with sulphur market outlook sheets
   - **Commodity Focus**: Sulphur (elemental form)
   - **Key Features**:
     - Oil refining-linked pricing
     - Sulfuric acid offtake pricing
     - Regional price differentials (Gulf, China, etc.)
     - Production cost correlation

#### 15. **st_prices_ammonia_data.py** (Short-Term Ammonia Price Forecasts)
   - **Purpose**: Extract short-term (3-6 month) ammonia price forecasts
   - **Template Structure**: Near-term forecast with weekly/monthly granularity
   - **Input Format**: Excel with "ST Price Fcst" sheet (ammonia outlook data files)
   - **Commodity Focus**: Ammonia short-term pricing
   - **Key Features**:
     - High-frequency updates (weekly/monthly forecasts)
     - Near-term supply/demand signals
     - Trading halt and contract renegotiation triggers
     - Immediate market direction indicators

### Common Parsing Strategy Across All Extractors

```
Column Header: "DAP Brazil FOB Nominal $/t (metric)"
                    ↓
1. Extract Grade: None (unless explicit grade like "68-70% BPL")
2. Extract Physical Form: None (unless "granular", "prills", etc.)
3. Parse Remaining: "DAP Brazil FOB Nominal $/t"
   ├── Product: "DAP"
   ├── Entity: "Brazil"
   ├── Metric Type: "FOB Nominal"
   └── Unit: "usd_per_ton_metric" (from "$/t (metric)")
   ↓
4. Classify Entity:
   - Check if "Brazil" in COUNTRIES → entity_type="country", region="Americas"
   - Check if in REGIONS → entity_type="region"
   - Check if in CITIES → entity_type="city"
   - Check if in VESSELS → entity_type="vessel"
   - Else → entity_type="other"
   ↓
5. Normalize Product:
   - "DAP" → _canon_key → "dap" → PRODUCT_ALIASES → "diammonium_phosphate"
   ↓
6. Build Metric Scope:
   scope = {
     "product_name": "diammonium_phosphate",
     "entity_name": "Brazil",
     "price_type": "fob_nominal",
     "delivery_mode": None,
     "unit": "usd_per_ton_metric"
   }
```

### Output Structure (SchemaCollection)

Each extractor produces a `SchemaCollection` dataclass containing:

```python
@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate]          # Metadata about source file
    metrics: List[MetricCreate]                # Individual price data points
    entities: List[EntityCreate]               # Companies, trading hubs
    products: List[ProductCreate]              # Base products (not variants)
    regions: List[RegionCreate]                # Geographic regions
    countries: List[CountryCreate]             # Countries with region mapping
```

---

## Functions Explanation

### Core Normalization Functions

#### `_canon_key(raw: Any) -> str`
**Purpose**: Create a canonical key for alias lookups
**Inputs**: Any raw value (string, number, etc.)
**Logic**:
```python
1. Convert to string if needed
2. Standardize case and separators
3. Replace non-word characters with underscores
4. Collapse multiple underscores
5. Strip leading/trailing underscores
```
**Output**: Normalized string key (e.g., "FOB Nominal" → "fob_nominal")
**Usage**: Used for product aliases, unit aliases, and entity lookups

#### `canonicalize_product(raw: Any) -> str`
**Purpose**: Standardize product name using referential aliases
**Inputs**: Raw product name from Excel
**Logic**:
```python
1. Apply _canon_key normalization
2. Look up in PRODUCT_ALIASES dict
3. Return standardized product name via CleanerService
4. Handle special cases (empty, null values)
```
**Output**: Standardized product name (e.g., "diammonium_phosphate")
**Example**: "DAP Brazil" → "dap_brazil" → "diammonium_phosphate"

#### `canonicalize_unit(raw: Any) -> str`
**Purpose**: Normalize units using referential configuration
**Inputs**: Raw unit string (e.g., "$/t (metric)")
**Logic**:
```python
1. Apply _canon_key to raw unit
2. Special pattern matching for price units
   - "$/t (metric)" → "usd_per_ton_metric"
   - "2024$/t (metric)" → "usd_per_ton_metric"
3. Apply UNIT_ALIASES lookup
4. Validate against UNITS whitelist
5. Fall back to default unit ("kiloton" or "usd_per_ton") if not found
6. Log warning for unmapped units
```
**Output**: Validated unit name (e.g., "usd_per_ton_metric")
**Error Handling**: Graceful fallback to safe defaults with logging

#### `extract_date_publication_from_doc_name(doc_name: str) -> Optional[date]`
**Purpose**: Extract publication date from document filename
**Inputs**: Document name string (e.g., "fertilizer-week-historical-prices-18-12-2025.xlsx")
**Supported Formats**:
- DD-MM-YYYY: "18-12-2025" → date(2025, 12, 18)
- YYYY-MM-DD: "2025-12-18" → date(2025, 12, 18)
- YYYYMnn: "2025M12" → date(2025, 12, 1)
- Method name: "august-2025" → date(2025, 8, 1)
- Quarter: "Q1 2024" or "1Q 2024" → date(2024, 1, 1)
**Output**: Python date object or None if parsing fails
**Usage**: Determines document publication_date in records

#### `extract_grade_and_clean(text: str) -> Tuple[Optional[str], str]`
**Purpose**: Extract product grade from text, clean text of grade markers
**Inputs**: Column header text
**Logic**:
```
1. Search for BPL patterns: "68-70pc BPL", "69% BPL"
2. Extract and normalize grade display
3. Remove grade from original text
4. Clean up extra spaces
```
**Output**: Tuple of (grade_string, cleaned_text)
**Example**: "DAP 68-70% BPL CFR" → ("68-70%", "DAP CFR")

#### `extract_physical_form_and_clean(text: str) -> Tuple[Optional[str], str]`
**Purpose**: Extract physical form from text, clean text
**Inputs**: Column header text
**Physical Forms**: granular, prills, solution, liquid, powder, standard
**Logic**:
```
1. Search for physical form keyword (ordered: longest first)
2. Extract normalized form name
3. Remove form from text
4. Return cleaned text
```
**Output**: Tuple of (physical_form, cleaned_text)
**Example**: "DAP granular Brazil FOB" → ("granular", "DAP Brazil FOB")

#### `extract_product_grade_from_colname(name: str) -> Optional[ProductGrade]`
**Purpose**: Parse complex grades (NPK, BPL, percentages) from column names
**Inputs**: Column name with grade info
**Supported Grade Formats**:
- **P2O5/P205 percentages**: "30-32% P2O5" → phosphate=31.0
- **Generic percentages**: "46%" → percentage=46.0
- **4-number NPKS**: "13:13:20:5" → nitrogen=13, phosphate=13, potash=20, sulfur=5
- **3-number NPK/NPS**: "15:15:15" or "15:15:15S" → nitrogen=15, phosphate=15, potash=15/sulfur=15
- **2-number NP**: "21:12" → nitrogen=21, phosphate=12
**Output**: `ProductGrade` dataclass with display_value and numeric components
**Usage**: Stored in Metric scope for variant tracking

#### `classify_entity(name: str) -> Dict[str, Any]`
**Purpose**: Classify entity type and map to geographic dimensions
**Inputs**: Entity name from column header
**Classification Logic**:
```
1. Check COUNTRIES set → type="country", apply COUNTRY_REGION_MAPPING
2. Check REGIONS set → type="region"
3. Check CITIES set → type="city", apply CITY_MAPPING_COUNTRY
4. Check VESSELS set → type="vessel"
5. Check LEGACY_COUNTRIES → type="legacy_country"
6. Default → type="other"
```
**Output**: Dictionary with:
```python
{
  "entity_type": "country" | "region" | "city" | "vessel" | "legacy_country" | "other",
  "canonical_name": standardized_name,
  "country_name": derived_country,
  "region_name": derived_region
}
```
**Example**: "Brazil" → {"entity_type": "country", "country_name": "Brazil", "region_name": "Americas"}

#### `clean_date(date_str: str) -> Optional[date]`
**Purpose**: Parse various date formats from Excel cells
**Inputs**: Date cell value as string
**Supported Formats**:
- "YYYY": "2024" → date(2024, 1, 1)
- "YYYYQQ": "2024Q1" → date(2024, 1, 1)
- Standard Excel date values
**Output**: Python date object or None
**Error Handling**: Logs warnings for unparseable dates

#### `normalize_value(x: Any) -> str`
**Purpose**: Standardize metric cell values for consistency
**Inputs**: Raw cell value (number, string, NaN, etc.)
**Logic**:
```
1. If NaN or None → "NA"
2. If in {"nm", "na", "n/a", "null", "none", "nan", ""} → "NA"
3. Else → strip and return string
```
**Output**: Normalized string ("NA" or numeric string)
**Usage**: Ensures consistent handling of missing/invalid price values

---

## Classes Explanation

### ColumnParser (Static Utility Class)

**Role**: Parses column header strings into structured metric metadata

**Key Attributes** (class constants):
```python
PERIOD_TOKENS = {"daily", "weekly", "monthly", "quarterly", "yearly", ...}
GRADE_MARKER_TOKENS = {"bpl"}
NON_ENTITY_TRAIT_TOKENS = {"barge", "railcar", "truck", "pipeline"}
```

**Key Methods**:

#### `colname_to_metric_scope(text: str) -> Optional[Dict[str, Any]]`
**Purpose**: Parse column header into metric scope metadata
**Input**: Column header like "DAP Brazil FOB Nominal $/t (metric)"
**Processing**:
1. Skip if contains index/deflator keywords
2. Extract price unit
3. Extract product name (first recognized product token)
4. Extract entity name (remaining non-temporal tokens)
5. Extract price type from special keywords (FOB, CFR, CIF, etc.)
6. Build scope dictionary
**Output**: Dictionary with keys:
```python
{
  "product_name": "dap",
  "entity_name": "Brazil",
  "price_type": "fob_nominal",
  "delivery_mode": None,
  "unit": "usd_per_ton_metric"
}
```
**Returns**: None if column should be skipped (index, indexes, deflators, etc.)

### SchemaCollection (Data Transfer Object)

**Purpose**: Container for all extracted database-ready schemas from a single document

**Structure**:
```python
@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate] = None
    metrics: List[MetricCreate] = field(default_factory=list)
    entities: List[EntityCreate] = field(default_factory=list)
    products: List[ProductCreate] = field(default_factory=list)
    regions: List[RegionCreate] = field(default_factory=list)
    countries: List[CountryCreate] = field(default_factory=list)
```

**Responsibilities**:
- Holds one DocumentCreate (metadata about the source file)
- Accumulates Metric records as rows are processed
- Tracks unique Entities, Products, Regions, Countries to avoid duplicates
- Serves as return value from `Caster.process_data()`

**Usage Pattern**:
```python
caster = Caster()
schema_collection = caster.process_data(raw_data, doc_name)
repo.save(schema_collection)  # Repository persists to database
```

### Caster (Main Extraction Engine)

**Role**: Orchestrates the entire extraction workflow for a single document

**Initialization**:
```python
def __init__(self):
    self.cleaner = CleanerService()         # For text normalization
    self.schema_collection = None            # Populated during extraction
    self.reset_state()                       # Clear tracking counters
```

**State Variables** (reset per document):
```python
self.errors: List[str]                      # Error messages during processing
self.warnings: List[str]                    # Warning messages
self.handled_rows: int                      # Total rows processed
self.successful_rows: int                   # Successfully processed rows
self.existing_entities: Dict                # Deduplication cache: entity_name → EntityCreate
self.existing_products: Dict                # Deduplication cache: product_name → ProductCreate
self.existing_regions: Dict                 # Deduplication cache: region_name → RegionCreate
self.existing_countries: Dict               # Deduplication cache: country_name → CountryCreate
```

**Key Methods**:

#### `raw_data_to_df(data: np.ndarray) -> pd.DataFrame`
**Purpose**: Convert raw numpy array to structured DataFrame with proper headers
**Logic**:
1. Auto-detect header start row (row 4 or 5 in Excel)
2. Auto-detect data start row (row 9 or 11 in Excel)
3. Extract header rows and combine multi-row headers
4. Force first column name to "Product:"
5. Build DataFrame from data rows
6. Remove duplicate columns
**Output**: Pandas DataFrame with combined headers and clean data

#### `process_data(data: np.ndarray, document_name: str, **kwargs) -> SchemaCollection`
**Purpose**: Main entry point for extraction
**Workflow**:
1. Initialize schema collection
2. Create DataFrame from raw data
3. Extract date column and build parsed_dates list
4. Create DocumentCreate with date ranges
5. Iterate through data rows, calling `_process_row()` for each
6. Collect statistics (handled_rows, successful_rows, errors)
7. Return populated SchemaCollection
**Output**: SchemaCollection ready for persistence

#### `_process_row(row: pd.Series, document_name: str) -> None`
**Purpose**: Extract metrics, entities, products from a single data row
**Detailed Process**:
```
1. Parse price date from first column
2. For each metric column (skip first column):
   a. Extract value and normalize
   b. Skip NA/missing values
   c. Extract grade and physical form from column name
   d. Parse column header: product, entity, price_type, unit
   e. Classify entity: country? region? city? other?
   f. Normalize product name using referential
   g. Create/deduplicate: RegionCreate, CountryCreate, EntityCreate, ProductCreate
   h. Create MetricCreate with all scope information
3. Append all created records to schema_collection
```
**Metrics Generated**: One MetricCreate per (product, entity, metric_type) combination per row

### SheetsExtractorLoader (Configuration Manager)

**Role**: Loads YAML configuration and resolves which extractor to use for a sheet

**Location**: `loader.py`

**Key Methods**:

#### `resolve_extractor(sheet_name: str, template_name: Optional[str]) -> Optional[MatchResult]`
**Purpose**: Find the appropriate extractor for a given sheet name
**Process**:
1. Load extractors configuration from YAML
2. First pass: Try exact name matches (high priority)
3. Second pass: Try regex pattern matches
4. Return MatchResult or None
**Output**: MatchResult with:
```python
{
  "extractor_name": "argus_ammonia_prices",
  "data_provider": "argus",
  "extractor_implementation": "ammonia_prices.py",
  "params": {"frequency": "monthly"},
  "match_groups": ()
}
```

---

## Processing Logic

### Price Data Transformation Pipeline

```
Raw Excel Cell → [Normalize] → [Classify] → [Validate] → [Database Schema]
    ↓               ↓             ↓            ↓             ↓
  "$445"      "445.0"      product="DAP"  unit="usd_per_ton"  Metric{
  "DAP"   standardize   entity="Brazil"  date=2025-01-15        ...
  Brazil   CleanerSvc   price_type=FOB   in_referential=✓     }
          aliases       region="Americas" scope.completes
```

### Step 1: Value Normalization

**Numeric Price Values**:
- Input: "$445.50", "445.50 USD/MT", " 445 ", NaN
- Process: Extract float, strip currency symbols, handle missing values
- Output: "445.50" (as string in Metric.value)

**Date Values**:
- Input: "2025", "2025Q1", "01-01-2025", etc.
- Process: Parse using `parse_date()` or standard Excel date handling
- Output: Python date object

**Product Names**:
- Input: "DAP", "Diammonium Phosphate", "dap", "D.A.P"
- Process: 
  1. Standardize case and separators
  2. Look up in PRODUCT_ALIASES (from referential.yaml)
  3. Apply CleanerService standardization
- Output: "diammonium_phosphate" (canonical form)

**Unit Values**:
- Input: "$/t (metric)", "USD/MT", "$/ton", "t"
- Process:
  1. Standardize case and separators
  2. Detect common patterns ($/t (metric) → usd_per_ton_metric)
  3. Look up in UNIT_ALIASES
  4. Validate against UNITS whitelist
  5. Fall back to safe default if not found
- Output: "usd_per_ton_metric" (validated)

### Step 2: Entity Classification

**Input**: Entity name from column header (e.g., "Brazil", "FOB Baltic", "Hull")

**Classification Process**:
```
Is it a COUNTRY? → Yes: type="country", map region via COUNTRY_REGION_MAPPING
                   No: ↓
Is it a REGION? → Yes: type="region"
                   No: ↓
Is it a CITY? → Yes: type="city", map country via CITY_MAPPING_COUNTRIES
                No: ↓
Is it a VESSEL? → Yes: type="vessel"
                   No: ↓
Is it a HUB? → Yes: type="hub", map country/region via HUB_MAPPING_*
                No: ↓
Is it a LEGACY_COUNTRY? → Yes: type="legacy_country"
                           No: ↓
Default: type="other", canonical_name=raw_string
```

**Output Example**:
```python
Input: "Brazil"
Output: {
  "entity_type": "country",
  "canonical_name": "Brazil",
  "country_name": "Brazil",
  "region_name": "Americas"  # from COUNTRY_REGION_MAPPING
}
```

### Step 3: Grade Extraction (for phosphate, potash, NPK)

**BPL Grades** (Phosphate Rock):
- Input: "68-70% BPL", "69pc BPL", "73-75% BPL Trend"
- Regex: `(\d+(?:-\d+)?\s*(?:pc|%)\s*BPL)`
- Output: ProductGrade(display_value="68-70%", stored for scope)

**NPK Grades** (Fertilizer Blends):
- Input: "15:15:15", "13:13:20:5", "21:12", "46% P2O5"
- Patterns:
  - 4-number: N:P:K:S → parse as four values
  - 3-number: N:P:K or N:P:K+S marker
  - 2-number: N:P
  - P2O5 percentage: e.g., "30-32% P2O5"
- Output: ProductGrade with nitrogen, phosphate, potash, sulfur fields

### Step 4: Physical Form Extraction

**Recognized Forms**: granular, prills, solution, liquid, powder, standard

**Process**:
```
Input: "DAP granular FOB Brazil"
1. Search for form keywords (longest match first)
2. Find "granular" → physical_form="granular"
3. Remove from text → "DAP  FOB Brazil"
4. Clean spaces → "DAP FOB Brazil"
Output: physical_form="granular", cleaned="DAP FOB Brazil"
```

### Step 5: Metric Scope Building

**Scope**: Dictionary containing parsed metadata for variant tracking

**Keys**:
```python
scope = {
  "product_name": "diammonium_phosphate",      # base product (canonical)
  "entity_name": "Brazil",                     # where sold/delivered
  "price_type": "fob_nominal",                 # FOB, CFR, CIF, etc.
  "delivery_mode": "truck",                    # optional: truck, pipeline, barge
  "unit": "usd_per_ton_metric",                # unit of measure
  "physical_form": "granular",                 # optional: if extracted
  "product_grade": "66% BPL",                  # optional: if extracted
  "region_name": "Americas",                   # optional: region for entity
}
```

**Usage**: Stored in Metric.scope JSON field for variant tracking and data enrichment

### Step 6: Deduplication

**Problem**: Single product can appear in multiple columns/rows

**Solution**: Use in-memory cache dictionaries
```python
self.existing_products = {}      # product_name → ProductCreate
self.existing_entities = {}      # entity_name → EntityCreate
self.existing_regions = {}       # region_name → RegionCreate
self.existing_countries = {}     # country_name → CountryCreate
```

**Logic**:
```python
if product_name not in self.existing_products:
    prod = ProductCreate(product_name, category, ...)
    self.existing_products[product_name] = prod
    self.schema_collection.products.append(prod)
else:
    # Reuse existing record
    pass
```

### Step 7: Metric Record Creation

**MetricCreate** structure:
```python
MetricCreate(
  entity_name="Brazil",                    # or None if entity is region/country
  product_name="diammonium_phosphate",     # base product name
  value="445.50",                          # price value as string
  unit_of_measure="usd_per_ton_metric",    # normalized unit
  metric_name="price_fob_nominal",         # metric_type prefixed
  metric_type="price",                     # always "price" for price extractors
  start_date_effect=date(2025, 1, 15),     # date from row
  end_date_effect=date(2026, 1, 14),       # start_date + 1 year - 1 day
  date_publication=date(...),              # extracted from doc name
  document_name="phosphate_prices_2025",   # standardized doc name
  country_name="Brazil",                   # if entity is country
  region_name="Americas",                  # geographic region
  scope=scope_dict,                        # full variant metadata
)
```

---

## Design Decisions

### 1. **Modular Extractor Architecture**
- **Why**: Different commodity price formats have distinct column structures and parsing rules
- **How**: Each commodity gets own extractor class (ammonia_prices.py, potash_prices.py, etc.)
- **Benefit**: Changes to one commodity don't affect others; easy to add new commodity types

### 2. **YAML-Driven Configuration**
- **Why**: Sheet name patterns vary; configuring them in code is inflexible
- **How**: `sheets_extractors.yaml` maps sheet names → extractor implementations
- **Benefit**: Add new sheets/templates without code changes; runtime configuration

### 3. **SchemaCollection DTO**
- **Why**: Extractors produce multiple entity types (Metrics, Products, Entities, etc.)
- **How**: Single return object groups all output together
- **Benefit**: Atomic transaction — either all records persist or none; easy to pass between layers

### 4. **Base Product vs Variants**
- **Why**: "DAP " and "DAP granular 66% BPL" are variants of same product
- **How**: Store only base product in products table; variants go in Metric.scope
- **Benefit**: Clean product master data; variants tracked in scope for queries

### 5. **Entity Deduplication Cache**
- **Why**: Same country/region/entity appears in hundreds of rows/columns
- **How**: In-memory dictionary prevents duplicate records
- **Benefit**: Single loop through data; clean database without post-processing

### 6. **Referential-Driven Normalization**
- **Why**: Data quality issues: "Diammonium Phosphate", "DAP", "dap" all mean same thing
- **How**: Load referential.yaml; use aliases and whitelists for validation
- **Benefit**: Consistent canonical forms; single source of truth for reference data

### 7. **Scope JSON Field**
- **Why**: Need to track complex metadata (grade, physical form, exact column header) without schema changes
- **How**: Store unstructured metadata in Metric.scope dictionary
- **Benefit**: Extensible without database migrations; flexible for future needs

### 8. **Dynamic Caster Loading**
- **Why**: Avoid hard-coding all extractor implementations
- **How**: Use Python importlib to load modules at runtime
- **Benefit**: Add new extractors by creating new .py file; no loader changes needed

### 9. **Auto-Detecting Header Rows**
- **Why**: Excel templates often have variable header positions
- **How**: Search for product name keywords and year patterns
- **Benefit**: Robust to template variations; handles both row 4 and row 5 headers

### 10. **Graceful Missing Value Handling**
- **Why**: Price data often has gaps (not all entities report every period)
- **How**: Skip cells with "NA", "N/A", "nm", NaN values
- **Benefit**: Incomplete data sets still extract successfully; downstream handles nulls

### 11. **Region-Country Mapping**
- **Why**: Need geographic context for entity (e.g., "Brazil" → Americas region)
- **How**: Maintain COUNTRY_REGION_MAPPING and CITY_MAPPING_COUNTRY dicts
- **Benefit**: Enable regional analysis; proper hierarchical relationships

### 12. **Entity Type Classification**
- **Why**: Same text might be country or city (e.g., "Hull" could be entity or city)
- **How**: Prioritized lookup: countries → regions → cities → vessels → legacy → other
- **Benefit**: Handle ambiguity consistently; capture incomplete/legacy data

---

## How to Extend

### Adding a New Commodity Price Extractor

#### 1. Create New Extractor File

Create `src/excel_ingestion/extractors/implementation/new_commodity_prices.py`:

```python
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

import numpy as np
import pandas as pd

from src.excel_ingestion.services.cleaner import CleanerService
from src.excel_ingestion.persistence.schemas import (
    DocumentCreate, MetricCreate, EntityCreate, ProductCreate,
    ProductGrade, RegionCreate, CountryCreate
)

logger = logging.getLogger("new_commodity_prices_caster")

# Load referential
BASE_DIR = Path(__file__).resolve().parents[2]
REF_PATH = BASE_DIR / "config" / "referential.yaml"

try:
    with REF_PATH.open("r", encoding="utf-8") as f:
        REF_CONFIG: Dict[str, Any] = yaml.safe_load(f) or {}
    logger.info(f"Loaded referential from {REF_PATH.resolve()}")
except Exception as e:
    logger.warning(f"Failed to load referential.yaml: {e}")
    REF_CONFIG = {}

# Extract referential views
SOURCES = set(REF_CONFIG.get("sources", []))
COMPANIES = set(REF_CONFIG.get("companies", []))
COUNTRIES = set(REF_CONFIG.get("country", []))
REGIONS = set(REF_CONFIG.get("regions", []))
CITIES = set(REF_CONFIG.get("cities", []))
VESSELS = set(REF_CONFIG.get("vessels", []))
PRODUCTS_BY_CATEGORY = REF_CONFIG.get("products_by_category", {})
UNITS = set(REF_CONFIG.get("units", []))

@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate] = None
    metrics: List[MetricCreate] = field(default_factory=list)
    entities: List[EntityCreate] = field(default_factory=list)
    products: List[ProductCreate] = field(default_factory=list)
    regions: List[RegionCreate] = field(default_factory=list)
    countries: List[CountryCreate] = field(default_factory=list)

class ColumnParser:
    """Parse columns for new commodity type."""
    
    PERIOD_TOKENS = {
        "daily", "weekly", "monthly", "quarterly", "yearly", "annual"
    }
    
    @staticmethod
    def colname_to_metric_scope(text: str) -> Optional[Dict[str, Any]]:
        # TODO: Implement column parsing logic specific to your format
        # Should extract product, entity, price_type, unit
        pass

class Caster:
    """Main extraction engine for new commodity prices."""
    
    def __init__(self) -> None:
        self.cleaner = CleanerService()
        self.schema_collection: Optional[SchemaCollection] = None
        self.reset_state()
    
    def reset_state(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.existing_entities: Dict[str, EntityCreate] = {}
        self.existing_products: Dict[str, ProductCreate] = {}
        self.existing_regions: Dict[str, RegionCreate] = {}
        self.existing_countries: Dict[str, CountryCreate] = {}
    
    def start_casting_sequence(self) -> None:
        self.reset_state()
        self.schema_collection = SchemaCollection()
    
    def raw_data_to_df(self, data: np.ndarray) -> pd.DataFrame:
        # TODO: Implement header detection and DataFrame creation
        pass
    
    def process_data(
        self,
        data: np.ndarray,
        document_name: str,
        document_path: Optional[str] = None,
        **kwargs: Any,
    ) -> SchemaCollection:
        """Main entry point."""
        self.start_casting_sequence()
        
        df = self.raw_data_to_df(data)
        logger.info(f"Columns: {list(df.columns)}")
        
        # TODO: Implement row processing loop
        for idx, row in df.iterrows():
            try:
                self._process_row(row, document_name)
            except Exception as e:
                logger.error(f"Error processing row {idx}: {e}")
                self.errors.append(str(e))
        
        return self.schema_collection
    
    def _process_row(self, row: pd.Series, document_name: str) -> None:
        # TODO: Implement row-by-row metric extraction
        pass
```

#### 2. Update sheets_extractors.yaml

Add your extractor to `sheets_extractors.yaml`:

```yaml
- name: "new_commodity_prices"
  description: "Extract new commodity prices from market reports"
  extractor_code: "new_commodity_prices.py"
  matches:
    exact:
      - value: "New Commodity Price Data"
        data_provider: "market_provider"
        params:
          commodity: "new_commodity"
    
    regex:
      - pattern: "^New Commodity.*Prices$"
        data_provider: "market_provider"
        params:
          frequency: "monthly"
```

#### 3. Update Referential Configuration

Add your commodity to `src/excel_ingestion/config/referential.yaml`:

```yaml
products_by_category:
  new_commodity_fertilizers:
    - new_commodity_a
    - new_commodity_b

product_aliases:
  "new_cmdy": "new_commodity_a"
  "new cmdy a": "new_commodity_a"

unit_aliases:
  "usd per unit": "usd_per_unit"
  "usd/unit": "usd_per_unit"

units:
  - usd_per_unit
  - usd_per_ton_metric
```

### Modifying an Existing Extractor

#### Example: Add Min/Max Price Support to Ammonia Extractor

**File**: `src/excel_ingestion/extractors/implementation/ammonia_prices.py`

**Change 1**: Enhance ColumnParser to detect min/max keywords
```python
@staticmethod
def colname_to_metric_scope(text: str) -> Optional[Dict[str, Any]]:
    # ... existing code ...
    
    # NEW: Detect min/max price types
    price_type = "nominal"
    if "minimum" in text_lower or "min" in text_lower:
        price_type = "minimum"
    elif "maximum" in text_lower or "max" in text_lower:
        price_type = "maximum"
    
    scope["price_type"] = price_type  # Add to scope
    return scope
```

**Change 2**: Update metric name generation
```python
def _process_row(self, row: pd.Series, document_name: str) -> None:
    # ... existing code ...
    
    # NEW: Include price_type in metric_name
    price_type = scope_.get("price_type", "nominal")
    metric = MetricCreate(
        # ... other fields ...
        metric_name=f"price_{commodity}_{price_type}",
        # ...
    )
```

#### Example: Add Date Range Extraction from Header

**In your Caster class**:
```python
def process_data(self, data: np.ndarray, document_name: str, **kwargs) -> SchemaCollection:
    # NEW: Extract date range from document name
    from dateutil.parser import parse
    
    # Parse date patterns like "ammonia_prices_2025_01_15.xlsx"
    import re
    match = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', document_name)
    if match:
        year, month, day = map(int, match.groups())
        doc_date = date(year, month, day)
    else:
        doc_date = date.today()
    
    # Use in DocumentCreate
    doc = DocumentCreate(
        # ...
        publication_date=doc_date,
    )
```

### Adding a New Entity Classification

**File**: `src/excel_ingestion/config/referential.yaml`

```yaml
# If adding a new "trading_hub" concept:
trading_hubs:
  - "panama_canal"
  - "suez_canal"
  - "rotterdam"

hub_mapping_countries:
  "panama_canal": "panama"
  "rotterdam": "netherlands"

hub_mapping_regions:
  "rotterdam": "europe"
```

**In your extractor's ColumnParser**:
```python
@staticmethod
def classify_entity(name: str) -> Dict[str, Any]:
    # ... existing country/region/city checks ...
    
    # NEW: Check trading hubs
    if name in TRADING_HUBS:
        return {
            "entity_type": "trading_hub",
            "canonical_name": name,
            "country_name": HUB_MAPPING_COUNTRY.get(name),
            "region_name": HUB_MAPPING_REGION.get(name),
        }
    
    # ... rest of logic ...
```

---

## Examples

### Example 1: Extract Ammonia Prices from Argus Report

**Input File**: `argus_ammonia_prices_jan_2025.xlsx`

**Sheet**: `Prices`

**Content**:
```
                 FOB Baltic    FOB Black Sea    CIF NW Europe
                 $/t export   $/t export       $/t import
January 2025
Week 1           445.50       432.75           465.00
Week 2           448.00       435.50           468.50
```

**Processing**:
```
1. Sheet name match: "Prices" + file contains "ammonia" 
   → Resolve to ammonia_prices.py extractor

2. Headers:
   - "FOB Baltic" → product="ammonia", entity="Baltic", price_type="fob"
   - "FOB Black Sea" → product="ammonia", entity="Black Sea", price_type="fob"
   - "CIF NW Europe" → product="ammonia", entity="NW Europe", price_type="cif"

3. Date parsing:
   - "January 2025", "Week 1" → 2025-01-06 (approximate)
   - "January 2025", "Week 2" → 2025-01-13 (approximate)

4. Output Metrics:
   - Metric(entity="Baltic", product="ammonia", value="445.50", unit="usd_per_ton_metric", price_type="fob_baltic", start_date=2025-01-06)
   - Metric(entity="Baltic", product="ammonia", value="448.00", unit="usd_per_ton_metric", price_type="fob_baltic", start_date=2025-01-13)
   - Metric(entity="Black Sea", product="ammonia", value="432.75", unit="usd_per_ton_metric", price_type="fob_black_sea", start_date=2025-01-06)
   - ... (more metrics for other entities/weeks)
```

**Output SchemaCollection**:
```python
SchemaCollection(
  document=DocumentCreate(
    document_name="argus_ammonia_prices_jan_2025",
    publication_date=2025-01-31,
    effective_start_date=2025-01-06,
    effective_end_date=2025-01-31,
  ),
  metrics=[
    MetricCreate(product_name="ammonia", entity_name="Baltic", value="445.50", ...),
    MetricCreate(product_name="ammonia", entity_name="Baltic", value="448.00", ...),
    # ... more metrics
  ],
  entities=[
    EntityCreate(entity_name="Baltic", entity_type="trading_hub", ...),
    EntityCreate(entity_name="Black Sea", entity_type="trading_hub", ...),
    EntityCreate(entity_name="NW Europe", entity_type="region", ...),
  ],
  products=[
    ProductCreate(product_name="ammonia", product_category="chemicals", ...),
  ],
  regions=[
    RegionCreate(region_name="Europe", ...),
  ],
  countries=[],
)
```

### Example 2: Extract Phosphate Rock Prices with Grades

**Input File**: `phosphate_rock_market_outlook_q1_2025.xlsx`

**Sheet**: `Price History`

**Content**:
```
                  68-70% BPL CFR    73-75% BPL FOB    66-68% BPL CIF
                  Brazil            Morocco           India
2025 Q1           105.50            110.25            112.75
2025 Q2 (Forecast) 108.00            113.00            115.50
```

**Processing**:
```
1. Column parsing:
   - "68-70% BPL CFR" + "Brazil"
     → product="phosrock", grade="68-70%", price_type="cfr", entity="Brazil"
   
   - "73-75% BPL FOB" + "Morocco"
     → product="phosrock", grade="73-75%", price_type="fob", entity="Morocco"

2. Entity classification:
   - "Brazil" → country, region="Americas"
   - "Morocco" → country, region="Africa"
   - "India" → country, region="Asia"

3. Grade extraction:
   - ProductGrade(display_value="68-70%", phosphate_content=69.0)

4. Output Metrics:
   - Metric(
       product="phosphate_rock",
       entity="Brazil",
       value="105.50",
       grade="68-70%",
       scope={"price_type": "cfr", "grade": "68-70%", "entity_country": "Brazil"},
       start_date=2025-01-01,
       end_date=2025-03-31,
     )
```

### Example 3: NPK Blend Price Extraction

**Input File**: `npk_blend_prices_2025.xlsx`

**Sheet**: `NPK Price Forecasts`

**Content**:
```
           15:15:15 DAP Mix    20:20:0 MAP Mix    17:17:17 NPS
           USD/t FOB Brazil    USD/t FOB Morocco  USD/t CFR India
2025-01    445.75              452.50             468.25
2025-02    448.00              455.75             471.50
```

**Processing**:
```
1. Grade parsing:
   - "15:15:15" → ProductGrade(nitrogen=15, phosphate=15, potash=15, sulfur=0)
   - "20:20:0" → ProductGrade(nitrogen=20, phosphate=20, potash=0, sulfur=0)
   - "17:17:17S" → ProductGrade(nitrogen=17, phosphate=17, potash=0, sulfur=17)

2. Column parsing:
   - "15:15:15 DAP Mix" + "USD/t FOB Brazil"
     → product="npk_blend_15_15_15", entity="Brazil", price_type="fob", unit="usd_per_ton"

3. Output Metrics:
   - Metric(
       product_name="npk_blend_15_15_15",
       entity_name="Brazil",
       value="445.75",
       scope={
         "product_name": "npk_blend_15_15_15",
         "grade": "15:15:15",
         "product_grade": ProductGrade(...),
         "price_type": "fob",
         "entity_country": "Brazil",
       },
       start_date=2025-01-01,
       end_date=2025-01-31,
       region_name="Americas",
     )
```

---

## Troubleshooting

### Common Issues

**Issue**: "Unmapped unit" warnings in logs
- **Cause**: Unit from Excel not in referential UNITS list
- **Solution**: Add unit to `config/referential.yaml` under `units` list, or add alias in `unit_aliases`

**Issue**: "Product not in referential" warnings
- **Cause**: Product name not recognized
- **Solution**: Add product to `products_by_category` in referential, or add alias in `product_aliases`

**Issue**: Empty metrics list in output
- **Cause**: All rows are skipped (e.g., date parsing fails, all values are NA)
- **Solution**: Check date column format; verify value columns contain numeric data

**Issue**: Duplicate entities in output
- **Cause**: Case sensitivity in entity names (e.g., "Brazil" vs "brazil")
- **Solution**: Use `CleanerService.standardize_value()` for case normalization

---

## References

- **Referential Configuration**: `src/excel_ingestion/config/referential.yaml`
- **Database Schemas**: `src/excel_ingestion/persistence/schemas.py`
- **Cleaner Service**: `src/excel_ingestion/services/cleaner.py`
- **Extractor Configuration**: `src/excel_ingestion/extractors/sheets_extractors.yaml`

---

**Document Version**: 1.0  
**Last Updated**: April 2, 2026  
**Maintainers**: Data Ingestion Team
