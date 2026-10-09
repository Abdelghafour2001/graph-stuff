# README: Freight Trade Extractor (Route Classification Pattern)

**File:** `freight_trad_caster.py`  
**Pattern:** Trade/freight route extraction with multi-entity classification  
**Data Sources:** CRU freight trade data files (multi-commodity)  
**Supported Products:** Ammonia, UAN, AS, DAP-MAP, Phosphoric Acid, Phosphate Rock, MOP, Sulphur, Sulphuric Acid  
**Status:** ⚠️ Inactive (commented in sheets_extractors.yaml) — Reference implementation available

---

## Overview

The **Freight Trade Extractor** is a specialized caster that normalizes CRU freight cost/time data across shipping routes. Unlike hierarchical or flat geographic extractors, this caster models **trade routes as networks** of origin-destination pairs, with dynamic entity classification (company, country, region, city, hub, vessel) and frequency-based temporal tracking.

### Unique Features

- **Multi-entity classification**: Company, Country, Region, City, Hub, Vessel, Legacy Country (7 types)
- **Route-based structure**: Origin | Destination routes as column headers with frequency variants (weekly avg, monthly avg, etc.)
- **Hub/City mapping**: Resolve shipping hubs → country/region; cities → country/region
- **Vessel tracking**: Track by vessel type/name
- **Frequency detection**: Parse "avg", "week", "month" indicators from route columns
- **Temporal tracking**: Effective start/end dates for freight routes
- **Multi-product support**: 9 commodities per file (Ammonia, UAN, AS, DAP-MAP, Phosphoric Acid, Phosphate Rock, MOP, Sulphur, Sulphuric Acid)

---

## Architecture

```
Freight Trade Route Extractor
│
├─ Input: Excel sheet with 2-row header + weekly date index + Route columns
│  ├─ Header Row 1: Section tabs (Ammonia, UAN, AS, DAP-MAP, Phosphoric Acid, etc.)
│  ├─ Header Row 2: Route columns with Frequency (e.g., "China to W.Europe | avg")
│  └─ Data Rows: Weekly observations (dates as index) + freight costs/times
│
├─ Stage 1: Document Context
│  ├─ Create DocumentCreate (publication date from filename)
│  ├─ Infer source code: "cru" (fixed)
│  ├─ Infer publication frequency: "weekly"
│  └─ Extract initial date from first data row
│
├─ Stage 2: Sheet Processing
│  ├─ Identify product section: Match sheet name to commodity
│  ├─ Skip if section sheet (landing tab, not data)
│  └─ Extract all route columns from row 2
│
├─ Stage 3: Route Parsing
│  ├─ For each column header (Route | Frequency):
│  │  ├─ Split by pipe: origin="China", dest="W.Europe", freq="avg"
│  │  ├─ Classify origin: Company? Country? City? Hub? Vessel?
│  │  ├─ Classify destination: Country? City? Hub? Region?
│  │  ├─ Normalize via referential (aliases, mappings)
│  │  └─ Build MetricCreate for each route
│  └─ SKIP routes with unresolvable origin/dest
│
├─ Stage 4: Temporal Tracking
│  ├─ Parse weekly dates from data rows
│  ├─ Track effective_start_date, effective_end_date
│  ├─ Handle date gaps (missing weeks) if needed
│  └─ Build date range for each freight route observation
│
├─ Stage 5: Metric Generation
│  ├─ For each route × week combination:
│  │  ├─ Extract freight cost OR time value
│  │  ├─ Build metric_name: "freight_cost_{origin}_to_{dest}_{frequency}"
│  │  ├─ Scope: route_origin, route_dest, frequency, vessel_type, commodity
│  │  └─ Emit MetricCreate
│  └─ Handle missing/NA values (skip, log warning)
│
└─ Output: SchemaCollection
   ├─ Document (file metadata)
   ├─ Metrics (freight by route-week)
   ├─ Entities (companies, countries, cities, hubs, vessels identified in routes)
   ├─ Products (9 commodities)
   ├─ Regions (from city/hub mappings)
   └─ Countries (from origin/dest classification)
```

---

## Multi-Entity Classification

**Problem:** Raw route text ("China", "W.Europe", "Yuzhnyy", "SPOT1") can refer to different entity types.  
**Solution:** Hierarchical classification with priority lookup.

### Classification Priority

