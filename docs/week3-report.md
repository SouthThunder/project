# Week 3 — Building Footprint Data Loading and Integration Report

End-to-end record of how the Microsoft and Google Open Buildings datasets were
downloaded, filtered to PDET territory, loaded into MongoDB, and audited.
Reproducible with the commands in §6.

---

## 1. Sources

| Dataset | Provider | Tiles | Raw size |
| --- | --- | ---: | ---: |
| Microsoft Global Building Footprints | Bing / Maxar / Airbus | 232 quadkey tiles (Colombia) | ~647 MB compressed |
| Google Open Buildings v3 | Google Research | 8 S2 level-4 cells | ~2.9 GB compressed |

Both datasets are openly licensed (ODbL) and cover Latin America.
Full provenance and download dates are in [`data/raw/SOURCES.md`](../data/raw/SOURCES.md).

---

## 2. Data acquisition & verification

### 2.1 Download

`scripts/download_buildings.py` fetches both datasets:

```bash
python scripts/download_buildings.py          # both sources
python scripts/download_buildings.py --ms     # Microsoft only
python scripts/download_buildings.py --google # Google only
```

**Microsoft**: the script fetches the dataset-links index from Azure Blob Storage,
filters to `Location=Colombia` (232 tiles, ~647 MB), and downloads in parallel
(8 threads). Each tile is a `.csv.gz` of newline-delimited GeoJSON features.

**Google**: the script uses the `score_thresholds_s2_level_4.csv` index to identify
the 8 S2 cells that intersect the PDET bounding box
`(lon_min=-79.01, lat_min=-0.71, lon_max=-70.00, lat_max=11.35)`.
Tiles are `.csv.gz` files with columns: `latitude`, `longitude`,
`area_in_meters`, `confidence`, `geometry` (WKT), `full_plus_code`.

Downloads are resumable: a tile whose local file matches the expected size is skipped.

### 2.2 Spatial filtering strategy

The spatial join is performed **at insert time** (not as a separate tagging pass):

1. The 169 PDET municipality polygons are pulled from `upme.municipalities` and
   indexed in a Shapely `STRtree`.
2. For each feature, the polygon's `representative_point()` (interior point) is
   tested against the STRtree. Features whose centroid falls outside every PDET
   polygon are dropped.
3. Only in-PDET buildings are inserted, with `divipola` already set.

This eliminates a costly post-load update step and keeps the collections clean.

---

## 3. Data integrity & format

### 3.1 Collections & schema

Both datasets are stored in separate MongoDB collections (`buildings_ms`,
`buildings_google`) sharing the same `$jsonSchema` validator
(`schema/buildings.schema.json`). Required fields per document:

| Field | Type | Notes |
| --- | --- | --- |
| `source` | string | `"microsoft"` or `"google"` |
| `source_id` | string | Unique tile-level identifier |
| `divipola` | string | 5-digit PDET municipality code |
| `area_sqm` | number | ≥ 0, m² in EPSG:9377 (MS) or from Google metadata |
| `geometry` | GeoJSON Polygon | WGS84 |
| `loaded_at` | string | ISO-8601 UTC |

`confidence` is optional (MS uses −1 as sentinel → stored as `null`; Google
provides values in `[0.5, 1.0]`).

### 3.2 Area computation

- **Microsoft**: polygons are reprojected to EPSG:9377 (MAGNA-SIRGAS Origen
  Nacional, the equal-area CRS for Colombia) using `pyproj.Transformer` and
  `Shapely` before area is computed.
- **Google**: `area_in_meters` is taken directly from the source CSV
  (pre-computed by Google). The EPSG:9377 fallback is used when that field
  is missing or non-numeric.

### 3.3 Spatial index

Each buildings collection has a `2dsphere` index on `geometry`, enabling
`$geoWithin` and `$geoIntersects` queries for the Week 4 analysis.
A compound index on `(source, divipola)` supports per-municipality aggregations.

### 3.4 Geometry validity issues

A small number of polygons in both datasets fail MongoDB's `2dsphere` geo-key
extraction (self-intersecting or otherwise degenerate geometries). These are
surfaced in the load log and skipped via `insert_many(ordered=False)`. They
represent < 0.01 % of the inserted corpus and have no material effect on results.

### 3.5 Known limitation — San José de Uré (DIVIPOLA 23580)

GADM 4.1 (the geometry source used for the Week 2 municipality re-load on this
machine) does not include San José de Uré, a municipality created in 2012 by
division of Montelíbano. The `municipalities` collection therefore contains
169 of the 170 PDET polygons. Buildings in the San José de Uré territory are
absent from both building collections; this affects < 0.05 % of the PDET
building stock. The original Week 2 run used DANE MGN 2025 and did include this
municipality.

