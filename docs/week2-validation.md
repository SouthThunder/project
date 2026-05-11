# Week 2 — Validation Report

Generated: 2026-05-11T17:50:52+00:00

## Summary

- Checks passed: **11**
- Warnings: **0**
- Failures: **0**
- Output: `data/processed/pdet_municipios.geojson` (65.2 MB, 170 features)

## Inputs

- `data/raw/municipios_colombia.geojson` — DANE MGN 2025 (1,122 municipios)
- `data/raw/pdet_municipios.csv` — ART list (170 PDET DIVIPOLA codes)

## Log

```
[*] Loading data\raw\municipios_colombia.geojson ...
    1122 features, CRS=EPSG:4326
[OK] CRS is EPSG:4326: True
[OK] Source columns present: missing=[]
[*] PDET reference list: 170 codes (170 expected)
[OK] PDET codes found in MGN: 170/170
[OK] No duplicate DIVIPOLA in filtered set: True
[OK] Geometry types: {'MultiPolygon': 170}
[OK] Invalid geometries: 0
[OK] Empty geometries: 0
[OK] Bounds within Colombia BBOX: (-79.010,-0.706,-69.995,11.349)
[*] Reprojecting to EPSG:9377 for equal-area computation ...
    Total PDET area: 389,182.0 km^2 (sanity: 300,000-500,000)
[OK] Total area within expected range: True
    Smallest muni: 83.67 km^2
    Largest muni:  42,233.53 km^2
[OK] PDET subregions: 16 (16 expected)
[OK] Wrote data\processed\pdet_municipios.geojson (65.2 MB, 170 features)
```

## Output schema

GeoJSON FeatureCollection (EPSG:4326). Each feature's `properties`:

| Field | Type | Notes |
| --- | --- | --- |
| divipola | string | 5-digit zero-padded |
| name | string | DANE official name |
| department | string | DANE department name |
| department_code | string | 2-digit zero-padded |
| subregion_pdet | string | ART subregion |
| is_pdet | boolean | always `true` in this file |
| area_sqkm | number | computed in EPSG:9377 |
| source | string | provenance |
| loaded_at | string | ISO-8601 UTC |