```python
def classify_entity(entity_name_raw: str) -> Dict[str, str]:
    """
    Classify raw entity name against referential sets.
    Returns: {"entity_type": "...", "canonical_name": "...", ...}
    """
    key = _norm_token(entity_name_raw)  # e.g., "n_se_asia"
    
    # 1. COMPANY (highest priority)
    if key in COMPANIES:
        return {"entity_type": "company", "canonical_name": key}
    
    # 2. COUNTRY ALIAS (e.g., "uk" → "united_kingdom")
    if key in COUNTRY_ALIASES:
        canon = COUNTRY_ALIASES[key]
        region = COUNTRY_REGION_MAPPING.get(canon)
        return {
            "entity_type": "country",
            "canonical_name": canon,
            "country_name": canon,
            "region_name": region,
        }
    
    # 3. COUNTRY DIRECT
    if key in COUNTRIES:
        region = COUNTRY_REGION_MAPPING.get(key)
        return {
            "entity_type": "country",
            "canonical_name": key,
            "country_name": key,
            "region_name": region,
        }
    
    # 4. LEGACY COUNTRY (e.g., USSR)
    if key in LEGACY_COUNTRIES:
        region = COUNTRY_REGION_MAPPING.get(key)
        return {
            "entity_type": "legacy_country",
            "canonical_name": key,
            "region_name": region,
        }
    
    # 5. REGION ALIAS (e.g., "n_se_asia" → "northeast_southeast_asia")
    if key in REGION_ALIASES:
        canon = REGION_ALIASES[key]
        return {
            "entity_type": "region",
            "canonical_name": canon,
            "region_name": canon,
        }
    
    # 6. REGION DIRECT
    if key in REGIONS:
        return {
            "entity_type": "region",
            "canonical_name": key,
            "region_name": key,
        }
    
    # 7. CITY (with optional country/region mapping)
    if key in CITIES:
        country = CITY_MAPPING_COUNTRY.get(key)
        region = CITY_MAPPING_REGION.get(key)
        return {
            "entity_type": "city",
            "canonical_name": key,
            "country_name": country,
            "region_name": region,
        }
    
    # 8. HUB (with optional country/region mapping)
    if key in HUBS:
        country = HUB_MAPPING_COUNTRY.get(key)
        region = HUB_MAPPING_REGION.get(key)
        return {
            "entity_type": "hub",
            "canonical_name": key,
            "country_name": country,
            "region_name": region,
        }
    
    # 9. VESSEL TYPE
    if key in VESSELS:
        return {
            "entity_type": "vessel",
            "canonical_name": key,
        }
    
    # 10. FALLBACK (unrecognized)
    return {
        "entity_type": "other",
        "canonical_name": key,
    }
```

### Referential Support

```yaml
# referential.yaml
companies:
  - shell
  - chevron
  - bp
  # ... trading companies

countries:
  - united_states
  - saudi_arabia
  - china
  # ... all countries

country_aliases:
  usa: united_states
  sa: saudi_arabia
  uae: united_arab_emirates

country_region_mapping:
  united_states: north_america
  saudi_arabia: middle_east
  china: east_asia

regions:
  - north_america
  - middle_east
  - east_asia
  - western_europe

region_aliases:
  n_se_asia: northeast_southeast_asia
  gulf_coast: gulf

cities:
  - dubai
  - rotterdam
  - singapore

city_mapping_countries:
  dubai: united_arab_emirates
  rotterdam: netherlands
  singapore: singapore

hubs:
  - yuzhnyy
  - amuay
  - salalah

hub_mapping_countries:
  yuzhnyy: ukraine
  amuay: venezuela
  salalah: oman

vessels:
  - handymax
  - panamax
  - ulcv
  - lpg_carrier
```

---

## Route Parsing & Column Detection

**Format:** `"{Origin} to {Destination} | {Frequency}"`

**Examples:**
```
"China to W. Europe | avg"       → origin="china", dest="w_europe", freq="avg"
"Saudi Arabia to US Gulf | week" → origin="saudi_arabia", dest="us_gulf", freq="week"
"N/SE Asia to India | avg"       → origin="n_se_asia", dest="india", freq="avg"
"Yuzhnyy to Amuay (SPOT1) | wk" → origin="yuzhnyy", dest="amuay", freq="wk"
"Shell Ammonia | avg"            → SPECIAL: Shell (company) as origin; endpoint varies
```

**Frequency Detection:**
```python
# Synonyms for frequency indicators:
freq_map = {
    "avg": "weekly_average",
    "week": "weekly",
    "wk": "weekly",
    "m": "monthly_average",
    "monthly": "monthly",
    "spot": "spot",
}
```

---

## Data Structures

### SchemaCollection (Output)

