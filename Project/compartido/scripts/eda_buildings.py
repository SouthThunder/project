"""
Week 3 — Initial Data Audit (EDA).

Quick post-load sanity report for buildings_ms + buildings_google.

Writes a Markdown summary to docs/week3-eda.md. All numbers come from
Mongo aggregations, so re-running it after a reload always reflects the
current state of the collections.

Run from project root:
  python scripts/eda_buildings.py
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "week3-eda.md"

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@localhost:27017/?authSource=admin",
)

SOURCES = [("buildings_ms", "Microsoft"), ("buildings_google", "Google")]


def fmt_int(n: int | float) -> str:
    return f"{int(n):,}"


def fmt_float(n: float, dp: int = 2) -> str:
    return f"{n:,.{dp}f}"


def main() -> int:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10_000)
    db = client["upme"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out: list[str] = ["# Week 3 — Initial Data Audit (EDA)", "", f"Generated: {now}", ""]

    # ---- Totals per source ----------------------------------------------
    out += ["## 1. Totals", "", "| Source | Documents | Tagged to PDET | Total rooftop area (km²) | Mean area (m²) |",
            "| --- | ---: | ---: | ---: | ---: |"]
    totals = {}
    for coll, label in SOURCES:
        c = db[coll]
        total = c.estimated_document_count()
        agg = list(c.aggregate([
            {"$match": {"divipola": {"$ne": None}}},
            {"$group": {
                "_id": None,
                "n": {"$sum": 1},
                "total_sqm": {"$sum": "$area_sqm"},
                "mean_sqm": {"$avg": "$area_sqm"},
            }},
        ]))
        tagged = agg[0]["n"] if agg else 0
        total_sqm = agg[0]["total_sqm"] if agg else 0
        mean_sqm = agg[0]["mean_sqm"] if agg else 0
        totals[coll] = {"total": total, "tagged": tagged, "total_sqm": total_sqm}
        out.append(f"| {label} | {fmt_int(total)} | {fmt_int(tagged)} | {fmt_float(total_sqm/1_000_000)} | {fmt_float(mean_sqm)} |")

    # ---- Top 15 munis (MS) ---------------------------------------------
    out += ["", "## 2. Top 15 PDET municipalities by Microsoft rooftop area", "",
            "| DIVIPOLA | Name | Department | MS buildings | MS rooftop km² | Google buildings | Google rooftop km² |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    pipeline_per_muni = [
        {"$match": {"divipola": {"$ne": None}}},
        {"$group": {
            "_id": "$divipola",
            "n": {"$sum": 1},
            "total_sqm": {"$sum": "$area_sqm"},
        }},
    ]
    ms_by_muni = {d["_id"]: d for d in db.buildings_ms.aggregate(pipeline_per_muni, allowDiskUse=True)}
    gg_by_muni = {d["_id"]: d for d in db.buildings_google.aggregate(pipeline_per_muni, allowDiskUse=True)}
    munis = {d["divipola"]: d for d in db.municipalities.find({}, {"divipola": 1, "name": 1, "department": 1})}
    rows = []
    for divipola, ms in ms_by_muni.items():
        gg = gg_by_muni.get(divipola, {"n": 0, "total_sqm": 0})
        info = munis.get(divipola, {"name": "?", "department": "?"})
        rows.append((divipola, info["name"], info["department"], ms["n"], ms["total_sqm"], gg["n"], gg["total_sqm"]))
    rows.sort(key=lambda r: -r[4])
    for r in rows[:15]:
        out.append(f"| {r[0]} | {r[1]} | {r[2]} | {fmt_int(r[3])} | {fmt_float(r[4]/1_000_000)} | {fmt_int(r[5])} | {fmt_float(r[6]/1_000_000)} |")

    # ---- Cross-source coverage delta -----------------------------------
    out += ["", "## 3. Cross-source coverage delta", "",
            "Number of PDET munis each source has > 0 detections for, plus a"
            " count of munis where the building-count differs by > 20 %.",
            ""]
    ms_munis = set(ms_by_muni)
    gg_munis = set(gg_by_muni)
    out += [
        f"- Munis with MS detections: **{len(ms_munis)}** / 170",
        f"- Munis with Google detections: **{len(gg_munis)}** / 170",
        f"- Munis with both: **{len(ms_munis & gg_munis)}**",
        f"- MS only: **{len(ms_munis - gg_munis)}**",
        f"- Google only: **{len(gg_munis - ms_munis)}**",
    ]
    diverging = 0
    for divipola in ms_munis & gg_munis:
        a = ms_by_muni[divipola]["n"]
        b = gg_by_muni[divipola]["n"]
        if max(a, b) > 0 and abs(a - b) / max(a, b) > 0.2:
            diverging += 1
    out.append(f"- Munis where MS and Google counts differ by > 20 %: **{diverging}**")

    # ---- Confidence distribution (Google only) -------------------------
    out += ["", "## 4. Google confidence distribution", "",
            "| Bucket | Count |", "| --- | ---: |"]
    buckets = list(db.buildings_google.aggregate([
        {"$match": {"divipola": {"$ne": None}, "confidence": {"$ne": None}}},
        {"$bucket": {
            "groupBy": "$confidence",
            "boundaries": [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.001],
            "default": "other",
            "output": {"n": {"$sum": 1}},
        }},
    ]))
    for b in buckets:
        out.append(f"| {b['_id']} | {fmt_int(b['n'])} |")

    # ---- Area distribution (both) --------------------------------------
    out += ["", "## 5. Building area distribution (m²)", "",
            "| Source | p10 | p50 | p90 | p99 | max |",
            "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for coll, label in SOURCES:
        rows = list(db[coll].aggregate([
            {"$match": {"divipola": {"$ne": None}}},
            {"$group": {"_id": None, "areas": {"$push": "$area_sqm"}}},
            {"$project": {
                "p10": {"$arrayElemAt": [{"$sortArray": {"input": "$areas", "sortBy": 1}}, {"$floor": {"$multiply": [{"$size": "$areas"}, 0.10]}}]},
                "p50": {"$arrayElemAt": [{"$sortArray": {"input": "$areas", "sortBy": 1}}, {"$floor": {"$multiply": [{"$size": "$areas"}, 0.50]}}]},
                "p90": {"$arrayElemAt": [{"$sortArray": {"input": "$areas", "sortBy": 1}}, {"$floor": {"$multiply": [{"$size": "$areas"}, 0.90]}}]},
                "p99": {"$arrayElemAt": [{"$sortArray": {"input": "$areas", "sortBy": 1}}, {"$floor": {"$multiply": [{"$size": "$areas"}, 0.99]}}]},
                "max": {"$max": "$areas"},
            }},
        ], allowDiskUse=True))
        if rows:
            r = rows[0]
            out.append(f"| {label} | {fmt_float(r['p10'])} | {fmt_float(r['p50'])} | {fmt_float(r['p90'])} | {fmt_float(r['p99'])} | {fmt_float(r['max'])} |")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"[OK] wrote {REPORT.relative_to(ROOT)}")
    print("\n".join(out[:30]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
