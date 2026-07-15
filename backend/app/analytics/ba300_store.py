from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def read_monthly_rows(root: Path, geography_id: str = "GR") -> list[dict[str, Any]]:
    jsonl = root / "ba300" / "derived" / geography_id / "monthly_stats.jsonl"
    if jsonl.exists():
        return [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    parquet = root / "ba300" / "derived" / geography_id / "monthly_stats.parquet"
    if parquet.exists():
        try:
            import pandas as pd

            return pd.read_parquet(parquet).to_dict(orient="records")
        except Exception:
            return []
    return []


def ingested_months(root: Path, geography_id: str = "GR") -> list[str]:
    rows = read_monthly_rows(root, geography_id)
    return sorted({f"{int(row['year']):04d}-{int(row['month']):02d}" for row in rows})


def find_month(root: Path, year: int, month: int, geography_id: str = "GR") -> dict[str, Any] | None:
    for row in read_monthly_rows(root, geography_id):
        if int(row.get("year", -1)) == year and int(row.get("month", -1)) == month:
            return row
    return None


def clusters_geojson(root: Path, geography_id: str = "GR", year: int | None = None, month: int | None = None) -> dict[str, Any]:
    path = root / "ba300" / "derived" / geography_id / "clusters.geojson"
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    if year is not None:
        features = [feature for feature in features if _feature_year(feature) == year]
    if month is not None:
        features = [feature for feature in features if _feature_month(feature) == month]
    return {"type": "FeatureCollection", "features": [normalise_cluster_feature(feature) for feature in features]}


def get_cluster(root: Path, cluster_id: str, geography_id: str = "GR") -> dict[str, Any]:
    for feature in clusters_geojson(root, geography_id).get("features", []):
        if feature.get("properties", {}).get("cluster_id") == cluster_id:
            return feature
    raise KeyError(f"Real BA300 cluster not found: {cluster_id}")


def largest_cluster(root: Path, geography_id: str = "GR", year: int | None = None) -> dict[str, Any]:
    features = clusters_geojson(root, geography_id, year=year).get("features", [])
    if not features:
        suffix = f" for {year}" if year else ""
        raise KeyError(f"No real BA300 clusters are available{suffix}.")
    return sorted(features, key=lambda f: float(f.get("properties", {}).get("area_ha", 0.0)), reverse=True)[0]


def normalise_cluster_feature(feature: dict[str, Any]) -> dict[str, Any]:
    out = dict(feature)
    props = dict(out.get("properties") or {})
    period_start = str(props.get("period_start") or "")
    period_end = str(props.get("period_end") or "")
    year = _feature_year(feature)
    month = _feature_month(feature)
    area_ha = float(props.get("burned_area_occurrence_ha") or props.get("unique_burned_surface_ha") or props.get("area_ha") or 0.0)
    mean_cp = props.get("mean_cp")
    props.setdefault("area_ha", area_ha)
    props.setdefault("month", month)
    props.setdefault("year", year)
    props.setdefault("burn_window_start", period_start)
    props.setdefault("burn_window_end", period_end)
    props.setdefault("first_burn_date", period_start)
    props.setdefault("pre_search_start", _shift_date(period_start, -45))
    props.setdefault("pre_search_end", _shift_date(period_start, -1))
    props.setdefault("post_search_start", _shift_date(period_end, 1))
    props.setdefault("post_search_end", _shift_date(period_end, 45))
    props.setdefault("mean_confidence", mean_cp)
    props.setdefault("admin_region", "Greece")
    props.setdefault("dominant_landcover", "not computed from real WorldCover yet")
    props.setdefault("landcover_ha", {})
    props.setdefault("population_exposure_proxy", None)
    props.setdefault("builtup_exposure_ha", None)
    props.setdefault("source_dataset", "CLMS BA300 monthly v4")
    out["properties"] = props
    return out


def summarise_year(root: Path, year: int, geography_id: str = "GR") -> dict[str, Any]:
    rows = [row for row in read_monthly_rows(root, geography_id) if int(row.get("year", -1)) == year]
    if not rows:
        raise KeyError(f"No real BA300 months have been ingested for Greece in {year}.")
    monthly = [
        {
            "month": int(row["month"]),
            "month_id": f"{int(row['year']):04d}-{int(row['month']):02d}",
            "burned_area_ha": float(row["burned_area_occurrence_ha"]),
            "unique_burned_surface_ha": float(row["unique_burned_surface_ha"]),
            "cluster_count": len(clusters_geojson(root, geography_id, int(row["year"]), int(row["month"])).get("features", [])),
        }
        for row in sorted(rows, key=lambda item: int(item["month"]))
    ]
    total = sum(item["burned_area_ha"] for item in monthly)
    peak = max(monthly, key=lambda item: item["burned_area_ha"])
    return {
        "year": year,
        "monthly": monthly,
        "annual": {
            "burned_area_ha": round(total, 4),
            "burned_area_km2": round(total / 100.0, 4),
            "peak_month": peak["month"],
            "months_ingested": len(monthly),
            "complete_year": len(monthly) == 12,
        },
    }


def _feature_year(feature: dict[str, Any]) -> int | None:
    value = str((feature.get("properties") or {}).get("period_start") or "")
    return int(value[:4]) if len(value) >= 4 and value[:4].isdigit() else None


def _feature_month(feature: dict[str, Any]) -> int | None:
    value = str((feature.get("properties") or {}).get("period_start") or "")
    return int(value[5:7]) if len(value) >= 7 and value[5:7].isdigit() else None


def _shift_date(value: str, days: int) -> str | None:
    try:
        return (date.fromisoformat(value) + timedelta(days=days)).isoformat()
    except ValueError:
        return None
