"""
Week 3 — load building footprints into MongoDB.

For each downloaded tile (MS .csv.gz of GeoJSONL, Google .csv.gz of CSV-with-WKT):
  1. Stream rows.
  2. Build a Shapely polygon, compute its centroid in WGS84.
  3. Point-in-polygon lookup against an STRtree of the 170 PDET municipality
     polygons (loaded from MongoDB). If no hit, drop the building -- this
     clips ~31M raw Google detections down to the ~4-6M actually inside
     PDET territory.
  4. Compute area_sqm in EPSG:9377 (MS) or reuse Google's area_in_meters.
  5. Bulk-write into upme.buildings_ms or upme.buildings_google with the
     containing divipola already populated -- no separate tagging ETL pass
     needed since we know it at insert time.

Idempotent on a per-tile basis: each tile has a manifest entry in
data/processed/buildings_load_manifest.json. A re-run skips tiles whose
manifest entry shows the same upstream byte size + inserted count.

Run from project root with mongo up + downloads complete:
  python scripts/load_buildings.py            # both
  python scripts/load_buildings.py --ms       # only MS
  python scripts/load_buildings.py --google   # only Google
  python scripts/load_buildings.py --reset    # drop both collections first
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from pyproj import Transformer
from shapely import wkt as shp_wkt
from shapely.geometry import Polygon, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MS_DIR = RAW / "ms_buildings"
GOOGLE_DIR = RAW / "google_buildings"
MANIFEST = ROOT / "data" / "processed" / "buildings_load_manifest.json"

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@localhost:27017/?authSource=admin",
)
DB_NAME = "upme"
BATCH = 5_000

# Equal-area projection for Colombia (MAGNA-SIRGAS Origen Nacional).
_TF = Transformer.from_crs(4326, 9377, always_xy=True)


def _polygon_area_sqm(poly: Polygon) -> float:
    """Reproject a WGS84 polygon to EPSG:9377 and return its area in m^2."""
    ext = list(poly.exterior.coords)
    xs, ys = _TF.transform(*zip(*ext))
    new_ext = list(zip(xs, ys))
    new_holes = []
    for ring in poly.interiors:
        rxs, rys = _TF.transform(*zip(*list(ring.coords)))
        new_holes.append(list(zip(rxs, rys)))
    return Polygon(new_ext, holes=new_holes).area


def load_pdet_index(client: MongoClient) -> tuple[STRtree, list[Polygon], list[str]]:
    """Pull the 170 PDET polygons from Mongo and build an STRtree."""
    coll = client[DB_NAME]["municipalities"]
    polys: list[Polygon] = []
    divipolas: list[str] = []
    for doc in coll.find({"is_pdet": True}, {"divipola": 1, "geometry": 1}):
        polys.append(shape(doc["geometry"]))
        divipolas.append(doc["divipola"])
    tree = STRtree(polys)
    print(f"[*] PDET spatial index: {len(polys)} polygons")
    return tree, polys, divipolas


def find_divipola(tree: STRtree, polys: list[Polygon], divipolas: list[str], pt) -> str | None:
    # Shapely 2: STRtree.query returns a numpy array of integer indices into the
    # original geometry list. Bbox prefilter only; we still need a real covers test.
    for idx in tree.query(pt):
        idx = int(idx)
        if polys[idx].covers(pt):
            return divipolas[idx]
    return None


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2))


_SAMPLED_ERRORS: list[str] = []


def flush(coll, batch: list[dict]) -> int:
    if not batch:
        return 0
    try:
        res = coll.insert_many(batch, ordered=False)
        return len(res.inserted_ids)
    except BulkWriteError as exc:
        # Surface up to 3 distinct error messages so silent validation failures
        # are debuggable instead of being swallowed.
        if len(_SAMPLED_ERRORS) < 3:
            for e in exc.details.get("writeErrors", [])[:3]:
                msg = e.get("errmsg", "")[:300]
                if msg and msg not in _SAMPLED_ERRORS:
                    _SAMPLED_ERRORS.append(msg)
                    print(f"  [!] insert validation error: {msg}", flush=True)
        return int(exc.details.get("nInserted", 0))


def load_ms_tile(path: Path, coll, tree, polys, divipolas, now_iso: str) -> dict:
    """Stream one MS quadkey tile and insert its in-PDET buildings."""
    seen = inserted = 0
    skipped_off_pdet = 0
    invalid = 0
    bad_geom_type = 0
    batch: list[dict] = []
    quadkey = path.stem.split("=")[-1]

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            seen += 1
            line = line.strip()
            if not line:
                continue
            try:
                feat = json.loads(line)
                geom = feat.get("geometry")
                if not geom or geom.get("type") != "Polygon":
                    bad_geom_type += 1
                    continue
                poly = shape(geom)
                if not poly.is_valid or poly.is_empty:
                    invalid += 1
                    continue
                centroid = poly.representative_point()
                divipola = find_divipola(tree, polys, divipolas, centroid)
                if divipola is None:
                    skipped_off_pdet += 1
                    continue
                area = _polygon_area_sqm(poly)
                props = feat.get("properties") or {}
                # Microsoft uses -1 as a sentinel for missing confidence; the
                # buildings.schema.json validator requires 0 <= confidence <= 1.
                ms_conf = props.get("confidence")
                if ms_conf is None or ms_conf < 0:
                    ms_conf = None
                doc = {
                    "source": "microsoft",
                    "source_id": f"ms-{quadkey}-{seen}",
                    "divipola": divipola,
                    "confidence": ms_conf,
                    "area_sqm": float(area),
                    "loaded_at": now_iso,
                    "geometry": geom,
                }
                batch.append(doc)
                if len(batch) >= BATCH:
                    inserted += flush(coll, batch)
                    batch.clear()
            except Exception:
                invalid += 1
    inserted += flush(coll, batch)
    return {
        "rows_seen": seen,
        "inserted": inserted,
        "skipped_off_pdet": skipped_off_pdet,
        "invalid": invalid,
        "bad_geom_type": bad_geom_type,
        "bytes": path.stat().st_size,
    }


def load_google_tile(path: Path, coll, tree, polys, divipolas, now_iso: str) -> dict:
    """Stream one Google S2 cell tile and insert its in-PDET buildings."""
    seen = inserted = 0
    skipped_off_pdet = 0
    invalid = 0
    batch: list[dict] = []
    cell = path.stem.split("_")[0]

    with gzip.open(path, "rt", encoding="utf-8") as gz:
        reader = csv.DictReader(gz)
        for row in reader:
            seen += 1
            try:
                wkt_str = row.get("geometry") or ""
                if not wkt_str.startswith("POLYGON"):
                    invalid += 1
                    continue
                poly = shp_wkt.loads(wkt_str)
                if not poly.is_valid or poly.is_empty:
                    invalid += 1
                    continue
                centroid = poly.representative_point()
                divipola = find_divipola(tree, polys, divipolas, centroid)
                if divipola is None:
                    skipped_off_pdet += 1
                    continue
                area_str = row.get("area_in_meters") or "0"
                try:
                    area = float(area_str)
                except ValueError:
                    area = _polygon_area_sqm(poly)
                conf = row.get("confidence")
                gg_conf = None
                if conf:
                    try:
                        gg_conf = float(conf)
                        if not (0.0 <= gg_conf <= 1.0):
                            gg_conf = None
                    except ValueError:
                        gg_conf = None
                doc = {
                    "source": "google",
                    "source_id": f"google-{cell}-{row.get('full_plus_code') or seen}",
                    "divipola": divipola,
                    "confidence": gg_conf,
                    "area_sqm": area,
                    "loaded_at": now_iso,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [list(poly.exterior.coords)],
                    },
                }
                batch.append(doc)
                if len(batch) >= BATCH:
                    inserted += flush(coll, batch)
                    batch.clear()
            except Exception:
                invalid += 1
    inserted += flush(coll, batch)
    return {
        "rows_seen": seen,
        "inserted": inserted,
        "skipped_off_pdet": skipped_off_pdet,
        "invalid": invalid,
        "bytes": path.stat().st_size,
    }


def run(which: str, src_dir: Path, glob: str, load_fn, coll_name: str, client, tree, polys, divipolas, manifest) -> None:
    coll = client[DB_NAME][coll_name]
    files = sorted(src_dir.glob(glob))
    if not files:
        print(f"[!] no {which} tiles in {src_dir}/{glob}", file=sys.stderr)
        return
    print(f"\n[*] {which}: {len(files)} tiles -> {coll_name}")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.time()
    total_inserted = 0
    total_seen = 0
    total_off = 0
    for i, path in enumerate(files, 1):
        key = f"{which}:{path.name}"
        m = manifest.get(key)
        if m and m.get("bytes") == path.stat().st_size:
            print(f"  [{i}/{len(files)}] {path.name}  SKIP (manifest)")
            continue
        ts = time.time()
        stats = load_fn(path, coll, tree, polys, divipolas, now_iso)
        dt = time.time() - ts
        total_inserted += stats["inserted"]
        total_seen += stats["rows_seen"]
        total_off += stats["skipped_off_pdet"]
        manifest[key] = stats | {"loaded_at": now_iso}
        save_manifest(manifest)
        rate = stats["inserted"] / dt if dt > 0 else 0
        print(f"  [{i:>3}/{len(files)}] {path.name:<40}  "
              f"seen={stats['rows_seen']:>7,} ins={stats['inserted']:>7,} "
              f"off_pdet={stats['skipped_off_pdet']:>7,} "
              f"{dt:>5.1f}s  {rate:>7,.0f} ins/s")
    elapsed = time.time() - t0
    print(f"[done] {which}: inserted {total_inserted:,} of {total_seen:,} "
          f"(off_pdet={total_off:,}) in {elapsed/60:.1f} min")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ms", action="store_true")
    ap.add_argument("--google", action="store_true")
    ap.add_argument("--reset", action="store_true", help="Drop target collections first")
    args = ap.parse_args()
    if not args.ms and not args.google:
        args.ms = args.google = True

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10_000)
    db = client[DB_NAME]

    if args.reset:
        for c in ("buildings_ms", "buildings_google"):
            if c in db.list_collection_names():
                print(f"[!] dropping {c}")
                db[c].drop()
        # Re-run init.js to recreate validators + indexes.
        print("[!] re-run scripts/init.js after --reset to restore validators and indexes.")
        return 0

    tree, polys, divipolas = load_pdet_index(client)
    manifest = load_manifest()

    if args.ms:
        run("ms", MS_DIR, "quadkey=*.csv.gz", load_ms_tile,
            "buildings_ms", client, tree, polys, divipolas, manifest)
    if args.google:
        run("google", GOOGLE_DIR, "*_buildings.csv.gz", load_google_tile,
            "buildings_google", client, tree, polys, divipolas, manifest)

    # Post-load counts.
    for c in ("buildings_ms", "buildings_google"):
        n = db[c].estimated_document_count()
        print(f"[OK] {c}: ~{n:,} documents")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
