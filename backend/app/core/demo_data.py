from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.settings import get_settings


@lru_cache
def load_json(name: str) -> Any:
    path = get_settings().data_dir / name
    if not path.exists():
        raise FileNotFoundError(
            f"Demo data file not found: {path}. Run `python scripts/generate_demo_data.py`."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def burned_area_summary(year: int) -> dict[str, Any]:
    return load_json(f"summary_{year}.json")


def clusters_geojson(year: int) -> dict[str, Any]:
    return load_json(f"clusters_{year}.geojson")


def get_cluster(year: int, cluster_id: str) -> dict[str, Any]:
    for feature in clusters_geojson(year)["features"]:
        if feature["properties"]["cluster_id"] == cluster_id:
            return feature
    raise KeyError(f"Cluster not found: {cluster_id}")


def largest_cluster(year: int) -> dict[str, Any]:
    features = clusters_geojson(year)["features"]
    return sorted(features, key=lambda f: f["properties"]["area_ha"], reverse=True)[0]


def imagery_candidates(year: int) -> dict[str, Any]:
    return load_json(f"imagery_candidates_{year}.json")


def aod_timeseries(year: int) -> dict[str, Any]:
    return load_json(f"aod_timeseries_{year}.json")


def drought_timeseries(year: int) -> dict[str, Any]:
    return load_json(f"drought_timeseries_{year}.json")