---

## 4. Data loading efficiency

| Source | Tiles | Rows seen | Inserted | Off-PDET dropped | Load time | Throughput |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Microsoft | 232 | 8,221,407 | 1,763,356 | 6,457,876 | 4.5 min | ~6,500 ins/s avg |
| Google | 8 | 31,499,115 | 2,691,812 | 28,807,164 | 9.1 min | ~4,900 ins/s avg |

The high off-PDET drop rate (~79 % MS, ~91 % Google) is expected: the tiles
cover entire S2 cells or quadkeys, most of which extend well beyond the 170 PDET
municipalities.

---

## 5. Initial data audit (EDA)

Full EDA output: [`docs/week3-eda.md`](week3-eda.md)

### 5.1 Totals

| Source | Documents | Total rooftop area (km²) | Mean area (m²) |
| --- | ---: | ---: | ---: |
| Microsoft | 1,763,356 | 221.18 | 125.43 |
| Google | 2,691,812 | 222.90 | 82.81 |

Total rooftop area is nearly identical across sources (~222 km²), which gives
confidence in the spatial filtering. Google reports **53 % more buildings** than
Microsoft for the same territory, reflecting denser detection of small structures
(mean area 82.8 m² vs. 125.4 m² for MS).

### 5.2 Cross-source coverage

- Munis with MS detections: **169** / 170
- Munis with Google detections: **165** / 170
- Munis covered by both: **165**
- 4 munis covered by MS only, 0 by Google only
- **126 of 165** shared munis have building counts differing > 20 % between sources

The large divergence in per-municipality counts (~76 % of shared munis) underlines
why comparing both datasets is required by the project mandate.

### 5.3 Top municipalities by rooftop area (MS)

Santa Marta (14.2 km²) and Valledupar (13.5 km²) lead, consistent with their
status as large departmental capitals within PDET territory. Buenaventura,
Florencia, and Turbo follow.

### 5.4 Google confidence distribution

All Google buildings inserted have `confidence ≥ 0.6` (the default threshold
in Google's v3 release). Distribution:

| Confidence bucket | Count |
| --- | ---: |
| [0.6, 0.7) | 429,902 |
| [0.7, 0.8) | 1,142,547 |
| [0.8, 0.9) | 1,042,360 |
| [0.9, 1.0] | 77,003 |

~42 % of Google detections have confidence ≥ 0.8. The Week 4 analysis will
report results both inclusive and filtered to `confidence ≥ 0.7` to assess
sensitivity.

### 5.5 Building area distribution (m²)

| Source | p10 | p50 | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Microsoft | 28.85 | 76.99 | 229.46 | 908.33 | 44,667 |
| Google | 16.72 | 58.05 | 160.30 | 447.13 | 42,207 |

Google detects substantially smaller footprints at every percentile, which
explains the higher document count at similar total area.

---

## 6. Reproducible commands

```bash
# 0. Prerequisites: MongoDB running, venv with requirements installed
python -m venv .venv && .venv/bin/pip install pymongo shapely pyproj requests geopandas pandas folium matplotlib

# 1. Initialize collections, validators, indexes (idempotent)
sed 's|/schema/|'"$(pwd)"'/schema/|g' scripts/init.js | mongosh "mongodb://localhost:27017/" --quiet

# 2. Build and load PDET municipalities (Week 2 re-run on local MongoDB)
#    Requires data/raw/municipios_colombia.geojson (DANE MGN 2025, not committed).
#    Alternative: use GADM 4.1 via the build_pdet_geojson.py helper (see SOURCES.md).
MONGO_URI="mongodb://localhost:27017/" python scripts/load_municipalities.py

# 3. Download building tiles (resumable)
MONGO_URI="mongodb://localhost:27017/" python scripts/download_buildings.py

# 4. Load buildings into MongoDB
MONGO_URI="mongodb://localhost:27017/" python scripts/load_buildings.py

# 5. Generate EDA report
MONGO_URI="mongodb://localhost:27017/" python scripts/eda_buildings.py
# → docs/week3-eda.md
```

---

## 7. MongoDB state after loading

```
upme.municipalities:   169 documents  (2dsphere + unique divipola indexes)
upme.buildings_ms:   1,763,356 documents  (2dsphere + divipola + source indexes)
upme.buildings_google: 2,691,812 documents  (2dsphere + divipola + source indexes)
upme.results:            0 documents  (populated in Week 4)
```
