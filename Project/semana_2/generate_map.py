"""
Week 2 — Visualización: Mapa PDET por subregión.

Genera un mapa PNG de los 170 municipios PDET coloreados por subregión,
listo para incluir en la defensa o el informe.

Requiere:
    pip install geopandas matplotlib mapclassify

Uso (desde la raíz del proyecto):
    python scripts/generate_map.py

Salida:
    docs/week2-screenshots/mapa_pdet_subregiones.png
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
GEOJSON = ROOT / "data" / "processed" / "pdet_municipios.geojson"
OUT = ROOT / "docs" / "week2-screenshots" / "mapa_pdet_subregiones.png"


# 16 colores distinguibles para las subregiones
PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
    "#aaffc3",
]


def main() -> None:
    if not GEOJSON.exists():
        print(f"[ERROR] No se encontró {GEOJSON}")
        print("        Ejecuta primero: python scripts/validate_pdet.py")
        raise SystemExit(1)

    print(f"[*] Leyendo {GEOJSON} ...")
    gdf = gpd.read_file(GEOJSON)

    subregiones = sorted(gdf["subregion_pdet"].unique())
    color_map = {sub: PALETTE[i % len(PALETTE)] for i, sub in enumerate(subregiones)}
    gdf["color"] = gdf["subregion_pdet"].map(color_map)

    fig, ax = plt.subplots(1, 1, figsize=(14, 16))
    gdf.plot(
        ax=ax,
        color=gdf["color"],
        edgecolor="white",
        linewidth=0.3,
    )

    # Leyenda
    patches = [
        mpatches.Patch(color=color_map[sub], label=sub.title())
        for sub in subregiones
    ]
    ax.legend(
        handles=patches,
        loc="lower left",
        fontsize=6.5,
        framealpha=0.9,
        title="Subregión PDET",
        title_fontsize=7,
    )

    ax.set_title(
        "170 Municipios PDET — Colombia\n(Decreto Ley 893 de 2017)",
        fontsize=14,
        fontweight="bold",
        pad=12,
    )
    ax.set_axis_off()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[OK] Mapa guardado en {OUT}")


if __name__ == "__main__":
    main()
