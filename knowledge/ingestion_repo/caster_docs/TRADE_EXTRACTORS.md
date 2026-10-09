# Trade Extractors Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture & Data Flow](#architecture--data-flow)
3. [Trade Extractors](#trade-extractors)
4. [Core Components](#core-components)
5. [Classes & Object Design](#classes--object-design)
6. [Data Processing & Transformation](#data-processing--transformation)
7. [Design Decisions](#design-decisions)
8. [Extensibility](#extensibility)
9. [Examples](#examples)
10. [Troubleshooting](#troubleshooting)

---

## Overview

### Purpose

The **Trade Extractors System** is a template-driven data ingestion pipeline designed to extract, parse, and normalize international trade flow data from Excel files. The system processes trade matrices, import/export data, freight flows, and commerce information, transforming raw spreadsheet data into structured database schemas.

### What is Trade Data Extraction?

Trade data extraction refers to the **automated extraction and structuring of international commerce information** from Excel trade reports and matrices, including:

- **Trade flows**: Import/export quantities between countries and regions
- **Trade matrices**: Bilateral trade data organized as origin → destination matrices
- **Commodities traded**: Products, fertilizers, chemicals, minerals
- **Trading entities**: Companies, ports, shipping operators
- **Geographic data**: Countries, regions, trading hubs, ports
- **Volume metrics**: Quantities in specified units (kilotons, tons, etc.)
- **Temporal data**: Reporting dates, trade periods, seasonal patterns

### Overall Workflow

```
Excel File (Trade Report/Matrix)
       ↓
[Sheet Detection] → Match sheet name against templates in sheets_extractors.yaml
       ↓
[Load Extractor] → Dynamically load appropriate Caster from implementation/
                   E.g., trade_data.py, trade_matrix.py, argus_npk_trades.py
       ↓
[Parse Headers]  → Extract column names and identify data fields:
                   - Origin country/region
                   - Destination country/region
                   - Product name
                   - Volume and unit of measure
                   - Trading entities (importers, exporters)
       ↓
[Process Rows]   → For each data row:
                   - Parse origin and destination geographies
                   - Clean and normalize entity names
                   - Classify countries and regions
                   - Extract trade volumes
                   - Parse products and commodities
                   - Extract temporal references
       ↓
[Entity Classification] → Using referential.yaml:
                   - Country → Region mapping
                   - Country aliases resolution
                   - Product categorization
                   - Port/hub identification
                   - Company entity creation
       ↓
[Database Ready] → SchemaCollection containing:
                   - Document metadata
                   - List of Metrics (trade flow records)
                   - List of Entities (companies, trading hubs, ports)
                   - List of Products (commodities traded)
                   - List of Regions and Countries
       ↓
[Persistence]    → Loaded into PostgreSQL database via repositories
```

---

## Architecture & Data Flow

### Component Hierarchy

```
extractors/
├── loader.py                                    # Sheet matcher & extractor resolver
├── utils.py                                     # Dynamic loading & standardization utilities
├── sheets_extractors.yaml                       # Configuration: sheet name → extractor mapping
└── implementation/
    ├── trade_data.py                            # Base trade data extractor (CRU)
    ├── trade_matrix.py                          # Trade matrix extractor
    ├── trade_matrix_sulphur_outlook_data.py    # Sulphur trade matrix (SCP)
    ├── argus_npk_trades.py                      # Argus NPK trade matrix
    ├── argus_phosrock_trade.py                  # Argus phosphate rock/ammonia trade
    ├── trades_from_ammended_file.py             # Specialty phosphate trades (CRU)
    ├── freight_trad_caster.py                   # Freight & logistics trade data
    ├── brazil_mop_raw_import_data.py            # Brazil MOP import data (Argus)
    └── raw_vessel_data.py                       # Raw vessel import data (Argus)
```

### Data Classification Hierarchy

```
RawExcelData ──[Caster]──> SchemaCollection
                            ├── Document (1 per file)
                            │   └── publication_date, effective_start/end_date
                            │
                            ├── Metrics[] (multiple trade flow records)
                            │   ├── product_name (e.g., ammonia, NPK, phosrock)
                            │   ├── entity_name (origin country/trading hub)
                            │   ├── value (trade volume in kilotons)
                            │   ├── unit (unit of measure)
                            │   └── scope (contains trade-specific metadata)
                            │
                            ├── Entities[] (countries, ports, companies)
                            │   ├── name (canonical entity name)
                            │   └── entity_type (country, port, company, etc.)
                            │
                            ├── Products[] (commodities)
                            │   ├── name (product name)
                            │   └── category (NPK, fertilizer, chemical, etc.)
                            │
                            ├── Regions[] (geographic regions)
                            └── Countries[] (with region assignments)
```

---

## Trade Extractors

### 1. **trade_data.py** - CRU Phosphate Fertilizer Trade Data

**Purpose:** Extract trade data from CRU Phosphate Fertilizer Market Outlook reports

**Key Features:**
- Processes bilateral trade matrices
- Handles origin/destination country pairs
- Extracts trade volumes for phosphate fertilizer products
- Normalizes country names and regions via referential.yaml

**Supported Sheets:**
- "Trade Data" (CRU Phosphate Market files)

**Data Sources:**
- CRU (Commodity Research Unit)

**Typical Output:**
```
Metrics: Trade flows between countries
Products: Phosphate fertilizer types
Entities: Countries, trading regions
Example: 10 kt of DAP exported from Morocco to Portugal
```

---

### 2. **trade_matrix.py** - Generic Trade Matrix Extractor

**Purpose:** Extract bilateral trade matrices from market outlook reports

**Key Features:**
- Generic matrix processing (works with multiple commodity types)
- Handles country → country trade flows
- Robust entity and product classification
- Support for annual/historical trade data

**Supported Sheets:**
- Historical and forecast trade matrices
- Multi-period trade data

**Data Sources:**
- Market research files (Argus, CRU, S&P)

**Typical Output:**
```
Metrics: Bilateral trade volumes
Scope contains: origin_country, destination_country, volume_unit
Entities: All trading countries/regions
Example: 5 kt NPK from India to Malaysia
```

---

### 3. **trade_matrix_sulphur_outlook_data.py** - Sulphur Trade Matrices

**Purpose:** Extract sulphur trade matrices from S&P (Sulphur Market) outlook reports

**Key Features:**
- Specialized for sulphur commodity
- Processes annual trade matrices (2022, 2023, 2024+)
- Extracts sulphur flows by country pairs
- Referential-backed entity normalization

**Supported Sheets:**
- "Sulphur Trade Matrix 2022"
- "Sulphur Trade Matrix 2023"
- "Sulphur Trade Matrix 2024"
- (Pattern continues for future years)

**Data Sources:**
- S&P (S&P Global/Platts)

**Typical Output:**
```
Metrics: Sulphur trade flows
Product: Sulphur (elemental or derived)
Entities: Country pairs (exporter, importer)
Example: 50 kt sulphur from Canada to USA
```

---

### 4. **argus_npk_trades.py** - Argus NPK Trade Matrix

**Purpose:** Extract NPK (combined nitrogen-phosphate-potassium) trade matrices from Argus reports

**Key Features:**
- Processes "Trade Matrix (Data)" sheets from Argus files
- Extracts NPK trade flows between countries
- Handles multi-product NPK blends
- Supports forecast and historical data

**Supported Sheets:**
- "Trade Matrix (Data)" (Argus NPK reports)

**Data Sources:**
- Argus Media

**Typical Output:**
```
Metrics: NPK trade volumes
Products: NPK, NPS, and other blends
Example: 8 kt NPK exported from Europe to Middle East
```

---

### 5. **argus_phosrock_trade.py** - Argus Phosphate Rock & Ammonia Trade

**Purpose:** Extract phosphate rock and ammonia/sulphur trade matrices from Argus Analytics reports

**Key Features:**
- Processes multi-year trade matrices (2021-2024+)
- Handles phosphate rock and related commodities
- Extracts ammonia supply chains
- Processes S&P Ammonia Analytics data

**Supported Sheets:**
- "2021 Trade Matrix", "2022 Trade Matrix", "2023 Trade Matrix", "2024 Trade Matrix"
- File matching: "Argus Ammonia Analytics.*"

**Data Sources:**
- Argus Media
- S&P Ammonia Analytics

**Typical Output:**
```
Metrics: Phosphate rock and ammonia trade volumes
Entities: Phosphate production countries, ammonia exporters
Example: 100 kt phosphate rock from Morocco to Belgium
Example: 25 kt ammonia from Russia to Germany
```

---

### 6. **trades_from_ammended_file.py** - Specialty Phosphate Market Trades

**Purpose:** Extract trade matrices from CRU Specialty Phosphate Market Outlook reports

**Key Features:**
- Processes specialty phosphate product trades
- Handles multiple product categories: PWA, TPA, tMAP, P4, STPP, DCP, MCP/MDCP
- Multi-year historical data (2021-2023+)
- Specialized product classification

**Supported Sheets:**
- PWA/TPA Trade Matrices (2021-2023+)
- tMAP Trade Matrices (2021-2023+)
- P4 Trade Matrices (2021-2023+)
- STPP Trade Matrices (2021-2023+)
- DCP Trade Matrices (2021-2023+)
- MCP/MDCP Trade Matrices (2021-2023+)

**Data Sources:**
- CRU Specialty Phosphate Market Outlook

**Typical Output:**
```
Metrics: Specialty phosphate product trades
Products: PWA, TPA, tMAP (tricalcium phosphate), P4, STPP, DCP, MCP, MDCP
Entities: Countries producing/trading specialty phosphates
Example: 3 kt PWA from USA to Japan
```

---

### 7. **freight_trad_caster.py** - Freight & Logistics Trade Data

**Purpose:** Extract freight flows, logistics costs, and shipping data from trade reports

**Key Features:**
- Processes freight rates and logistics costs
- Handles shipping corridors and routes
- Extracts transportation volumes
- Normalizes ports and shipping hubs

**Supported Sheets:**
- Generic freight/logistics data

**Data Sources:**
- Logistics and freight reports
- Shipping cost analyses

**Typical Output:**
```
Metrics: Freight volumes/costs by shipping corridor
Entities: Origin ports, destination ports
Example: 12 USD/ton freight cost from Saudi Arabia to Europe
```

---

### 8. **brazil_mop_raw_import_data.py** - Brazil MOP Import Data

**Purpose:** Extract raw import data for Muriate of Potash (MOP) into Brazil

**Key Features:**
- Processes detailed import manifests
- Extracts origin country and supplier information
- Captures MOP volumes and import values
- Tracks import patterns and trends

**Supported Sheets:**
- "Raw Import Data" (Brazil MOP import records)

**Data Sources:**
- Argus Media (Brazil trade data)

**Typical Output:**
```
Metrics: MOP import volumes into Brazil
Entities: Exporting countries, Brazilian ports
Products: Muriate of Potash (MOP/KCl)
Example: 45 kt MOP imported from Canada in March 2024
```

---

### 9. **raw_vessel_data.py** - Raw Vessel Import Data

**Purpose:** Extract raw vessel-level import data from port records and manifests

**Key Features:**
- Processes individual vessel shipments
- Extracts cargo manifests and import details
- Captures vessel information and arrival dates
- Handles multiple commodity types

**Supported Sheets:**
- "Raw Vessel Data" (Import manifests)

**Data Sources:**
- Argus Media (Port records)

**Typical Output:**
```
Metrics: Individual vessel cargoes
Entities: Vessels, origin countries, destination ports
Products: Various commodities per shipment
Example: Vessel "Atlantic" carrying 30 kt MAP from Morocco, arrives Brazil
```

---

## Core Components

### loader.py

The loader module is responsible for:

1. **Sheet Matching**: Compares incoming sheet names against configuration in `sheets_extractors.yaml`
2. **Extractor Resolution**: Dynamically imports the correct Python extractor class
3. **Parameter Passing**: Forwards sheet-specific parameters to the extractor

**Key Functions:**
- `load_extractor(sheet_name, data_provider)` → Returns instantiated Caster
- `match_sheet_config(sheet_name)` → Returns matching configuration dict

---

### utils.py

The utils module provides:

1. **Dynamic imports**: Load extractor classes from `implementation/` directory
2. **Name standardization**: Normalize product names, entity names, country names
3. **Unit conversion**: Map and convert between different measurement units
4. **Type inference**: Detect numeric vs. text vs. date values

**Key Functions:**
- `dynamic_import(module_name)` → Returns module
- `standardize_name(raw_string)` → Returns normalized name
- `parse_numeric_value(cell_value)` → Returns float or None

---

### sheets_extractors.yaml

Configuration file that maps:
- **Sheet name patterns** → Extractor classes
- **Data providers** → Matcher rules
- **File regex** → Additional filtering criteria

**Example Entry:**
```yaml
- name: "trade_data_phosphate"
  description: "CRU Phosphate fertilizer trade data"
  extractor_code: "trade_data.py"
  matches:
    exact:
      - value: "Trade Data"
        params:
          data_provider: "cru"
```

---

## Classes & Object Design

### SchemaCollection

Container that holds all extracted data structures:

```python
@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate]      # File metadata
    metrics: List[MetricCreate]             # Trade flow records
    entities: List[EntityCreate]            # Countries, ports, companies
    products: List[ProductCreate]           # Commodities
    regions: List[RegionCreate]             # Geographic regions
    countries: List[CountryCreate]          # Country records with regions
```

### DocumentCreate

Metadata about the source Excel file:

```python
@dataclass
class DocumentCreate:
    name: str                               # File name
    publication_date: Optional[date]        # When data was published
    effective_start: Optional[date]         # Data validity start
    effective_end: Optional[date]           # Data validity end
    content: List[DocumentContentCreate]    # Sheets processed
```

### MetricCreate

Individual trade flow record:

```python
@dataclass
class MetricCreate:
    product_name: str                       # Commodity (e.g., "ammonia")
    entity_name: str                        # Trading entity/country
    value: float                            # Trade volume
    unit: str                               # Unit of measure (e.g., "kt")
    scope: Dict[str, str]                   # Metadata (origin, destination, etc.)
    start_date: Optional[date]              # Trade period start
    end_date: Optional[date]                # Trade period end
```

### EntityCreate

Trading entity (country, port, company):

```python
@dataclass
class EntityCreate:
    name: str                               # Canonical name
    entity_type: str                        # Type: country, port, company, hub
    region: Optional[str]                   # Region assignment (if applicable)
    country: Optional[str]                  # Parent country (if applicable)
```

### ProductCreate

Commodity/product being traded:

```python
@dataclass
class ProductCreate:
    name: str                               # Product name
    category: str                           # Category: NPK, phosphate, ammonia, etc.
    physical_form: Optional[str]            # Form: liquid, solid, granule, etc.
```

---

## Data Processing & Transformation

### Column Header Parsing

Trade matrices typically have:
- **Headers**: Product names, entity names, metrics
- **Index columns**: Origin countries or trading entities
- **Data columns**: Trade volumes

**Processing Steps:**
1. Detect multi-row header regions
2. Merge header rows into product/entity descriptions
3. Extract unit information from headers
4. Validate against referential data

### Data Row Processing

For each data row in the matrix:

1. **Extract row index**: Origin country/entity
2. **Parse each column**:
   - Extract destination country/region
   - Parse numeric trade volume
   - Identify product from column header
   - Apply unit conversions if needed
3. **Classify entities**: Map to referential countries/regions
4. **Create Metric records**: One per cell with valid data

### Referential-Backed Normalization

The system uses `referential.yaml` to:

1. **Resolve country aliases** → Canonical country names
2. **Map countries to regions** → Geographic classification
3. **Classify products** → Product categories
4. **Validate cities and ports** → Geographic entities

**Example:**
- "USA" and "United States" → "United States" (canonical)
- "United States" → "North America" (region)
- "DAP" → "Phosphate Fertilizers" (category)

---

## Design Decisions

### 1. **One Metric per Trade Pair**

Each trade flow between two entities is represented as a single Metric record:
- Origin: Stored in entity_name
- Destination: Stored in scope["destination"]
- Volume: Stored in value

**Rationale**: Enables efficient queries like "All exports from country X"

### 2. **Referential.yaml as Single Source of Truth**

All entity and product classifications use the centralized `referential.yaml`:
- Ensures consistency across all extractors
- Simplifies updates (update YAML, all extractors benefit)
- Reduces duplicate logic

### 3. **Numeric Validation**

Trade data easily contains text artifacts and garbage values. The system:
- Skips non-numeric cells (text, formulas, errors)
- Validates unit names against referential
- Logs skipped rows for debugging

### 4. **Generic vs. Specialized Extractors**

- **Generic** (`trade_matrix.py`): Works with multiple commodities
- **Specialized** (`argus_npk_trades.py`, `trades_from_ammended_file.py`): Optimized for specific commodities
- Allows both flexibility and customization

---

## Extensibility

### Adding a New Trade Extractor

**Step 1**: Create new Python file in `implementation/`

```python
# implementation/my_trade_extractor.py
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict, Any

@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate] = None
    metrics: List[MetricCreate] = field(default_factory=list)
    entities: List[EntityCreate] = field(default_factory=list)
    products: List[ProductCreate] = field(default_factory=list)
    regions: List[RegionCreate] = field(default_factory=list)
    countries: List[CountryCreate] = field(default_factory=list)

class MyCaster:
    def __init__(self, file_path: str, **kwargs):
        self.file_path = file_path
        
    def cast(self) -> SchemaCollection:
        result = SchemaCollection()
        # Read Excel and populate result
        return result
```

**Step 2**: Add to `sheets_extractors.yaml`

```yaml
- name: "my_trade_extractor"
  description: "My new trade data"
  extractor_code: "my_trade_extractor.py"
  matches:
    exact:
      - value: "My Sheet Name"
        params:
          data_provider: "my_provider"
```

**Step 3**: Test and validate

---

## Examples

### Example 1: Processing NPK Trade Matrix

**Input File**: `Argus_NPK_10_2024.xlsx`, Sheet: "Trade Matrix (Data)"

```
            USA    Europe  India  China
Morocco     5      8       3      12
India       0      15      0      2
Brazil      10     4       0      1
```

**Processing**:
1. Sheet detected → Load `argus_npk_trades.py`
2. Parse headers: USA, Europe, India, China → Destination countries
3. Parse rows:
   - Row 1 (Morocco): Create 4 Metrics
   - Row 2 (India): Create 4 Metrics (skip India→India)
   - Row 3 (Brazil): Create 4 Metrics

**Output Metrics**:
```
Metric 1: Morocco → USA, 5 kt NPK
Metric 2: Morocco → Europe, 8 kt NPK
Metric 3: Morocco → India, 3 kt NPK
Metric 4: Morocco → China, 12 kt NPK
...
```

### Example 2: Processing Brazil MOP Imports

**Input File**: `Brazil_MOP_Imports_Q4_2024.xlsx`, Sheet: "Raw Import Data"

```
Vessel            Origin      Volume(kt)  Import_Date
Atlantic          Canada      45          2024-03-15
Pacific           USA         30          2024-03-20
Indian Ocean      Australia   25          2024-03-25
```

**Processing**:
1. Sheet matched → Load `brazil_mop_raw_import_data.py`
2. For each row:
   - Extract vessel name → Entity (Vessel)
   - Parse origin → Entity (Country)
   - Extract volume → Metric value
   - Parse date → Metric temporal reference

**Output**:
```
Metrics: 3 import records
- Vessel Atlantic, 45 kt MOP from Canada
- Vessel Pacific, 30 kt MOP from USA
- Vessel Indian Ocean, 25 kt MOP from Australia

Entities: Atlantic, Pacific, Indian Ocean, Canada, USA, Australia
```

### Example 3: Processing Sulphur Trade Matrix

**Input File**: `Sulphur_Outlook_2024.xlsx`, Sheet: "Sulphur Trade Matrix 2024"

```
          USA   Mexico  Europe  Asia
Canada    100   50      30      10
USA       0     40      50      60
Mexico    15    0       20      40
```

**Processing**:
1. Sheet matched → Load `trade_matrix_sulphur_outlook_data.py`
2. Product identified: Sulphur
3. For each non-zero cell:
   - Row country = Exporter
   - Column country = Importer
   - Value = Trade volume

**Output**:
```
Metrics: 11 trade flows
Entities: Canada, USA, Mexico, Europe, Asia
Product: Sulphur
```

---

## Troubleshooting

### Common Issues & Solutions

#### **Issue 1: Sheet Not Recognized**

**Symptom**: `ExtractorNotFoundError: No extractor found for sheet "Trade Data"`

**Causes**:
- Sheet name not in `sheets_extractors.yaml`
- Typo in sheet name or data_provider

**Solution**:
```yaml
# Add to sheets_extractors.yaml
- value: "Trade Data"
  data_provider: "cru"  # <- Must match file metadata
```

---

#### **Issue 2: Country Names Not Normalized**

**Symptom**: Entities appear as "USA", "United States", "US" (duplicates)

**Causes**:
- Country aliases not in `referential.yaml`
- Regex matching not catching variations

**Solution**:
```yaml
# Add to referential.yaml
country_aliases:
  "USA": "United States"
  "US": "United States"
  "US of A": "United States"
```

---

#### **Issue 3: Zero or Null Volumes Appearing as Metrics**

**Symptom**: Trade metrics with value=0 or None created

**Causes**:
- Insufficient numeric validation
- Empty cells parsed as 0

**Solution**:
- Most extractors already skip zero/null values
- Check `_process_row()` method for validation logic
- May need to update referential unit definitions

---

#### **Issue 4: Unit Conversion Failures**

**Symptom**: `ValueError: Unknown unit 'kilotonne'`

**Causes**:
- Unit alias missing from referential
- Extractor doesn't perform unit mapping

**Solution**:
```yaml
# Add to referential.yaml
units:
  - "kt"
  - "kiloton"
  - "kilotonne"  # <- Add missing variation
  - "t"
  - "ton"
  - "tonnes"
```

---

#### **Issue 5: File Parse Error**

**Symptom**: `pd.errors.ParserError: Could not construct index...`

**Causes**:
- Unexpected file format or corrupted file
- Header row count mismatch
- File encoding issues

**Solution**:
- Verify file is valid .xlsx
- Check `header_rows` parameter in config
- Validate file encoding (UTF-8 preferred)

---

## Best Practices

### For Extractor Authors

1. **Load referential.yaml early** in `__init__`
2. **Log progress and skipped rows** for debugging
3. **Validate data before creating Metrics**
4. **Handle missing headers gracefully**
5. **Test with real data** before production

### For Data Quality

1. **Keep referential.yaml updated** with new countries/products
2. **Document custom mappings** in code comments
3. **Validate output against source totals**
4. **Create audit reports** of rejected rows

### For Performance

1. **Use set membership** for lookups (O(1))
2. **Vectorize operations** with pandas where possible
3. **Cache referential** data after loading
4. **Profile slow extractors** with logging

---

## Related Documentation

- [Price Extractors README](README_PRICE_EXTRACTORS.md)
- [Vessel Trackers README](README_VESSEL_TRACKERS.md)
- [Main Data Ingestion README](../Data_Acquisition_All_README.md)
- Referential Configuration: `config/referential.yaml`
- Extractor Configuration: `sheets_extractors.yaml`

---

## Version History

- **v1.0** (2024-Q1): Initial trade extractors documentation
  - Documented 9 trade extractors
  - Added troubleshooting section
  - Provided extension examples

---

## Support & Feedback

For issues, questions, or feature requests:
- Check troubleshooting section above
- Review logs in extractor output
- Contact data engineering team
- Submit issues with sample files and error logs
