# UPME Solar Rooftop Potential — PDET Municipalities

Final project for *Database Administration*. Estimates the number of
buildings and total rooftop area suitable for solar panel installation in
each of Colombia's 170 PDET municipalities, comparing two open building
footprint datasets (Microsoft Bing + Google Open Buildings).

## Week 1 deliverable

> NoSQL Database Schema Design and Implementation Plan.

What's here:

```
project/
├── docker-compose.yml          # MongoDB 7 + Mongo Express
├── docs/
│   └── data-model.md           # Design rationale, CRS strategy, index plan
├── schema/
│   ├── municipalities.schema.json
│   ├── buildings.schema.json
│   └── results.schema.json
└── scripts/
    ├── init.js                 # Creates collections, validators, indexes
    └── smoke_load.js           # Loads synthetic data + runs full ETL
```

The schema files are the contract. `init.js` installs them as MongoDB
`$jsonSchema` validators. `smoke_load.js` proves the model end-to-end with
synthetic data so the design isn't just paper.

## Quick start

```bash
docker compose up -d

# 1. Create collections, validators, indexes (idempotent).
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /scripts/init.js

# 2. Smoke test: load 1 fake PDET muni + ~1400 fake buildings, tag, aggregate.
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /scripts/smoke_load.js
```

Browse the data at <http://localhost:8081> (admin / admin).

## What the smoke test demonstrates

1. **Collections + validators** reject malformed documents.
2. **2dsphere indexes** answer `$geoWithin` queries on building geometry.
3. **Spatial-join ETL** tags every building with its containing PDET
   `divipola` in one pass — the pattern week 3 will run on real data.
4. **Aggregation pipeline** produces per-`(divipola, source)` totals and
   writes them to `results`, ready for the cross-dataset comparison the
   project mandates.

Expected output: side-by-side counts and total rooftop m² for the
synthetic Tumaco municipality from both Microsoft and Google sources.

## Roadmap

| Week | Deliverable                                     | Status |
| ---- | ----------------------------------------------- | ------ |
| 1    | Schema, indexes, smoke test                     | done   |
| 2    | Real DANE MGN PDET polygons loaded              | done   |
| 3    | Real MS + Google buildings loaded for PDET area | done   |
| 4    | Reproducible analysis workflow + maps           | done   |
| 5    | Final technical report                          | next   |

## Week 2 deliverable

> PDET Municipality Boundaries Dataset Integration.

170 PDET polygons from DANE MGN 2025, joined against the official ART
list (Decreto 893/2017), validated, projected for area, and loaded into
`upme.municipalities`. Full write-up: [`docs/week2-pdet-loading.md`](docs/week2-pdet-loading.md).

```bash
# After `docker compose up -d` and init.js:
python scripts/validate_pdet.py      # emits data/processed/pdet_municipios.geojson
python scripts/load_municipalities.py # upserts 170 docs + runs sanity queries
```

## Week 3 deliverable

> Building Footprint Data Loading and Integration Report.

Microsoft (232 quadkey tiles, 1,763,356 PDET buildings) and Google Open
Buildings v3 (8 S2 cells, 2,691,812 PDET buildings) loaded into
`upme.buildings_ms` and `upme.buildings_google`. Full write-up:
[`docs/week3-report.md`](docs/week3-report.md). EDA:
[`docs/week3-eda.md`](docs/week3-eda.md).

```bash
# After init.js and load_municipalities.py:
MONGO_URI="mongodb://localhost:27017/" python scripts/download_buildings.py
MONGO_URI="mongodb://localhost:27017/" python scripts/load_buildings.py
MONGO_URI="mongodb://localhost:27017/" python scripts/eda_buildings.py
```

## Week 4 deliverable

> Reproducible Geospatial Analysis Workflow (Rooftop Count and Area Estimation).

`scripts/analyze.py` aggregates building footprints per municipality,
populates `upme.results` (334 documents), runs a Google confidence
sensitivity sweep, and generates choropleth maps + comparison charts.
Full write-up: [`docs/week4-report.md`](docs/week4-report.md).

```bash
# After Week 3 data is loaded:
MONGO_URI="mongodb://localhost:27017/" python scripts/analyze.py
# → upme.results (334 docs), 4 HTML maps, 4 PNG charts, 2 CSVs, report
```

## Tear down

```bash
docker compose down -v
```