```python
@dataclass
class SchemaCollection:
    document: DocumentCreate                   # File metadata
    metrics: List[MetricCreate]                # Freight by route-week
    entities: List[EntityCreate]               # Companies, cities, hubs, vessels
    products: List[ProductCreate]              # 9 commodities
    regions: List[RegionCreate]                # From hub/city mappings
    countries: List[CountryCreate]             # From origin/dest classification
```

### DocumentCreate

```python
DocumentCreate(
    document_name="cru_freight_trades_2025_weekly",
    document_path="/path/to/file.xlsx",
    source_code="cru",
    publication_date=date(2025, 1, 1),        # From filename or first data date
    ingestion_date=date.today(),
    is_archived=False,
)
```

### ProductCreate

```python
ProductCreate(
    product_name="ammonia",
    product_category_name="primary_chemical",
    is_active=True,
)
```

### EntityCreate (Company)

```python
EntityCreate(
    entity_name="shell",
    entity_type="company",
    country_name=None,                        # Company may not have country
    region_name=None,
    is_active=True,
)
```

### EntityCreate (City)

```python
EntityCreate(
    entity_name="rotterdam",
    entity_type="city",
    country_name="netherlands",
    region_name="western_europe",
    is_active=True,
)
```

### EntityCreate (Hub)

```python
EntityCreate(
    entity_name="yuzhnyy",
    entity_type="hub",
    country_name="ukraine",
    region_name="eastern_europe",
    metadata_={"hub_type": "ammonia_terminal"},
    is_active=True,
)
```

### MetricCreate

```python
MetricCreate(
    metric_name="freight_cost_china_to_w_europe_weekly_avg",
    metric_type="freight_cost",
    value="45.50",                              # USD per tonne
    unit_of_measure="usd_per_tonne",
    year=2025,
    start_date_effect=date(2025, 1, 6),        # Week starting Jan 6
    end_date_effect=date(2025, 1, 12),         # Week ending Jan 12
    date_publication=date(2025, 1, 15),        # Publication date
    country_name="china",                      # Origin
    region_name="east_asia",
    entity_name="china",                       # Route origin entity
    product_name="ammonia",
    sheet_name="Ammonia",
    document_name="cru_freight_trades_2025_weekly",
    scope={
        "route_origin": "china",
        "route_destination": "w_europe",
        "frequency": "weekly_average",
        "origin_entity_type": "country",
        "dest_entity_type": "region",
        "vessel_type": None,
        "commodity": "ammonia",
        "lane_code": "AMMONIA_CN_EU",
    }
)
```

---

## Worked Examples

### Example 1: Ammonia Weekly Freight Costs

**File:** `CRU_Freight_Trades_Weekly_January_2025.xlsx`  
**Sheet:** "Ammonia"

**Header Row 2:**
```
| China to W. Europe | avg | Saudi Arabia to US Gulf | week | N/SE Asia to India | avg |
|------------------|-----|----------------------|------|------------------|-----|
```

**Data Rows:**
```
Date      | China_WEur_avg | Saudi_USGulf_wk | NEAsia_India_avg |
2025-01-06|     45.50      |      38.75       |      32.10       |
2025-01-13|     46.00      |      39.25       |      32.50       |
```

**Processing:**

Route 1: "China to W. Europe | avg"
- Origin Classification: china → entity_type="country", region="east_asia"
- Dest Classification: w_europe → entity_type="region", region="western_europe"
- Frequency: "avg" → "weekly_average"
- Metric Name: "freight_cost_china_to_w_europe_weekly_avg"

Route 2: "Saudi Arabia to US Gulf | week"
- Origin: saudi_arabia → entity_type="country", region="middle_east"
- Dest: us_gulf → entity_type="hub", country="united_states"
- Frequency: "week" → "weekly"
- Metric Name: "freight_cost_saudi_arabia_to_us_gulf_weekly"

**Metrics Emitted (6 total: 3 routes × 2 weeks):**
1. Week 1: freight_cost_china_to_w_europe_weekly_avg = 45.50 USD/ton
2. Week 1: freight_cost_saudi_arabia_to_us_gulf_weekly = 38.75 USD/ton
3. Week 1: freight_cost_ne_asia_to_india_weekly_avg = 32.10 USD/ton
4. Week 2: freight_cost_china_to_w_europe_weekly_avg = 46.00 USD/ton
5. Week 2: freight_cost_saudi_arabia_to_us_gulf_weekly = 39.25 USD/ton
6. Week 2: freight_cost_ne_asia_to_india_weekly_avg = 32.50 USD/ton

---

