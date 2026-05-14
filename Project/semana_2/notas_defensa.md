# Week 2 Defense — Speaker Notes & Slide Content

Drop-in content for a 6-8 slide presentation. Paste each slide block into
PowerPoint / Google Slides. Screenshots referenced are in
`docs/week2-screenshots/`.

The deliverable being defended is the **PDET Municipality Boundaries
Dataset Integration**, evaluated against four sub-items:
*Data Acquisition & Verification*, *Data Integrity & Format*, *NoSQL
Spatial Integration*, *Documentation of Process*.

---

## Slide 1 — Title

> **PDET Municipality Boundaries Dataset Integration**
> Database Administration — Week 2 Deliverable
> [Group members]
> 2026-05-11

Speaker notes: 30-second intro. "We integrated the 170 PDET municipal
polygons into MongoDB with spatial indexing, end-to-end reproducible. I'll
walk through each of the four checkpoints."

---

## Slide 2 — What was required

Four checkpoints from `reference.md` §3.1.2:

1. Data Acquisition & Verification
2. Data Integrity & Format
3. NoSQL Spatial Integration
4. Documentation of Process

Plus the project mandate: **NoSQL only**, **PDET-scoped**, **reproducible**.

Speaker notes: "Each of the next slides addresses one checkpoint. All
artifacts are committed to GitHub."

---

## Slide 3 — Data Acquisition & Verification

**Two authoritative sources combined:**

| Dataset | Provider | What it contributes |
| --- | --- | --- |
| MGN 2025 (Marco Geoestadístico Nacional) | DANE | All 1,122 municipal polygons, EPSG:4326 |
| MunicipiosPDET.xlsx | ART — Agencia de Renovación del Territorio | Official 170-muni list per Decreto 893/2017 |

Provenance recorded in `data/raw/SOURCES.md` (URLs, dates, licenses).

**Cross-check result: 170 / 170 PDET DIVIPOLA codes found in MGN. Zero
orphans.**

Visual to include: screenshot of `data/raw/SOURCES.md` rendered in
GitHub, plus the file tree showing both files in `data/raw/`.

Speaker notes: "We chose two sources because the MGN is the polygon
authority and the ART spreadsheet is the legal authority for which munis
are PDET. The 170-out-of-170 join means there are no naming or coding
ambiguities."

---

## Slide 4 — Data Integrity & Format

**11 automated checks implemented in `scripts/validate_pdet.py`:**

