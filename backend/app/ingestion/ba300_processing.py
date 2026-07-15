from __future__ import annotations

import calendar
import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import bounds as geometry_bounds
from rasterio.features import geometry_mask, shapes
from rasterio.transform import Affine
from rasterio.warp import calculate_default_transform, reproject, transform_geom
from rasterio.windows import Window, bounds as window_bounds, from_bounds

from app.ingestion.ba300_common import PROCESSING_VERSION, Period, now_iso, real_root, write_json

REQUIRED = ["bf", "cp", "dob", "lfp"]
TARGET_CRS = "EPSG:3035"


def _load_aoi(path: Path) -> dict[str, Any]:
    if not path.exists() and str(path).replace("\\", "/") == "app/data/aoi/greece.geojson":
        path = Path(__file__).resolve().parents[1] / "data" / "aoi" / "greece.geojson"
    if not path.exists():
        raise FileNotFoundError(f"AOI GeoJSON not found: {path}. Use --aoi app/data/aoi/greece.geojson from backend/ or provide an absolute AOI path.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") == "FeatureCollection":
        features = data.get("features") or []
        if not features:
            raise RuntimeError(f"AOI has no features: {path}")
        return features[0]["geometry"]
    if data.get("type") == "Feature":
        return data["geometry"]
    return data


def _read_reprojected(
    path: Path,
    dst_crs: str,
    aoi_geom: dict[str, Any] | None = None,
    *,
    resampling: Resampling = Resampling.nearest,
    reference_profile: dict[str, Any] | None = None,
):
    with rasterio.open(path) as src:
        if reference_profile:
            transform = reference_profile["transform"]
            width = int(reference_profile["width"])
            height = int(reference_profile["height"])
            data = np.zeros((height, width), dtype=src.dtypes[0])
            reproject(
                source=rasterio.band(src, 1),
                destination=data,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                resampling=resampling,
                src_nodata=src.nodata,
                dst_nodata=src.nodata if src.nodata is not None else 0,
            )
        elif aoi_geom:
            geom_src = transform_geom("EPSG:4326", src.crs, aoi_geom)
            src_left, src_bottom, src_right, src_top = geometry_bounds(geom_src)
            window = from_bounds(src_left, src_bottom, src_right, src_top, transform=src.transform)
            window = window.round_offsets().round_lengths()
            window = window.intersection(Window(0, 0, src.width, src.height))
            if window.width <= 0 or window.height <= 0:
                raise RuntimeError(f"AOI does not intersect raster extent: {path}")
            src_transform = src.window_transform(window)
            src_bounds = window_bounds(window, src.transform)
            src_data = src.read(1, window=window, boundless=False)
            transform, width, height = calculate_default_transform(src.crs, dst_crs, int(window.width), int(window.height), *src_bounds)
            data = np.zeros((height, width), dtype=src.dtypes[0])
            reproject(
                source=src_data,
                destination=data,
                src_transform=src_transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                resampling=resampling,
                src_nodata=src.nodata,
                dst_nodata=src.nodata if src.nodata is not None else 0,
            )
        else:
            src_bounds = src.bounds
            transform, width, height = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src_bounds)
            data = np.zeros((height, width), dtype=src.dtypes[0])
            reproject(
                source=rasterio.band(src, 1),
                destination=data,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                resampling=resampling,
                src_nodata=src.nodata,
                dst_nodata=src.nodata if src.nodata is not None else 0,
            )
        profile = src.profile.copy()
        profile.update(crs=dst_crs, transform=transform, width=width, height=height, count=1)
    if aoi_geom:
        geom_3035 = transform_geom("EPSG:4326", dst_crs, aoi_geom)
        mask = geometry_mask([geom_3035], out_shape=data.shape, transform=transform, invert=True)
    else:
        mask = np.ones(data.shape, dtype=bool)
    return data, mask, profile


