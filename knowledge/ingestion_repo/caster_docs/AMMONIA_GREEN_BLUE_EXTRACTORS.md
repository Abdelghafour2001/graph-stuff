# Green & Blue Ammonia Projects Extractor Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture & Data Flow](#architecture--data-flow)
3. [Data Extraction Process](#data-extraction-process)
4. [Core Components](#core-components)
5. [Classes & Object Design](#classes--object-design)
6. [Data Processing & Transformation](#data-processing--transformation)
7. [Design Decisions](#design-decisions)
8. [Project Metadata](#project-metadata)
9. [Technical Specifications](#technical-specifications)
10. [Examples](#examples)
11. [Troubleshooting](#troubleshooting)

---

## Overview

### Purpose

The **Green & Blue Ammonia Projects Extractor** is a specialized data ingestion pipeline designed to extract, parse, and normalize project-level information from Argus ammonia market analysis reports. The system processes detailed project databases containing information about advanced ammonia production initiatives (green and blue ammonia), transforming raw spreadsheet data into structured database schemas.

### What is Green & Blue Ammonia Data Extraction?

Green and blue ammonia extraction refers to the **automated extraction and structuring of information about advanced ammonia production projects** from market research reports:

**Green Ammonia:**
- Ammonia produced from renewable electricity via electrolysis
- Zero or near-zero carbon footprint
- Electrolyser-based production
- Renewable energy source specifications

**Blue Ammonia:**
- Conventional ammonia production with carbon capture and storage (CCS)
- Reduced carbon emissions via carbon sequestration
- Retrofit opportunities for existing plants
- CCS infrastructure requirements

### Key Data Extracted

The system captures comprehensive project information:

- **Project identification**: Name, location, operator(s), country
- **Capacity metrics**: Gross capacity, merchant capacity (in kilotons per year)
- **Project status**: Phase, rating, development stage
- **Timelines**: Original target dates, forecast dates, commissioning dates
- **Technical specifications**: Electrolyser type, renewable source, retrofit capabilities
- **Development progress**: Groundwork status, construction phase, commissioning status
- **Project governance**: Companies involved, EPC contractors, financing status, gas supply arrangements

### Overall Workflow

```
Excel File (Argus Ammonia Projects Database)
       ↓
[Sheet Detection] → Match sheet name: "Blue ammonia projects" or "Green ammonia projects"
       ↓
[Load Extractor] → Load green_blue_ammonia_projects.py
       ↓
[Header Detection] → Find project table header row (contains "Name", "Country", "T/D", etc.)
       ↓
[Identify File Type] → Determine if Blue or Green ammonia from sheet name content
       ↓
[Parse Headers]  → Extract column indices for:
                   - Project name, site, country
                   - Capacity (T/D, Gross, Merchant)
                   - Status, Phase, Target completion date
                   - Technical specs, Financing, EPC contractors
       ↓
[Process Rows]   → For each project row:
                   - Extract project and company names
                   - Parse capacity values
                   - Classify country and region
                   - Determine project phase
                   - Extract dates (targets, forecasts)
                   - Collect technical metadata
       ↓
[Entity Classification] → Using referential.yaml:
                   - Company → Entity mapping
                   - Country → Region assignment
                   - Status classification (Firm, Probable, Speculative, etc.)
       ↓
[Scope Aggregation] → Compile project metadata into scope:
                   - Progress indicators (groundwork, construction, commissioning)
                   - Ownership structure and additional owners
                   - Technical specifications (renewable source, electrolyser, retrofit)
                   - Financing and EPC information
       ↓
[Database Ready] → SchemaCollection containing:
                   - Document metadata
                   - List of Metrics (one per project)
                   - List of Entities (companies, project owners)
                   - List of Products (green ammonia, blue ammonia)
                   - List of Regions and Countries
       ↓
[Persistence]    → Loaded into PostgreSQL database via repositories
```

---

## Architecture & Data Flow

### Component Hierarchy

```
extractors/
├── loader.py                                       # Sheet matcher & extractor resolver
├── utils.py                                        # Dynamic loading & utilities
├── sheets_extractors.yaml                          # Configuration: sheet name → extractor mapping
└── implementation/
    └── green_blue_ammonia_projects.py              # Green & Blue ammonia project extractor
```

### Data Classification Hierarchy

```
RawExcelData ──[Caster]──> SchemaCollection
                            ├── Document (1 per file)
                            │   └── publication_date, effective_start/end_date
                            │
                            ├── Metrics[] (multiple project records)
                            │   ├── entity_name (project owner/company)
                            │   ├── product_name ("ammonia" variant: green/blue)
                            │   ├── metric_type ("project")
                            │   ├── value (empty - data in scope)
                            │   └── scope (project metadata: capacity, status, dates, etc.)
                            │
                            ├── Entities[] (companies, project operators)
                            │   ├── name (canonical entity name)
                            │   ├── type (company, operator)
                            │   └── metadata (country, region, sites)
                            │
                            ├── Products[] (ammonia types)
                            │   ├── name (ammonia)
                            │   └── category (green or blue)
                            │
                            ├── Regions[] (geographic regions)
                            └── Countries[] (with region assignments)
```

---

## Data Extraction Process

### 1. File Type Detection

The extractor first detects the file content type by checking sheet names:

```python
if 'green' in self.sheet_name.lower().split():
    is_green_content = True
    product_variant = "green"
elif 'blue' in self.sheet_name.lower().split():
    is_blue_content = True
    product_variant = "blue"
```

**Supported Sheet Names:**
- "Blue ammonia projects"
- "Green ammonia projects"
- Any sheet name containing these keywords (case-insensitive)

### 2. Header Row Detection

The system scans rows to find the project table header:

```python
# Look for header containing "T/D" and either "Name" or "Project"
# This typically appears in row 0-40 of the sheet
for i in range(min(40, len(df_raw))):
    row_vals = df_raw.iloc[i].astype(str).str.lower().tolist()
    if "t/d" in row_vals and ("name" in row_vals or "project" in row_vals):
        header_idx = i
        is_project_file = True
        break
```

### 3. Column Mapping

Once the header is found, the system maps column indices:

| Column Name | Index Var | Purpose |
|---|---|---|
| Name | `idx_name` | Project/company names |
| Site | `idx_site` | Project site location |
| Country | `idx_country` | Project country |
| T/D | `idx_td` | Capacity in tons per day |
| Gross | `idx_gross` | Gross capacity (T/D + 1) |
| Merchant | `idx_merch` | Merchant capacity (T/D + 2) |
| Argus Forecast | `idx_forecast` | Forecast/target date |
| Rating | `idx_status` | Project status (Firm, Probable, Speculative) |
| Unit | `idx_unit` | Capacity unit |
| Phase | `idx_phase` | Development phase |
| EPC | `idx_epc` | Engineering, Procurement, Construction contractor |
| Gas Supply | `idx_supply` | Gas supply arrangement |
| Financing | `idx_financing` | Financing status |
| Project Completion Date | `idx_completion` | Target completion/commissioning date |
| Renewable Source | `idx_renewable_source` | Type of renewable energy (for green) |
| Renewable Supply | `idx_renewable_supply` | Renewable energy supply details |
| Electrolyser | `idx_electrolyser` | Electrolyser technology/specifications |
| Retrofit | `idx_retrofit` | Retrofit feasibility/status |
| Groundwork | `idx_groundwork` | Groundwork progress |
| Construction | `idx_construction` | Construction progress |
| Commissioning | `idx_commissioning` | Commissioning progress |

### 4. Data Row Processing

For each project row, the extractor:

1. **Extracts names** → Parse company/project names from the "Name" column
2. **Classifies entities** → Split multiple owners, identify primary operator
3. **Parses capacities** → Convert T/D values to numeric metrics
4. **Resolves geography** → Map country to canonical name and region
5. **Parses dates** → Handle multiple date formats (YYYY, ranges, H1/H2, YYYY-MM-DD)
6. **Collects metadata** → Aggregate technical specs into scope object

---

## Core Components

### green_blue_ammonia_projects.py

Main extractor file containing:

#### Class: `Caster`

Responsible for transforming raw Excel data into structured schemas.

**Key Methods:**
- `process_data(data, document_name, sheet_name, **kwargs)` → Main entry point, returns SchemaCollection
- `_parse_date_range(date_str)` → Converts various date formats to (start_date, end_date) tuples
- `_format_entity_name(raw_name)` → Standardizes entity names (lowercase, spaces → underscores)
- `_format_project_entity_name(owners, site, country)` → Creates composite entity names with parent/site/country structure
- `_clean_text(text)` → Handles None/NaN/empty values
- `_clean_value(value)` → Converts numbers, handles special text values

#### Class: `ColumnParser`

Utilities for column header parsing and entity classification.

**Key Methods:**
- `extract_date_publication_from_doc_name(doc_name)` → Parses dates from filenames (formats: 2024M10, august-2025, Q1 2024)
- `colname_to_metric_scope(text)` → Parses column headers for product/incoterm/unit information
- `classify_entity(entity_name)` → Maps entity names to canonical forms and types
- `get_product_category(product_name)` → Returns product category from referential

### SchemaCollection

Container holding all extracted data structures:

```python
@dataclass
class SchemaCollection:
    document: Optional[DocumentCreate]      # File metadata
    metrics: List[MetricCreate]             # Project records
    entities: List[EntityCreate]            # Companies/operators
    products: List[ProductCreate]           # Ammonia products
    regions: List[RegionCreate]             # Geographic regions
    countries: List[CountryCreate]          # Country records
```

---

## Classes & Object Design

### DocumentCreate

Metadata about the source Excel file:

```python
@dataclass
class DocumentCreate:
    document_name: str                      # Standardized filename
    document_path: str                      # Full file path
    source_code: str                        # "Argus"
    publication_date: Optional[date]        # When data was published
    ingestion_date: date                    # When data was ingested
    effective_start_date: Optional[date]    # Data validity period start
    effective_end_date: Optional[date]      # Data validity period end
    is_archived: bool                       # Archive flag
    sheets: List[DocumentSheetCreate]       # Processed sheets
```

### MetricCreate

Individual project record:

```python
@dataclass
class MetricCreate:
    metric_id: Optional[str]                # Unique ID (optional)
    entity_name: str                        # Project owner/operator
    country_name: Optional[str]             # Project location country
    region_name: Optional[str]              # Project location region
    product_name: str                       # "ammonia"
    metric_type: str                        # "project"
    metric_name: str                        # e.g., "project_firm"
    start_date_effect: Optional[date]       # Project start/target date
    end_date_effect: Optional[date]         # Project end/completion date
    date_publication: Optional[date]        # Document publication date
    date_insertion: date                    # Extraction date
    document_name: str                      # Source document name
    unit_of_measure: str                    # Empty for projects
    value: str                              # Empty for projects
    sheet_name: Optional[str]               # Source sheet name
    scope: Dict[str, Any]                   # Project metadata
```

### Scope Dictionary (Project Metadata)

The `scope` field contains detailed project information:

```python
scope = {
    # Identity
    "project_status": str,                  # Firm, Probable, Speculative
    "owners_raw": str,                      # Original company names list
    "additional_owners": str,               # Secondary operators
    "phase": str,                           # Development phase
    
    # Product variant
    "product_variant_display": str,         # "green" or "blue"
    
    # Capacity
    "gross_capacity": float,                # Gross capacity (kilotons/year)
    "merchant_capacity": float,             # Merchant capacity (kilotons/year)
    "unit_of_measure": str,                 # "kiloton_per_year"
    
    # Dates
    "original_target_date": str,            # Target completion date
    "forecast_date": str,                   # Argus forecast date
    
    # Technical specifications (Green)
    "progress_renewable_source": str,       # Type: Solar, Wind, Hydro, etc.
    "progress_electrolyser": str,           # Electrolyser technology/size
    "progress_renewable_supply": str,       # Renewable energy supply details
    
    # Technical specifications (Blue)
    "progress_retrofit": str,               # Retrofit feasibility
    
    # Construction progress
    "progress_groundwork": str,             # Groundwork status
    "progress_construction": str,           # Construction status
    "progress_commissioning": str,          # Commissioning status
    
    # Project governance
    "progress_epc": str,                    # EPC contractor
    "progress_gas_supply": str,             # Gas supply arrangement
    "progress_financing": str,              # Financing status
    "progress_unit": str,                   # Unit specifications
    
    # Metadata
    "progress_argus_forecast": str,         # Argus forecast data
    "progress_rating": str                  # Project rating/status
}
```

### EntityCreate

Project company/operator:

```python
@dataclass
class EntityCreate:
    entity_name: str                        # Canonical entity name
    entity_type: str                        # Type: "company", "operator"
    description: Optional[str]              # Entity description
    parent_entity: Optional[str]            # Parent company (if applicable)
    metadata_: Dict[str, Any]               # Additional metadata:
                                            # - region_name
                                            # - country_name
                                            # - site
    is_active: bool                         # Activity flag
```

### ProductCreate

Ammonia product type:

```python
@dataclass
class ProductCreate:
    product_name: str                       # "ammonia"
    product_category_name: str              # "green" or "blue"
    product_category_id: Optional[str]      # Optional category ID
    description: Optional[str]              # Product description
    is_active: bool                         # Activity flag
    is_group: bool                          # Group flag
```

---

## Data Processing & Transformation

### Date Parsing Logic

The extractor handles multiple date formats:

**Format 1: Year Only**
- Input: `"2025"`
- Output: `(2025-01-01, 2025-12-31)`

**Format 2: Half-Year**
- Input: `"H1 2025"` or `"1H-25"`
- Output H1: `(2025-01-01, 2025-06-30)`
- Output H2: `(2025-07-01, 2025-12-31)`

**Format 3: Full Date Range**
- Input: `"2024-08-15"`
- Output: `(2024-08-15, 2024-08-31)` (end of month)

**Format 4: Year Range**
- Input: `"2024-2025"`
- Output: `(2024-01-01, 2025-12-31)`

**Special Values** (ignored/null):
- "n/k", "TBC", "Post 2029", "Speculative", "Not started", "Operating", "Underway", "Complete"

### Entity Name Formatting

Raw names are standardized using strict rules:

```
Input:  "Company Name (JSV with Partner), Inc."
Step 1: Remove content in parentheses
        → "Company Name , Inc."
Step 2: Replace commas with underscores
        → "Company Name _ Inc."
Step 3: Replace spaces with underscores
        → "Company_Name_Inc"
Step 4: Lowercase
        → "company_name_inc"
```

### Value Cleaning

Numeric values are extracted and validated:

```
Valid:  "100", "100.5", "1,000", " 100 "
Invalid: "-", "n/a", "nan", "n/K", "TBC", "Speculative", "Operating"
Output:  None (skipped)
```

### Company Classification

When multiple companies are listed, the extractor:

1. Splits on commas
2. Identifies primary operator (matches referential company list with highest priority)
3. Records additional owners in metadata
4. Creates hierarchical entity structure

Example:
```
Input: "Shell, Siemens, GreenAmonia Partners"
→ Primary: "Shell" (found in referential)
→ Additional: ["Siemens", "GreenAmonia Partners"]
```

---

## Design Decisions

### 1. **One Metric per Project**

Each project is represented as a single Metric record:
- Entity: Primary operator/owner
- Product: ammonia (variant in scope)
- Scope: Contains all project metadata

**Rationale**: Enables efficient queries like "All projects by company X" or "Green ammonia projects in Europe"

### 2. **Scope as Metadata Container**

Project-specific details stored in `scope` dictionary instead of separate tables:
- Flexibility for project-specific fields
- Reduces schema complexity
- Allows future fields without schema changes

**Rationale**: Projects have highly variable metadata (some have electrolyser details, others don't)

### 3. **Referential-Backed Classification**

All company/country mappings use centralized `referential.yaml`:
- Consistency across all extractors
- Single source of truth
- Easy to update and maintain

### 4. **Separate Green/Blue Classification**

Product variant stored in scope rather than separate product records:
- Both types share base infrastructure (ammonia)
- Variant determined by sheet name
- Simplifies product hierarchy

### 5. **Date Range Handling**

Projects capture both start and end dates:
- `start_date_effect`: Target/desired start date
- `end_date_effect`: Target completion date
- Supports time-series analysis and forecasting

---

## Project Metadata

### Project Status Values

The extractor captures project status in the "Rating" column:

| Status | Meaning | Confidence |
|---|---|---|
| Firm | Project commitment confirmed | High |
| Probable | Project likely to proceed | Medium |
| Speculative | Project under consideration | Low |
| TBC | To be confirmed | Unknown |

### Development Phases

Projects track development through several phases:

| Phase | Description |
|---|---|
| Groundwork | Site preparation, permitting, planning |
| Construction | Active construction underway |
| Commissioning | Testing and startup phase |
| Operating | Fully operational |

### Technical Specifications

**For Green Ammonia:**
- Renewable source type (solar, wind, hydro, geothermal)
- Electrolyser technology and capacity
- Renewable energy supply arrangements
- Water sourcing and usage

**For Blue Ammonia:**
- Carbon capture technology
- CCS storage location
- Retrofit feasibility analysis
- CO₂ utilization options

---

## Technical Specifications

### Supported Date Formats in Filenames

The document name parser recognizes:

- YYYYMnn format: `2024M10` → October 2024
- Month-Year format: `august-2025` → August 2025
- Quarter format: `Q1 2024` or `1Q 2024` → Q1 2024

### Supported Data Provider

- **Argus Media** (primary source)
- Data source code: "Argus"

### Unit Conventions

All capacity measurements converted to **kilotons per year (kt/a)**:
- T/D (tons per day) → kt/a
- Internal calculation: T/D value × 0.365 ≈ kt/a

### Product Default

If no product variant detected from headers:
- Default product: `"ammonia"`
- Category determined from sheet name (`"green"` or `"blue"`)

---

## Examples

### Example 1: Processing Green Ammonia Project File

**Input File**: `Argus_Ammonia_Analytics_October_2024.xlsx`
**Sheet**: "Green ammonia projects"

```
Project database with headers in row 1:
  Name | Site | Country | T/D | Gross | Merchant | ... | Electrolyser | Renewable Source | etc.
```

**Processing**:
1. Sheet detected → "Green ammonia projects"
2. Header found at row 1 → Maps column indices
3. Product variant set → "green" (from sheet name)

**First Project Row**:
```
Name: "Shell Catalum"
Site: "Chile"
Country: "Chile"
T/D: 150
Gross: 150
Merchant: 100
Status: "Firm"
Target Date: "2027"
Renewable Source: "Solar"
Electrolyser: "PEM 10 MW"
```

**Output Metric**:
```python
MetricCreate(
    entity_name="shell",
    country_name="Chile",
    region_name="South America",
    product_name="ammonia",
    metric_type="project",
    metric_name="project_firm",
    start_date_effect=None,
    end_date_effect=date(2027, 12, 31),
    document_name="argus_ammonia_analytics_october_2024",
    scope={
        "project_status": "Firm",
        "owners_raw": "Shell Catalum",
        "product_variant_display": "green",
        "gross_capacity": 150.0,
        "merchant_capacity": 100.0,
        "original_target_date": "2027-01-01",
        "progress_renewable_source": "Solar",
        "progress_electrolyser": "PEM 10 MW"
    }
)
```

### Example 2: Processing Blue Ammonia Project File

**Input File**: `Argus_Ammonia_Analytics_November_2024.xlsx`
**Sheet**: "Blue ammonia projects"

**First Project Row**:
```
Name: "CF Industries, ConocoPhillips"
Site: "Tuscola"
Country: "United States"
T/D: 350
Gross: 350
Merchant: 250
Status: "Probable"
Target Date: "2026"
Retrofit: "Yes"
CCS Storage: "CO₂ Pipeline"
```

**Output Metric**:
```python
MetricCreate(
    entity_name="cf_industries",
    country_name="United States",
    region_name="North America",
    product_name="ammonia",
    metric_type="project",
    metric_name="project_probable",
    end_date_effect=date(2026, 12, 31),
    document_name="argus_ammonia_analytics_november_2024",
    scope={
        "project_status": "Probable",
        "owners_raw": "CF Industries, ConocoPhillips",
        "additional_owners": "ConocoPhillips",
        "product_variant_display": "blue",
        "gross_capacity": 350.0,
        "merchant_capacity": 250.0,
        "original_target_date": "2026-01-01",
        "progress_retrofit": "Yes"
    }
)
```

### Example 3: Multi-Owner Project with Progress Tracking

**Input Row**:
```
Name: "Yara, Norsk Hydro, DNV"
Site: "Herøya"
Country: "Norway"
Groundwork: "Complete"
Construction: "In Progress"
Commissioning: "Planned for H2 2025"
EPC: "Wood Group"
Financing: "Confirmed"
```

**Output Includes**:
```python
Entity for Yara created (primary)
Metadata: {
    "additional_owners": "Norsk Hydro, DNV",
    "country_name": "Norway",
    "region_name": "Europe",
    "site": "Herøya"
}

Scope includes progress indicators:
"progress_groundwork": "Complete",
"progress_construction": "In Progress",
"progress_commissioning": "Planned for H2 2025",
"progress_epc": "Wood Group",
"progress_financing": "Confirmed"
```

---

## Troubleshooting

### Common Issues & Solutions

#### **Issue 1: Sheet Not Recognized**

**Symptom**: `ExtractorNotFoundError: No extractor found for sheet "Green Ammonia Projects"`

**Causes**:
- Sheet name not matching recognized patterns
- Different language or typo in sheet name

**Solution**:
```yaml
# Update sheets_extractors.yaml
- name: "blue_and_green_ammonia_projects"
  description: "Blue and green ammonia projects"
  extractor_code: "green_blue_ammonia_projects.py"
  matches:
    exact:
      - value: "Green Ammonia Projects"  # <- Exact match
      - value: "Blue Ammonia Projects"
      - data_provider: argus
```

---

#### **Issue 2: Header Row Not Found**

**Symptom**: `Impossible de trouver l'en-tête` (No header found)

**Causes**:
- Project table doesn't start with expected format
- Column names not matching search criteria (missing "T/D" or "Name")
- Header beyond row 40

**Solution**:
- Verify file has standard Argus project table layout
- Check first 40 rows contain "T/D" and ("Name" or "Project")
- May need to adjust header search logic

---

#### **Issue 3: Company Name Not Recognized**

**Symptom**: Multiple companies in "Name" column but only first one used

**Causes**:
- Non-primary companies not in referential
- Company name format variation

**Solution**:
```yaml
# Update referential.yaml
companies:
  - "Shell"
  - "CF Industries"
  - "Siemens"
  - "Norsk Hydro"
```

---

#### **Issue 4: Capacity Values Not Extracted**

**Symptom**: `gross_capacity: None` and `merchant_capacity: None` in scope

**Causes**:
- Capacity columns contain text instead of numbers
- Non-numeric characters in cells (commas, units)
- Missing capacity columns in file

**Solution**:
- Ensure capacity columns (T/D, Gross, Merchant) contain numeric values
- Clean cells if they contain units like "kt/a" or "t/d"
- Verify column header names match mapping (exact case/spelling)

---

#### **Issue 5: Date Range Not Parsed**

**Symptom**: `original_target_date: None` and `end_date_effect: None`

**Causes**:
- Unexpected date format in target date column
- Special text values (TBC, Speculative, etc.)
- Missing target date column

**Solution**:
Supported formats in target date column:
- "2027" (year only)
- "H1 2025" or "1H-25" (half-year)
- "2024-08-15" (full date)
- "2024-2026" (year range)

Does NOT support:
- "Post 2029" → Skipped
- "TBC" → Skipped
- Empty cells → Skipped

---

#### **Issue 6: Entity Names Have Underscores or Special Characters**

**Symptom**: Entity names like `"company__name_inc"` have double underscores

**Causes**:
- Original names had commas and spaces together
- Parentheses content removal creates extra spaces
- Consecutive replacement operations

**Solution**:
- This is acceptable behavior (standardization)
- Regex normalization collapses multiple underscores in ColumnParser
- Names are canonicalized and deduplicated before storage

---

### Debug Tips

#### Enable Logging

```python
import logging
logger = logging.getLogger("monthly_min_max_prices_ammonia_sulphur_phosrock_caster")
logger.setLevel(logging.DEBUG)
```

#### Key Log Points

1. **Header detection**:
   ```
   [Caster] Header detected at row: X
   [Caster] Column mapping: name → idx_Y, country → idx_Z, ...
   ```

2. **Row processing**:
   ```
   [Caster] Processing project: Shell Catalum, Chile
   [Caster] Creating parent entity for owner: shell
   ```

3. **Scope compilation**:
   ```
   [Caster] Added merchant capacity metric for entity shell, 
            product ammonia, value 100.0, scope {...}
   ```

#### Manual Testing

To test extraction outside the framework:

```python
from src.excel_ingestion.extractors.implementation.green_blue_ammonia_projects import Caster
import pandas as pd

# Load raw data
df = pd.read_excel("your_file.xlsx", sheet_name="Green ammonia projects", header=None)
data = df.values

# Create caster and process
caster = Caster()
result = caster.process_data(
    data=data,
    document_name="test_file.xlsx",
    sheet_name="Green ammonia projects",
    data_provider="argus"
)

# Inspect output
print(f"Entities: {len(result.entities)}")
print(f"Metrics: {len(result.metrics)}")
print(f"Products: {len(result.products)}")
print(f"Regions: {len(result.regions)}")
```

---

## Best Practices

### For Users

1. **Ensure consistent file format**: Maintain Argus standard column structure
2. **Keep company names updated**: Update referential.yaml as new operators emerge
3. **Validate numeric values**: Ensure capacity columns contain only numbers
4. **Check date formats**: Use supported date formats in target date columns

### For Developers

1. **Test with real Argus files**: Use actual market analysis files for testing
2. **Update referential regularly**: Add new companies, countries, regions as discovered
3. **Log extensively**: Help debug issues by logging header mappings and row counts
4. **Handle edge cases**: Special text values, date ranges, multi-company projects

### For Maintainers

1. **Review date parsing** if new formats appear (quarterly, seasonal, etc.)
2. **Expand PERIOD_TOKENS** if new temporal keywords are discovered
3. **Monitor scope dictionary** for new technical fields from Argus reports
4. **Keep referential.yaml current** with emerging ammonia project operators

---

## Related Documentation

- [Price Extractors README](README_PRICE_EXTRACTORS.md)
- [Trade Extractors README](README_TRADE_EXTRACTORS.md)
- [Vessel Trackers README](README_VESSEL_TRACKERS.md)
- [Main Data Ingestion README](../Data_Acquisition_All_README.md)
- Referential Configuration: `config/referential.yaml`
- Extractor Configuration: `sheets_extractors.yaml`

---

## Version History

- **v1.0** (2024-Q4): Initial green & blue ammonia projects documentation
  - Documented project extraction pipeline
  - Added troubleshooting section
  - Provided comprehensive examples

---

## Support & Feedback

For issues, questions, or feature requests:
- Check troubleshooting section above
- Review logs for header/column mapping issues
- Test with sample Argus files
- Contact data engineering team for schema updates
