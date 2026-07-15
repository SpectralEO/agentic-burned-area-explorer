from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from app.settings import get_settings

STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac/search"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PRODUCT_NAME = "CLMS BA300 monthly v4"
PROCESSING_VERSION = "ba300-real-v1"
BANDS = {
    "BF": ("bf", "bf_raw.tif"),
    "CP": ("cp", "cp_raw.tif"),
    "DOB": ("dob", "dob.tif"),
    "LFP": ("lfp", "lfp_raw.tif"),
    "DATAMASK": ("dataMask", "data_mask.tif"),
    "DATA_MASK": ("dataMask", "data_mask.tif"),
}


@dataclass(frozen=True)
class Period:
    year: int
    month: int

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def start(self) -> str:
        return f"{self.label}-01T00:00:00Z"

    @property
    def end(self) -> str:
        import calendar

        return f"{self.label}-{calendar.monthrange(self.year, self.month)[1]:02d}T23:59:59Z"


def parse_period(value: str) -> Period:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if not match:
        raise argparse.ArgumentTypeError("Period must be YYYY-MM.")
    year, month = int(match.group(1)), int(match.group(2))
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError("Month must be 01..12.")
    return Period(year, month)


def iter_periods(start: Period, end: Period) -> Iterable[Period]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield Period(year, month)
        month += 1
        if month == 13:
            year += 1
            month = 1


def real_root() -> Path:
    return get_settings().real_data_dir


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def search_month(period: Period, *, limit: int = 5) -> list[dict[str, Any]]:
    settings = get_settings()
    body = {
        "collections": [settings.ba300_stac_collection],
        "datetime": f"{period.start}/{period.end}",
        "limit": limit,
    }
    response = requests.post(STAC_URL, json=body, timeout=30)
    response.raise_for_status()
    return response.json().get("features", [])


