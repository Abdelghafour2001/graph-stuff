# Vessel Trackers Extractors Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture & Data Flow](#architecture--data-flow)
3. [Vessel Extractors](#vessel-extractors)
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

The **Vessel Trackers Extraction System** is a template-driven data ingestion pipeline designed to extract, parse, and normalize maritime vessel movement data from Excel files. The system processes vessel shipment information including cargo loads, discharges, vessel specifications, and logistics routes, transforming raw spreadsheet data into structured database schemas.

### What is Vessel Tracking?

Vessel tracking refers to the **automated extraction and structuring of maritime logistics data** from Excel shipment manifests, including:

- **Vessel identification**: Ship names, types, capacity (Dead Weight Tonnage)
- **Cargo movements**: Products loaded and discharged at ports
- **Route information**: Load ports, discharge ports, sailing dates, ETAs
- **Business entities**: Shippers, receivers, suppliers, charterers
- **Geographic data**: Countries, regions, port locations
- **Temporal events**: Sailing dates, discharge dates, event sequences

### Overall Workflow

```
Excel File (Vessel Tracking Manifest)
       ↓
[Sheet Detection] → Match sheet name against templates in sheets_extractors.yaml
       ↓
[Load Extractor] → Dynamically load appropriate Caster from implementation/
                   E.g., vessel_tracker.py or vessel_tracker_ammonia.py
       ↓
[Parse Headers]  → Extract column names and identify data fields:
                   - Vessel name, DWT, Product, Volume
                   - Load/Discharge ports and dates
                   - Shippers, receivers, suppliers
       ↓
[Process Rows]   → For each data row:
                   - Parse vessel specifications
                   - Clean and normalize entity names
                   - Classify ports and locations
                   - Extract dates (sailed, ETA)
                   - Parse volumes and products
       ↓
[Entity Classification] → Using referential.yaml:
                   - Country mapping → Region assignment
                   - Port identification
                   - Product categorization
                   - Vessel entity creation
       ↓
[Database Ready] → SchemaCollection containing:
                   - Document metadata
                   - List of Metrics (shipment events with cargo volumes)
                   - List of Entities (vessels, ports, companies)
                   - List of Products (commodities)
                   - List of Regions and Countries
       ↓
[Persistence]    → Loaded into PostgreSQL database via repositories
```

---

## Architecture & Data Flow

### Component Hierarchy

```
extractors/
├── loader.py                          # Sheet matcher & extractor resolver
├── utils.py                           # Dynamic loading & standardization utilities
├── sheets_extractors.yaml             # Configuration: sheet name → extractor mapping
└── implementation/
    ├── vessel_tracker.py              # Main vessel tracker (Nitrates, Potash, etc.)
    ├── vessel_tracker_ammonia.py      # Ammonia-specific vessel tracker
    └── raw_vessel_data.py             # Raw vessel import data extractor
```

### Data Classification Hierarchy

```
RawExcelData ──[Caster]──> SchemaCollection
                            ├── Document (1 per file)
                            │   └── publication_date, effective_start/end_date
                            │
                            ├── Metrics[] (multiple shipment events)
                            │   ├── product_name (e.g., ammonia, urea, sulfur)
                            │   ├── entity_name (vessel name)
                            │   ├── value (cargo volume in kilotons)
                            │   ├── unit_of_measure (kt)
                            │   ├── scope metadata (ports, routes, entities)
                            │   └── dates (sailed, ETA)
                            │
                            ├── Entities[] (unique participants in supply chain)
                            │   ├── Vessels (type='vessel', metadata: DWT)
                            │   ├── Ports (type='port')
                            │   ├── Suppliers (type='supplier')
                            │   ├── Shippers (type='shipper')
                            │   ├── Receivers (type='receiver')
                            │   └── Other companies/locations
                            │
                            ├── Products[] (unique commodities)
                            │   └── product_category_name (e.g., fertilizer_ammonia)
                            │
                            ├── Regions[] (geographic macro-regions)
                            │
                            └── Countries[] (country entities with region mapping)
```

### Key Flow Points

1. **Sheet Matching** (loader.py)
   - Configuration-driven matching via `sheets_extractors.yaml`
   - Supports exact and regex pattern matching
   - Routes to appropriate Caster implementation

2. **Data Ingestion** (Caster.process_data)
   - Converts Excel array to pandas DataFrame
   - Extracts document metadata
   - Iterates through rows for processing

3. **Row-Level Processing** (Caster.process_row)
   - Parses vessel specifications and DWT
   - Extracts load and discharge ports
   - Identifies products and volumes
   - Classifies entities using referential mappings

4. **Entity Normalization** (ColumnParser.classify_entity)
   - Maps entity names to canonical types
   - Links entities to geographic regions/countries
   - Handles aliases and standardization

5. **Schema Collection**
   - Aggregates parsed entities, products, metrics
   - Deduplicates entities and products
   - Produces output ready for database persistence

---

## Vessel Extractors

### 1. Vessel Tracker (vessel_tracker.py)

**Supported Commodities:**
- Nitrates
- Potash
- Sulfur / Sulfuric Acid
- Phosphates
- Urea

**Supported Sheets:**
```yaml
matches:
  exact:
    - value: "Nitrates"
      data_provider: sp
    - value: "Potash"
      data_provider: sp
    - value: "Sulfur"
      data_provider: sp
    - value: "Phosphates"
      data_provider: sp
    - value: "Urea"
      data_provider: sp
    - value: "Sulfuric Acid"
      data_provider: sp
```

**Input Schema:**
| Column | Type | Example | Purpose |
|--------|------|---------|---------|
| Vessel_1 | str | "Ever Given" | Vessel identifier |
| DWT (mt)_1 | float | 20000 | Deadweight tonnage capacity |
| Loadport_1 | str | "Rotterdam" | Port where cargo loaded |
| Disport_1 | str | "Singapore" | Port where cargo discharged |
| Country_1 | str | "Netherlands" | Country of load port |
| Country_2 | str | "Singapore" | Country of discharge port |
| Region_1 | str | "Europe" | Geographic region of load port |
| Region_2 | str | "Asia" | Geographic region of discharge port |
| Product_1 | str | "ammonia" | Commodity type |
| Sailed Date (dd/mm/yy)_1 | str | "15/03/2024" | Date vessel sailed |
| Volume_* | float | 15000 | Cargo volume in kilotons |

**Output Metrics:**
- **Metric Type**: "vessel"
- **Metric Name**: "vessel_loads_from_port"
- **Scope Fields**:
  - `from`: Load port name
  - `to`: Discharge port name
  - `vessel_name`: Vessel identifier
  - `type_of_vessel`: Vessel classification
  - `incoterm`: Trade terms (if available)

---

### 2. Vessel Tracker Ammonia (vessel_tracker_ammonia.py)

**Supported Commodity:**
- Ammonia

**Supported Sheets:**
```yaml
matches:
  exact:
    - value: "Ammonia"
      data_provider: sp
```

**Key Differences from vessel_tracker.py:**

| Aspect | vessel_tracker.py | vessel_tracker_ammonia.py |
|--------|-------------------|---------------------------|
| **Commodity Focus** | Multi-commodity | Ammonia-specific |
| **Entity Types** | Ports, vessels | Ports, vessels, suppliers, shippers, receivers |
| **Data Structure** | Simple load-discharge pairs | Complex supply chain with multiple participants |
| **Metric Creation** | Single load/discharge event | Supplier→Vessel→Receiver chain tracking |
| **Date Tracking** | Single sailed/ETA | Multiple date columns for complex journeys |
| **Entity Deduplication** | Basic | Advanced with role-based classification |

**Input Schema (Extended):**
| Column | Type | Purpose |
|--------|------|---------|
| Vessel_1 | str | Vessel name |
| DWT (mt)_1 | str | Deadweight tonnage |
| Product_1 | str | Commodity (ammonia) |
| Volume_* | float | Cargo volume at each stage |
| Sailed Date (dd/mm/yy)_1 | str | Date vessel sailed from load port |
| ETA_* | str | Estimated time of arrival |
| Shipper_* | str | Company responsible for shipment |
| Supplier_* | str | Commodity source/producer |
| Receiver_* | str | Ultimate cargo receiver |
| Loadport_* | str | Port of loading |
| Disport_* | str | Port of discharge |
| Country_* | str | Country of port |
| Region_* | str | Geographic region |

**Output Metrics:**
- **Supplier → Vessel Load**: Commodity picked up from supplier
- **Vessel → Receiver Discharge**: Commodity delivered to receiver
- **Volume Tracking**: Delta calculations at each stage

---

## Core Components

### ColumnParser Class

Static utility class providing parsing and classification functions.

#### Key Methods

**`clean_date(date_str) → date`**
- Converts various date formats to Python `date` object
- **Formats supported**:
  - `YYYY-MM-DD` (ISO)
  - `YYYY` (returns Jan 1)
  - `YYYYQn` or `YYYY Qn` (quarter, returns first month)
  - `YYYYMnn` (month, returns first day)
  - `dd-mm-yyyy` or `dd/mm/yyyy` (day-based)
- **Special values**: Converts "TBD", "TBC", "NG" to None

```python
# Examples
ColumnParser.clean_date("2024-03-15")  # date(2024, 3, 15)
ColumnParser.clean_date("2024Q1")      # date(2024, 1, 1)
ColumnParser.clean_date("2024M03")     # date(2024, 3, 1)
```

**`clean_float(value) → Optional[float]`**
- Sanitizes float values with flexible parsing
- Handles commas as decimal separators
- Filters non-numeric characters
- Returns None for invalid/special values (NM, etc.)

```python
# Examples
ColumnParser.clean_float("1,234.56")   # 1234.56
ColumnParser.clean_float("15 000")     # 15000.0
ColumnParser.clean_float("NM")         # None
```

**`classify_entity(entity_name) → Dict[str, Optional[str]]`**
- Rich entity classification using referential YAML
- **Returns**:
  ```python
  {
    "entity_type": "company|country|region|city|vessel|port|other",
    "canonical_name": "<standardized name>",
    "country_name": "<country if applicable>",
    "region_name": "<macro-region if applicable>"
  }
  ```
- **Lookup order**:
  1. Company names (from COMPANIES set)
  2. Country aliases (from COUNTRY_ALIASES)
  3. Standard countries
  4. Regions and region aliases
  5. Cities and city aliases
  6. Vessels
  7. Fallback: "other"

```python
# Examples
ColumnParser.classify_entity("Rotterdam")
# {
#   "entity_type": "port",
#   "canonical_name": "rotterdam",
#   "country_name": "netherlands",
#   "region_name": "europe"
# }

ColumnParser.classify_entity("Ever Given")
# {
#   "entity_type": "vessel",
#   "canonical_name": "ever_given",
#   "country_name": None,
#   "region_name": None
# }
```

**`extract_product_grade_from_colname(name) → Optional[ProductGrade]`**
- Extracts fertilizer grades from column headers
- **Supported patterns**:
  - BPL: "73-75% BPL"
  - P2O5/P205: "18-20% P2O5"
  - NPK: "12-46-0" (N-P-K-S)
  - NP: "12:52" (N:P)
  - Generic %: "32%"

```python
# Examples
ColumnParser.extract_product_grade_from_colname("12-46-0")
# ProductGrade(nitrogen=12.0, phosphate=46.0, potash=0.0, sulfur=0.0)
```

**`extract_date_publication_from_doc_name(doc_name) → Optional[date]`**
- Extracts publication date from Excel filename
- **Formats**:
  - YYYYMnn: "2024M03"
  - Month-year: "august-2025"
  - Quarter format: "Q1 2024", "1Q 2024"
- Returns first day of period encountered

```python
# Examples
ColumnParser.extract_date_publication_from_doc_name("argus_ammonia_2024M03")
# date(2024, 3, 1)

ColumnParser.extract_date_publication_from_doc_name("vessel_tracker_Q1_2025")
# date(2025, 1, 1)
```

---

### Caster Class

Main transformation engine for converting Excel data to structured schemas.

#### Constructor
```python
def __init__(self) -> None:
    self.cleaner = CleanerService()
    self.schema_collection: Optional[SchemaCollection] = None
    self.reset_state()
```

#### Key Methods

**`process_data(data, document_name, document_path, **kwargs) → SchemaCollection`**

Main entry point for data extraction pipeline.

**Parameters:**
- `data: np.ndarray` - Raw Excel data as 2D array
- `document_name: str` - Source Excel filename
- `document_path: Optional[str]` - Full file path
- `**kwargs` - Additional parameters:
  - `sheet_name` - Excel sheet name
  - `frequency` - Data frequency (optional)

**Returns:** `SchemaCollection` - Structured output ready for database

**Process:**
1. Convert numpy array to pandas DataFrame
2. Parse document metadata (publication date, effective date range)
3. Extract and validate vessel-specific columns
4. Iterate through rows for data extraction
5. Track success/error metrics

```python
# Typical usage
caster = Caster()
schema_collection = caster.process_data(
    data=excel_array,
    document_name="vessel_tracker_Q1_2024.xlsx",
    sheet_name="Ammonia",
    frequency="quarterly"
)

# Access results
for metric in schema_collection.metrics:
    print(f"Vessel: {metric.entity_name}, Volume: {metric.value}")
```

**`process_row(row, document_name) → None`**

Processes individual shipment row.

**Logic Flow:**
1. Extract product name from row
2. Parse vessel specifications (name, DWT)
3. Identify load port with country/region
4. Identify discharge port with country/region
5. Extract volume and dates
6. Create/reference entities (vessel, ports, supplier, receiver)
7. Create product entity (if new)
8. Generate metrics for shipment event
9. Append to schema collection

**Key Transformations:**
```python
# Raw row data
{
    'Vessel_1': 'Ever Given',
    'Product_1': 'ammonia',
    'Volume_1': 18000,
    'Loadport_1': 'Rotterdam',
    'Disport_1': 'Singapore',
    'DWT (mt)_1': 20000,
    'Sailed Date (dd/mm/yy)_1': '15/03/2024'
}

# Transforms to entities and metrics:
# Entity: ever_given (vessel, DWT=20000)
# Entity: rotterdam (port, country=netherlands, region=europe)
# Entity: singapore (port, country=singapore, region=asia)
# Product: ammonia
# Metric: 18000 kt ammonia on ever_given from rotterdam to singapore
```

#### State Management

**`reset_state() → None`**

Initializes tracking structures for new document:
- `errors: List[str]` - Collection of processing errors
- `warnings: List[str]` - Processing warnings
- `handled_rows: int` - Total rows processed
- `successful_rows: int` - Successfully processed rows
- `sheet_name: str` - Current Excel sheet name
- `existing_entities: Dict` - Deduplication cache for entities
- `existing_products: Dict` - Deduplication cache for products
- `existing_regions: Dict` - Deduplication cache for regions
- `existing_countries: Dict` - Deduplication cache for countries

---

### SchemaCollection Class

Container for parsed data structures.

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

**Fields:**

| Field | Type | Purpose |
|-------|------|---------|
| document | DocumentCreate | Source file metadata |
| metrics | List[MetricCreate] | Shipment events (volumes, prices, quantities) |
| entities | List[EntityCreate] | Supply chain participants (vessels, ports, companies) |
| products | List[ProductCreate] | Commodities processed |
| regions | List[RegionCreate] | Geographic macro-regions |
| countries | List[CountryCreate] | Country entities with region mapping |

**Usage:**
```python
schema = SchemaCollection()

# Add a metric (shipment event)
schema.metrics.append(MetricCreate(
    entity_name="ever_given",
    product_name="ammonia",
    value="18000",
    unit_of_measure="kt",
    metric_name="vessel_loads_from_port",
    scope={"from": "rotterdam", "to": "singapore"},
    start_date_effect=date(2024, 3, 15),
    end_date_effect=date(2024, 3, 15)
))

# Persist to database
repo.save_schema_collection(schema)
```

---

## Classes & Object Design

### MetricCreate Schema

Represents a shipment event or movement.

```python
@dataclass
class MetricCreate:
    entity_name: str                      # e.g., "ever_given" (vessel)
    product_name: str                     # e.g., "ammonia"
    metric_name: str                      # e.g., "vessel_loads_from_port"
    value: str                            # Volume or quantity
    unit_of_measure: str                  # e.g., "kiloton"
    start_date_effect: date               # When the load occurred
    end_date_effect: date                 # When unload occurred
    
    # Metadata
    region_name: Optional[str]            # Geographic region
    country_name: Optional[str]           # Country
    metric_type: str                      # e.g., "vessel" or "financial"
    document_name: str                    # Source document
    date_publication: date                # When document was published
    date_insertion: date                  # When parsed
    sheet_name: Optional[str]             # Excel sheet name
    
    # Rich context
    scope: Dict[str, Any]                 # Additional context
    # Example scope:
    # {
    #   "from": "rotterdam",
    #   "to": "singapore",
    #   "type_of_vessel": "container_ship",
    #   "incoterm": "cif",
    #   "entity_origin": "supplier_name",
    #   "entity_destination": "receiver_name"
    # }
```

### EntityCreate Schema

Represents a supply chain participant.

```python
@dataclass
class EntityCreate:
    entity_name: str                      # e.g., "rotterdam" or "ever_given"
    entity_type: str                      # vessel|port|supplier|receiver|shipper|company|country
    
    # Relationships
    parent_entity: Optional[str]          # Parent entity (for hierarchies)
    description: Optional[str]            # Human-readable description
    
    # Status and metadata
    is_active: bool = True
    metadata_: Dict[str, Any] = field(default_factory=dict)
    # Example metadata:
    # {
    #   "dwt_mt": 20000,
    #   "region": "europe",
    #   "country": "netherlands"
    # }
```

### ProductCreate Schema

Represents a commodity.

```python
@dataclass
class ProductCreate:
    product_name: str                     # e.g., "ammonia"
    product_category_name: str            # e.g., "fertilizer_ammonia"
    product_category_id: Optional[int]
    
    # Status and metadata
    is_active: bool = True
    is_group: bool = False
    description: Optional[str]
```

### RegionCreate & CountryCreate Schemas

Geographic entities.

```python
@dataclass
class RegionCreate:
    region_name: str                      # e.g., "europe", "middle_east"
    parent_region_name: Optional[str]
    description: Optional[str]
    is_active: bool = True

@dataclass
class CountryCreate:
    country_name: str                     # e.g., "netherlands"
    country_code: Optional[str]           # ISO codes
    region_name: Optional[str]            # Macro-region assignment
    genc_code: Optional[str]
    description: Optional[str]
    is_active: bool = True
```

---

## Data Processing & Transformation

### 1. Vessel Name Normalization

**Raw Input:**
```
"Ever Given", "EVER GIVEN", "ever given", "Ever-Given"
```

**Transformation via CleanerService.clean_entity_name():**
```python
def clean_entity_name(name: str) -> str:
    """
    - Lowercase
    - Remove special characters
    - Replace spaces with underscores
    - Collapse multiple underscores
    """
    return "ever_given"  # Canonical form
```

**Deduplication:** Stored in `existing_entities` dict to prevent duplicate rows

---

### 2. Port Classification

**Raw Input:**
```
"Rotterdam", "Singapore", "Port of Rotterdam"
```

**Transformation via ColumnParser.classify_entity():**

1. **Standardize**: lowercase, remove accents → "rotterdam"
2. **Lookup in referential.yaml**:
   - Check CITIES set
   - Check COUNTRY_ALIASES
   - Check COUNTRIES
   - Check REGIONS
3. **Assignment**:
   - entity_type: "port"
   - country_name: "netherlands" (from referential mapping)
   - region_name: "europe" (from COUNTRY_REGION_MAPPING)

**Result Entities Created:**
```python
# Port entity
EntityCreate(
    entity_name="rotterdam",
    entity_type="port",
    metadata_={"region": "europe", "country": "netherlands"}
)

# Country entity (if new)
CountryCreate(
    country_name="netherlands",
    region_name="europe"
)

# Region entity (if new)
RegionCreate(
    region_name="europe"
)
```

---

### 3. Product Parsing

**Raw Input:**
```
"Ammonia", "ammonia_urea", "MAP/NP 10.45"
```

**Transformation:**

1. **Split by "/" separator:**
   - "MAP/NP 10.45" → ["MAP", "NP 10.45"]

2. **Grade extraction (if numeric pattern found):**
   - "NP 10.45" → grade="10-45", base="np"
   - Result: product_name="np", grade="10-45"

3. **Product category lookup:**
   - Input: "ammonia"
   - Lookup in PRODUCT_CATEGORY_BY_PRODUCT: "fertilizer_ammonia"
   - If not found: category="unclassified" with warning

4. **Deduplication:**
   - Store in existing_products to prevent duplicates

**Result Products Created:**
```python
ProductCreate(
    product_name="ammonia",
    product_category_name="fertilizer_ammonia",
    is_group=False
)
```

---

### 4. Volume Tracking (Ammonia Extractor Only)

**Raw Input (Multi-Stage Transfer):**
```
Volume_1: 15000 kt (loaded at port A)
Volume_2: 500 kt (transferred at port B)
Volume_3: 14500 kt (delivered at final destination)
```

**Transformation - Delta Calculation:**

```python
# Initial value
value_delta = [15000]

# Stage 1: Load event
value_delta[0] = 15000  # Full load

# Stage 2: Transfer (subtract)
value_delta.append(value_delta[-1] - 500)  # 14500 in transit

# Stage 3: Discharge (subtract)
value_delta.append(value_delta[-1] - 14500)  # 0 discharged

# Result
value_delta = [15000, 14500, 0]
```

**Application to Metrics:**
- Each delta value creates a separate Metric entry
- Tracks progression of cargo through supply chain
- Maintains chronological order via date sort

---

### 5. Date Parsing Strategy

**Multi-Format Input Handling:**

| Raw Input | Parsed Date | Logic |
|-----------|-------------|-------|
| "15/03/2024" | 2024-03-15 | dd/mm/yyyy regex |
| "2024-03-15" | 2024-03-15 | ISO format |
| "2024" | 2024-01-01 | Year only → Jan 1 |
| "2024Q1" | 2024-01-01 | Quarter → first month |
| "2024M03" | 2024-03-01 | Month → day 1 |
| "TBD" | None | Special value → None |

**Date Fields in Result:**
- `start_date_effect`: Sailed date
- `end_date_effect`: ETA (or same as sailed if no ETA)
- `date_publication`: Extracted from document name

---

### 6. Entity Chain Resolution (Ammonia)

**Complex Supply Chain Model:**

```
Supplier ──→ Shippers ──→ Vessel ──→ Receivers
  (source)     (transport)  (convey)   (destination)
```

**Row-by-Row Processing:**

```python
# Extract participant lists
suppliers = [row.get(f'Supplier_{i}') for i in range(n_suppliers)]
shippers = [row.get(f'Shipper_{i}') for i in range(n_shippers)]
receivers = [row.get(f'Receiver_{i}') for i in range(n_receivers)]

# Create entities with role classification
for sup in suppliers:
    EntityCreate(
        entity_name=clean_entity_name(sup),
        entity_type="supplier"  # Role-based
    )

for ship in shippers:
    EntityCreate(
        entity_name=clean_entity_name(ship),
        entity_type="shipper"  # Role-based
    )

for rec in receivers:
    EntityCreate(
        entity_name=clean_entity_name(rec),
        entity_type="receiver"  # Role-based
    )

# Create metrics linking the chain
MetricCreate(
    entity_name=vessel_name,
    scope={
        "from": load_port,
        "to": discharge_port,
        "supplier": supplier,
        "shipper": shipper,
        "receiver": receiver
    }
)
```

---

### 7. Referential-Driven Normalization

**referential.yaml Structure:**

```yaml
companies:
  - "bp"
  - "shell"
  - "chevron"

countries:
  - "netherlands"
  - "singapore"
  - "saudi_arabia"

country_aliases:
  "nl": "netherlands"
  "sg": "singapore"
  "sa": "saudi_arabia"

country_region_mapping:
  "netherlands": "europe"
  "singapore": "asia"
  "saudi_arabia": "middle_east"

regions:
  - "europe"
  - "asia"
  - "middle_east"

cities:
  - "rotterdam"
  - "singapore"
  - "ras_tanura"

products_by_category:
  fertilizer_ammonia:
    - "ammonia"
  fertilizer_urea:
    - "urea"
  fertilizer_potash:
    - "potash"
  ...

physical_form:
  - "liquid"
  - "solid"
  - "gas"
```

**Lookup Cascade:**
1. Exact match in COMPANIES
2. Match in COUNTRY_ALIASES → get canonical country
3. Match in COUNTRIES directly
4. Match in REGION_ALIASES → get canonical region
5. Match in REGIONS directly
6. Match in CITIES
7. Fallback: classification as "other"

---

## Design Decisions

### 1. **Template-Driven Extraction**

**Decision:** Use separate Caster classes per commodity type

**Rationale:**
- **Flexibility**: Ammonia supply chains differ significantly from simple potash shipments
- **Maintainability**: Commodity-specific logic stays isolated
- **Extensibility**: Easy to add new commodity extractors without affecting existing ones

**Tradeoff:**
- Code duplication between `vessel_tracker.py` and `vessel_tracker_ammonia.py`
- Mitigated by sharing ColumnParser utility class

---

### 2. **Entity Deduplication via In-Memory Dict**

**Decision:** Track existing entities in `existing_entities` dictionary during processing

```python
if vessel_name and vessel_name not in self.existing_entities:
    ent = EntityCreate(...)
    self.existing_entities[vessel_name] = ent
    self.schema_collection.entities.append(ent)
```

**Rationale:**
- **Performance**: O(1) lookup prevents duplicate creation
- **Consistency**: Ensures single entity per name within document
- **Ordering**: Preserves first-encountered entity definition

**Alternative Considered:** Database-level unique constraints
- Rejected: Would require database round-trips during extraction

---

### 3. **Scope as Generic Dictionary**

**Decision:** Use `scope: Dict[str, Any]` for rich contextual metadata

**Rationale:**
- **Extensibility**: New fields can be added without schema changes
- **Context**: Preserves original data relationships (ports, routes, roles)
- **Query Flexibility**: Allows JSON-path queries in PostgreSQL

**Example Scope Values:**
```python
{
    "from": "rotterdam",
    "to": "singapore",
    "vessel_name": "ever_given",
    "type_of_vessel": "container_ship",
    "incoterm": "cif",
    "supplier": "bp",
    "shipper": "shell",
    "receiver": "chevron",
    "dwt_mt": 20000
}
```

---

### 4. **Date-Based Metric Sorting (Ammonia)**

**Decision:** Sort metrics chronologically by sailed/ETA dates

```python
combined_sorted = sorted(combined, key=lambda x: x[5])  # date index
```

**Rationale:**
- **Causality**: Ensures load events precede discharge events
- **Accuracy**: Prevents temporal inconsistencies in supply chain
- **Traceability**: Creates auditable event sequence

---

### 5. **Metadata Fields in Entities**

**Decision:** Store DWT and geographic info in Entity.metadata_ field

```python
EntityCreate(
    entity_name="ever_given",
    entity_type="vessel",
    metadata_={
        "dwt_mt": 20000,
        "region": "europe",
        "country": "netherlands"
    }
)
```

**Rationale:**
- **Flexibility**: JSON field in PostgreSQL
- **Context**: Preserves domain-specific attributes
- **Query**: Enable filtering by capacity, region, etc.

**Alternative:** Separate VesselEntity class
- Rejected: Overly complex for simple attribute storage

---

### 6. **Product Categorization via Referential**

**Decision:** Map product names to categories from YAML referential

```python
category_name = ColumnParser.get_product_category(product_name)
# Lookup in PRODUCT_CATEGORY_BY_PRODUCT
```

**Rationale:**
- **Centralization**: Single source of truth for categories
- **Maintainability**: Non-developers can update categories via YAML
- **Consistency**: Prevents ad-hoc categorization

**Fallback:** Default to "unclassified" with warning
- Allows extraction to continue if category not found
- Alerts operators to missing referential data

---

## Extensibility

### Adding a New Vessel Extractor

**Step 1: Create new extractor file**

Create `src/excel_ingestion/extractors/implementation/vessel_tracker_<commodity>.py`:

```python
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional, List, Dict, Any

from src.excel_ingestion.services.cleaner import CleanerService
from src.excel_ingestion.persistence.schemas import (
    DocumentCreate,
    MetricCreate,
    EntityCreate,
    ProductCreate,
    SchemaCollection
)

logger = logging.getLogger("vessel_tracker_<commodity>")

# Load referential
# ... (same pattern as vessel_tracker.py)

@dataclass
class SchemaCollection:
    # ... (same pattern)
    pass

class ColumnParser:
    # ... (reuse or customize) ...
    pass

class Caster:
    """Caster for <commodity> vessel tracking."""

    def __init__(self) -> None:
        self.cleaner = CleanerService()
        self.schema_collection: Optional[SchemaCollection] = None
        self.reset_state()

    def reset_state(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.handled_rows: int = 0
        self.successful_rows: int = 0
        self.sheet_name: str = ""
        self.existing_entities: Dict = {}
        self.existing_products: Dict = {}
        self.existing_regions: Dict = {}
        self.existing_countries: Dict = {}

    def start_casting_sequence(self) -> None:
        self.reset_state()
        self.schema_collection = SchemaCollection()

    def raw_data_to_df(self, data) -> pd.DataFrame:
        """Convert Excel array to DataFrame."""
        # Implement conversion logic specific to your template
        pass

    def process_data(self, data, document_name, document_path=None, **kwargs):
        """Main entry point."""
        self.start_casting_sequence()
        self.sheet_name = kwargs.get("sheet_name", "").strip()

        # Convert to DataFrame
        df = self.raw_data_to_df(data)

        # Create document
        doc = DocumentCreate(
            document_name=CleanerService.standardize_document_name(document_name),
            document_path=document_path or document_name,
            source_code="argus",  # or your source
            publication_date=date.today(),
            ingestion_date=date.today()
        )
        self.schema_collection.document = doc

        # Process rows
        for idx, row in df.iterrows():
            self.handled_rows += 1
            try:
                self.process_row(row, doc.document_name)
                self.successful_rows += 1
            except Exception as e:
                self.errors.append(str(e))
                logger.error(f"Error processing row {idx}: {e}")

        return self.schema_collection

    def process_row(self, row, document_name: str) -> None:
        """Process individual row."""
        # Step 1: Extract product
        product_name = row.get('product_col', 'unknown')

        # Step 2: Extract vessel
        vessel_name = row.get('vessel_col')
        if vessel_name and vessel_name not in self.existing_entities:
            ent = EntityCreate(
                entity_name=vessel_name,
                entity_type='vessel',
                metadata_=dict(...)
            )
            self.existing_entities[vessel_name] = ent
            self.schema_collection.entities.append(ent)

        # Step 3: Extract geographic entities
        # ... (similar pattern)

        # Step 4: Create metrics
        metric = MetricCreate(
            entity_name=vessel_name,
            product_name=product_name,
            value=str(row.get('volume')),
            unit_of_measure='kiloton',
            metric_name='vessel_loads_from_port',
            metric_type='vessel',
            start_date_effect=row_date,
            end_date_effect=row_date,
            document_name=document_name,
            date_publication=date.today(),
            date_insertion=date.today(),
            scope={...}
        )
        self.schema_collection.metrics.append(metric)
```

**Step 2: Register in sheets_extractors.yaml**

```yaml
extractors:
  - name: "vessel_tracker_<commodity>"
    description: "Vessel tracker for <commodity>"
    extractor_code: "vessel_tracker_<commodity>.py"
    matches:
      exact:
        - value: "<SheetName>"
          data_provider: sp
```

**Step 3: Update referential.yaml (if needed)**

Add product categories:
```yaml
products_by_category:
  fertilizer_<commodity>:
    - "<commodity>"
    - "<commodity>_variant1"
    - "<commodity>_variant2"
```

**Step 4: Test**

```python
from src.excel_ingestion.extractors.implementation.vessel_tracker_<commodity> import Caster

caster = Caster()
schema = caster.process_data(
    data=excel_array,
    document_name="vessel_tracker_<commodity>_2024Q1.xlsx",
    sheet_name="<SheetName>"
)

# Verify output
print(f"Metrics: {len(schema.metrics)}")
print(f"Entities: {len(schema.entities)}")
print(f"Errors: {schema_collection.errors if hasattr(caster, 'schema_collection') else 'N/A'}")
```

---

### Maintaining Consistency Across Extractors

**1. Use shared ColumnParser methods**
- Don't reimplement `clean_date()`, `clean_float()`, etc.
- Ensures consistent date/number parsing across all extractors

**2. Update referential.yaml centrally**
- Add new products/countries/regions to single YAML
- Extractors automatically pick up new data

**3. Follow naming conventions**
- Entity names: snake_case, lowercase
- Product names: match categorization from YAML
- Metric names: <type>_<operation>, e.g., "vessel_loads_from_port"

**4. Document commodity-specific logic**
- Add docstrings explaining template differences
- Include examples of expected input/output

**5. Code review checklist**
- [ ] Uses `CleanerService` for standardization
- [ ] Implements deduplication via existing_* dicts
- [ ] Handles None/NaN values correctly
- [ ] Logs warnings for missing referential entries
- [ ] Includes error handling in process_row
- [ ] Scope dictionary captures relevant context

---

## Examples

### Example 1: Ammonia Shipment Processing

**Raw Excel Data:**

| Vessel_1 | DWT | Product_1 | Volume_1 | Volume_2 | Sailed Date | ETA | Loadport | Disport | Supplier | Shipper | Receiver |
|----------|-----|-----------|----------|----------|-------------|-----|---------|---------|----------|---------|----------|
| Ever Given | 20000 | Ammonia | 15000 | 14500 | 15/03/2024 | 20/04/2024 | Rotterdam | Singapore | BP | Shell | Chevron |

**Processing Steps:**

1. **Vessel Entity Creation:**
   ```python
   EntityCreate(
       entity_name="ever_given",
       entity_type="vessel",
       metadata_={"dwt_mt": 20000}
   )
   ```

2. **Port Entity Creation:**
   ```python
   # Rotterdam
   EntityCreate(
       entity_name="rotterdam",
       entity_type="port",
       metadata_={"country": "netherlands", "region": "europe"}
   )
   
   # Singapore (similar)
   ```

3. **Participant Entity Creation:**
   ```python
   EntityCreate(entity_name="bp", entity_type="supplier")
   EntityCreate(entity_name="shell", entity_type="shipper")
   EntityCreate(entity_name="chevron", entity_type="receiver")
   ```

4. **Product Creation:**
   ```python
   ProductCreate(
       product_name="ammonia",
       product_category_name="fertilizer_ammonia"
   )
   ```

5. **Metric Creation (with delta calculation):**
   ```python
   # Load event
   MetricCreate(
       entity_name="ever_given",
       product_name="ammonia",
       value="15000",
       unit_of_measure="kt",
       metric_name="supplier_vessel_load",
       scope={
           "from": "rotterdam",
           "to": "singapore",
           "supplier": "bp",
           "shipper": "shell",
           "event": "load"
       },
       start_date_effect=date(2024, 3, 15),
       end_date_effect=date(2024, 3, 15)
   )

   # Intermediate transfer
   MetricCreate(
       entity_name="ever_given",
       product_name="ammonia",
       value="500",
       unit_of_measure="kt",
       metric_name="transfer_event",
       scope={...},
       start_date_effect=date(2024, 4, 1),
       end_date_effect=date(2024, 4, 1)
   )

   # Discharge event
   MetricCreate(
       entity_name="ever_given",
       product_name="ammonia",
       value="14500",
       unit_of_measure="kt",
       metric_name="receiver_vessel_discharge",
       scope={
           "from": "rotterdam",
           "to": "singapore",
           "receiver": "chevron",
           "event": "discharge"
       },
       start_date_effect=date(2024, 4, 20),
       end_date_effect=date(2024, 4, 20)
   )
   ```

**Final SchemaCollection:**
```python
SchemaCollection(
    document=DocumentCreate(...),
    metrics=[...3 metrics...],
    entities=[
        ever_given (vessel),
        rotterdam (port),
        singapore (port),
        netherlands (country),
        singapore_country (country),
        europe (region),
        asia (region),
        bp (supplier),
        shell (shipper),
        chevron (receiver)
    ],
    products=[ammonia],
    regions=[europe, asia],
    countries=[netherlands, singapore]
)
```

---

### Example 2: Potash/Urea Simple Loading

**Raw Excel Data:**

| Vessel_1 | DWT | Product_1 | Volume | Loadport | Disport | Country_1 | Country_2 |
|----------|-----|-----------|--------|----------|---------|-----------|-----------|
| Panamax Star | 65000 | Potash | 55000 | Klaipeda | Shanghai | Lithuania | China |

**Processing Steps:**

1. **Entity Creation:**
   - Vessel: panamax_star (DWT=65000)
   - Load Port: klaipeda (country=lithuania, region=europe)
   - Discharge Port: shanghai (country=china, region=asia)
   - Countries: lithuania, china
   - Regions: europe, asia

2. **Metric Creation:**
   ```python
   MetricCreate(
       entity_name="panamax_star",
       product_name="potash",
       value="55000",
       unit_of_measure="kiloton",
       metric_name="vessel_loads_from_port",
       scope={
           "from": "klaipeda",
           "to": "shanghai"
       },
       start_date_effect=date(2024, 3, 15),
       end_date_effect=date(2024, 3, 15)
   )
   ```

---

## Troubleshooting

### Issue: "Extractor not found for sheet name"

**Cause:** Sheet name doesn't match any configuration in `sheets_extractors.yaml`

**Solution:**
1. Verify sheet name in Excel file
2. Add entry to `sheets_extractors.yaml`:
   ```yaml
   - name: "my_new_tracker"
     extractor_code: "vessel_tracker_<commodity>.py"
     matches:
       exact:
         - value: "SheetNameInExcel"
           data_provider: sp
   ```
3. Reload configuration

---

### Issue: "Product not in referential; assigning category 'unclassified'"

**Cause:** Product name not found in `referential.yaml`

**Solution:**
1. Add product to referential:
   ```yaml
   products_by_category:
     fertilizer_new_product:
       - "new_product"
   ```
2. Re-run extraction

---

### Issue: Port country lookup returns None

**Cause:** Port name not in CITIES or country mapping missing

**Solution:**
1. Add port to `referential.yaml`:
   ```yaml
   cities:
     - "port_name"
   ```
2. Add country mapping:
   ```yaml
   country_region_mapping:
     "country_name": "region_name"
   ```

---

### Issue: Dates parsing as None

**Cause:** Date format not recognized

**Solution:**
1. Check date format in `ColumnParser.clean_date()`:
   - Supported: YYYY-MM-DD, YYYY, YYYYQn, YYYYMnn, dd/mm/yyyy, dd-mm-yyyy
2. Check for special values: TBD, TBC, NG, "at_port", "alongside"
3. Add date format to regex pattern if needed:
   ```python
   # In clean_date method
   match = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', s)  # Add new pattern
   ```

---

### Issue: Entity names not deduplicating

**Cause:** Different capitalization or spacing in raw data

**Solution:**
1. Ensure `CleanerService.clean_entity_name()` is called consistently
2. Verify standardization rules in CleanerService:
   - lowercase
   - underscores replace spaces
   - special chars removed
3. Test deduplication manually:
   ```python
   from src.excel_ingestion.services.cleaner import CleanerService
   
   name1 = CleanerService.clean_entity_name("Ever Given")
   name2 = CleanerService.clean_entity_name("EVER_GIVEN")
   assert name1 == name2  # Should be True
   ```

---

### Issue: High error count when processing

**Cause:** Unexpected column names or missing data

**Solution:**
1. Check actual column headers:
   ```python
   df = caster.raw_data_to_df(data)
   print(df.columns)
   ```
2. Adjust column references in code:
   ```python
   raw_product = row.get('Correct_Column_Name_1', row.get('Product_1'))
   ```
3. Add try-except blocks in process_row:
   ```python
   try:
       value = ColumnParser.clean_float(row.get('Volume_1'))
   except Exception as e:
       logger.warning(f"Could not parse volume: {e}")
       value = None
   ```

---

### Issue: Memory usage high with large files

**Cause:** All entities/products held in memory; no streaming

**Solution:**
1. Process in batches (currently processes entire document)
2. Implement batch persistence:
   ```python
   if self.handled_rows % 1000 == 0:
       self._persist_batch()
       self.existing_entities.clear()  # Optional: clear cache
   ```

---

## References

### Related Files
- [Referential Configuration](../config/referential.yaml)
- [CleanerService](../services/cleaner.py)
- [Schema Models](../persistence/schemas.py)
- [Extractor Loader](loader.py)
- [Extractor Utilities](utils.py)

### Key Classes
- `Caster` - Main transformation engine
- `ColumnParser` - Parsing and classification utilities
- `SchemaCollection` - Output data container

### Configuration Files
- `sheets_extractors.yaml` - Sheet-to-extractor mapping
- `referential.yaml` - Entity and product normalization

---

**Last Updated:** April 2, 2026
**Version:** 1.0
