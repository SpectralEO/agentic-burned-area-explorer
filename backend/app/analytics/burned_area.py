from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.analytics.ba300_store import read_monthly_rows
from app.analytics.temporal import resolve_temporal_window
from app.schemas.analytics import (
    BurnedAreaMetrics,
    BurnedAreaTemporalQuery,
    BurnedAreaTimelineResponse,
    MapRasterLayer,
)
from app.settings import Settings


PROCESSING_VERSION = "real-data-contract-v1"


@dataclass
class RealDataUnavailable(Exception):
    message: str
    payload: dict[str, Any]


def _analytics_cache_ready(root: Path) -> bool:
    return (
        (root / "analytics" / "monthly_stats.parquet").exists()
        or (root / "ba300" / "derived" / "GR" / "monthly_stats.jsonl").exists()
    )


def _read_monthly_rows(root: Path, geography_id: str) -> list[dict[str, Any]]:
    return read_monthly_rows(root, geography_id)


def _find_month(rows: list[dict[str, Any]], *, year: int, month: int) -> dict[str, Any] | None:
    for row in rows:
        if int(row.get("year", -1)) == year and int(row.get("month", -1)) == month:
            return row
    return None


def _tile_url(path: str, settings: Settings) -> str:
    href = path
    if href.startswith("app/data/real/"):
        href = f"/app/app/data/real/{href.removeprefix('app/data/real/')}"
    query = urlencode(
        {
            "r": href,
            "g": href,
            "b": href,
            "composite": "ba300_bf",
            "r_min": 0.001,
            "r_max": 1.0,
            "g_min": 0.001,
            "g_max": 1.0,
            "b_min": 0.001,
            "b_max": 1.0,
        }
    )
    return f"{settings.tiler_public_base.rstrip('/')}/tiles/{{z}}/{{x}}/{{y}}.png?{query}"


def burned_area_timeline(query: BurnedAreaTemporalQuery, settings: Settings) -> BurnedAreaTimelineResponse:
    window = resolve_temporal_window(query)
    root = settings.real_data_dir
    thresholds = {
        "minimum_cp": query.minimum_cp,
        "minimum_lfp": query.minimum_lfp,
        "minimum_bf": query.minimum_bf,
    }

    geography_id = query.geography_id or "GR"
    if not _analytics_cache_ready(root):
        response = BurnedAreaTimelineResponse(
            resolved_window=window,
            metrics=BurnedAreaMetrics(
                burned_area_occurrence_ha=0.0,
                unique_burned_surface_ha=0.0,
                cluster_count=0,
            ),
            layers={
                "active": MapRasterLayer(tiles=[], bounds=[], opacity=0.9),
                "context": MapRasterLayer(tiles=[], bounds=[], opacity=0.12),
            },
            clusters={"type": "FeatureCollection", "features": []},
            ui_context={
                "scope": "period-result",
                "capabilities": [
                    {"id": "burned-area-timeline", "visible": True, "enabled": False},
                    {"id": "cluster-selection", "visible": True, "enabled": False},
                    {"id": "legend", "visible": True, "enabled": True},
                ],
            },
            provenance={
                "source_product": "CLMS BA300 monthly v4",
                "processing_version": PROCESSING_VERSION,
                "calculation_crs": "EPSG:3035",
                "thresholds": thresholds,
                "real_data_dir": str(root),
            },
            caveats=[
                "Real BA300 analytics cache is not available yet.",
                "No synthetic burned-area values are returned in real-data mode.",
                "Run BA300 ingestion/preprocessing before requesting timeline metrics or map layers.",
            ],
        )
        raise RealDataUnavailable("BA300 monthly analytics cache is missing.", response.model_dump(mode="json"))

    rows = _read_monthly_rows(root, geography_id)
    if query.granularity != "month":
        raise RealDataUnavailable(
            "Only artifact-backed month timeline queries are implemented for real BA300 data in this pass.",
            {
                "resolved_window": window.model_dump(mode="json"),
                "caveats": ["Use granularity='month' until day/year derived artifacts are generated."],
            },
        )
    row = _find_month(rows, year=window.active_start.year, month=window.active_start.month)
    if not row:
        period = f"{window.active_start.year:04d}-{window.active_start.month:02d}"
        raise RealDataUnavailable(
            f"BA300 month {period} has not been ingested.",
            {
                "resolved_window": window.model_dump(mode="json"),
                "missing_period": period,
                "sync_command": f"cd backend && UV_CACHE_DIR=/tmp/wea-uv-cache uv run python -m app.ingestion.ba300_sync --start {period} --end {period} --aoi app/data/aoi/greece.geojson --source auto",
                "manual_import_command": f"cd backend && UV_CACHE_DIR=/tmp/wea-uv-cache uv run python -m app.ingestion.ba300_import --input app/data/real/inbox/ba300/{window.active_start.year:04d}/{window.active_start.month:02d} --aoi app/data/aoi/greece.geojson",
                "caveats": ["No synthetic burned-area values are returned for missing BA300 months."],
            },
        )

    clusters_path = root / "ba300" / "derived" / geography_id / "clusters.geojson"
    clusters = {"type": "FeatureCollection", "features": []}
    if clusters_path.exists():
        clusters = json.loads(clusters_path.read_text(encoding="utf-8"))
        clusters["features"] = [
            feature
            for feature in clusters.get("features", [])
            if feature.get("properties", {}).get("period_start") == row.get("period_start")
        ]

    bounds = [19.0, 34.0, 30.0, 42.5]
    active_path = str(row["bf_scaled_path"])
    context_tiles: list[str] = []
    response = BurnedAreaTimelineResponse(
        resolved_window=window,
        metrics=BurnedAreaMetrics(
            burned_area_occurrence_ha=float(row["burned_area_occurrence_ha"]),
            unique_burned_surface_ha=float(row["unique_burned_surface_ha"]),
            cluster_count=len(clusters.get("features", [])),
        ),
        layers={
            "active": MapRasterLayer(tiles=[_tile_url(active_path, settings)], bounds=bounds, opacity=0.9),
            "context": MapRasterLayer(tiles=context_tiles, bounds=bounds, opacity=0.12),
        },
        clusters=clusters,
        ui_context={
            "scope": "period-result",
            "capabilities": [
                {"id": "burned-area-timeline", "visible": True, "enabled": True},
                {"id": "cluster-selection", "visible": True, "enabled": True},
                {"id": "legend", "visible": True, "enabled": True},
            ],
        },
        provenance={
            "source_product": row.get("source_product", "CLMS BA300 monthly v4"),
            "source_item_id": row.get("source_item_id"),
            "processing_version": row.get("processing_version", PROCESSING_VERSION),
            "calculation_crs": row.get("calculation_crs", "EPSG:3035"),
            "thresholds": thresholds,
            "bf_scaled_path": active_path,
        },
        caveats=[
            "Mapped burned area uses CLMS BA300 monthly v4 BF scaled by 0.001.",
            "Monthly clusters are connected mapped burned-area clusters, not confirmed individual wildfire events.",
        ],
    )
    return response