def asset_summary(item: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, asset in (item.get("assets") or {}).items():
        bands = asset.get("bands") or asset.get("eo:bands") or asset.get("raster:bands") or []
        out.append(
            {
                "key": key,
                "title": asset.get("title"),
                "type": asset.get("type"),
                "roles": asset.get("roles") or [],
                "href": asset.get("href"),
                "bands": bands,
            }
        )
    return out


def classify_assets(item: dict[str, Any]) -> dict[str, Any]:
    quantitative: dict[str, dict[str, Any]] = {}
    archives: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for key, asset in (item.get("assets") or {}).items():
        haystack = " ".join(
            str(v or "")
            for v in [
                key,
                asset.get("title"),
                asset.get("href"),
                json.dumps(asset.get("bands") or asset.get("eo:bands") or ""),
            ]
        ).upper()
        media_type = str(asset.get("type") or "").lower()
        if "ZIP" in media_type or key.lower() == "product":
            archives.append({"key": key, **asset})
            continue
        matched = False
        for token, (band, _filename) in BANDS.items():
            if token in haystack:
                quantitative[band] = {"key": key, **asset}
                matched = True
        if not matched:
            unsupported.append({"key": key, **asset})
    return {"bands": quantitative, "archives": archives, "unsupported": unsupported}


def manual_download_payload(period: Period, item: dict[str, Any] | None, *, aoi: str | None = None) -> dict[str, Any]:
    item_id = item.get("id") if item else None
    local_target = f"app/data/real/inbox/ba300/{period.year:04d}/{period.month:02d}/"
    return {
        "status": "manual_download_required",
        "product": PRODUCT_NAME,
        "period": period.label,
        "stac_item_id": item_id,
        "download_options": ["CDSE Browser", "STAC Product asset", "OData product download", "EODATA S3 with credentials"],
        "local_target": local_target,
        "expected_files": ["Product ZIP archive, separate BA300 GeoTIFF/COG bands, or extracted BF/CP/DOB/LFP/dataMask files"],
        "import_command": f"cd backend && UV_CACHE_DIR=/tmp/wea-uv-cache uv run python -m app.ingestion.ba300_import --input {local_target.rstrip('/')} --aoi {aoi or 'app/data/aoi/greece.geojson'}",
        "validation_command": f"cd backend && UV_CACHE_DIR=/tmp/wea-uv-cache uv run python -m app.ingestion.ba300_preprocess --start {period.label} --end {period.label} --aoi {aoi or 'app/data/aoi/greece.geojson'}",
    }


def cdse_token() -> str | None:
    settings = get_settings()
    if settings.cdse_username and settings.cdse_password:
        data = {
            "grant_type": "password",
            "client_id": "cdse-public",
            "username": settings.cdse_username,
            "password": settings.cdse_password,
        }
    elif settings.cdse_client_id and settings.cdse_client_secret:
        data = {
            "grant_type": "client_credentials",
            "client_id": settings.cdse_client_id,
            "client_secret": settings.cdse_client_secret,
        }
    else:
        return None
    response = requests.post(
        TOKEN_URL,
        data=data,
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("access_token")


def download_product(item: dict[str, Any], period: Period, *, force: bool = False) -> Path:
    settings = get_settings()
    token = cdse_token()
    if not token:
        raise RuntimeError(
            "CDSE credentials are required for OData product download. "
            "Set CDSE_USERNAME/CDSE_PASSWORD; BA300 OData product download uses the CDSE password grant with client_id=cdse-public."
        )
    product = (item.get("assets") or {}).get("Product")
    if not product:
        raise RuntimeError("STAC item does not expose a Product archive asset.")
    target_dir = real_root() / "ba300" / "raw" / f"{period.year:04d}" / f"{period.month:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{item['id']}.zip"
    if target.exists() and not force:
        return target
    with tempfile.NamedTemporaryFile(dir=target_dir, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        with requests.get(product["href"], headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=120) as response:
            if response.status_code == 401 and not (settings.cdse_username and settings.cdse_password):
                raise RuntimeError(
                    "CDSE OData rejected the configured client-credentials token. "
                    "The CDSE Product Download API expects a user access token from CDSE_USERNAME/CDSE_PASSWORD with client_id=cdse-public. "
                    "Sentinel Hub OAuth clients such as sh-* can authenticate, but are not accepted for this OData product download."
                )
            response.raise_for_status()
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    tmp.write(chunk)
    tmp_path.replace(target)
    return target


def safe_extract_zip(path: Path, target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(path) as zf:
        for member in zf.infolist():
            member_path = target_dir / member.filename
            resolved = member_path.resolve()
            if not str(resolved).startswith(str(target_dir.resolve())):
                raise RuntimeError(f"Unsafe ZIP member path: {member.filename}")
            if member.is_dir():
                resolved.mkdir(parents=True, exist_ok=True)
                continue
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, resolved.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(resolved)
    return extracted


def detect_period_from_name(path: Path) -> Period | None:
    text = path.name
    match = re.search(r"(20\d{2})(\d{2})01", text)
    if match:
        return Period(int(match.group(1)), int(match.group(2)))
    match = re.search(r"(20\d{2})[-_]?(\d{2})", text)
    if match:
        return Period(int(match.group(1)), int(match.group(2)))
    return None


def detect_band(path: Path) -> str | None:
    text = path.name.upper()
    for token, (band, _filename) in BANDS.items():
        if re.search(rf"(^|[-_]){re.escape(token)}([-_]|\\.|$)", text):
            return band
    return None


def discover_local_inputs(input_dir: Path) -> dict[str, dict[str, Path]]:
    files: list[Path] = []
    scratch = input_dir / ".extracted"
    for path in input_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".zip":
            files.extend(safe_extract_zip(path, scratch / path.stem))
        elif path.is_file():
            files.append(path)
    products: dict[str, dict[str, Path]] = {}
    for path in files:
        if path.suffix.lower() in {".nc", ".netcdf"}:
            raise RuntimeError(f"NetCDF BA300 input is detected but not implemented yet: {path}")
        if path.suffix.lower() not in {".tif", ".tiff"}:
            continue
        period = detect_period_from_name(path)
        band = detect_band(path)
        if not period or not band:
            continue
        products.setdefault(period.label, {})[band] = path
    return products


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