def _write_single(path: Path, data: np.ndarray, profile: dict[str, Any], *, dtype: str, description: str, nodata: float | int | None = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out_profile = profile.copy()
    out_profile.update(driver="GTiff", count=1, dtype=dtype, nodata=nodata, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(path, "w", **out_profile) as dst:
        dst.write(data.astype(dtype), 1)
        dst.set_band_description(1, description)


def _write_multiband(path: Path, arrays: list[np.ndarray], profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out_profile = profile.copy()
    out_profile.update(driver="GTiff", count=5, dtype="float32", nodata=0, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    descriptions = ["BF", "CP", "DOB", "LFP", "dataMask"]
    with rasterio.open(path, "w", **out_profile) as dst:
        for idx, (array, desc) in enumerate(zip(arrays, descriptions), start=1):
            dst.write(array.astype("float32"), idx)
            dst.set_band_description(idx, desc)


def _pixel_area_m2(transform: Affine) -> float:
    return abs(float(transform.a) * float(transform.e))


def _cluster_features(active_mask: np.ndarray, bf: np.ndarray, cp: np.ndarray, transform: Affine, period: Period, source_item_id: str | None) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    pixel_area_ha = _pixel_area_m2(transform) / 10000.0
    for idx, (geom, value) in enumerate(shapes(active_mask.astype("uint8"), mask=active_mask.astype(bool), transform=transform), start=1):
        if int(value) != 1:
            continue
        cluster_mask = geometry_mask([geom], out_shape=active_mask.shape, transform=transform, invert=True)
        pixels = cluster_mask & active_mask
        if not np.any(pixels):
            continue
        geom_4326 = transform_geom(TARGET_CRS, "EPSG:4326", geom)
        burned_ha = float(np.nansum(bf[pixels]) * pixel_area_ha)
        features.append(
            {
                "type": "Feature",
                "geometry": geom_4326,
                "properties": {
                    "cluster_id": f"GR-{period.year:04d}-{period.month:02d}-M-{idx:04d}",
                    "period_start": f"{period.label}-01",
                    "period_end": f"{period.label}-{calendar.monthrange(period.year, period.month)[1]:02d}",
                    "granularity": "month",
                    "burned_area_occurrence_ha": round(burned_ha, 4),
                    "unique_burned_surface_ha": round(burned_ha, 4),
                    "pixel_count": int(np.sum(pixels)),
                    "mean_bf": round(float(np.nanmean(bf[pixels])), 6),
                    "mean_cp": round(float(np.nanmean(cp[pixels])), 6) if np.any(cp[pixels]) else None,
                    "source_item_ids": [source_item_id] if source_item_id else [],
                    "processing_version": PROCESSING_VERSION,
                },
            }
        )
    return features


def process_month(
    period: Period,
    band_paths: dict[str, Path],
    *,
    aoi_path: Path,
    geography_id: str = "GR",
    source_item_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    missing = [band for band in REQUIRED if band not in band_paths]
    if missing:
        raise RuntimeError(f"BA300 month {period.label} is missing required band(s): {', '.join(missing)}")

    aoi_geom = _load_aoi(aoi_path)
    bf_raw, aoi_mask, profile = _read_reprojected(band_paths["bf"], TARGET_CRS, aoi_geom, resampling=Resampling.nearest)
    cp_raw, _cp_mask, _ = _read_reprojected(band_paths["cp"], TARGET_CRS, None, resampling=Resampling.nearest, reference_profile=profile)
    dob, _dob_mask, _ = _read_reprojected(band_paths["dob"], TARGET_CRS, None, resampling=Resampling.nearest, reference_profile=profile)
    lfp_raw, _lfp_mask, _ = _read_reprojected(band_paths["lfp"], TARGET_CRS, None, resampling=Resampling.nearest, reference_profile=profile)
    if "dataMask" in band_paths:
        data_mask, _dm_mask, _ = _read_reprojected(band_paths["dataMask"], TARGET_CRS, None, resampling=Resampling.nearest, reference_profile=profile)
        valid_mask = data_mask > 0
    else:
        data_mask = np.ones_like(bf_raw, dtype="uint8")
        valid_mask = np.ones_like(bf_raw, dtype=bool)

    bf = np.asarray(bf_raw, dtype="float32") * 0.001
    cp = np.asarray(cp_raw, dtype="float32") * 0.001
    lfp = np.asarray(lfp_raw, dtype="float32") * 0.001
    if np.nanmax(bf) > 1.001 or np.nanmax(cp) > 1.001 or np.nanmax(lfp) > 1.001:
        raise RuntimeError("BA300 scaling validation failed: scaled BF/CP/LFP exceed 1.")
    if np.nanmax(dob) > 366:
        raise RuntimeError("BA300 DOB validation failed: DOB exceeds 366.")

    valid = aoi_mask & valid_mask
    active = valid & (bf > 0)
    if not np.any(valid):
        raise RuntimeError("AOI does not intersect valid BA300 coverage.")

    pixel_area_ha = _pixel_area_m2(profile["transform"]) / 10000.0
    burned_occurrence = float(np.nansum(bf[active]) * pixel_area_ha)
    unique_surface = float(np.nansum(np.minimum(bf[active], 1.0)) * pixel_area_ha)
    mean_bf = float(np.nanmean(bf[active])) if np.any(active) else 0.0
    mean_cp = float(np.nanmean(cp[active])) if np.any(active) else 0.0

    out_dir = real_root() / "ba300" / "clipped" / geography_id / f"{period.year:04d}" / f"{period.month:02d}"
    if out_dir.exists() and not force:
        pass
    out_dir.mkdir(parents=True, exist_ok=True)
    multiband = out_dir / "ba300_multiband.tif"
    bf_scaled = out_dir / "bf_scaled.tif"
    active_mask_path = out_dir / "active_mask.tif"
    dob_path = out_dir / "dob.tif"
    _write_multiband(multiband, [bf, cp, dob.astype("float32"), lfp, data_mask.astype("float32")], profile)
    _write_single(bf_scaled, np.where(valid, bf, 0), profile, dtype="float32", description="BA300 scaled burned fraction")
    _write_single(active_mask_path, active.astype("uint8"), profile, dtype="uint8", description="BA300 active burned-area mask")
    _write_single(dob_path, np.where(valid, dob, 0), profile, dtype="int16", description="BA300 date of burn")

    stats = {
        "geography_id": geography_id,
        "year": period.year,
        "month": period.month,
        "period_start": f"{period.label}-01",
        "period_end": f"{period.label}-{calendar.monthrange(period.year, period.month)[1]:02d}",
        "burned_area_occurrence_ha": round(burned_occurrence, 4),
        "unique_burned_surface_ha": round(unique_surface, 4),
        "valid_pixel_count": int(np.sum(valid)),
        "burned_pixel_count": int(np.sum(active)),
        "mean_bf": round(mean_bf, 6),
        "mean_cp": round(mean_cp, 6),
        "source_item_id": source_item_id,
        "source_product": "CLMS BA300 monthly v4",
        "source_version": "V4.0.1",
        "processing_version": PROCESSING_VERSION,
        "ingested_at": now_iso(),
        "bf_scaled_path": str(bf_scaled),
        "active_mask_path": str(active_mask_path),
        "dob_path": str(dob_path),
        "multiband_path": str(multiband),
        "calculation_crs": TARGET_CRS,
        "pixel_area_m2": _pixel_area_m2(profile["transform"]),
    }
    features = _cluster_features(active, bf, cp, profile["transform"], period, source_item_id)
    clusters = {"type": "FeatureCollection", "features": features}

    derived_dir = real_root() / "ba300" / "derived" / geography_id
    derived_dir.mkdir(parents=True, exist_ok=True)
    monthly_json = derived_dir / "monthly_stats.jsonl"
    existing = []
    if monthly_json.exists():
        existing = [json.loads(line) for line in monthly_json.read_text(encoding="utf-8").splitlines() if line.strip()]
        existing = [row for row in existing if not (row.get("year") == period.year and row.get("month") == period.month and row.get("geography_id") == geography_id)]
    existing.append(stats)
    monthly_json.write_text("\n".join(json.dumps(row, sort_keys=True) for row in sorted(existing, key=lambda r: (r["year"], r["month"]))) + "\n", encoding="utf-8")
    try:
        import pandas as pd

        pd.DataFrame(existing).to_parquet(derived_dir / "monthly_stats.parquet", index=False)
        analytics_dir = real_root() / "analytics"
        analytics_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(existing).to_parquet(analytics_dir / "monthly_stats.parquet", index=False)
    except Exception:
        pass

    clusters_path = derived_dir / "clusters.geojson"
    existing_features = []
    if clusters_path.exists():
        try:
            existing_clusters = json.loads(clusters_path.read_text(encoding="utf-8"))
            existing_features = [
                feature for feature in existing_clusters.get("features", [])
                if feature.get("properties", {}).get("period_start") != stats["period_start"]
            ]
        except json.JSONDecodeError:
            existing_features = []
    clusters = {
        "type": "FeatureCollection",
        "features": sorted(
            [*existing_features, *features],
            key=lambda feature: (
                feature.get("properties", {}).get("period_start", ""),
                feature.get("properties", {}).get("cluster_id", ""),
            ),
        ),
    }
    clusters_path.write_text(json.dumps(clusters), encoding="utf-8")
    write_json(out_dir / "metadata.json", {**stats, "cluster_count": len(features), "validation": {"bf_scaled_range": [float(np.nanmin(bf)), float(np.nanmax(bf))], "cp_scaled_range": [float(np.nanmin(cp)), float(np.nanmax(cp))], "lfp_scaled_range": [float(np.nanmin(lfp)), float(np.nanmax(lfp))], "dob_range": [float(np.nanmin(dob)), float(np.nanmax(dob))]}})
    return {**stats, "cluster_count": len(features), "clusters_path": str(clusters_path)}
