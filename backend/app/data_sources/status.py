from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.analytics import AnalyticsDatasetStatus, DatasetStatusEntry
from app.settings import Settings


BA300_COLLECTION_ID = "b8b617c6-182f-427e-a86c-23fc36ac6098"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _configured_file(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def dataset_status(settings: Settings) -> AnalyticsDatasetStatus:
    root = settings.real_data_dir
    ba300_meta = _read_json(root / "ba300" / "metadata.json")
    ba300_summary = root / "analytics" / "monthly_stats.parquet"
    ba300_jsonl = root / "ba300" / "derived" / "GR" / "monthly_stats.jsonl"
    ba300_timeline = root / "ba300" / "timeline"
    ba300_months = sorted(ba300_timeline.glob("*.json")) if ba300_timeline.exists() else []
    ingested_months: list[str] = []
    last_sync = None
    if ba300_jsonl.exists():
        for line in ba300_jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            ingested_months.append(f"{int(row['year']):04d}-{int(row['month']):02d}")
            last_sync = row.get("ingested_at") or last_sync
    ba300_missing: list[str] = []
    cdse_configured = bool(settings.cdse_username and settings.cdse_password)
    if not cdse_configured:
        ba300_missing.append("CDSE_USERNAME/CDSE_PASSWORD for OData Product Download")
    if not ba300_summary.exists() and not ba300_months and not ingested_months:
        ba300_missing.append("BA300 monthly analytics cache")

    worldcover_path = root / "worldcover" / "greece_mosaic.tif"
    natura_path = root / "protected_areas" / "natura2000.gpkg"
    ramsar_path = root / "protected_areas" / "ramsar.gpkg"
    protected_meta = _read_json(root / "protected_areas" / "metadata.json")

    return AnalyticsDatasetStatus(
        ba300_monthly_v4=DatasetStatusEntry(
            configured=cdse_configured,
            discovered=bool(ba300_meta.get("discovered") or ingested_months),
            downloaded=bool(ba300_meta.get("downloaded") or ingested_months),
            validated=bool(ba300_meta.get("validated") or ingested_months),
            processed=bool(ba300_summary.exists() or ingested_months),
            queryable=bool(ba300_summary.exists() or ingested_months),
            source_mode=settings.ba300_source_mode,
            available_from=ba300_meta.get("available_from"),
            available_to=ba300_meta.get("available_to"),
            last_synced=ba300_meta.get("last_synced"),
            last_sync=ba300_meta.get("last_synced") or last_sync,
            months_cached=ba300_meta.get("months_cached") or len(ba300_months) or len(ingested_months) or None,
            ingested_months=sorted(set(ingested_months)),
            version=ba300_meta.get("version") or "monthly-v4",
            path=str(root / "ba300"),
            missing=ba300_missing,
            caveats=[
                "Authoritative MVP source is CLMS Burnt Area 300 m monthly version 4.",
                f"Collection identifier: {BA300_COLLECTION_ID}.",
            ],
        ),
        worldcover_2021=DatasetStatusEntry(
            configured=_configured_file(worldcover_path),
            version="v200",
            path=str(worldcover_path),
            missing=[] if _configured_file(worldcover_path) else ["ESA WorldCover 2021 v200 Greece mosaic"],
            caveats=["Land-cover baseline: ESA WorldCover 2021; it is not fire-year land cover."],
        ),
        natura2000=DatasetStatusEntry(
            configured=_configured_file(natura_path),
            version=protected_meta.get("natura2000_version") or "end-2024",
            path=str(natura_path),
            boundary_count=protected_meta.get("natura2000_boundary_count"),
            missing=[] if _configured_file(natura_path) else ["Official Natura 2000 GeoPackage/Shapefile"],
        ),
        ramsar=DatasetStatusEntry(
            configured=_configured_file(ramsar_path),
            version=protected_meta.get("ramsar_version"),
            path=str(ramsar_path),
            boundary_count=protected_meta.get("ramsar_boundary_count"),
            missing=[] if _configured_file(ramsar_path) else ["Official Ramsar polygon boundaries"],
        ),
    )