1. CRS = EPSG:4326 ✅
2. Required MGN columns present ✅
3. 170 / 170 PDET codes found ✅
4. No duplicate DIVIPOLA ✅
5. Geometry types restricted to Polygon / MultiPolygon ✅ (170 MultiPolygons)
6. Geometry validity (`shapely.is_valid`) ✅ 0 invalid
7. No empty geometries ✅
8. Bounds inside Colombia bbox ✅
9. Total area in sanity range ✅ **389,182 km²** ≈ 34 % of Colombia (matches ART's published "~36 %")
10. 16 PDET subregiones present ✅
11. Cleaned output file written ✅

Every run captures these to `docs/week2-validation.md`, so the audit
trail re-generates automatically.

Visual: screenshot of `docs/week2-validation.md` showing the 11 OK lines.

Speaker notes: "The biggest decision here was *EPSG:9377* for area
computation — that's MAGNA-SIRGAS Origen Nacional, the official Colombian
equal-area CRS. You cannot compute area in WGS84 degrees correctly. Storage
stays in WGS84 because MongoDB's 2dsphere needs it."

---

## Slide 5 — NoSQL Spatial Integration (Architecture)

```
data/raw/municipios_colombia.geojson  (273 MB, 1122 munis)  ─┐
data/raw/pdet_municipios.csv          (170 DIVIPOLA codes)  ─┤
                                                              │
        scripts/validate_pdet.py  ── 11 checks ──────────────▶│
                                                              │
data/processed/pdet_municipios.geojson (170 features, 65 MB)─▶│
                                                              │
        scripts/load_municipalities.py  ── pymongo upsert ───▶│
                                                              ▼
                                MongoDB upme.municipalities
                                ├─ $jsonSchema validator (validationAction: error)
                                ├─ 2dsphere index on geometry
                                ├─ unique index on divipola
                                └─ index on is_pdet
```

**Result in MongoDB:**

- 170 documents (`is_pdet = true` for all 170)
- 4 indexes: `_id_`, `geometry_2dsphere`, `divipola_1` (unique), `is_pdet_1`
- 19 departments, 16 subregiones (matches Decreto 893/2017)

Visuals to include:
- Screenshot of Mongo Express showing `upme.municipalities` with 170 docs
  and one document expanded (paste the JSON view of e.g. Tumaco 52835).
- Screenshot of `db.municipalities.getIndexes()` output.
- Plain-text dump in `docs/week2-screenshots/01_mongo_evidence.txt`.

Speaker notes: "MongoDB is the right NoSQL choice because GeoJSON
geometry + 2dsphere index does $geoWithin and $geoIntersects natively —
that's exactly the spatial join Week 3 needs to attribute buildings to
municipalities."

---

## Slide 6 — Spatial query proof

Two queries that prove the index works AND the collection is PDET-only:

```js
// Tumaco (DIVIPOLA 52835) IS a PDET muni
db.municipalities.find({
  geometry: { $geoIntersects: {
    $geometry: { type: "Point", coordinates: [-78.69039, 1.61122] }
  } }
})
// → 1 hit: SAN ANDRÉS DE TUMACO, NARIÑO, PACÍFICO Y FRONTERA NARIÑENSE

// Bogotá D.C. is NOT PDET
db.municipalities.find({
  geometry: { $geoIntersects: {
    $geometry: { type: "Point", coordinates: [-74.07, 4.60] }
  } }
})
// → 0 hits — collection correctly excludes non-PDET
```

Visual: screenshot of running both queries in mongosh side-by-side.

Speaker notes: "The Bogotá miss is just as important as the Tumaco hit
— it proves we filtered correctly. If we'd accidentally loaded all 1,122
munis, Bogotá would return a result."

---

## Slide 7 — PDET subregions covered

| Subregión PDET | Munis | Área (km²) |
| --- | ---: | ---: |
| MACARENA - GUAVIARE | 12 | 96,169 |
| CUENCA DEL CAGUÁN Y PIEDEMONTE CAQUETEÑO | 17 | 93,298 |
| CHOCÓ | 14 | 29,548 |
| PUTUMAYO | 9 | 25,063 |
| SIERRA NEVADA - PERIJÁ | 15 | 20,415 |
| BAJO CAUCA Y NORDESTE ANTIOQUEÑO | 13 | 17,615 |
| PACÍFICO Y FRONTERA NARIÑENSE | 11 | 17,119 |
| PACÍFICO MEDIO | 4 | 14,302 |
| ALTO PATÍA Y NORTE DEL CAUCA | 24 | 13,178 |
| ARAUCA | 4 | 10,540 |
| SUR DE BOLÍVAR | 7 | 10,332 |
| SUR DE CÓRDOBA | 5 | 9,581 |
| URABÁ ANTIOQUEÑO | 8 | 9,459 |
| CATATUMBO | 8 | 9,238 |
| SUR DEL TOLIMA | 4 | 6,919 |
| MONTES DE MARÍA | 15 | 6,407 |
| **TOTAL** | **170** | **389,182** |

Optional visual: open `data/processed/pdet_municipios.geojson` in QGIS,
style by `subregion_pdet` (Categorized), overlay on a Colombia basemap.
This is the slide that makes the audience *see* the data.

Speaker notes: "The largest subregión by area is Macarena-Guaviare —
Amazonian frontier munis. By muni count, Alto Patía / Norte del Cauca has
24."

---

## Slide 8 — Documentation & reproducibility

**Documents produced:**

- `data/raw/SOURCES.md` — full provenance for both sources
- `docs/week2-validation.md` — auto-generated audit log (re-runs every time)
- `docs/week2-pdet-loading.md` — methodology write-up

**Reproducibility — 5 commands from a clean checkout:**

```bash
docker compose up -d
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /scripts/init.js
# (place data/raw/municipios_colombia.geojson per SOURCES.md)
python scripts/validate_pdet.py
python scripts/load_municipalities.py
```

Speaker notes: "The whole pipeline is idempotent. Re-running upserts on
DIVIPOLA, validators reject malformed inserts, the audit log regenerates.
That is the contract we needed for Week 3 to build on top."

---

## Backup slide — anticipated Q&A

| Question | Concise answer |
| --- | --- |
| Why MongoDB, not PostGIS? | Project mandates NoSQL. MongoDB has native GeoJSON + 2dsphere, no add-on needed. |
| Why EPSG:9377 for area? | Equal-area projection for Colombia (MAGNA-SIRGAS Origen Nacional). WGS84 degrees ≠ metres. |
| Why is `additionalProperties: false`? | Strict schema contract — malformed inserts fail loudly via `validationAction: error`. |
| Why aren't non-PDET munis loaded? | Scope is PDET-only; loading 1,122 would pollute Week 3's spatial join. Raw GeoJSON stays in `data/raw/` for future re-scoping. |
| 0 invalid geometries — what if DANE ships bad data later? | `make_valid` is applied conditionally in `validate_pdet.py`; defensive even though current input is clean. |
| Why are loaded_at + source on every doc? | Provenance and re-load tracking. Required for the eventual cross-dataset comparison in Week 3-4. |
| How will Week 3 use this? | Each building will get its containing `divipola` via point-in-polygon against this collection. 2dsphere makes that O(log N). |

---

## What to do *right now*

1. Open `docs/week2-screenshots/01_mongo_evidence.txt` — that is the
   text you can show if the projector cannot render Mongo Express.
2. Open Mongo Express at <http://localhost:8081> (admin / admin), navigate
   to `upme` → `municipalities`, screenshot the list view (170 docs) and
   the expanded view of one document.
3. Run the two queries from Slide 6 in mongosh; screenshot the output.
4. Open `data/processed/pdet_municipios.geojson` in QGIS, style by
   `subregion_pdet`, export as image — that's the visual for Slide 7.
5. Open `docs/week2-validation.md` rendered (GitHub or VS Code preview);
   screenshot the "Checks passed: 11" header.
