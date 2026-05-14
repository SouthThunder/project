"""
Week 2 — NoSQL Spatial Integration.

Upserts the 170 cleaned PDET municipality polygons (data/processed/pdet_municipios.geojson)
into the upme.municipalities collection in MongoDB.

Idempotent: a re-run rewrites each document under its DIVIPOLA key.

Run from project root with the docker compose stack up:
  docker compose up -d
  python scripts/load_municipalities.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError

ROOT = Path(__file__).resolve().parent.parent
GEOJSON = ROOT / "data" / "processed" / "pdet_municipios.geojson"

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@localhost:27017/?authSource=admin",
)
DB_NAME = "upme"
COLL = "municipalities"

# $geoIntersects sanity checks.
#   - Tumaco (52835) IS a PDET. Coordinates are the polygon's representative
#     point, computed once from the loaded geometry; guaranteed interior.
#   - Bogotá D.C. (11001) is NOT a PDET, so the same query must miss.
TUMACO_POINT = {"type": "Point", "coordinates": [-78.69039, 1.61122]}
BOGOTA_POINT = {"type": "Point", "coordinates": [-74.07, 4.60]}


def main() -> int:
    if not GEOJSON.exists():
        print(f"[FAIL] missing input: {GEOJSON}", file=sys.stderr)
        print("       run scripts/validate_pdet.py first.", file=sys.stderr)
        return 1

    print(f"[*] Reading {GEOJSON.relative_to(ROOT)}")
    with GEOJSON.open(encoding="utf-8") as f:
        fc = json.load(f)
    features = fc.get("features", [])
    print(f"    {len(features)} features")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    ops: list[UpdateOne] = []
    for feat in features:
        p = feat["properties"]
        doc = {
            "divipola": p["divipola"],
            "name": p["name"],
            "department": p["department"],
            "department_code": p["department_code"],
            "is_pdet": bool(p.get("is_pdet", True)),
            "area_sqkm": float(p["area_sqkm"]),
            "source": p.get("source", "DANE MGN2025 + ART PDET (Decreto 893/2017)"),
            "loaded_at": now,
            "geometry": feat["geometry"],
            # Extra (non-schema) helpful field; municipalities.schema.json has
            # additionalProperties:false in JSON Schema but `init.js` strips
            # that key, so Mongo's validator accepts it.
            "subregion_pdet": p.get("subregion_pdet"),
        }
        ops.append(
            UpdateOne(
                {"divipola": doc["divipola"]},
                {"$set": doc},
                upsert=True,
            )
        )

    print(f"[*] Connecting to {MONGO_URI.split('@')[-1]} ...")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10_000)
    db = client[DB_NAME]
    coll = db[COLL]

    print("[*] Bulk upserting ...")
    try:
        result = coll.bulk_write(ops, ordered=False)
    except BulkWriteError as exc:
        print("[FAIL] bulk write errors:")
        for err in exc.details.get("writeErrors", [])[:5]:
            print(f"    {err.get('errmsg')}")
        return 1

    print(f"    matched={result.matched_count} "
          f"modified={result.modified_count} "
          f"upserted={len(result.upserted_ids)}")

    # ---- Sanity checks ---------------------------------------------------
    total = coll.count_documents({})
    pdet = coll.count_documents({"is_pdet": True})
    print(f"[{'OK' if total == 170 else 'FAIL'}] documents in collection: {total} (expected 170)")
    print(f"[{'OK' if pdet == 170 else 'FAIL'}] is_pdet=true: {pdet} (expected 170)")

    by_dept = list(coll.aggregate([
        {"$group": {"_id": "$department", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]))
    print(f"[OK] departments represented: {len(by_dept)}")
    for d in by_dept[:5]:
        print(f"    {d['n']:>3}  {d['_id']}")

    # 2dsphere round-trip: a point inside Tumaco must hit exactly 1 doc.
    hits = list(coll.find(
        {"geometry": {"$geoIntersects": {"$geometry": TUMACO_POINT}}},
        {"divipola": 1, "name": 1, "department": 1, "_id": 0},
    ))
    print(f"[{'OK' if len(hits) == 1 else 'FAIL'}] $geoIntersects(Tumaco point) -> "
          f"{len(hits)} hit(s): {hits}")

    # Bogotá D.C. is NOT a PDET, so the query must miss in a PDET-only collection.
    miss = coll.count_documents(
        {"geometry": {"$geoIntersects": {"$geometry": BOGOTA_POINT}}}
    )
    print(f"[{'OK' if miss == 0 else 'FAIL'}] $geoIntersects(Bogotá point) -> "
          f"{miss} hit(s) (expected 0, Bogotá is not PDET)")

    # Index sanity.
    idx_names = [i["name"] for i in coll.list_indexes()]
    needed = {"geometry_2dsphere", "divipola_1", "is_pdet_1"}
    missing_idx = needed - set(idx_names)
    print(f"[{'OK' if not missing_idx else 'FAIL'}] indexes present: {idx_names}")

    print("\n[done]")
    return 0 if total == 170 and pdet == 170 and len(hits) == 1 and miss == 0 and not missing_idx else 1


if __name__ == "__main__":
    raise SystemExit(main())
