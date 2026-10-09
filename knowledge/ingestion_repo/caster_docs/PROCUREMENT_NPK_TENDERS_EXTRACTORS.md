# README: Africa NPK Tenders Extractor

**File:** `africa_npk_tenders.py` (883 lines)  
**Pattern:** Tender/procurement data extraction  
**Data Source:** Argus NPK Analytics (Africa region)  
**Supported Products:** NPK, NP, PK, N-based blends  
**Status:** ⚠️ Inactive (commented in sheets_extractors.yaml) — Reference implementation available

---

## Overview

The **Africa NPK Tenders Extractor** is a specialized caster that normalizes procurement tender data from Argus NPK Analytics reports. It extracts buyer/holder information, geographic locations, tender timelines, and procurement volumes for African fertilizer tenders, transforming raw spreadsheet data into structured metrics that track regional demand patterns and procurement activities.

### Unique Features

- **Buyer entity tracking**: Distinguish between buyers (demand agents) vs. suppliers
- **Tender lifecycle dates**: Issue date, closing date, delivery start/end dates
- **Procurement volume**: Track quantities in kilotons
- **Status tracking**: Open, closed, pending, awarded tender statuses
- **Product grade metadata**: Extract and store product specifications (BPL scoring, etc.)
- **Regional demand signals**: Geographic-level procurement patterns for planning

---

## Architecture

```
Africa NPK Tenders Extractor
│
├─ Input: Excel sheet "Tenders" with rows = procurement records
│  ├─ Header Row (Row 6): Column labels
│  ├─ Data Rows (7+): One tender per row
│  └─ Columns: Country, Holder (Buyer), Product, Status, Issued, Closing date,
│     Delivery start date, Delivery end date, Volume ('000t), Grade info
│
├─ Stage 1: Document Context
│  ├─ Create DocumentCreate (publication date from filename)
│  ├─ Set source_code: "argus" (fixed)
│  ├─ Set publication frequency: "irregular" or "ad-hoc"
│  └─ Extract sheet metadata
│
├─ Stage 2: Sheet Validation
│  ├─ Check sheet name = "Tenders"
│  ├─ Verify expected columns present
│  └─ Log warnings if columns missing
│
├─ Stage 3: Row-by-Row Processing
│  ├─ For each data row (starting row 7):
│  │  ├─ Extract buyer/holder name
│  │  ├─ Extract country → resolve to region
│  │  ├─ Extract product → resolve to category
│  │  ├─ Parse tender status (open, closed, awarded, pending)
│  │  ├─ Parse dates (issued, closing, delivery range)
│  │  ├─ Extract volume in kilotons
│  │  └─ Register entities (buyer/holder, country, region)
│  └─ SKIP if mandatory fields missing (buyer, product, country)
│
├─ Stage 4: Entity Deduplication
│  ├─ Buyers: Track by standardized name
│  ├─ Countries: Map via referential aliases
│  ├─ Regions: Derive from country_region_mapping
│  ├─ Products: Track by category (NPK, NP, PK, N, etc.)
│  └─ Avoid duplicates across tender records
│
├─ Stage 5: Metric Generation
│  ├─ For each valid tender row:
│  │  ├─ Create MetricCreate with:
│  │  │  ├─ entity_name: buyer/holder
│  │  │  ├─ metric_type: "demand" (procurement demand)
│  │  │  ├─ metric_name: "tender" or "tender_{status}"
│  │  │  ├─ value: volume in kilotons
│  │  │  ├─ unit_of_measure: "kiloton"
│  │  │  ├─ start_date_effect: issued date
│  │  │  ├─ end_date_effect: closing date
│  │  │  └─ scope: rich metadata (holder, country, delivery dates, grade)
│  └─ Skip missing/invalid values gracefully
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Entities (buyers/holders identified in tenders)
   ├─ Metrics (tender records with volumes & dates)
   ├─ Products (NPK, NP, PK categories)
   ├─ Regions (derived from country mappings)
   └─ Countries (procurement locations)
```

---

## Data Structure

### Input Format

