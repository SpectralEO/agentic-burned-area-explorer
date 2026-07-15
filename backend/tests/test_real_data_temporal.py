from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
import pytest

from app.analytics.temporal import DAY_DERIVATION, UnsupportedTemporalQuery, resolve_temporal_window
from app.main import app
from app.schemas.analytics import BurnedAreaTemporalQuery
from app.settings import get_settings


def test_month_period_resolves_calendar_month() -> None:
    window = resolve_temporal_window(
        BurnedAreaTemporalQuery(
            geography_type="country",
            geography_id="GR",
            granularity="month",
            cursor=date(2024, 2, 15),
        )
    )

    assert window.active_start == date(2024, 2, 1)
    assert window.active_end == date(2024, 2, 29)
    assert window.context_start == date(2024, 1, 1)
    assert window.context_end == date(2024, 12, 31)


def test_day_period_uses_retrospective_dob_wording() -> None:
    window = resolve_temporal_window(
        BurnedAreaTemporalQuery(
            geography_type="country",
            geography_id="GR",
            granularity="day",
            cursor=date(2024, 8, 15),
        )
    )

    assert window.active_start == date(2024, 8, 15)
    assert window.active_end == date(2024, 8, 15)
    assert window.context_start == date(2024, 8, 1)
    assert window.context_end == date(2024, 8, 31)
    assert window.derivation_method == DAY_DERIVATION


def test_pre_2018_period_is_rejected() -> None:
    with pytest.raises(UnsupportedTemporalQuery):
        resolve_temporal_window(
            BurnedAreaTemporalQuery(
                geography_type="country",
                geography_id="GR",
                granularity="year",
                cursor=date(2017, 1, 1),
            )
        )


def test_timeline_endpoint_does_not_fallback_to_synthetic_without_cache(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "real_data_dir", tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/analytics/burned-area/timeline",
        json={
            "geography_type": "country",
            "geography_id": "GR",
            "granularity": "month",
            "cursor": "2024-05-01",
            "display_mode": "period",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["metrics"]["burned_area_occurrence_ha"] == 0
    assert "No synthetic burned-area values" in " ".join(detail["caveats"])
    assert detail["resolved_window"]["active_start"] == "2024-05-01"
    assert detail["resolved_window"]["active_end"] == "2024-05-31"
