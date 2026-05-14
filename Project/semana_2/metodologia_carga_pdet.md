# Week 2 — PDET Municipality Boundaries Dataset Integration

End-to-end record of how the 170 PDET municipality polygons were acquired,
validated, and loaded into MongoDB. Reproducible with the commands in §6.

## 1. Sources

| Dataset | Provider | File in repo |
| --- | --- | --- |
| Marco Geoestadístico Nacional 2025 (1,122 municipios, polygons) | DANE | `data/raw/municipios_colombia.geojson` (273 MB, not committed) |
| Lista oficial de municipios PDET (170 munis, no geometry) | ART — Agencia de Renovación del Territorio | `data/raw/MunicipiosPDET.xlsx`, derived `data/raw/pdet_municipios.csv` |

Full provenance, licenses, download dates, and reproduction steps are in
[`data/raw/SOURCES.md`](../data/raw/SOURCES.md). Legal basis for the PDET
list is **Decreto Ley 893 de 2017**.

## 2. Data acquisition & verification

- The DANE MGN ZIP (~1.5 GB) was downloaded and unpacked locally; the
  municipal layer (`ADMINISTRATIVO/MGN_ADM_MPIO_GRAFICO.shp`) was exported
  from QGIS to GeoJSON in EPSG:4326.
- The ART PDET spreadsheet was downloaded directly from
  `centralpdet.renovacionterritorio.gov.co` and converted to CSV with
  zero-padded 5-digit DIVIPOLA codes and UTF-8 encoding.

Sanity at acquisition time:

- 1,122 MGN features, all with the expected DIVIPOLA column (`mpio_cdpmp`).
- 170 PDET DIVIPOLA codes, 16 subregiones, matching Decreto 893/2017.
- **0** PDET codes missing from the MGN GeoJSON (full join, no orphans).

## 3. Data integrity & format

Implemented by [`scripts/validate_pdet.py`](../scripts/validate_pdet.py).
Eleven checks, every result captured to `docs/week2-validation.md` on each
run:

1. CRS = EPSG:4326.
2. Source columns present (`mpio_cdpmp`, `mpio_cnmbr`, `dpto_cnmbr`,
   `dpto_ccdgo`, `mpio_ccdgo`).
3. 170/170 PDET DIVIPOLA codes found in the MGN.
4. No duplicate DIVIPOLA in the filtered set.
5. Geometry types restricted to `Polygon` / `MultiPolygon` (result: 170
   MultiPolygons).
6. `shapely.is_valid` on every geometry; `make_valid` applied if needed.
   Result on the current input: **0** invalid geometries.
7. **0** empty geometries.
8. Total bounds inside Colombia's bbox (−82, −5, −66, 13.5).
9. Total PDET area in `[300 000, 500 000] km²`. Computed area:
   **389,182 km²** ≈ 34 % of Colombia — consistent with ART's published
   "~36 % of national territory" figure.
10. 16 PDET subregiones present after merge.
11. Output file written with the canonical schema field names.

Output: [`data/processed/pdet_municipios.geojson`](../data/processed/pdet_municipios.geojson)
— 65 MB, 170 features, EPSG:4326. Each feature's `properties`:

| Field | Type | Notes |
| --- | --- | --- |
| `divipola` | string | 5-digit zero-padded |
| `name` | string | DANE official municipality name |
| `department` | string | DANE department name |
| `department_code` | string | 2-digit zero-padded |
| `subregion_pdet` | string | One of 16 ART subregiones |
| `is_pdet` | boolean | always `true` in this file |
| `area_sqkm` | number | computed in EPSG:9377 (equal-area), rounded to 6 dp |
| `source` | string | `DANE MGN2025 + ART PDET (Decreto 893/2017)` |
| `loaded_at` | string | ISO-8601 UTC |

### Why EPSG:9377 for areas

Stored geometry stays in EPSG:4326 because that is the CRS MongoDB's
2dsphere index requires. Area in m² cannot be measured directly in 4326
because longitude degrees compress with latitude. **EPSG:9377
(MAGNA-SIRGAS Origen Nacional)** is the equal-area projection
recommended by IGAC for national-scale analysis in Colombia.
`area_sqkm` is therefore precomputed at validation time and stored as a
plain number, so analytical queries never need to reproject.

## 4. NoSQL spatial integration

Implemented by [`scripts/load_municipalities.py`](../scripts/load_municipalities.py).

Steps:

1. Connect to MongoDB (`mongodb://root:root@localhost:27017/`, db `upme`).
2. For each of the 170 features, build a document matching
   `schema/municipalities.schema.json` (DIVIPOLA, name, department,
   department_code, is_pdet, area_sqkm, subregion_pdet, source,
   loaded_at, geometry).
3. `UpdateOne(..., upsert=true)` keyed by `divipola` — idempotent
   re-runs replace documents in place rather than duplicating.
4. Sanity queries:
   - `countDocuments({})` → **170** ✅
   - `countDocuments({is_pdet: true})` → **170** ✅
   - 19 distinct departments (Antioquia 24, Cauca 20, Caquetá 16,
     Nariño 16, Bolívar 13, …).
   - `$geoIntersects` from a point inside Tumaco (52835) → **1** hit ✅
   - `$geoIntersects` from a point in Bogotá D.C. (not PDET) →
     **0** hits ✅ (proves the collection is PDET-only AND that the
     2dsphere index works).
   - Indexes present: `geometry_2dsphere`, `divipola_1`, `is_pdet_1`,
     `_id_` ✅.

The validator (`$jsonSchema` from `schema/municipalities.schema.json`,
installed by `scripts/init.js`) rejects malformed inserts. During Week 2
the `subregion_pdet` field was added to the schema so that the ART
subregion (useful for later analyses) can be stored alongside the
core MGN fields.

## 5. Caveats and decisions worth recording

- **170 = MGN match.** Decreto 893/2017 lists 170 municipios. The
  current MGN 2025 layer still contains all 170 codes; no PDET muni has
  been split or renamed since 2017 in a way that breaks the DIVIPOLA
  join.
- **Geometry repair.** `make_valid` is applied conditionally even though
  the current input has zero invalid geometries — keeps the pipeline
  defensive in case DANE issues a future revision with topology errors.
- **The full MGN GeoJSON is not committed.** 273 MB. `SOURCES.md`
  documents how to regenerate it. Only the 65 MB cleaned/filtered
  PDET-only GeoJSON in `data/processed/` is committed.
- **Areas are precomputed, not derived on read.** Classic
  denormalize-derived-values pattern, matching the rationale in
  `docs/data-model.md`.

## 6. Reproducing from a clean checkout

```bash
# 1. Bring up Mongo + Mongo Express
docker compose up -d

# 2. Install the validator + indexes (idempotent)
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /scripts/init.js

# 3. Place data/raw/municipios_colombia.geojson — see data/raw/SOURCES.md
#    (the ART spreadsheet and derived CSV are already committed)

# 4. Validate + emit data/processed/pdet_municipios.geojson
python scripts/validate_pdet.py

# 5. Load the 170 polygons into upme.municipalities
python scripts/load_municipalities.py
```

Expected end state: `upme.municipalities` contains exactly 170
documents, all with `is_pdet: true`, fully indexed for the building
spatial join that Week 3 will perform.
