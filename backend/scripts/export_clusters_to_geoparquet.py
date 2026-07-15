"""Optional helper to convert demo cluster GeoJSON to GeoParquet.

Requires optional geospatial dependencies:
    uv sync --extra geospatial
    uv run python scripts/export_clusters_to_geoparquet.py
"""

from pathlib import Path

import geopandas as gpd

DATA_DIR = Path(__file__).resolve().parents[1] / "app" / "data" / "demo"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "vectors"

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gdf = gpd.read_file(DATA_DIR / "clusters_2024.geojson")
    gdf.to_parquet(OUT_DIR / "burn_clusters_2024_greece.parquet")
    print(f"Wrote {OUT_DIR / 'burn_clusters_2024_greece.parquet'}")

if __name__ == "__main__":
    main()
