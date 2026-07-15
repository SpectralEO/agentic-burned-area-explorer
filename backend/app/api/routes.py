from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import RedirectResponse

from app import db
from app.agent.router import DEFAULT_ACTIONS, select_skill
from app.analytics import ba300_store
from app.analytics.burned_area import RealDataUnavailable, burned_area_timeline
from app.analytics.temporal import UnsupportedTemporalQuery
from app.core.imagery_preview import (
    PreviewError,
    maplibre_image_coordinates,
    preview_bounds_4326,
    selected_candidate_index,
    tiler_render_url_for_payload,
    tiler_tile_url_for_payload,
    update_selected_candidate,
)
from app.core.reports import generate_markdown_report, generate_pdf_report
from app.data_sources.status import dataset_status
from app.ingestion.ba300_common import parse_period
from app.ingestion.ba300_service import discover_range, import_input, preprocess_range, sync_range
from app.models import (
    AgentActionRequest,
    AgentQueryRequest,
    AgentResponse,
    AgentRun,
    CreateInvestigationRequest,
    ImagerySelectionRequest,
    Investigation,
    PinFindingRequest,
    ReportGenerateRequest,
    SelectClusterRequest,
)
from app.schemas.analytics import (
    AnalyticsDatasetStatus,
    Ba300DiscoverRequest,
    Ba300ImportRequest,
    Ba300OperationResponse,
    Ba300PreprocessRequest,
    Ba300SyncRequest,
    BurnedAreaTemporalQuery,
    BurnedAreaTimelineResponse,
)
from app.settings import get_settings
from app.workflows.loader import list_skills
from app.workflows.runner import WorkflowContextError, run_skill

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/skills")
def skills() -> list[dict[str, str]]:
    return list_skills()


@router.post("/investigations", response_model=Investigation)
def create_investigation(req: CreateInvestigationRequest) -> Investigation:
    inv = Investigation(title=req.title or f"{req.aoi.title()} wildfire investigation, {req.year}", aoi=req.aoi, year=req.year)
    return db.save_investigation(get_settings().db_path, inv)


@router.get("/investigations", response_model=list[Investigation])
def investigations() -> list[Investigation]:
    return db.list_investigations(get_settings().db_path)


