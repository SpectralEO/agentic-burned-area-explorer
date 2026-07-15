from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.ingestion.ba300_common import (
    BANDS,
    Period,
    asset_summary,
    classify_assets,
    discover_local_inputs,
    download_product,
    iter_periods,
    manual_download_payload,
    now_iso,
    real_root,
    search_month,
    write_json,
)
from app.ingestion.ba300_processing import process_month
from app.settings import get_settings


DEFAULT_AOI = Path("app/data/aoi/greece.geojson")
REQUIRED_BANDS = sorted({canonical for canonical, _filename in BANDS.values()} - {"dataMask"})


def _metadata_path() -> Path:
    return real_root() / "ba300" / "metadata.json"


def _read_metadata() -> dict[str, Any]:
    path = _metadata_path()
    if not path.exists():
        return {}
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_unique(existing: list[str] | None, values: list[str]) -> list[str]:
    return sorted(set(existing or []) | set(values))


def update_metadata(**updates: Any) -> dict[str, Any]:
    metadata = _read_metadata()
    metadata.update({key: value for key, value in updates.items() if value is not None})
    metadata["last_synced"] = now_iso()
    write_json(_metadata_path(), metadata)
    return metadata


def discover_range(start: Period, end: Period, *, limit: int | None = None, aoi: str | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    discovered_months: list[str] = []
    for index, period in enumerate(iter_periods(start, end)):
        if limit and index >= limit:
            break
        items = search_month(period, limit=1)
        item = items[0] if items else None
        if not item:
            results.append({"period": period.label, "status": "not_discovered"})
            continue
        classified = classify_assets(item)
        discovered_months.append(period.label)
        results.append(
            {
                "period": period.label,
                "status": "discovered",
                "item_id": item.get("id"),
                "datetime": item.get("properties", {}).get("datetime"),
                "start_datetime": item.get("properties", {}).get("start_datetime"),
                "end_datetime": item.get("properties", {}).get("end_datetime"),
                "assets": asset_summary(item),
                "detected_bands": sorted(classified["bands"].keys()),
                "archives": [asset.get("key") for asset in classified["archives"]],
                "authentication_required": True,
                "manual_download": manual_download_payload(period, item, aoi=aoi),
            }
        )
    if discovered_months:
        update_metadata(
            discovered=True,
            available_from=discovered_months[0],
            available_to=discovered_months[-1],
            discovered_months=_merge_unique(_read_metadata().get("discovered_months"), discovered_months),
            version="monthly-v4",
        )
    return {"results": results}


def import_input(
    input_dir: Path,
    *,
    aoi_path: Path = DEFAULT_AOI,
    force: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    source_item_id: str | None = None,
    source: str = "manual-import",
) -> dict[str, Any]:
    products = discover_local_inputs(input_dir)
    if limit:
        products = dict(list(sorted(products.items()))[:limit])
    if not products:
        return {"imported": [], "status": "no_products_detected", "input": str(input_dir)}

    output: list[dict[str, Any]] = []
    processed_months: list[str] = []
    for label, bands in sorted(products.items()):
        year, month = [int(x) for x in label.split("-")]
        missing = [canonical for canonical in REQUIRED_BANDS if canonical not in bands]
        entry: dict[str, Any] = {"period": label, "bands": {k: str(v) for k, v in bands.items()}, "missing": missing}
        if missing:
            entry["status"] = "missing_required_bands"
            output.append(entry)
            continue
        if dry_run:
            entry["status"] = "ready"
            output.append(entry)
            continue

        norm_dir = real_root() / "ba300" / "normalized" / f"{year:04d}" / f"{month:02d}"
        norm_dir.mkdir(parents=True, exist_ok=True)
        normalized_paths: dict[str, Path] = {}
        checksums: dict[str, str] = {}
        from app.ingestion.ba300_common import sha256_file

        for band, src in bands.items():
            filename = next((fname for canonical, fname in BANDS.values() if canonical == band), f"{band}.tif")
            dst = norm_dir / filename
            if force or not dst.exists():
                shutil.copy2(src, dst)
            normalized_paths[band] = dst
            checksums[band] = sha256_file(dst)

        result = process_month(Period(year, month), normalized_paths, aoi_path=aoi_path, source_item_id=source_item_id, force=force)
        manifest = {
            "period": label,
            "source": source,
            "input": str(input_dir),
            "source_item_id": source_item_id,
            "imported_at": now_iso(),
            "bands": {k: str(v) for k, v in normalized_paths.items()},
            "checksums": checksums,
            "result": result,
        }
        write_json(real_root() / "ba300" / "manifests" / f"{label}.json", manifest)
        entry["status"] = "processed"
        entry["result"] = result
        processed_months.append(label)
        output.append(entry)

    if processed_months:
        update_metadata(
            downloaded=True,
            validated=True,
            processed=True,
            queryable=True,
            processed_months=_merge_unique(_read_metadata().get("processed_months"), processed_months),
            months_cached=len(_merge_unique(_read_metadata().get("processed_months"), processed_months)),
            version="monthly-v4",
        )
    return {"imported": output}


def preprocess_range(
    start: Period,
    end: Period,
    *,
    aoi_path: Path = DEFAULT_AOI,
    force: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    processed_months: list[str] = []
    for index, period in enumerate(iter_periods(start, end)):
        if limit and index >= limit:
            break
        norm_dir = real_root() / "ba300" / "normalized" / f"{period.year:04d}" / f"{period.month:02d}"
        band_paths: dict[str, Path] = {}
        for canonical, filename in set(BANDS.values()):
            candidate = norm_dir / filename
            if candidate.exists():
                band_paths[canonical] = candidate
        missing = [band for band in REQUIRED_BANDS if band not in band_paths]
        if missing:
            results.append({"period": period.label, "status": "missing_normalized_bands", "missing": missing, "normalized_dir": str(norm_dir)})
            continue
        if dry_run:
            results.append({"period": period.label, "status": "ready", "bands": {k: str(v) for k, v in band_paths.items()}})
            continue
        result = process_month(period, band_paths, aoi_path=aoi_path, force=force)
        results.append({"period": period.label, "status": "processed", "result": result})
        processed_months.append(period.label)
    if processed_months:
        update_metadata(
            validated=True,
            processed=True,
            queryable=True,
            processed_months=_merge_unique(_read_metadata().get("processed_months"), processed_months),
            months_cached=len(_merge_unique(_read_metadata().get("processed_months"), processed_months)),
            version="monthly-v4",
        )
    return {"results": results}


def sync_range(
    start: Period,
    end: Period,
    *,
    aoi_path: Path = DEFAULT_AOI,
    source: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    preprocess: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    source_mode = source or settings.ba300_source_mode
    results: list[dict[str, Any]] = []
    downloaded_months: list[str] = []
    for index, period in enumerate(iter_periods(start, end)):
        if limit and index >= limit:
            break
        items = search_month(period, limit=1)
        item = items[0] if items else None
        if not item:
            results.append({"period": period.label, "status": "not_discovered"})
            continue
        if source_mode == "local":
            results.append(manual_download_payload(period, item, aoi=str(aoi_path)))
            continue
        if dry_run:
            results.append({"period": period.label, "status": "dry_run", "item_id": item["id"], "manual_download": manual_download_payload(period, item, aoi=str(aoi_path))})
            continue
        try:
            archive = download_product(item, period, force=force)
        except Exception as exc:
            payload = manual_download_payload(period, item, aoi=str(aoi_path))
            payload["reason"] = str(exc)
            results.append(payload)
            continue
        inbox = real_root() / "inbox" / "ba300" / f"{period.year:04d}" / f"{period.month:02d}"
        inbox.mkdir(parents=True, exist_ok=True)
        copied = inbox / archive.name
        if force or not copied.exists():
            shutil.copy2(archive, copied)
        entry: dict[str, Any] = {
            "period": period.label,
            "status": "downloaded",
            "item_id": item["id"],
            "archive": str(archive),
            "inbox": str(inbox),
        }
        downloaded_months.append(period.label)
        if preprocess:
            entry["import"] = import_input(inbox, aoi_path=aoi_path, force=force, source_item_id=item.get("id"), source="cdse-odata")
        else:
            entry["next_command"] = f"python -m app.ingestion.ba300_import --input {inbox} --aoi {aoi_path}"
        results.append(entry)
    if downloaded_months:
        update_metadata(
            discovered=True,
            downloaded=True,
            downloaded_months=_merge_unique(_read_metadata().get("downloaded_months"), downloaded_months),
            source_mode=source_mode,
            version="monthly-v4",
        )
    return {"results": results}
