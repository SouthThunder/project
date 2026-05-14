# Data Model — Week 1

## Why MongoDB

The project mandates a NoSQL store. Of the realistic options for polygon
data at this scale (~2-4M building footprints across 170 PDET
municipalities), MongoDB is the strongest fit:

- **Native GeoJSON + 2dsphere indexes.** `$geoWithin` and `$geoIntersects`
  do exactly the spatial join we need — "which buildings fall inside which
  municipality?" — without bolting on an external spatial library.
- **Document-per-building** matches the natural grain of the upstream data.
  Both Microsoft (GeoJSONL) and Google (CSV with one row per building)
  ship one footprint per record; we mirror that.
- **Aggregation framework** handles the analytical query end-to-end:
  `$match` → `$group` → `$lookup` against municipalities → write to
  `results`. No application-side fan-out required.
- **Operationally cheap.** A single container handles the full Colombia
  subset; no clustering needed for week 1-4.

Rejected:
- **Elasticsearch / OpenSearch** — capable but heavier ops; overkill at
  this size, and aggregation ergonomics are weaker for the join we need.
- **Redis Geo** — points only, no polygon queries. Wrong primitive.
- **Couchbase** — the geo story is thinner and the ecosystem help is
  scarce in Spanish-language reports.
- **PostGIS** — gold standard for this exact problem, but it's SQL, so
  disqualified by the "NoSQL solutions" mandate.

## Collections

| Collection         | Grain                              | Approx. size (final) |
| ------------------ | ---------------------------------- | -------------------- |
| `municipalities`   | one PDET municipality polygon      | 170 docs             |
| `buildings_ms`     | one Microsoft building footprint   | ~2-4M docs           |
| `buildings_google` | one Google building footprint      | ~1-3M docs           |
| `results`          | one (divipola, source) aggregate   | ~340 docs            |

`buildings_ms` and `buildings_google` share the same JSON Schema. They are
kept in *separate collections* (rather than one collection with a `source`
field) for three pragmatic reasons:

1. **Bulk loads can run in parallel** without contention on the same
   write-ahead log section.
2. **Spatial indexes stay smaller** per collection — a 2dsphere over 4M
   docs is meaningfully faster than over 7M.
3. **Re-loading one source** doesn't risk touching the other.

## Coordinate systems

Two CRSs are in play and the model is explicit about which is stored
where:

| Use                                 | CRS                | Why |
| ----------------------------------- | ------------------ | --- |
| Stored geometry (`geometry` field)  | EPSG:4326 / WGS84  | What 2dsphere requires; what GeoJSON defaults to. |
| Area computation (`area_sqm` field) | EPSG:9377 (MAGNA-SIRGAS Origen Nacional) or EPSG:6933 fallback | Equal-area projection. WGS84 areas in m² are wrong because longitude degrees compress with latitude. |

Areas are **precomputed at load time and stored as numbers** so analytical
queries never reproject. This is the standard "denormalize derived values"
pattern for OLAP-shaped reads on a document store.

## Spatial join: tag-at-load, not query-at-read

The naïve approach is to spatial-join at query time:

```js
db.buildings_ms.aggregate([
  { $match: { geometry: { $geoWithin: { $geometry: muni.geometry } } } },
  { $group: { _id: null, n: { $sum: 1 }, area: { $sum: "$area_sqm" } } },
]);
```

Run for each of 170 municipalities, that's 170 spatial scans per analysis
run. Instead, the ETL **tags every building with its containing
`divipola` once at load time** (`smoke_load.js` shows the pattern). Then
every analytical query is a plain indexed `$match` on `divipola` plus a
`$group`. Trades a one-shot ETL cost for unlimited cheap reads — the right
shape for this workload.

`divipola` is `null` for buildings that fall outside any PDET territory;
those are kept (not deleted) so that the dataset can be re-scoped to other
municipalities later without re-loading.

## Indexes

| Collection         | Index                        | Purpose |
| ------------------ | ---------------------------- | --- |
| `municipalities`   | `{ geometry: "2dsphere" }`   | Spatial join from buildings into munis. |
| `municipalities`   | `{ divipola: 1 }` unique     | Lookup key, also enforces no duplicates. |
| `municipalities`   | `{ is_pdet: 1 }`             | Cheap filter for the 170-of-many subset. |
| `buildings_*`      | `{ geometry: "2dsphere" }`   | Inverse spatial query (used during the tagging ETL). |
| `buildings_*`      | `{ divipola: 1 }`            | Per-municipality aggregation match. |
| `buildings_*`      | `{ source: 1, divipola: 1 }` | Composite for cross-source comparisons. |
| `buildings_*`      | `{ confidence: 1 }` sparse   | Filter low-confidence Google detections. |
| `results`          | `{ divipola: 1, source: 1 }` unique | One aggregate per cell. |

## Validation

Each collection has a `$jsonSchema` validator with `validationAction:
"error"` so a malformed insert fails loudly. The full JSON Schema files in
`/schema/` are also the spec used by code reviews and external tooling.
`init.js` strips the keywords MongoDB's `$jsonSchema` subset doesn't
support (`$schema`, `$id`, `format`) before installing the validator.

## What is *not* in scope for week 1

- Loading the real DANE MGN polygons — week 2.
- Loading the real Microsoft and Google buildings — week 3.
- The choropleth maps and final report — weeks 4-5.

Week 1 ships the *shape* of the system: a Mongo container, the four
collections, the indexes, the validators, and a smoke test that proves the
shape end-to-end with synthetic data so the design is demonstrably
exercisable, not just on paper.