@router.get("/investigations/{investigation_id}", response_model=Investigation)
def investigation(investigation_id: str) -> Investigation:
    try:
        return db.get_investigation(get_settings().db_path, investigation_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.patch("/investigations/{investigation_id}/select-cluster", response_model=Investigation)
def select_cluster(investigation_id: str, req: SelectClusterRequest) -> Investigation:
    try:
        inv = db.get_investigation(get_settings().db_path, investigation_id)
        ba300_store.get_cluster(get_settings().real_data_dir, req.cluster_id)
        inv.selected_cluster_id = req.cluster_id
        return db.save_investigation(get_settings().db_path, inv)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/clusters")
def clusters(year: int = 2025) -> dict:
    data = ba300_store.clusters_geojson(get_settings().real_data_dir, year=year)
    if not data.get("features"):
        raise HTTPException(
            409,
            {
                "message": f"No real BA300 clusters are available for Greece in {year}.",
                "available_months": ba300_store.ingested_months(get_settings().real_data_dir),
                "suggested_actions": [
                    f"Sync BA300 for {year}: cd backend && UV_CACHE_DIR=/tmp/wea-uv-cache uv run python -m app.ingestion.ba300_sync --start {year}-01 --end {year}-12 --aoi app/data/aoi/greece.geojson --source auto",
                    "Use the BA300 control to sync a month range that is actually available.",
                ],
            },
        )
    return data


@router.get("/clusters/{cluster_id}")
def cluster(cluster_id: str, year: int = 2025) -> dict:
    try:
        return ba300_store.get_cluster(get_settings().real_data_dir, cluster_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/summary/{year}")
def summary(year: int) -> dict:
    try:
        return ba300_store.summarise_year(get_settings().real_data_dir, year)
    except KeyError as exc:
        raise HTTPException(
            409,
            {
                "message": str(exc),
                "available_months": ba300_store.ingested_months(get_settings().real_data_dir),
                "suggested_actions": [
                    f"Sync BA300 for {year}: cd backend && UV_CACHE_DIR=/tmp/wea-uv-cache uv run python -m app.ingestion.ba300_sync --start {year}-01 --end {year}-12 --aoi app/data/aoi/greece.geojson --source auto",
                ],
            },
        ) from exc


@router.get("/analytics/datasets/status", response_model=AnalyticsDatasetStatus)
def analytics_dataset_status() -> AnalyticsDatasetStatus:
    return dataset_status(get_settings())


@router.post("/analytics/ba300/discover", response_model=Ba300OperationResponse)
def analytics_ba300_discover(req: Ba300DiscoverRequest) -> Ba300OperationResponse:
    try:
        result = discover_range(parse_period(req.start), parse_period(req.end), limit=req.limit, aoi=req.aoi_path)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return Ba300OperationResponse(**result)


@router.post("/analytics/ba300/sync", response_model=Ba300OperationResponse)
def analytics_ba300_sync(req: Ba300SyncRequest) -> Ba300OperationResponse:
    try:
        result = sync_range(
            parse_period(req.start),
            parse_period(req.end),
            aoi_path=Path(req.aoi_path),
            source=req.source,
            force=req.force,
            dry_run=req.dry_run,
            limit=req.limit,
            preprocess=req.preprocess,
        )
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc
    return Ba300OperationResponse(**result)


@router.post("/analytics/ba300/import", response_model=Ba300OperationResponse)
def analytics_ba300_import(req: Ba300ImportRequest) -> Ba300OperationResponse:
    try:
        result = import_input(Path(req.input_path), aoi_path=Path(req.aoi_path), force=req.force, dry_run=req.dry_run, limit=req.limit)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return Ba300OperationResponse(**result)


@router.post("/analytics/ba300/preprocess", response_model=Ba300OperationResponse)
def analytics_ba300_preprocess(req: Ba300PreprocessRequest) -> Ba300OperationResponse:
    try:
        result = preprocess_range(parse_period(req.start), parse_period(req.end), aoi_path=Path(req.aoi_path), force=req.force, dry_run=req.dry_run, limit=req.limit)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return Ba300OperationResponse(**result)


@router.post("/analytics/burned-area/timeline", response_model=BurnedAreaTimelineResponse)
def analytics_burned_area_timeline(req: BurnedAreaTemporalQuery) -> BurnedAreaTimelineResponse:
    try:
        return burned_area_timeline(req, get_settings())
    except UnsupportedTemporalQuery as exc:
        raise HTTPException(422, str(exc)) from exc
    except RealDataUnavailable as exc:
        raise HTTPException(409, detail=exc.payload) from exc


@router.get("/investigations/{investigation_id}/finding")
def finding(investigation_id: str):
    return db.list_finding_cards(get_settings().db_path, investigation_id)


@router.patch("/finding/{finding_id}/pin")
def pin_finding(finding_id: str, req: PinFindingRequest):
    try:
        return db.set_finding_pin(get_settings().db_path, finding_id, req.pinned)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.patch("/finding/{finding_id}/report-inclusion")
def set_finding_report_inclusion(finding_id: str, req: PinFindingRequest):
    try:
        return db.set_finding_pin(get_settings().db_path, finding_id, req.pinned)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/finding/{finding_id}", status_code=204)
def delete_finding(finding_id: str) -> Response:
    try:
        db.delete_finding_card(get_settings().db_path, finding_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)


@router.post("/agent/query", response_model=AgentResponse)
def agent_query(req: AgentQueryRequest) -> AgentResponse:
    settings = get_settings()
    try:
        inv = db.get_investigation(settings.db_path, req.investigation_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    skill_id, reason, parameters = select_skill(req.message, inv.model_dump(mode="json"))
    if skill_id is None:
        return AgentResponse(
            answer=(
                "I cannot resolve that prompt with the real-data workflows currently loaded. "
                f"{reason} Try BA300 burned-area totals, real BA300 cluster selection, or real STAC optical imagery for a selected cluster."
            ),
            selected_skill_id=None,
            suggested_actions=DEFAULT_ACTIONS,
            trace=[],
            agent_mode=settings.agent_mode,
        )
    try:
        response = run_skill(skill_id, inv, parameters)
    except WorkflowContextError as exc:
        return AgentResponse(
            answer=str(exc),
            selected_skill_id=skill_id,
            suggested_actions=DEFAULT_ACTIONS,
            trace=[],
            agent_mode=settings.agent_mode,
        )
    response.agent_mode = settings.agent_mode
    run = AgentRun(
        investigation_id=inv.id,
        user_message=req.message,
        selected_skill_id=skill_id,
        answer=response.answer,
        trace=response.trace,
        created_finding_ids=[c.id for c in response.finding_cards],
        suggested_actions=response.suggested_actions,
        agent_mode=settings.agent_mode,
    )
    db.save_agent_run(settings.db_path, run)
    response.answer = f"{response.answer}\n\nSelection reason: {reason}"
    return response


@router.post("/agent/action", response_model=AgentResponse)
def agent_action(req: AgentActionRequest) -> AgentResponse:
    try:
        inv = db.get_investigation(get_settings().db_path, req.investigation_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        response = run_skill(req.skill_id, inv, req.parameters)
    except WorkflowContextError as exc:
        return AgentResponse(answer=str(exc), selected_skill_id=req.skill_id, suggested_actions=DEFAULT_ACTIONS, trace=[])
    run = AgentRun(
        investigation_id=inv.id,
        user_message=f"ACTION:{req.action_id}",
        selected_skill_id=req.skill_id,
        answer=response.answer,
        trace=response.trace,
        created_finding_ids=[c.id for c in response.finding_cards],
        suggested_actions=response.suggested_actions,
    )
    db.save_agent_run(get_settings().db_path, run)
    return response


@router.get("/imagery/{finding_id}/preview/{role}.png")
def imagery_preview(finding_id: str, role: str, width: int = 720, candidate_index: int | None = None):
    """Redirect to the tiler static-render endpoint for finding/report previews."""
    settings = get_settings()
    try:
        card = db.get_finding_card(settings.db_path, finding_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        render_url, _item = tiler_render_url_for_payload(
            card.payload,
            role=role,
            candidate_index=candidate_index,
            tiler_base=settings.tiler_public_base,
            width=width,
        )
    except PreviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return RedirectResponse(render_url, status_code=307)


@router.get("/imagery/{finding_id}/map-layer/{role}.json")
def imagery_map_layer(finding_id: str, role: str, width: int = 1400, candidate_index: int | None = None) -> dict:
    """Return a MapLibre layer description for the selected STAC scene.

    In tiler mode this returns a raster-tile source pointing at the local
    custom composite tiler. In preview mode it returns the legacy single-image
    overlay. The frontend supports both, so you can keep a fallback while
    developing the tiler locally.
    """
    settings = get_settings()
    try:
        card = db.get_finding_card(settings.db_path, finding_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        bounds = preview_bounds_4326(card.payload)
        idx = candidate_index if candidate_index is not None else selected_candidate_index(card.payload, role)
        role_value = role.lower().replace("_", "-")
        if role_value in {"pre", "before", "pre-fire"}:
            normalised_role = "before"
        elif role_value in {"during", "during-window", "event", "active-fire"}:
            normalised_role = "during"
        else:
            normalised_role = "after"
        if settings.imagery_render_mode == "tiler":
            layer, _item = tiler_tile_url_for_payload(
                card.payload,
                role=normalised_role,
                candidate_index=idx,
                tiler_base=settings.tiler_public_base,
                tiler_stats_base=settings.tiler_internal_base,
            )
            layer.update({
                "finding_id": finding_id,
                "role": normalised_role,
                "candidate_index": idx,
            })
            return layer

        url = f"{settings.api_public_base.rstrip('/')}/imagery/{finding_id}/preview/{normalised_role}.png?width={width}&candidate_index={idx}"
        return {
            "kind": "image",
            "finding_id": finding_id,
            "role": normalised_role,
            "candidate_index": idx,
            "url": url,
            "bounds": list(bounds),
            "coordinates": maplibre_image_coordinates(bounds),
        }
    except PreviewError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/imagery/{finding_id}/selection")
def update_imagery_selection(finding_id: str, req: ImagerySelectionRequest):
    """Persist a user-reviewed before/after candidate selection on the finding card."""
    try:
        card = db.get_finding_card(get_settings().db_path, finding_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        card.payload = update_selected_candidate(card.payload, req.role, req.candidate_index)
        scenes = card.payload.get("selected_scenes") or {}
        pair = card.payload.get("selected_pair") or {}
        before = (scenes.get("before") if isinstance(scenes, dict) else None) or pair.get("pre") or {}
        if card.payload.get("composite") == "fire_front_highlight":
            comparison = (scenes.get("during") if isinstance(scenes, dict) else None) or pair.get("post") or {}
            pair_label = "pre-fire/event"
        else:
            comparison = (scenes.get("after") if isinstance(scenes, dict) else None) or pair.get("post") or {}
            pair_label = "before/after"
        pre = before.get("datetime", "pre-fire candidate")
        post = comparison.get("datetime", "comparison candidate")
        card.summary = (
            f"Selected {card.payload.get('sensor_label', 'optical')} "
            f"{str(card.payload.get('composite_label', 'composite')).lower()} {pair_label} pair "
            f"for cluster {card.payload.get('cluster_id')}: {pre} → {post}."
        )
        return db.save_finding_card(get_settings().db_path, card)
    except PreviewError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/reports/generate")
def generate_report(req: ReportGenerateRequest) -> dict[str, str]:
    try:
        inv = db.get_investigation(get_settings().db_path, req.investigation_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    cards = db.list_finding_cards(get_settings().db_path, req.investigation_id)
    if not req.include_unpinned:
        cards = [c for c in cards if c.pinned]
    return {"markdown": generate_markdown_report(inv, cards)}


@router.get("/reports/{investigation_id}/pdf")
def generate_report_pdf(investigation_id: str) -> Response:
    try:
        inv = db.get_investigation(get_settings().db_path, investigation_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    cards = [c for c in db.list_finding_cards(get_settings().db_path, investigation_id) if c.pinned]
    try:
        pdf = generate_pdf_report(inv, cards)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    filename = f"wildfire-finding-brief-{inv.aoi}-{inv.year}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})