**Sheet Name:** "Tenders"  
**Header Row:** Row 6 (0-indexed: row 5)  
**Data Rows:** Row 7+ (0-indexed: row 6+)

**Expected Columns:**
| Column | Type | Required | Description |
|--------|------|----------|-------------|
| Country | String | ✅ | Buyer's country of origin |
| Holder | String | ✅ | Buyer/procurement entity name |
| Product | String | ✅ | Fertilizer product (NPK, NP, PK, etc.) |
| Status | String | ✅ | Tender status (open, closed, awarded, pending) |
| Issued | Date | ✅ | Tender issuance date |
| Closing date | Date | ✅ | Tender closing/submission deadline |
| Delivery start date | Date | ✅ | Earliest delivery date |
| Delivery end date | Date | ✅ | Latest delivery date |
| Volume ('000t) | Numeric | ✅ | Procurement volume in kilotons (000 tonnes) |
| (Optional) Grade / Specification | String | ❌ | Product grade (BPL, etc.) for metadata |

### SchemaCollection Output

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate
    metrics: List[MetricCreate]        # Tender records
    entities: List[EntityCreate]       # Buyers/holders
    products: List[ProductCreate]      # NPK, NP, PK
    regions: List[RegionCreate]        # From country mappings
    countries: List[CountryCreate]     # Buyer countries
```

### DocumentCreate

```python
DocumentCreate(
    document_name="argus_npk_analytics_2025_africa_tenders",
    document_path="/path/to/file.xlsx",
    source_code="argus",
    publication_date=date(2025, 1, 15),        # From filename
    ingestion_date=date.today(),
    effective_start_date=min(issued_dates),    # Earliest tender issued
    effective_end_date=max(closing_dates),     # Latest tender closing
    is_archived=False,
)
```

### EntityCreate (Buyer)

```python
EntityCreate(
    entity_name="egypt_ministry_agriculture",
    entity_type="buyer",                       # NEW TYPE: not company/supplier
    country_name="egypt",
    region_name="north_africa",
    description=None,
    metadata_={
        "role": "government_buyer",
        "entity_class": "public_procurement",
    },
    is_active=True,
)
```

### MetricCreate (Tender)

```python
MetricCreate(
    entity_name="egypt_ministry_agriculture",
    metric_name="tender_open",                 # Or "tender_closed", "tender_awarded"
    metric_type="demand",
    value="500",                                # Volume in kilotons
    unit_of_measure="kiloton",
    country_name="egypt",
    region_name="north_africa",
    product_name="npp k18",                    # Or "npk_15_15_15"
    
    start_date_effect=date(2025, 1, 10),      # Issued date
    end_date_effect=date(2025, 3, 31),        # Closing date
    date_publication=date(2025, 1, 15),       # Report publication
    date_insertion=date.today(),
    
    document_name="argus_npk_analytics_2025_africa_tenders",
    sheet_name="Tenders",
    
    scope={
        "holder": "egypt_ministry_agriculture",
        "country": "egypt",
        "value": "500",
        "delivery_start_date": "2025-05-01",
        "delivery_end_date": "2025-12-31",
        "product_grade_info": "bpl_65_min",    # If applicable
        "tender_status": "open",
    }
)
```

---

## Processing Logic

### Date Parsing

The extractor supports multiple date formats for tender key dates:

```python
# Supported formats:
"15-01-2025"        → date(2025, 1, 15)
"15/01/2025"        → date(2025, 1, 15)  
"15 January 2025"   → date(2025, 1, 15)
"Jan 2025"          → date(2025, 1, 1)
"January 2025"      → date(2025, 1, 1)
"2025-01-15"        → date(2025, 1, 15)
"Q1 2025"           → date(2025, 1, 1)
"2025"              → date(2025, 1, 1)
```

### Status Classification

Tender status is standardized and included in metric_name:

```python
status_raw = "Open"
status_clean = status_raw.lower().replace(" ", "_")  # "open"
scope_metric_name = f"tender_{status_clean}"         # "tender_open"

# Recognized statuses:
"open" → "tender_open"
"closed" → "tender_closed"
"awarded" → "tender_awarded"
"pending" → "tender_pending"
"cancelled" → "tender_cancelled"
(if missing) → "tender"  # Fallback
```

### Volume Handling

Volumes are read as numeric (kilotons) and converted to strings for metric storage:

```python
value_raw = 500  # 500 kilotons (500,000 tonnes)
value = str(value_raw)  # "500"

# If missing/NaN:
value = "not_specified"
```

### Buyer/Holder Entity Classification

Buyers are classified as entity_type="buyer" (distinct from "company" suppliers):

```python
entity_name = "Egypt Ministry of Agriculture"
entity_type = "buyer"  # → identifies as procurement entity, not supplier

# Metadata includes:
metadata_ = {
    "Country": "egypt",           # Buyer's country
    "Region": "north_africa",
    "role": "government_buyer",   # If inferred
}
```

### Product Grade Extraction

If grade information is detected (BPL scoring, etc.), it's stored in scope:

```python
grade_pieces = ["bpl_65", "min"]
product_grade = "BPL 65% Min"

scope["product_grade_info"] = "bpl_65_min"
scope["product_grade_display"] = "BPL 65% Min"
```

---

## Configuration (sheets_extractors.yaml)

```yaml
# Uncomment to enable:

# - name: tenders_npk
#   description: Extract Argus NPK Africa tenders
#   extractor_code: africa_npk_tenders.py
#
#   matches:
#     exact:
#       - value: "Tenders"
#         data_provider: argus
```

**Activation:** Once uncommented, the loader will detect "Tenders" sheets in Argus files and route to `africa_npk_tenders.py`.

---

## Referential Integration

### Critical Mappings

```yaml
# referential.yaml MUST include:

companies:
  # Buyer organizations (government agencies, private traders)
  - egypt_ministry_agriculture
  - kenya_farming_board
  - morocco_grain_board
  # ... all known African buyers

countries:
  - egypt
  - ethiopia
  - kenya
  - morocco
  - nigeria
  - south_africa
  - tanzania
  # ... all African countries

country_aliases:
  eg: egypt
  ke: kenya
  ma: morocco
  ng: nigeria
  za: south_africa

country_region_mapping:
  egypt: "north_africa"
  ethiopia: "east_africa"
  kenya: "east_africa"
  morocco: "north_africa"
  nigeria: "west_africa"
  south_africa: "southern_africa"
  # ... complete mapping

regions:
  - north_africa
  - east_africa
  - west_africa
  - southern_africa
  - central_africa

products_by_category:
  npk:
    - npk_15_15_15
    - npk_17_17_17
    - npk_18_18_18
  np:
    - np_20_20
    - np_25_0
  pk:
    - pk_0_20_30
    - pk_0_0_60
  n_based:
    - urea
    - ammonium_nitrate
    - ammonium_sulphate
```

---

## Worked Example

### Input Data

**File:** `Argus_NPK_Analytics_Q1_2025_Africa_Tenders.xlsx`  
**Sheet:** "Tenders"

| Country | Holder | Product | Status | Issued | Closing date | Delivery start date | Delivery end date | Volume ('000t) |
|---------|--------|---------|--------|--------|--------------|---------------------|-------------------|-----------------|
| Egypt | Egypt Ministry of Agriculture | NPP K18 | Open | 10-Jan-25 | 31-Mar-25 | 15-May-25 | 31-Dec-25 | 500 |
| Kenya | Kenya Grain Board | NP 20-20 | Closed | 05-Jan-25 | 20-Mar-25 | 01-Apr-25 | 30-Sep-25 | 250 |
| Nigeria | Fertilizer Producers Association | NPK 17-17-17 | Awarded | 15-Dec-24 | 28-Feb-25 | 01-Mar-25 | 31-May-25 | 1200 |
| South Africa | Private Trader - ABC Corp | PK 0-20-30 | Open | 01-Feb-25 | 15-Apr-25 | 01-May-25 | 31-Aug-25 | 300 |

### Processing

**Row 1: Egypt Ministry Tender**
```
Country: "Egypt" 
  → Classified: entity_type="country", region="north_africa", country="egypt"
  
Holder: "Egypt Ministry of Agriculture"
  → Classified: entity_type="buyer", registered as buyer entity
  → Metadata: {"Country": "egypt", "Region": "north_africa"}

Product: "NPP K18"
  → Resolved: product_name="npp_k18", category="npk"

Status: "Open"
  → metric_name: "tender_open"

Dates:
  → start_date_effect: date(2025, 1, 10)    # Issued
  → end_date_effect: date(2025, 3, 31)      # Closing

Volume: 500 kilotons

Metric Output:
  MetricCreate(
      entity_name="egypt_ministry_of_agriculture",
      metric_name="tender_open",
      metric_type="demand",
      value="500",
      unit_of_measure="kiloton",
      country_name="egypt",
      region_name="north_africa",
      product_name="npp_k18",
      start_date_effect=date(2025, 1, 10),
      end_date_effect=date(2025, 3, 31),
      scope={
          "holder": "egypt_ministry_of_agriculture",
          "country": "egypt",
          "value": "500",
          "delivery_start_date": "2025-05-15",
          "delivery_end_date": "2025-12-31",
      }
  )
```

**Row 2: Kenya Board Tender (Closed)**
```
Status: "Closed" → metric_name: "tender_closed"

Product: "NP 20-20" → category="np"

Metric Output:
  MetricCreate(
      entity_name="kenya_grain_board",
      metric_name="tender_closed",
      value="250",
      region_name="east_africa",
      country_name="kenya",
      product_name="np_20_20",
      start_date_effect=date(2025, 1, 5),
      end_date_effect=date(2025, 3, 20),
      scope={
          "holder": "kenya_grain_board",
          "country": "kenya",
          "value": "250",
          "delivery_start_date": "2025-04-01",
          "delivery_end_date": "2025-09-30",
      }
  )
```

**Row 3: Nigeria Producer Association (Awarded)**
```
Status: "Awarded" → metric_name: "tender_awarded"

Holder: "Fertilizer Producers Association" → entity_type="buyer"

Metric Output:
  MetricCreate(
      entity_name="fertilizer_producers_association",
      metric_name="tender_awarded",
      metric_type="demand",
      value="1200",
      region_name="west_africa",
      country_name="nigeria",
      product_name="npk_17_17_17",
      start_date_effect=date(2024, 12, 15),
      end_date_effect=date(2025, 2, 28),
      ... (delivery: Mar - May 2025)
  )
```

### Output: SchemaCollection

```python
SchemaCollection(
    document=DocumentCreate(
        document_name="argus_npk_analytics_q1_2025_africa_tenders",
        source_code="argus",
        publication_date=date(2025, 2, 1),
        ingestion_date=date.today(),
        effective_start_date=date(2024, 12, 15),
        effective_end_date=date(2025, 4, 15),
    ),
    entities=[
        EntityCreate(entity_name="egypt_ministry_of_agriculture", entity_type="buyer", country_name="egypt", region_name="north_africa"),
        EntityCreate(entity_name="kenya_grain_board", entity_type="buyer", country_name="kenya", region_name="east_africa"),
        EntityCreate(entity_name="fertilizer_producers_association", entity_type="buyer", country_name="nigeria", region_name="west_africa"),
        EntityCreate(entity_name="abc_corp", entity_type="buyer", country_name="south_africa", region_name="southern_africa"),
    ],
    products=[
        ProductCreate(product_name="npp_k18", product_category_name="npk"),
        ProductCreate(product_name="np_20_20", product_category_name="np"),
        ProductCreate(product_name="npk_17_17_17", product_category_name="npk"),
        ProductCreate(product_name="pk_0_20_30", product_category_name="pk"),
    ],
    regions=[
        RegionCreate(region_name="north_africa"),
        RegionCreate(region_name="east_africa"),
        RegionCreate(region_name="west_africa"),
        RegionCreate(region_name="southern_africa"),
    ],
    countries=[
        CountryCreate(country_name="egypt", region_name="north_africa"),
        CountryCreate(country_name="kenya", region_name="east_africa"),
        CountryCreate(country_name="nigeria", region_name="west_africa"),
        CountryCreate(country_name="south_africa", region_name="southern_africa"),
    ],
    metrics=[
        MetricCreate(entity_name="egypt_ministry_of_agriculture", metric_name="tender_open", ...),
        MetricCreate(entity_name="kenya_grain_board", metric_name="tender_closed", ...),
        MetricCreate(entity_name="fertilizer_producers_association", metric_name="tender_awarded", ...),
        MetricCreate(entity_name="abc_corp", metric_name="tender_open", ...),
    ]
)
```

---

## Troubleshooting

### Issue 1: Missing "Tenders" Sheet

**Symptom:** Extractor called but report has no "Tenders" sheet

**Root Cause:** File structure doesn't match expected layout

**Solution:**
1. Verify filename matches Argus NPK Analytics pattern
2. Confirm "Tenders" sheet exists (case-sensitive)
3. Check sheet is not hidden or deleted

---

### Issue 2: Buyer Entity Not Recognized

**Symptom:** Buyer name stored as-is in entity_name; no deduplication

**Root Cause:** Buyer inconsistently named across records (e.g., "Egypt Agric" vs. "Egypt Ministry of Agriculture")

**Solution:**
1. Add buyer organization aliases to referential:
   ```yaml
   companies:
     - egypt_ministry_of_agriculture
     # Add common misspellings/variations
   ```
2. Include standardization rules in referential
3. Review extracted entity names for consistency

---

### Issue 3: Delivery Dates Parsing Fails

**Symptom:** Delivery start/end dates missing from scope

**Root Cause:** Date format not recognized

**Solution:**
1. Check date column format (must be dd-mm-yyyy or similar)
2. Ensure dates are actual date objects in Excel (not text)
3. Verify date parser supports format:
   ```python
   # Add custom format support if needed
   ColumnParser.clean_date(date_str)  # Extends base parser
   ```

---

### Issue 4: Volume Values Missing or Non-Numeric

**Symptom:** Volume marked as "not_specified" for many records

**Root Cause:** Column contains text, formulas, or blank cells

**Solution:**
1. Check for "TBD", "TBA", "Pending" text in volume column
2. Ensure numeric values (not formulas)
3. Handle missing values gracefully (already defaults to "not_specified")

---

### Issue 5: Status Not In Recognized List

**Symptom:** metric_name shows generic "tender" instead of "tender_{status}"

**Root Cause:** Status value not in expected set

**Solution:**
1. Check actual status values in data:
   ```python
   # Enhance status mapping in ColumnParser if needed
   status_map = {
       "open": "open",
       "opened": "open",
       "accepting_bids": "open",
       "closed": "closed",
       ...
   }
   ```

---

## Implementation Checklist

When setting up tender extraction:

- [ ] Verify referential has all African countries + regions
- [ ] Add known buyer organizations to referential companies list
- [ ] Confirm Argus report uses "Tenders" sheet name
- [ ] Test date parsing with sample dates from report
- [ ] Validate expected columns present (Country, Holder, Product, Status, dates, Volume)
- [ ] Check product category assignments for all products in data
- [ ] Verify no Inf/NaN values in volume column
- [ ] Test buyer name standardization (check for case vs. abbreviation issues)
- [ ] Validate entity_type="buyer" vs. "company" classification
- [ ] Test metric_name generation for all unique statuses
- [ ] Confirm delivery date ranges populated correctly

---

## Related Documentation

- [README_PRICE_EXTRACTORS.md](README_PRICE_EXTRACTORS.md) — Argus commodity prices (sister dataset)
- [README_TRADE_EXTRACTORS.md](README_TRADE_EXTRACTORS.md) — Trade data extraction
- **sheets_extractors.yaml** — Configuration (africa_npk_tenders currently commented)
- **referential.yaml** — Entity & product classification database

---

**Version:** 1.0 (Specialized Extractor)  
**Status:** ⚠️ Inactive/Reference  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team  
**Next Step:** Enable in sheets_extractors.yaml when ready to ingest Argus Africa NPK tender data for regional procurement analysis
