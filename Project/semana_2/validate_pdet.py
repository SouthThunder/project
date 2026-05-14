"""
Week 2 — Data Integrity & Format.

Reads the full DANE MGN municipalities GeoJSON and the official ART PDET list,
filters to the 170 PDET municipalities, validates every geometry, computes
equal-area `area_sqkm` in EPSG:9377 (MAGNA-SIRGAS Origen Nacional), and emits:

  - data/processed/pdet_municipios.geojson   cleaned 170-feature dataset
                                             with the field names that
                                             municipalities.schema.json expects
  - docs/week2-validation.md                 validation report

Run from project root:
  python scripts/validate_pdet.py
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.validation import explain_validity, make_valid

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"

MGN_GEOJSON = RAW / "municipios_colombia.geojson"
PDET_CSV = RAW / "pdet_municipios.csv"
OUT_GEOJSON = PROCESSED / "pdet_municipios.geojson"
OUT_REPORT = DOCS / "week2-validation.md"

# Colombia mainland + island bounding box (lon_min, lat_min, lon_max, lat_max).
COLOMBIA_BBOX = (-82.0, -5.0, -66.0, 13.5)
EXPECTED_COUNT = 170
EXPECTED_SUBREGIONS = 16
# ART reports PDET municipalities cover ~36% of Colombia's ~1.14M km^2 territory,
# i.e. ~410,000 km^2. The 170 polygons include very large Amazonian munis
# (Solano ~42k km^2, San Vicente del Caguán ~20k km^2). Bracket loosely.
AREA_LOW_KM2 = 300_000
AREA_HIGH_KM2 = 500_000


def load_pdet_codes() -> dict[str, dict]:
    with PDET_CSV.open(encoding="utf-8") as f:
        return {row["divipola"]: row for row in csv.DictReader(f)}


def main() -> int:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    log: list[str] = []

    def say(msg: str) -> None:
        print(msg)
        log.append(msg)

    say(f"[*] Loading {MGN_GEOJSON.relative_to(ROOT)} ...")
    gdf = gpd.read_file(MGN_GEOJSON)
    say(f"    {len(gdf)} features, CRS={gdf.crs}")

    # ---- 1. CRS check -----------------------------------------------------
    crs_ok = gdf.crs is not None and gdf.crs.to_epsg() == 4326
    say(f"[{'OK' if crs_ok else 'FAIL'}] CRS is EPSG:4326: {crs_ok}")

    # ---- 2. Required source fields ---------------------------------------
    required_src = ["mpio_cdpmp", "mpio_cnmbr", "dpto_cnmbr", "dpto_ccdgo", "mpio_ccdgo"]
    missing_cols = [c for c in required_src if c not in gdf.columns]
    say(f"[{'OK' if not missing_cols else 'FAIL'}] Source columns present: missing={missing_cols}")
    if missing_cols:
        return 1

    # Normalize DIVIPOLA to zero-padded 5-digit strings.
    gdf["divipola"] = gdf["mpio_cdpmp"].astype(str).str.zfill(5)

    # ---- 3. Filter to PDET ----------------------------------------------
    pdet = load_pdet_codes()
    say(f"[*] PDET reference list: {len(pdet)} codes ({EXPECTED_COUNT} expected)")

    sub = gdf[gdf["divipola"].isin(pdet)].copy()
    found = set(sub["divipola"])
    expected = set(pdet)
    missing = sorted(expected - found)
    extras = sorted(found - expected)

    say(f"[{'OK' if not missing else 'FAIL'}] PDET codes found in MGN: {len(found)}/{EXPECTED_COUNT}")
    if missing:
        say(f"    Missing: {missing}")
    if extras:
        say(f"    Unexpected extras: {extras}")

    # ---- 4. Uniqueness ---------------------------------------------------
    dups = sub["divipola"].value_counts()
    dups = dups[dups > 1]
    say(f"[{'OK' if dups.empty else 'FAIL'}] No duplicate DIVIPOLA in filtered set: {dups.empty}")
    if not dups.empty:
        say(f"    Duplicates: {dups.to_dict()}")

    # ---- 5. Geometry type ------------------------------------------------
    types = sub.geometry.geom_type.value_counts().to_dict()
    bad_types = {t: n for t, n in types.items() if t not in {"Polygon", "MultiPolygon"}}
    say(f"[{'OK' if not bad_types else 'FAIL'}] Geometry types: {types}")

    # ---- 6. Validity + repair -------------------------------------------
    invalid_mask = ~sub.geometry.is_valid
    n_invalid = int(invalid_mask.sum())
    say(f"[{'OK' if n_invalid == 0 else 'WARN'}] Invalid geometries: {n_invalid}")
    if n_invalid:
        for idx in sub[invalid_mask].index[:5]:
            say(f"    {sub.at[idx, 'divipola']}  {sub.at[idx, 'mpio_cnmbr']}: "
                f"{explain_validity(sub.at[idx, 'geometry'])}")
        # Repair in place.
        sub.loc[invalid_mask, "geometry"] = sub.loc[invalid_mask, "geometry"].apply(make_valid)
        still_bad = int((~sub.geometry.is_valid).sum())
        say(f"    after make_valid: {still_bad} still invalid")

    empty = int(sub.geometry.is_empty.sum())
    say(f"[{'OK' if empty == 0 else 'FAIL'}] Empty geometries: {empty}")

    # ---- 7. Bounding box (Colombia) -------------------------------------
    minx, miny, maxx, maxy = sub.total_bounds
    in_box = (
        COLOMBIA_BBOX[0] <= minx
        and COLOMBIA_BBOX[1] <= miny
        and maxx <= COLOMBIA_BBOX[2]
        and maxy <= COLOMBIA_BBOX[3]
    )
    say(f"[{'OK' if in_box else 'WARN'}] Bounds within Colombia BBOX: "
        f"({minx:.3f},{miny:.3f},{maxx:.3f},{maxy:.3f})")

    # ---- 8. Area (EPSG:9377) --------------------------------------------
    say("[*] Reprojecting to EPSG:9377 for equal-area computation ...")
    sub_9377 = sub.to_crs(epsg=9377)
    sub["area_sqkm"] = (sub_9377.geometry.area / 1_000_000).round(6)
    total = float(sub["area_sqkm"].sum())
    say(f"    Total PDET area: {total:,.1f} km^2 (sanity: {AREA_LOW_KM2:,}-{AREA_HIGH_KM2:,})")
    area_sane = AREA_LOW_KM2 <= total <= AREA_HIGH_KM2
    say(f"[{'OK' if area_sane else 'WARN'}] Total area within expected range: {area_sane}")
    say(f"    Smallest muni: {sub['area_sqkm'].min():,.2f} km^2")
    say(f"    Largest muni:  {sub['area_sqkm'].max():,.2f} km^2")

    # ---- 9. Subregion count ---------------------------------------------
    pdet_df = sub.merge(
        gpd.pd.DataFrame.from_records(list(pdet.values())),
        on="divipola",
        how="left",
        suffixes=("", "_art"),
    )
    n_subregions = pdet_df["subregion_pdet"].nunique()
    say(f"[{'OK' if n_subregions == EXPECTED_SUBREGIONS else 'FAIL'}] "
        f"PDET subregions: {n_subregions} ({EXPECTED_SUBREGIONS} expected)")

    # ---- 10. Build cleaned output ---------------------------------------
    loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = pdet_df[[
        "divipola",
        "mpio_cnmbr",
        "dpto_cnmbr",
        "dpto_ccdgo",
        "subregion_pdet",
        "area_sqkm",
        "geometry",
    ]].rename(columns={
        "mpio_cnmbr": "name",
        "dpto_cnmbr": "department",
        "dpto_ccdgo": "department_code",
    })
    out["department_code"] = out["department_code"].astype(str).str.zfill(2)
    out["is_pdet"] = True
    out["source"] = "DANE MGN2025 + ART PDET (Decreto 893/2017)"
    out["loaded_at"] = loaded_at

    out.to_file(OUT_GEOJSON, driver="GeoJSON")
    size_mb = OUT_GEOJSON.stat().st_size / (1024 * 1024)
    say(f"[OK] Wrote {OUT_GEOJSON.relative_to(ROOT)} ({size_mb:.1f} MB, {len(out)} features)")

    # ---- 11. Report ------------------------------------------------------
    pass_marks = sum(1 for ln in log if ln.startswith("[OK]"))
    fail_marks = sum(1 for ln in log if ln.startswith("[FAIL]"))
    warn_marks = sum(1 for ln in log if ln.startswith("[WARN]"))

    report = [
        "# Week 2 — Validation Report",
        "",
        f"Generated: {loaded_at}",
        "",
        "## Summary",
        "",
        f"- Checks passed: **{pass_marks}**",
        f"- Warnings: **{warn_marks}**",
        f"- Failures: **{fail_marks}**",
        f"- Output: `{OUT_GEOJSON.relative_to(ROOT).as_posix()}` ({size_mb:.1f} MB, {len(out)} features)",
        "",
        "## Inputs",
        "",
        f"- `{MGN_GEOJSON.relative_to(ROOT).as_posix()}` — DANE MGN 2025 (1,122 municipios)",
        f"- `{PDET_CSV.relative_to(ROOT).as_posix()}` — ART list (170 PDET DIVIPOLA codes)",
        "",
        "## Log",
        "",
        "```",
        *log,
        "```",
        "",
        "## Output schema",
        "",
        "GeoJSON FeatureCollection (EPSG:4326). Each feature's `properties`:",
        "",
        "| Field | Type | Notes |",
        "| --- | --- | --- |",
        "| divipola | string | 5-digit zero-padded |",
        "| name | string | DANE official name |",
        "| department | string | DANE department name |",
        "| department_code | string | 2-digit zero-padded |",
        "| subregion_pdet | string | ART subregion |",
        "| is_pdet | boolean | always `true` in this file |",
        "| area_sqkm | number | computed in EPSG:9377 |",
        "| source | string | provenance |",
        "| loaded_at | string | ISO-8601 UTC |",
        "",
    ]
    OUT_REPORT.write_text("\n".join(report), encoding="utf-8")
    say(f"[OK] Wrote {OUT_REPORT.relative_to(ROOT).as_posix()}")

    return 0 if fail_marks == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
