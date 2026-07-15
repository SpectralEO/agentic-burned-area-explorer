from uuid import uuid4

from app import db
from app.agent.router import select_skill
from app.analytics import ba300_store
from app.models import Investigation
from app.settings import get_settings
from app.workflows.runner import run_skill


def test_burned_area_accounting_creates_finding():
    settings = get_settings()
    db.init_db(settings.db_path)
    inv = db.save_investigation(settings.db_path, Investigation(id=f"test-investigation-accounting-{uuid4()}"))
    response = run_skill("burned_area_accounting", inv, {})
    assert response.selected_skill_id == "burned_area_accounting"
    assert len(response.finding_cards) >= 2
    assert response.finding_cards[0].provenance["skill_id"] == "burned_area_accounting"
    assert all(card.pinned is False for card in response.finding_cards)


def test_agent_extracts_optical_sensor_and_composite_intent():
    skill, reason, params = select_skill("Show before/after Sentinel-2 false colour imagery", {})
    assert skill == "optical_imagery_finding"
    assert params["sensor"] == "sentinel-2"
    assert params["composite"] == "false_color"
    assert "sensor=sentinel-2" in reason


def test_agent_extracts_fire_front_event_date():
    skill, reason, params = select_skill("Show a Sentinel-2 fire-front highlight for 23 August 2023", {})
    assert skill == "optical_imagery_finding"
    assert params["sensor"] == "sentinel-2"
    assert params["composite"] == "fire_front_highlight"
    assert params["event_date"] == "2023-08-23"
    assert "composite=fire_front_highlight" in reason


def test_cluster_workflow_persists_default_selected_cluster():
    settings = get_settings()
    db.init_db(settings.db_path)
    inv = db.save_investigation(
        settings.db_path,
        Investigation(id="test-investigation-selected-cluster", selected_cluster_id=None),
    )
    response = run_skill("burn_cluster_investigation", inv, {})
    saved = db.get_investigation(settings.db_path, inv.id)

    assert response.selected_skill_id == "burn_cluster_investigation"
    assert saved.selected_cluster_id
    assert saved.selected_cluster_id.startswith("GR-2025-")


def test_fire_front_highlight_skill_creates_optical_finding():
    settings = get_settings()
    settings.stac_mode = "real"
    cluster_id = ba300_store.largest_cluster(settings.real_data_dir, year=2024)["properties"]["cluster_id"]
    db.init_db(settings.db_path)
    inv = db.save_investigation(
        settings.db_path,
        Investigation(id=f"test-investigation-imagery-{uuid4()}", selected_cluster_id=cluster_id),
    )
    response = run_skill(
        "optical_imagery_finding",
        inv,
        {"sensor": "sentinel-2", "composite": "fire_front_highlight"},
    )
    assert response.selected_skill_id == "optical_imagery_finding"
    assert response.finding_cards
    card = response.finding_cards[0]
    assert card.pinned is False
    assert card.payload["sensor_request"] == "sentinel-2"
    assert card.payload["composite"] == "fire_front_highlight"
    assert card.payload["cluster_id"] == cluster_id
    assert card.payload["search_status"] in {"real-stac", "real-stac-fallback", "real-stac-no-results", "real-stac-error"}
    assert "mock" not in card.payload["search_status"]
    assert "fire-front" in card.payload["composite_label"].lower()
