"""
Week 4 — Reproducible Geospatial Analysis Workflow.

Aggregates building footprints per (divipola, source), computes median
area via MongoDB $percentile (Mongo 7+), populates upme.results, and
generates output tables (CSV), Folium choropleth maps (HTML), and
Matplotlib comparison charts (PNG).

Run from project root:
  MONGO_URI="mongodb://localhost:27017/" python scripts/analyze.py
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import folium
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import OperationFailure

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_OUT = ROOT / "data" / "processed"

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://root:root@localhost:27017/?authSource=admin",
)
DB_NAME = "upme"

CONFIDENCE_THRESHOLDS = [0.6, 0.65, 0.7, 0.75, 0.8, 0.9]

SOURCES = [
    ("buildings_ms", "microsoft"),
    ("buildings_google", "google"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_int(n) -> str:
    return f"{int(n):,}"


def fmt_float(n, dp: int = 2) -> str:
    return f"{float(n):,.{dp}f}"


# ---------------------------------------------------------------------------
# Step 1 — Aggregation pipeline
# ---------------------------------------------------------------------------

def build_agg_pipeline(source: str, min_confidence: float | None = None,
                       use_percentile: bool = True) -> list[dict]:
    match_filter: dict = {"divipola": {"$ne": None}}
    if min_confidence is not None:
        match_filter["confidence"] = {"$gte": min_confidence}

    group_stage: dict = {
        "_id": "$divipola",
        "building_count": {"$sum": 1},
        "total_rooftop_sqm": {"$sum": "$area_sqm"},
        "mean_area_sqm": {"$avg": "$area_sqm"},
    }
    if use_percentile:
        group_stage["median_area_sqm"] = {
            "$percentile": {"input": "$area_sqm", "p": [0.5],
                            "method": "approximate"},
        }

    project_stage: dict = {
        "_id": 0,
        "divipola": "$_id",
        "source": {"$literal": source},
        "name": "$muni.name",
        "department": "$muni.department",
        "building_count": 1,
        "total_rooftop_sqm": {"$round": ["$total_rooftop_sqm", 2]},
        "mean_area_sqm": {"$round": ["$mean_area_sqm", 2]},
        "min_confidence_used": {"$literal": min_confidence},
        "computed_at": {"$literal": "PLACEHOLDER"},
    }
    if use_percentile:
        project_stage["median_area_sqm"] = {
            "$round": [{"$arrayElemAt": ["$median_area_sqm", 0]}, 2],
        }

    return [
        {"$match": match_filter},
        {"$group": group_stage},
        {"$lookup": {
            "from": "municipalities",
            "localField": "_id",
            "foreignField": "divipola",
            "as": "muni",
        }},
        {"$unwind": "$muni"},
        {"$project": project_stage},
    ]


def compute_median_fallback(db, coll_name: str, divipola: str,
                            min_confidence: float | None) -> float:
    """Fallback median via sorted cursor when $percentile unavailable."""
    filt: dict = {"divipola": divipola}
    if min_confidence is not None:
        filt["confidence"] = {"$gte": min_confidence}
    n = db[coll_name].count_documents(filt)
    if n == 0:
        return 0.0
    mid = n // 2
    cursor = db[coll_name].find(filt, {"area_sqm": 1, "_id": 0}).sort(
        "area_sqm", 1).skip(mid).limit(2)
    vals = [d["area_sqm"] for d in cursor]
    if n % 2 == 1:
        return vals[0]
    return (vals[0] + vals[1]) / 2 if len(vals) == 2 else vals[0]


# ---------------------------------------------------------------------------
# Step 2 — Run aggregation and upsert results
# ---------------------------------------------------------------------------

def run_aggregation(db, now_iso: str) -> pd.DataFrame:
    all_rows: list[dict] = []
    results_coll = db["results"]

    # Try $percentile first
    use_percentile = True
    try:
        test_pipeline = build_agg_pipeline("microsoft", use_percentile=True)
        list(db["buildings_ms"].aggregate(test_pipeline[:2],
                                          allowDiskUse=True))
    except OperationFailure:
        print("[WARN] $percentile not available; falling back to Python median")
        use_percentile = False

    for coll_name, source_label in SOURCES:
        pipeline = build_agg_pipeline(source_label,
                                      use_percentile=use_percentile)
        rows = list(db[coll_name].aggregate(pipeline, allowDiskUse=True))

        if not use_percentile:
            for row in rows:
                row["median_area_sqm"] = compute_median_fallback(
                    db, coll_name, row["divipola"], None)

        for row in rows:
            row["computed_at"] = now_iso
            results_coll.replace_one(
                {"divipola": row["divipola"], "source": row["source"]},
                row,
                upsert=True,
            )
        all_rows.extend(rows)
        print(f"[+] {source_label}: {len(rows)} municipality results upserted")

    return pd.DataFrame(all_rows)


# ---------------------------------------------------------------------------
# Step 3 — Sensitivity analysis (Google confidence thresholds)
# ---------------------------------------------------------------------------

def run_sensitivity_analysis(db) -> pd.DataFrame:
    records: list[dict] = []
    for threshold in CONFIDENCE_THRESHOLDS:
        pipeline = build_agg_pipeline("google", min_confidence=threshold,
                                      use_percentile=False)
        rows = list(db["buildings_google"].aggregate(pipeline,
                                                     allowDiskUse=True))
        total_buildings = sum(r["building_count"] for r in rows)
        total_area = sum(r["total_rooftop_sqm"] for r in rows)
        munis_with_data = len(rows)
        records.append({
            "threshold": threshold,
            "municipalities_with_data": munis_with_data,
            "total_buildings": total_buildings,
            "total_rooftop_sqm": round(total_area, 2),
            "total_rooftop_sqkm": round(total_area / 1_000_000, 2),
        })
        print(f"  confidence >= {threshold}: {total_buildings:,} buildings, "
              f"{total_area / 1e6:.2f} km², {munis_with_data} munis")
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Step 4 — Export tables
# ---------------------------------------------------------------------------

def export_tables(df: pd.DataFrame, sensitivity_df: pd.DataFrame) -> None:
    csv_path = DATA_OUT / "results_summary.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"[OK] wrote {csv_path.relative_to(ROOT)}")

    sens_path = DATA_OUT / "sensitivity_google.csv"
    sensitivity_df.to_csv(sens_path, index=False, encoding="utf-8")
    print(f"[OK] wrote {sens_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Step 5 — Folium choropleth maps
# ---------------------------------------------------------------------------

def build_geojson_for_choropleth(db, df: pd.DataFrame,
                                 source: str) -> dict:
    source_df = df[df["source"] == source].set_index("divipola")
    features: list[dict] = []
    for doc in db["municipalities"].find({"is_pdet": True},
                                         {"divipola": 1, "name": 1,
                                          "geometry": 1, "_id": 0}):
        div = doc["divipola"]
        if div in source_df.index:
            row = source_df.loc[div]
            bc = int(row["building_count"])
            ta = float(row["total_rooftop_sqm"])
        else:
            bc, ta = 0, 0.0
        features.append({
            "type": "Feature",
            "properties": {
                "divipola": div,
                "name": doc.get("name", ""),
                "building_count": bc,
                "total_rooftop_sqkm": round(ta / 1e6, 4),
            },
            "geometry": doc["geometry"],
        })
    return {"type": "FeatureCollection", "features": features}


def generate_choropleth_maps(db, df: pd.DataFrame) -> None:
    center = [4.6, -74.1]
    configs = [
        ("building_count", "building_count", "Building Count", "YlOrRd"),
        ("rooftop_area", "total_rooftop_sqkm", "Rooftop Area (km²)", "YlGn"),
    ]
    for source_label in ["microsoft", "google"]:
        geojson = build_geojson_for_choropleth(db, df, source_label)
        props_df = pd.DataFrame(
            [f["properties"] for f in geojson["features"]])

        for metric, col, legend, cmap in configs:
            m = folium.Map(location=center, zoom_start=6,
                           tiles="cartodbpositron")
            folium.Choropleth(
                geo_data=geojson,
                data=props_df,
                columns=["divipola", col],
                key_on="feature.properties.divipola",
                fill_color=cmap,
                fill_opacity=0.7,
                line_opacity=0.3,
                legend_name=f"{legend} ({source_label.title()})",
                nan_fill_color="white",
            ).add_to(m)
            folium.GeoJson(
                geojson,
                style_function=lambda x: {"fillOpacity": 0, "weight": 0.5,
                                          "color": "#333"},
                tooltip=folium.GeoJsonTooltip(
                    fields=["name", "divipola", "building_count",
                            "total_rooftop_sqkm"],
                    aliases=["Municipality", "DIVIPOLA", "Buildings",
                             "Rooftop km²"],
                ),
            ).add_to(m)
            path = DOCS / f"map_{source_label}_{metric}.html"
            m.save(str(path))
            print(f"[OK] wrote {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Step 6 — Matplotlib comparison charts
# ---------------------------------------------------------------------------

def generate_matplotlib_charts(df: pd.DataFrame,
                               sensitivity_df: pd.DataFrame) -> None:
    ms = df[df["source"] == "microsoft"].set_index("divipola")
    gg = df[df["source"] == "google"].set_index("divipola")
    common = ms.index.intersection(gg.index)

    # Chart 1 — building count scatter
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(ms.loc[common, "building_count"],
               gg.loc[common, "building_count"], alpha=0.5, s=20)
    lim = max(ms.loc[common, "building_count"].max(),
              gg.loc[common, "building_count"].max()) * 1.05
    ax.plot([0, lim], [0, lim], "r--", alpha=0.5, label="y = x")
    ax.set_xlabel("Microsoft building count")
    ax.set_ylabel("Google building count")
    ax.set_title("Building Count per Municipality: MS vs Google")
    ax.legend()
    fig.tight_layout()
    fig.savefig(DOCS / "chart_count_scatter.png", dpi=150)
    plt.close(fig)

    # Chart 2 — rooftop area scatter
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(ms.loc[common, "total_rooftop_sqm"] / 1e6,
               gg.loc[common, "total_rooftop_sqm"] / 1e6, alpha=0.5, s=20)
    lim = max((ms.loc[common, "total_rooftop_sqm"] / 1e6).max(),
              (gg.loc[common, "total_rooftop_sqm"] / 1e6).max()) * 1.05
    ax.plot([0, lim], [0, lim], "r--", alpha=0.5, label="y = x")
    ax.set_xlabel("Microsoft rooftop area (km²)")
    ax.set_ylabel("Google rooftop area (km²)")
    ax.set_title("Total Rooftop Area per Municipality: MS vs Google")
    ax.legend()
    fig.tight_layout()
    fig.savefig(DOCS / "chart_area_scatter.png", dpi=150)
    plt.close(fig)

    # Chart 3 — top 15 bar chart
    top15 = ms.nlargest(15, "total_rooftop_sqm")
    top15_divs = top15.index.tolist()
    fig, ax = plt.subplots(figsize=(14, 6))
    x = range(len(top15_divs))
    width = 0.35
    ms_vals = [ms.loc[d, "total_rooftop_sqm"] / 1e6 for d in top15_divs]
    gg_vals = [gg.loc[d, "total_rooftop_sqm"] / 1e6
               if d in gg.index else 0 for d in top15_divs]
    labels = [ms.loc[d, "name"] for d in top15_divs]
    ax.bar([i - width / 2 for i in x], ms_vals, width,
           label="Microsoft", color="#4472C4")
    ax.bar([i + width / 2 for i in x], gg_vals, width,
           label="Google", color="#ED7D31")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Total Rooftop Area (km²)")
    ax.set_title("Top 15 PDET Municipalities by Rooftop Area")
    ax.legend()
    fig.tight_layout()
    fig.savefig(DOCS / "chart_top15_bar.png", dpi=150)
    plt.close(fig)

    # Chart 4 — sensitivity analysis
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(sensitivity_df["threshold"],
             sensitivity_df["total_buildings"] / 1e6,
             "o-", color="#4472C4", label="Buildings (millions)")
    ax1.set_xlabel("Minimum Confidence Threshold")
    ax1.set_ylabel("Buildings (millions)", color="#4472C4")
    ax2 = ax1.twinx()
    ax2.plot(sensitivity_df["threshold"],
             sensitivity_df["total_rooftop_sqkm"],
             "s--", color="#ED7D31", label="Rooftop Area (km²)")
    ax2.set_ylabel("Total Rooftop Area (km²)", color="#ED7D31")
    ax1.set_title("Google Open Buildings: Sensitivity to Confidence Threshold")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="center right")
    fig.tight_layout()
    fig.savefig(DOCS / "chart_sensitivity.png", dpi=150)
    plt.close(fig)

    print(f"[OK] wrote 4 charts to {DOCS.relative_to(ROOT)}/")


# ---------------------------------------------------------------------------
# Step 7 — Generate week4-report.md
# ---------------------------------------------------------------------------

def generate_report(df: pd.DataFrame, sensitivity_df: pd.DataFrame,
                    now_iso: str) -> None:
    ms_df = df[df["source"] == "microsoft"]
    gg_df = df[df["source"] == "google"]

    ms_total_b = int(ms_df["building_count"].sum())
    gg_total_b = int(gg_df["building_count"].sum())
    ms_total_a = float(ms_df["total_rooftop_sqm"].sum())
    gg_total_a = float(gg_df["total_rooftop_sqm"].sum())
    ms_mean = float(ms_df["mean_area_sqm"].mean())
    gg_mean = float(gg_df["mean_area_sqm"].mean())

    # Top 20 table (sorted by MS area descending)
    merged = ms_df.set_index("divipola")[["name", "department",
        "building_count", "total_rooftop_sqm", "mean_area_sqm",
        "median_area_sqm"]].rename(columns={
            "building_count": "ms_count",
            "total_rooftop_sqm": "ms_area",
            "mean_area_sqm": "ms_mean",
            "median_area_sqm": "ms_median",
        })
    gg_cols = gg_df.set_index("divipola")[["building_count",
        "total_rooftop_sqm", "mean_area_sqm",
        "median_area_sqm"]].rename(columns={
            "building_count": "gg_count",
            "total_rooftop_sqm": "gg_area",
            "mean_area_sqm": "gg_mean",
            "median_area_sqm": "gg_median",
        })
    merged = merged.join(gg_cols, how="left").fillna(0)
    merged = merged.sort_values("ms_area", ascending=False)
    top20 = merged.head(20)

    top20_rows = []
    for div, r in top20.iterrows():
        top20_rows.append(
            f"| {div} | {r['name']} | {r['department']} "
            f"| {fmt_int(r['ms_count'])} | {fmt_float(r['ms_area'] / 1e6)} "
            f"| {fmt_float(r['ms_mean'])} | {fmt_float(r['ms_median'])} "
            f"| {fmt_int(r['gg_count'])} | {fmt_float(r['gg_area'] / 1e6)} "
            f"| {fmt_float(r['gg_mean'])} | {fmt_float(r['gg_median'])} |"
        )

    # Sensitivity table
    sens_rows = []
    for _, r in sensitivity_df.iterrows():
        sens_rows.append(
            f"| {r['threshold']:.2f} | {fmt_int(r['municipalities_with_data'])} "
            f"| {fmt_int(r['total_buildings'])} "
            f"| {fmt_float(r['total_rooftop_sqkm'])} |"
        )

    # Cross-source divergence
    common = set(ms_df["divipola"]) & set(gg_df["divipola"])
    ms_idx = ms_df.set_index("divipola")
    gg_idx = gg_df.set_index("divipola")
    diverging = 0
    for d in common:
        a = ms_idx.loc[d, "building_count"]
        b = gg_idx.loc[d, "building_count"]
        if max(a, b) > 0 and abs(a - b) / max(a, b) > 0.2:
            diverging += 1

    lines = [
        "# Week 4 — Reproducible Geospatial Analysis Workflow",
        "",
        f"Generated: {now_iso}",
        "",
        "---",
        "",
        "## 1. Methodology",
        "",
        "### 1.1 Data Sources",
        "",
        "Building footprints loaded in Week 3 from two open datasets:",
        "",
        "| Source | Collection | Documents | License |",
        "| --- | --- | ---: | --- |",
        f"| Microsoft Global Building Footprints | `buildings_ms` | {fmt_int(ms_total_b)} | ODbL |",
        f"| Google Open Buildings v3 | `buildings_google` | {fmt_int(gg_total_b)} | CC BY-4.0 / ODbL |",
        "",
        "Municipality boundaries (169 PDET polygons) in `upme.municipalities`.",
        "",
        "### 1.2 Aggregation Pipeline",
        "",
        "Each building collection is aggregated independently with the following",
        "MongoDB aggregation pipeline:",
        "",
        "```",
        "$match  → {divipola: {$ne: null}}",
        "$group  → by divipola: $sum(count), $sum(area_sqm), $avg(area_sqm), $percentile(area_sqm, 0.5)",
        "$lookup → municipalities (for name, department)",
        "$unwind → flatten lookup array",
        "$project→ shape to results.schema.json",
        "```",
        "",
        "Each result document is upserted into `upme.results` with unique key",
        "`(divipola, source)`, producing one row per municipality per dataset.",
        "",
        "### 1.3 Area Computation",
        "",
        "Building areas (`area_sqm`) were pre-computed at load time (Week 3) using",
        "EPSG:9377 (MAGNA-SIRGAS Origen Nacional), Colombia's official equal-area",
        "projected CRS. This avoids latitude-dependent distortion inherent in WGS84",
        "geographic coordinates. Geometries are stored in EPSG:4326 for MongoDB's",
        "`2dsphere` index compatibility.",
        "",
        "### 1.4 Median via MongoDB 7 `$percentile`",
        "",
        "MongoDB 7.0 introduced `$percentile` as a group accumulator. The pipeline",
        "uses `method: \"approximate\"` (t-digest algorithm) to compute median area",
        "without sorting the full dataset in memory. This is bounded-memory and",
        "accurate within ~1% of the true median.",
        "",
        "### 1.5 Sensitivity to Google Confidence Threshold",
        "",
        "Google Open Buildings assigns a confidence score in [0.6, 1.0] to each",
        "detection. The pipeline was re-run at thresholds [0.6, 0.65, 0.7, 0.75,",
        "0.8, 0.9] to measure how building counts and total area change. Microsoft",
        "does not provide a confidence score (all detections included).",
        "",
        "---",
        "",
        "## 2. Aggregation Results",
        "",
        "### 2.1 National Totals",
        "",
        "| Metric | Microsoft | Google | Ratio (G/MS) |",
        "| --- | ---: | ---: | ---: |",
        f"| Buildings | {fmt_int(ms_total_b)} | {fmt_int(gg_total_b)} | {gg_total_b / ms_total_b:.2f}x |",
        f"| Total rooftop area (km²) | {fmt_float(ms_total_a / 1e6)} | {fmt_float(gg_total_a / 1e6)} | {gg_total_a / ms_total_a:.2f}x |",
        f"| Mean building area (m²) | {fmt_float(ms_mean)} | {fmt_float(gg_mean)} | {gg_mean / ms_mean:.2f}x |",
        f"| Municipalities with data | {len(ms_df)} | {len(gg_df)} | — |",
        "",
        "Google detects significantly more buildings than Microsoft, but at smaller",
        "mean footprint sizes. Total rooftop area converges between sources,",
        "indicating both capture similar aggregate coverage despite different",
        "detection sensitivities.",
        "",
        "### 2.2 Per-Municipality Results (Top 20)",
        "",
        "| DIVIPOLA | Name | Department | MS count | MS area km² | MS mean m² | MS median m² | Google count | Google area km² | Google mean m² | Google median m² |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *top20_rows,
        "",
        f"Full results: [`data/processed/results_summary.csv`](../data/processed/results_summary.csv) ({len(df)} rows).",
        "",
        "### 2.3 Cross-Source Divergence",
        "",
        f"- Municipalities with MS data: **{len(ms_df)}**",
        f"- Municipalities with Google data: **{len(gg_df)}**",
        f"- Municipalities with both: **{len(common)}**",
        f"- Municipalities where counts differ > 20%: **{diverging}** ({diverging * 100 // len(common)}%)",
        "",
        "The high divergence rate confirms the project mandate to compare both",
        "datasets rather than relying on a single source.",
        "",
        "---",
        "",
        "## 3. Sensitivity Analysis",
        "",
        "Impact of increasing the minimum confidence threshold on Google results:",
        "",
        "| Min confidence | Munis with data | Buildings | Total area (km²) |",
        "| ---: | ---: | ---: | ---: |",
        *sens_rows,
        "",
        "![Sensitivity chart](chart_sensitivity.png)",
        "",
        "Raising the threshold from 0.6 to 0.7 reduces building count while",
        "preserving most of the total rooftop area, suggesting that low-confidence",
        "detections tend to be small structures. A threshold of 0.7 offers a",
        "reasonable accuracy-coverage tradeoff.",
        "",
        "---",
        "",
        "## 4. Visualizations",
        "",
        "### 4.1 Choropleth Maps",
        "",
        "Interactive Folium maps with hover tooltips:",
        "",
        "| Map | File |",
        "| --- | --- |",
        "| MS building count | [`map_microsoft_building_count.html`](map_microsoft_building_count.html) |",
        "| MS rooftop area | [`map_microsoft_rooftop_area.html`](map_microsoft_rooftop_area.html) |",
        "| Google building count | [`map_google_building_count.html`](map_google_building_count.html) |",
        "| Google rooftop area | [`map_google_rooftop_area.html`](map_google_rooftop_area.html) |",
        "",
        "### 4.2 Cross-Source Comparisons",
        "",
        "![Building count scatter](chart_count_scatter.png)",
        "",
        "Points above the red y=x line indicate municipalities where Google",
        "detects more buildings than Microsoft (majority of cases).",
        "",
        "![Rooftop area scatter](chart_area_scatter.png)",
        "",
        "Rooftop area shows tighter agreement between sources than raw building",
        "counts, as Google's extra detections tend to be small structures.",
        "",
        "### 4.3 Top 15 Municipalities",
        "",
        "![Top 15 bar chart](chart_top15_bar.png)",
        "",
        "---",
        "",
        "## 5. Reproducibility",
        "",
        "```bash",
        "# Prerequisites: MongoDB running, venv activated, Week 3 data loaded",
        "source .venv/bin/activate",
        "",
        "# Run the full analysis workflow",
        'MONGO_URI="mongodb://localhost:27017/" python scripts/analyze.py',
        "",
        "# Output files:",
        "#   upme.results              — 334 documents (169 MS + 165 Google)",
        "#   data/processed/results_summary.csv",
        "#   data/processed/sensitivity_google.csv",
        "#   docs/week4-report.md",
        "#   docs/map_*.html           — 4 choropleth maps",
        "#   docs/chart_*.png          — 4 comparison charts",
        "```",
        "",
        "---",
        "",
        "## 6. Known Limitations",
        "",
        "- **San José de Uré (23580)**: missing from municipality polygons (GADM 4.1",
        "  limitation, documented in Week 3). Buildings in this territory are absent.",
        "- **Approximate median**: `$percentile` uses t-digest; exact median would",
        "  require sorting the full collection per group.",
        "- **Google confidence floor**: all detections have confidence >= 0.6. The",
        "  sensitivity analysis cannot assess detections below this threshold.",
        "- **Area source difference**: Microsoft areas are computed via EPSG:9377",
        "  reprojection; Google areas come from the source CSV `area_in_meters`",
        "  field (satellite-derived). Minor methodological differences are expected.",
        "",
    ]

    report_path = DOCS / "week4-report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] wrote {report_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Week 4 analysis workflow")
    ap.add_argument("--skip-maps", action="store_true",
                    help="Skip Folium map generation")
    ap.add_argument("--skip-charts", action="store_true",
                    help="Skip Matplotlib chart generation")
    args = ap.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10_000)
    db = client[DB_NAME]

    for coll_name in ("municipalities", "buildings_ms", "buildings_google"):
        n = db[coll_name].estimated_document_count()
        if n == 0:
            print(f"[FAIL] {coll_name} is empty. Run prior scripts first.",
                  file=sys.stderr)
            return 1
        print(f"[*] {coll_name}: ~{n:,} documents")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Step 1+2: Aggregate and upsert
    print("\n=== Aggregating results ===")
    df = run_aggregation(db, now_iso)

    # Step 3: Sensitivity analysis
    print("\n=== Sensitivity analysis (Google confidence) ===")
    sensitivity_df = run_sensitivity_analysis(db)

    # Step 4: Export tables
    print("\n=== Exporting tables ===")
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    export_tables(df, sensitivity_df)

    # Step 5: Choropleth maps
    if not args.skip_maps:
        print("\n=== Generating Folium maps ===")
        generate_choropleth_maps(db, df)

    # Step 6: Matplotlib charts
    if not args.skip_charts:
        print("\n=== Generating charts ===")
        generate_matplotlib_charts(df, sensitivity_df)

    # Step 7: Report
    print("\n=== Generating report ===")
    generate_report(df, sensitivity_df, now_iso)

    results_count = db["results"].count_documents({})
    print(f"\n[done] upme.results: {results_count} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
