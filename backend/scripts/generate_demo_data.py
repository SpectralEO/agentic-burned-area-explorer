from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "app" / "data" / "demo"


def polygon(cx: float, cy: float, w: float, h: float):
    return [[
        [cx - w / 2, cy - h / 2],
        [cx + w / 2, cy - h / 2],
        [cx + w / 2, cy + h / 2],
        [cx - w / 2, cy + h / 2],
        [cx - w / 2, cy - h / 2],
    ]]


def bbox_from_poly(poly: list[list[list[float]]]) -> list[float]:
    coords = poly[0]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def pad_bbox(bbox: list[float], pad: float) -> list[float]:
    return [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad]


def footprint_from_bbox(bbox: list[float]) -> dict:
    minx, miny, maxx, maxy = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]
        ]],
    }


def month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def mock_asset_href(sensor: str, item_id: str, asset: str) -> str:
    return f"mock://{sensor}/{item_id}/{asset}.tif"


def make_candidate(
    *,
    cluster_id: str,
    sensor_key: str,
    collection: str,
    item_id: str,
    role: str,
    dt: date,
    cloud: float,
    coverage: float,
    footprint: dict,
    reason: str,
) -> dict:
    sensor_label = {
        "sentinel-2": "Sentinel-2 L2A",
        "landsat": "Landsat Collection 2 Level-2",
        "modis": "MODIS surface reflectance",
    }[sensor_key]
    if sensor_key == "sentinel-2":
        assets = {k: mock_asset_href(sensor_key, item_id, k) for k in ["visual", "blue", "green", "red", "nir", "swir16", "swir22"]}
    elif sensor_key == "landsat":
        assets = {k: mock_asset_href(sensor_key, item_id, k) for k in ["blue", "green", "red", "nir08", "swir16", "swir22"]}
    else:
        assets = {k: mock_asset_href(sensor_key, item_id, k) for k in ["red", "green", "blue", "nir", "swir"]}
    return {
        "cluster_id": cluster_id,
        "item_id": item_id,
        "collection": collection,
        "sensor_key": sensor_key,
        "sensor": sensor_label,
        "role": role,
        "datetime": f"{dt.isoformat()}T09:20:00Z",
        "cloud_cover": cloud,
        "coverage": coverage,
        "geometry": footprint,
        "bbox": bbox_from_poly(footprint["coordinates"]),
        "assets": assets,
        "source": "mock-stac",
        "reason": reason,
    }


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    monthly = []
    vals = [0, 0, 18, 42, 76, 130, 410, 1540, 880, 210, 34, 5]
    for i, ha in enumerate(vals, start=1):
        monthly.append({"month": i, "burned_area_ha": ha * 100, "burned_area_km2": round(ha, 2)})
    summary = {
        "annual": {
            "aoi": "greece",
            "year": 2024,
            "burned_area_ha": sum(m["burned_area_ha"] for m in monthly),
            "burned_area_km2": round(sum(m["burned_area_km2"] for m in monthly), 2),
            "peak_month": 8,
            "mean_confidence": 0.78,
        },
        "monthly": monthly,
    }
    (DATA_DIR / "summary_2024.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    cluster_specs = [
        ("GR-2024-001", 26.0, 41.03, 0.96, 0.62, 58200, 8, 0.86, "Eastern Macedonia and Thrace", "tree cover", {"tree_cover": 40800, "shrub_grass": 12300, "cropland": 5100}, 210, 31.5, 14),
        ("GR-2024-002", 23.78, 38.18, 0.28, 0.18, 24650, 7, 0.74, "Attica", "shrub / herbaceous", {"tree_cover": 4200, "shrub_grass": 17100, "cropland": 2100, "built_up": 1250}, 1840, 74.2, 19),
        ("GR-2024-003", 21.82, 37.68, 0.36, 0.19, 31200, 8, 0.69, "Western Greece", "cropland", {"tree_cover": 9200, "shrub_grass": 8700, "cropland": 12900, "built_up": 400}, 620, 12.0, 21),
        ("GR-2024-004", 22.41, 39.24, 0.30, 0.16, 19800, 9, 0.81, "Thessaly", "cropland", {"tree_cover": 2600, "shrub_grass": 5900, "cropland": 11000, "built_up": 300}, 420, 8.7, 9),
        ("GR-2024-005", 24.04, 40.72, 0.22, 0.13, 9100, 8, 0.77, "Central Macedonia", "tree cover", {"tree_cover": 6900, "shrub_grass": 1700, "cropland": 500}, 95, 4.1, 27),
    ]
    event_overrides = {
        "GR-2024-001": {
            "first_burn": date(2023, 8, 23),
            "burn_start": date(2023, 8, 23),
            "burn_end": date(2023, 8, 23),
            "fire_front_event_date": "2023-08-23",
        },
    }
    features = []
    imagery = {}
    for cid, cx, cy, w, h, area, month, conf, region, dom, lc, pop, built, first_day in cluster_specs:
        geom_coords = polygon(cx, cy, w, h)
        geom = {"type": "Polygon", "coordinates": geom_coords}
        override = event_overrides.get(cid, {})
        first_burn = override.get("first_burn") or date(2024, month, first_day)
        burn_start = override.get("burn_start") or first_burn - timedelta(days=5)
        burn_end = override.get("burn_end") or first_burn + timedelta(days=12)
        pre_start = burn_start - timedelta(days=45)
        post_end = burn_end + timedelta(days=45)
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "cluster_id": cid,
                "area_ha": area,
                "month": month,
                "first_burn_date": first_burn.isoformat(),
                "burn_window_start": burn_start.isoformat(),
                "burn_window_end": burn_end.isoformat(),
                "fire_front_event_date": override.get("fire_front_event_date"),
                "pre_search_start": pre_start.isoformat(),
                "pre_search_end": (burn_start - timedelta(days=1)).isoformat(),
                "post_search_start": (burn_end + timedelta(days=1)).isoformat(),
                "post_search_end": post_end.isoformat(),
                "mean_confidence": conf,
                "admin_region": region,
                "dominant_landcover": dom,
                "landcover_ha": lc,
                "population_exposure_proxy": pop,
                "builtup_exposure_ha": built,
            },
        })
        bbox = pad_bbox(bbox_from_poly(geom_coords), 0.08)
        footprint = footprint_from_bbox(bbox)
        imagery[cid] = [
            make_candidate(
                cluster_id=cid,
                sensor_key="sentinel-2",
                collection="sentinel-2-l2a",
                item_id=f"S2A_DEMO_{cid}_PRE",
                role="pre-fire",
                dt=first_burn - timedelta(days=24),
                cloud=4.2,
                coverage=0.99,
                footprint=footprint,
                reason="Low-cloud Sentinel-2 image before the inferred burn window; covers cluster footprint.",
            ),
            make_candidate(
                cluster_id=cid,
                sensor_key="sentinel-2",
                collection="sentinel-2-l2a",
                item_id=f"S2A_DEMO_{cid}_EVENT",
                role="during-window",
                dt=first_burn,
                cloud=8.5,
                coverage=0.99,
                footprint=footprint,
                reason="Sentinel-2 event-window image intended for natural-colour/SWIR fire-front highlight review.",
            ),
            make_candidate(
                cluster_id=cid,
                sensor_key="sentinel-2",
                collection="sentinel-2-l2a",
                item_id=f"S2B_DEMO_{cid}_POST",
                role="post-fire",
                dt=first_burn + timedelta(days=18),
                cloud=6.8,
                coverage=0.98,
                footprint=footprint,
                reason="Low-cloud Sentinel-2 image after the inferred burn window; covers cluster footprint.",
            ),
            make_candidate(
                cluster_id=cid,
                sensor_key="landsat",
                collection="landsat-c2-l2",
                item_id=f"LC09_DEMO_{cid}_PRE",
                role="pre-fire",
                dt=first_burn - timedelta(days=30),
                cloud=9.6,
                coverage=1.0,
                footprint=footprint,
                reason="Landsat fallback before the inferred burn window.",
            ),
            make_candidate(
                cluster_id=cid,
                sensor_key="landsat",
                collection="landsat-c2-l2",
                item_id=f"LC09_DEMO_{cid}_POST",
                role="post-fire",
                dt=first_burn + timedelta(days=23),
                cloud=12.4,
                coverage=1.0,
                footprint=footprint,
                reason="Landsat fallback after the inferred burn window.",
            ),
            make_candidate(
                cluster_id=cid,
                sensor_key="modis",
                collection="modis-demo-context",
                item_id=f"MODIS_DEMO_{cid}_CONTEXT",
                role="during-window",
                dt=first_burn + timedelta(days=1),
                cloud=18.0,
                coverage=1.0,
                footprint=footprint_from_bbox(pad_bbox(bbox, 0.24)),
                reason="Coarse MODIS-style regional context only; not cluster-level validation.",
            ),
        ]
    geojson = {"type": "FeatureCollection", "features": features}
    (DATA_DIR / "clusters_2024.geojson").write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    (DATA_DIR / "imagery_candidates_2024.json").write_text(json.dumps(imagery, indent=2), encoding="utf-8")

    aod = {}
    drought = {}
    for f in features:
        cid = f["properties"]["cluster_id"]
        first = date.fromisoformat(f["properties"]["first_burn_date"])
        start = first - timedelta(days=10)
        aod[cid] = []
        for i in range(22):
            d = start + timedelta(days=i)
            peak = math.exp(-((i - 12) ** 2) / 18)
            aod[cid].append({"date": d.isoformat(), "aod": round(0.12 + 0.75 * peak + 0.02 * math.sin(i), 3)})
        dstart = first - timedelta(days=60)
        drought[cid] = []
        for i in range(0, 61, 5):
            d = dstart + timedelta(days=i)
            drought[cid].append({
                "date": d.isoformat(),
                "temperature_anomaly_c": round(1.0 + 1.8 * (i/60) + 0.2 * math.sin(i), 2),
                "precipitation_anomaly_mm": round(-12 - 35 * (i/60), 1),
                "soil_moisture_anomaly": round(-0.25 - 0.65 * (i/60), 2),
            })
    (DATA_DIR / "aod_timeseries_2024.json").write_text(json.dumps(aod, indent=2), encoding="utf-8")
    (DATA_DIR / "drought_timeseries_2024.json").write_text(json.dumps(drought, indent=2), encoding="utf-8")
    print(f"Demo data written to {DATA_DIR}")


if __name__ == "__main__":
    main()
