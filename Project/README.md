# UPME Solar Rooftop Potential — PDET Municipalities

Final project for *Database Administration*. Estimates the number of
buildings and total rooftop area suitable for solar panel installation in
each of Colombia's 170 PDET municipalities, comparing two open building
footprint datasets (Microsoft Bing + Google Open Buildings).

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

---

## Roadmap

| Week | Deliverable                                     | Status |
| ---- | ----------------------------------------------- | ------ |
| 1    | Schema, indexes, smoke test                     | ✅ done |
| 2    | Real DANE MGN PDET polygons loaded              | ✅ done |
| 3    | Real MS + Google buildings loaded for PDET area | next   |
| 4    | Reproducible analysis workflow + maps           | todo   |
| 5    | Final technical report                          | todo   |

---

## Week 1 — Schema Design and Implementation Plan

> NoSQL Database Schema Design and Implementation Plan.

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

### What the smoke test demonstrates

1. **Collections + validators** reject malformed documents.
2. **2dsphere indexes** answer `$geoWithin` queries on building geometry.
3. **Spatial-join ETL** tags every building with its containing PDET
   `divipola` in one pass — the pattern week 3 will run on real data.
4. **Aggregation pipeline** produces per-`(divipola, source)` totals and
   writes them to `results`, ready for the cross-dataset comparison the
   project mandates.

---

## Week 2 — PDET Municipality Boundaries Dataset Integration

> 170 PDET polygons from DANE MGN 2025, joined against the official ART
> list (Decreto 893/2017), validated, projected for area, and loaded into
> `upme.municipalities`.

Full write-up: [`docs/week2-pdet-loading.md`](docs/week2-pdet-loading.md)

### Pipeline (from a clean checkout)

```bash
# 1. Bring up Mongo + Mongo Express
docker compose up -d

# 2. Install validator + indexes (idempotent)
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /scripts/init.js

# 3. Place data/raw/municipios_colombia.geojson — see data/raw/SOURCES.md
#    (the ART spreadsheet and derived CSV are already committed)

# 4. Validate + emit data/processed/pdet_municipios.geojson
python scripts/validate_pdet.py

# 5. Load the 170 polygons into upme.municipalities
python scripts/load_municipalities.py

# 6. (Optional) Verify the $jsonSchema validator rejects malformed docs
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /scripts/verify_schema_validator.js

# 7. (Optional) Generate subregion map for the report/defense
python scripts/generate_map.py
```

### What this deliverable proves

| Checkpoint | Evidence |
| --- | --- |
| Data Acquisition & Verification | Two sources, 170/170 DIVIPOLA join, `SOURCES.md` |
| Data Integrity & Format | 11/11 automated checks in `validate_pdet.py`; `week2-validation.md` |
| NoSQL Spatial Integration | 170 docs, 4 indexes, `$geoIntersects` hits Tumaco, misses Bogotá |
| Documentation of Process | `SOURCES.md`, `week2-validation.md`, `week2-pdet-loading.md` |

### Key design decisions

- **CRS strategy**: geometry stored in EPSG:4326 (required by MongoDB 2dsphere);
  `area_sqkm` precomputed in EPSG:9377 (MAGNA-SIRGAS Origen Nacional, Colombia's
  official equal-area projection) so queries never need to reproject.
- **Idempotency**: `UpdateOne(..., upsert=true)` keyed on `divipola` — safe to re-run.
- **Strict schema**: `validationAction: error` means malformed inserts fail loudly.
- **PDET-only**: only the 170 PDET municipalities are loaded, not all 1,122 MGN
  municipalities. The Bogotá $geoIntersects miss proves this.

### Large files (not committed)

| File | Size | How to regenerate |
| --- | --- | --- |
| `data/raw/municipios_colombia.geojson` | ~273 MB | See `data/raw/SOURCES.md` |
| `data/processed/pdet_municipios.geojson` | ~65 MB | `python scripts/validate_pdet.py` |

---

## Tear down

```bash
docker compose down -v
```
