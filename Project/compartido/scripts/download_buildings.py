"""
Week 3 — download building footprint tiles.

Microsoft Global Building Footprints (Bing/Maxar/Airbus):
  Index: https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv
  We filter to Location="Colombia" -> 232 tiles, ~647 MB compressed.
  Files are .csv.gz containing newline-delimited GeoJSON features.

Google Open Buildings v3:
  Index: https://storage.googleapis.com/open-buildings-data/v3/score_thresholds_s2_level_4.csv
  We pick the 8 S2 level-4 cells that intersect the PDET bbox (~3.0 GB).
  Files are .csv.gz with columns:
    latitude, longitude, area_in_meters, confidence, geometry (WKT), full_plus_code

Resumable: skips a tile whose target file exists with the expected size.

Run from project root:
  python scripts/download_buildings.py            # both datasets
  python scripts/download_buildings.py --ms       # only MS
  python scripts/download_buildings.py --google   # only Google
"""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from shapely import wkt as shp_wkt
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MS_DIR = RAW / "ms_buildings"
GOOGLE_DIR = RAW / "google_buildings"
MS_INDEX = MS_DIR / "dataset-links.csv"
GOOGLE_INDEX = GOOGLE_DIR / "score_thresholds.csv"

# Same PDET bbox computed by scripts/validate_pdet.py (lon_min, lat_min, lon_max, lat_max).
PDET_BBOX = box(-79.010, -0.706, -69.995, 11.349)

MS_PARALLEL = 8
GOOGLE_PARALLEL = 4   # Google tiles are large; smaller parallelism avoids saturating.

# Order matters: check multi-letter suffixes (KB/MB/GB) before plain "B".
SIZE_UNITS = [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024), ("B", 1)]


def parse_ms_size(s: str) -> int:
    s = s.strip()
    for unit, mult in SIZE_UNITS:
        if s.endswith(unit):
            return int(float(s[: -len(unit)]) * mult)
    return int(float(s))


def download(url: str, dest: Path, expected_size: int | None = None) -> tuple[Path, str]:
    if dest.exists():
        if expected_size is None or abs(dest.stat().st_size - expected_size) < max(2048, expected_size * 0.01):
            return dest, "skipped"
        dest.unlink()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    tmp.rename(dest)
    return dest, "downloaded"


def download_ms() -> int:
    MS_DIR.mkdir(parents=True, exist_ok=True)
    if not MS_INDEX.exists():
        print(f"[*] fetching MS dataset-links index ...")
        download(
            "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv",
            MS_INDEX,
        )

    with MS_INDEX.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["Location"] == "Colombia"]
    total_bytes = sum(parse_ms_size(r["Size"]) for r in rows)
    print(f"[*] MS tiles for Colombia: {len(rows)}  ({total_bytes/1024/1024:.1f} MB compressed)")

    tasks = []
    for row in rows:
        dest = MS_DIR / f"quadkey={row['QuadKey']}.csv.gz"
        tasks.append((row["Url"], dest, parse_ms_size(row["Size"])))

    done = 0
    downloaded = 0
    skipped = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=MS_PARALLEL) as ex:
        futures = {ex.submit(download, u, d, sz): d.name for (u, d, sz) in tasks}
        for fut in as_completed(futures):
            done += 1
            name = futures[fut]
            try:
                _, status = fut.result()
                if status == "downloaded":
                    downloaded += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                print(f"  [!] {name}: {exc}", file=sys.stderr)
            if done % 25 == 0 or done == len(tasks):
                print(f"    {done}/{len(tasks)}  downloaded={downloaded} skipped={skipped} failed={failed}")
    print(f"[done] MS: downloaded={downloaded} skipped={skipped} failed={failed}")
    return failed


def download_google() -> int:
    GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    if not GOOGLE_INDEX.exists():
        print(f"[*] fetching Google score_thresholds index ...")
        download(
            "https://storage.googleapis.com/open-buildings-data/v3/score_thresholds_s2_level_4.csv",
            GOOGLE_INDEX,
        )

    cells: list[str] = []
    with GOOGLE_INDEX.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            geom = shp_wkt.loads(row["geometry"])
            if geom.intersects(PDET_BBOX):
                cells.append(row["s2_token"])
    print(f"[*] Google S2 cells intersecting PDET bbox: {len(cells)} ({cells})")

    tasks = []
    for cell in cells:
        url = f"https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_4_gzip/{cell}_buildings.csv.gz"
        dest = GOOGLE_DIR / f"{cell}_buildings.csv.gz"
        tasks.append((url, dest))

    done = 0
    downloaded = 0
    skipped = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=GOOGLE_PARALLEL) as ex:
        futures = {ex.submit(download, u, d): d.name for (u, d) in tasks}
        for fut in as_completed(futures):
            done += 1
            name = futures[fut]
            try:
                _, status = fut.result()
                if status == "downloaded":
                    downloaded += 1
                else:
                    skipped += 1
                print(f"    [{done}/{len(tasks)}] {name}  {status}")
            except Exception as exc:
                failed += 1
                print(f"  [!] {name}: {exc}", file=sys.stderr)
    print(f"[done] Google: downloaded={downloaded} skipped={skipped} failed={failed}")
    return failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ms", action="store_true")
    ap.add_argument("--google", action="store_true")
    args = ap.parse_args()
    if not args.ms and not args.google:
        args.ms = args.google = True
    rc = 0
    if args.ms:
        rc += download_ms()
    if args.google:
        rc += download_google()
    return 1 if rc else 0


if __name__ == "__main__":
    raise SystemExit(main())