### Example 2: Multi-Product Freight Data

**File:** `CRU_Freight_Trades_All_Products_2025.xlsx`  
**Sheets:** Ammonia, UAN, AS, DAP-MAP, Phosphoric Acid, Phosphate Rock, MOP, Sulphur, Sulphuric Acid

**Processing per sheet:**
- Same route parsing logic
- Different product context (scope["commodity"])
- Separate metrics for each commodity's freight lanes

---

## Configuration (sheets_extractors.yaml)

```yaml
# Example: Freight Trades (currently commented)
# - name: "freight_trades_caster"
#   description: "Extracteur freight trades"
#   extractor_code: "freight_trad_caster.py"
#   matches:
#     exact:
#       - value: "Ammonia"
#         data_provider: "cru"
#       - value: "UAN"
#         data_provider: "cru"
#       - value: "AS"
#         data_provider: "cru"
#       - value: "DAP-MAP"
#         data_provider: "cru"
#       - value: "Phosphoric Acid"
#         data_provider: "cru"
#       - value: "Phosphate Rock"
#         data_provider: "cru"
#       - value: "MOP"
#         data_provider: "cru"
#       - value: "Sulphur"
#         data_provider: "cru"
#       - value: "Sulphuric Acid"
#         data_provider: "cru"
```

---

## Referential Integration

### Critical Mappings

```yaml
# referential.yaml MUST include:
companies:
  - (all known trading companies)

countries:
  - (all countries in route data)

country_aliases:
  usa: united_states
  # ... all regional shorthand

country_region_mapping:
  (all countries → regions)

cities:
  - rotterdam
  - dubai
  - singapore
  - (all port cities in routes)

city_mapping_countries:
  rotterdam: netherlands
  # ... city → country mappings

hubs:
  - yuzhnyy
  - amuay
  - salalah
  - (all major ammonia/liquid processing hubs)

hub_mapping_countries:
  yuzhnyy: ukraine
  # ... hub → country mappings

vessels:
  - handymax
  - panamax
  - ulcv
  - lpg_carrier
  - (all vessel types mentioned in data)
```

---

## Troubleshooting

### Issue 1: Route Parsing Fails (Origin/Dest Unrecognized)

**Symptom:** Routes skipped; log shows "Unresolvable origin/dest"

**Root Cause:** Entity name not in referential (city, hub, country, company)

**Solution:**
1. Add to appropriate referential set:
   ```yaml
   cities:
     - new_city
   city_mapping_countries:
     new_city: country_name
   ```
2. Or check for typos in route column header

---

### Issue 2: Frequency Not Detected

**Symptom:** Metrics emitted with frequency="other" or None

**Root Cause:** Route format doesn't match expected delimiter (pipe)

**Solution:** Verify route column headers use "Origin to Dest | Frequency" format

---

### Issue 3: Temporal Dates Out of Range

**Symptom:** start_date_effect/end_date_effect are None or incorrect

**Root Cause:** Date parsing from data rows failed

**Solution:**
1. Verify first column is date or datetime
2. Check date format (YYYY-MM-DD, MM/DD/YYYY, etc.)
3. Ensure no merged cells in date column

---

## Implementation Checklist

When adapting freight extractors to new routes/sources:

- [ ] Verify referential has all countries/cities/hubs in route data
- [ ] Confirm route column format: "Origin to Dest | Frequency"
- [ ] Add new cities/hubs to referential BEFORE extraction
- [ ] Test entity classification (all origin/dest types recognized)
- [ ] Validate date parsing (first column is date index)
- [ ] Check frequency detection (avg, week, month synonyms)
- [ ] Verify no Inf/NaN in freight values
- [ ] Confirm metric naming consistency
- [ ] Test multi-product sheet switching

---

## Related Documentation

- [README_HIERARCHICAL_CAPACITY_EXTRACTORS.md](README_HIERARCHICAL_CAPACITY_EXTRACTORS.md) — Facility-based extraction
- [README_FLAT_GEOGRAPHIC_EXTRACTORS.md](README_FLAT_GEOGRAPHIC_EXTRACTORS.md) — Regional aggregates
- **sheets_extractors.yaml** — Master configuration (freight trades currently commented)
- **referential.yaml** — Entity classification database (critical for route parsing)

---

**Version:** 1.0 (Specialized Extractor)  
**Status:** ⚠️ Inactive/Reference  
**Last Updated:** April 2026  
**Author:** Corporate Data Ingestion Team  
**Next Step:** Enable in sheets_extractors.yaml when ready to ingest CRU weekly freight trade data
