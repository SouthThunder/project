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
| 2    | Real DANE MGN PDET polygons loaded              | next   |
| 3    | Real MS + Google buildings loaded for PDET area | todo   |
| 4    | Reproducible analysis workflow + maps           | todo   |
| 5    | Final technical report                          | todo   |

## Tear down

```bash
docker compose down -v
```
