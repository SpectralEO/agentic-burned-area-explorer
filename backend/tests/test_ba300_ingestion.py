from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient

from app.ingestion.ba300_common import Period, classify_assets
from app.ingestion.ba300_processing import process_month
from app.main import app
from app.settings import get_settings


def _write_tif(path: Path, data: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": data.shape[1],
        "height": data.shape[0],
        "count": 1,
        "dtype": str(data.dtype),
        "crs": "EPSG:4326",
        "transform": from_origin(20, 42, 0.01, 0.01),
        "nodata": 0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def test_classify_ba300_stac_assets() -> None:
    item = {
        "assets": {
            "ba300_bf_ntc": {"href": "s3://x/c_gls_BA300-BF-NTC_202408010000.tiff", "type": "image/tiff"},
            "ba300_cp_ntc": {"href": "s3://x/c_gls_BA300-CP-NTC_202408010000.tiff", "type": "image/tiff"},
            "ba300_dob_ntc": {"href": "s3://x/c_gls_BA300-DOB-NTC_202408010000.tiff", "type": "image/tiff"},
            "ba300_lfp_ntc": {"href": "s3://x/c_gls_BA300-LFP-NTC_202408010000.tiff", "type": "image/tiff"},
            "Product": {"href": "https://example.test/product.zip", "type": "application/zip"},
        }
    }
    classified = classify_assets(item)
    assert set(classified["bands"]) == {"bf", "cp", "dob", "lfp"}
    assert classified["archives"][0]["key"] == "Product"


def test_process_month_writes_real_artifacts(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "real_data_dir", tmp_path / "real")
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text(
        json.dumps(
            {
                "type": "Polygon",
                "coordinates": [[[20, 41.96], [20.04, 41.96], [20.04, 42], [20, 42], [20, 41.96]]],
            }
        ),
        encoding="utf-8",
    )
    bands = {
        "bf": tmp_path / "bf.tif",
        "cp": tmp_path / "cp.tif",
        "dob": tmp_path / "dob.tif",
        "lfp": tmp_path / "lfp.tif",
    }
    _write_tif(bands["bf"], np.array([[0, 500], [1000, 0]], dtype="uint16"))
    _write_tif(bands["cp"], np.array([[0, 900], [800, 0]], dtype="uint16"))
    _write_tif(bands["dob"], np.array([[0, 230], [231, 0]], dtype="int16"))
    _write_tif(bands["lfp"], np.array([[0, 700], [900, 0]], dtype="uint16"))

    result = process_month(Period(2024, 8), bands, aoi_path=aoi, source_item_id="fixture")

    assert result["burned_area_occurrence_ha"] > 0
    assert result["burned_pixel_count"] == 2
    assert Path(result["bf_scaled_path"]).exists()
    assert (settings.real_data_dir / "ba300" / "derived" / "GR" / "monthly_stats.jsonl").exists()
    assert result["cluster_count"] >= 1


def test_ba300_api_discover_uses_real_service_contract(tmp_path, monkeypatch) -> None:
    import app.ingestion.ba300_service as service

    settings = get_settings()
    monkeypatch.setattr(settings, "real_data_dir", tmp_path / "real")
    item = {
        "id": "c_gls_BA300-NTC_202408010000_GLOBE_S3_V4.0.1_cog",
        "properties": {
            "datetime": "2024-08-01T00:00:00Z",
            "start_datetime": "2024-08-01T00:00:00Z",
            "end_datetime": "2024-08-31T23:59:59Z",
        },
        "assets": {
            "ba300_bf_ntc": {"href": "s3://x/c_gls_BA300-BF-NTC_202408010000.tiff", "type": "image/tiff"},
            "ba300_cp_ntc": {"href": "s3://x/c_gls_BA300-CP-NTC_202408010000.tiff", "type": "image/tiff"},
            "ba300_dob_ntc": {"href": "s3://x/c_gls_BA300-DOB-NTC_202408010000.tiff", "type": "image/tiff"},
            "ba300_lfp_ntc": {"href": "s3://x/c_gls_BA300-LFP-NTC_202408010000.tiff", "type": "image/tiff"},
            "Product": {"href": "https://example.test/product.zip", "type": "application/zip"},
        },
    }
    monkeypatch.setattr(service, "search_month", lambda period, limit=1: [item])

    response = TestClient(app).post("/api/analytics/ba300/discover", json={"start": "2024-08", "end": "2024-08"})

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "discovered"
    assert set(result["detected_bands"]) == {"bf", "cp", "dob", "lfp"}
    assert result["manual_download"]["import_command"].endswith("--input app/data/real/inbox/ba300/2024/08 --aoi app/data/aoi/greece.geojson")


def test_ba300_api_sync_without_credentials_returns_manual_path(tmp_path, monkeypatch) -> None:
    import app.ingestion.ba300_service as service

    settings = get_settings()
    monkeypatch.setattr(settings, "real_data_dir", tmp_path / "real")
    monkeypatch.setattr(settings, "cdse_username", None)
    monkeypatch.setattr(settings, "cdse_password", None)
    monkeypatch.setattr(settings, "cdse_client_secret", None)
    item = {
        "id": "c_gls_BA300-NTC_202408010000_GLOBE_S3_V4.0.1_cog",
        "properties": {},
        "assets": {"Product": {"href": "https://example.test/product.zip", "type": "application/zip"}},
    }
    monkeypatch.setattr(service, "search_month", lambda period, limit=1: [item])

    response = TestClient(app).post("/api/analytics/ba300/sync", json={"start": "2024-08", "end": "2024-08"})

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "manual_download_required"
    assert "CDSE" in result["reason"]
