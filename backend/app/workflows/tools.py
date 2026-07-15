from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from app.analytics import ba300_store
from app.core.stac_search import (
    COMPOSITE_LABELS,
    SENSOR_LABELS,
    add_roles,
    choose_scenes,
    geometry_bbox,
    normalise_composite,
    normalise_sensor,
    pad_bbox,
    parse_iso_date,
    render_recipe,
    resolve_render_assets,
    search_stac_items_with_fallback,
    search_windows,
    sensor_order,
)
from app.models import FindingCard, FindingType, Investigation
from app.settings import get_settings

ToolFn = Callable[[Investigation, dict[str, Any], dict[str, Any]], dict[str, Any]]


def _selected_cluster(inv: Investigation, inputs: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    cluster_id = inputs.get("cluster_id") or inv.selected_cluster_id
    if cluster_id:
        return ba300_store.get_cluster(settings.real_data_dir, cluster_id)
    return ba300_store.largest_cluster(settings.real_data_dir, year=inv.year)


def _requested_years(inv: Investigation, inputs: dict[str, Any]) -> list[int]:
    years = inputs.get("years")
    if isinstance(years, list) and years:
        return sorted({int(year) for year in years})
    year = inputs.get("year")
    if year:
        return [int(year)]
    return [inv.year]


def _missing_real_ba300_message(years: list[int], available_months: list[str]) -> str:
    years_text = ", ".join(str(year) for year in years)
    available_text = ", ".join(available_months) if available_months else "none"
    return (
        f"I cannot resolve that burned-area request from real BA300 data yet. "
        f"Requested year(s): {years_text}. Available ingested BA300 month(s): {available_text}. "
        "Sync or import the missing BA300 months, then rerun the prompt. "
        "No synthetic burned-area values were used."
    )


def compute_annual_burned_area(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    years = _requested_years(inv, inputs)
    available = ba300_store.ingested_months(settings.real_data_dir)
    summaries: list[dict[str, Any]] = []
    for year in years:
        try:
            summaries.append(ba300_store.summarise_year(settings.real_data_dir, year))
        except KeyError as exc:
            raise ValueError(_missing_real_ba300_message(years, available)) from exc
    by_year = {
        str(summary["year"]): summary["annual"]
        for summary in summaries
    }
    primary = summaries[-1]
    annual = primary["annual"]
    return {
        "aoi": inv.aoi,
        "year": primary["year"],
        "years": years,
        "annual_by_year": by_year,
        "burned_area_ha": annual["burned_area_ha"],
        "burned_area_km2": annual["burned_area_km2"],
        "months_ingested": annual["months_ingested"],
        "complete_year": annual["complete_year"],
        "method": "Sum monthly BA300 burned-area occurrence hectares computed from clipped BF rasters in EPSG:3035.",
        "source_dataset": "CLMS Burnt Area 300 m monthly v4",
        "caveats": [
            "No synthetic burned-area values are used.",
            "Annual totals are partial when fewer than 12 BA300 months are ingested.",
            "The result is not an emergency-response or damage-estimation product.",
        ],
    }


def compute_monthly_burned_area(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    years = _requested_years(inv, inputs)
    available = ba300_store.ingested_months(settings.real_data_dir)
    monthly: list[dict[str, Any]] = []
    peak = None
    for year in years:
        try:
            summary = ba300_store.summarise_year(settings.real_data_dir, year)
        except KeyError as exc:
            raise ValueError(_missing_real_ba300_message(years, available)) from exc
        monthly.extend(summary["monthly"])
        year_peak = summary["annual"]["peak_month"]
        if peak is None:
            peak = year_peak
    return {
        "year": years[-1],
        "years": years,
        "monthly": monthly,
        "peak_month": peak,
        "source_dataset": "CLMS Burnt Area 300 m monthly v4",
        "method": "Monthly BA300 burned-area occurrence hectares computed from clipped BF rasters in EPSG:3035.",
        "caveats": ["No synthetic burned-area values are used.", "Missing months are omitted rather than estimated."],
    }


def rank_burn_clusters(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    limit = int(inputs.get("limit", 10))
    features = ba300_store.clusters_geojson(settings.real_data_dir, year=int(inputs.get("year") or inv.year))["features"]
    if not features:
        available = ba300_store.ingested_months(settings.real_data_dir)
        raise ValueError(_missing_real_ba300_message([int(inputs.get("year") or inv.year)], available))
    ranked = sorted(features, key=lambda f: f["properties"]["area_ha"], reverse=True)[:limit]
    return {
        "year": int(inputs.get("year") or inv.year),
        "clusters": ranked,
        "count": len(ranked),
        "source_dataset": "CLMS Burnt Area 300 m monthly v4",
        "method": "Connected mapped burned-area components derived from real BA300 monthly BF rasters, ranked by burned-area occurrence hectares.",
        "caveats": [
            "Clusters are analytical objects derived from burned-area rasters, not authoritative fire perimeters.",
            "Monthly clusters are not confirmed individual wildfire events.",
        ],
    }


def summarise_selected_cluster(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    cluster = _selected_cluster(inv, inputs)
    props = cluster["properties"]
    inv.selected_cluster_id = props["cluster_id"]
    return {
        "cluster_id": props["cluster_id"],
        "cluster": cluster,
        "area_ha": props["area_ha"],
        "month": props["month"],
        "first_burn_date": props.get("first_burn_date"),
        "burn_window": {
            "start": props.get("burn_window_start"),
            "end": props.get("burn_window_end"),
        },
        "pre_fire_search_window": {
            "start": props.get("pre_search_start"),
            "end": props.get("pre_search_end"),
        },
        "post_fire_search_window": {
            "start": props.get("post_search_start"),
            "end": props.get("post_search_end"),
        },
        "mean_confidence": props["mean_confidence"],
        "admin_region": props["admin_region"],
        "dominant_landcover": props["dominant_landcover"],
        "source_dataset": "CLMS Burnt Area 300 m monthly v4",
        "method": "Selected connected BA300 burned-area component, including inferred monthly burn and imagery-search windows.",
        "caveats": [
            "Cluster geometry is derived from real BA300 burned-area rasters, not a verified fire perimeter.",
            "Burn window is monthly unless DOB-derived daily refinement is available.",
        ],
    }


def _selected_pair_from_scenes(selected_scenes: dict[str, dict[str, Any]], composite: str) -> dict[str, Any] | None:
    before = selected_scenes.get("before")
    if normalise_composite(composite) == "fire_front_highlight":
        comparison = selected_scenes.get("during") or selected_scenes.get("after")
        comparison_label = "event scene" if selected_scenes.get("during") else "post-fire scene"
    else:
        comparison = selected_scenes.get("after")
        comparison_label = "post-fire scene"
    if not before or not comparison:
        return None
    return {
        "pre": before,
        "post": comparison,
        "selection_reason": f"Best-ranked pre-fire scene and {comparison_label}, prioritising AOI coverage, then cloud cover and temporal proximity.",
    }


def search_optical_imagery(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    cluster = _selected_cluster(inv, inputs)
    props = cluster["properties"]
    cluster_id = props["cluster_id"]
    requested_sensor = normalise_sensor(inputs.get("sensor") or inputs.get("sensor_key"))
    requested_composite = normalise_composite(inputs.get("composite") or inputs.get("composite_type"))
    max_cloud = float(inputs.get("max_cloud", 20.0))
    pre_days = int(inputs.get("pre_days", 45))
    post_days = int(inputs.get("post_days", 45))
    windows = search_windows(cluster, inv.year, pre_days=pre_days, post_days=post_days)
    windows["during"] = dict(windows["burn_window"])
    event_date_value = inputs.get("event_date") or props.get("fire_front_event_date")
    event_window: dict[str, str] | None = None
    if requested_composite == "fire_front_highlight" and event_date_value:
        event_date = parse_iso_date(str(event_date_value))
        event_window = {"start": event_date.isoformat(), "end": event_date.isoformat()}
        windows["burn_window"] = dict(event_window)
        windows["during"] = dict(event_window)
        windows["pre_fire"] = {
            "start": (event_date - timedelta(days=pre_days)).isoformat(),
            "end": (event_date - timedelta(days=1)).isoformat(),
        }
        windows["post_fire"] = {
            "start": (event_date + timedelta(days=1)).isoformat(),
            "end": (event_date + timedelta(days=post_days)).isoformat(),
        }
    cluster_bbox = geometry_bbox(cluster["geometry"])
    bbox = pad_bbox(cluster_bbox, 0.04)
    min_coverage = float(inputs.get("min_coverage_percent", 70.0))

    real_candidates: list[dict[str, Any]] = []
    status = "mock"
    errors: list[str] = []
    search_diagnostics: list[dict[str, Any]] = []
    if settings.stac_mode in {"real", "auto"}:
        for sensor_key in sensor_order(requested_sensor):
            if sensor_key == "modis" and not settings.stac_modis_api_url:
                errors.append("MODIS STAC search requested, but WEA_STAC_MODIS_API_URL/WEA_STAC_MODIS_COLLECTIONS are not configured.")
                continue
            try:
                window_specs = [
                    ("pre-fire", windows["pre_fire"]),
                    ("during-window", windows["during"]),
                    ("post-fire", windows["post_fire"]),
                ]
                window_diagnostics: list[dict[str, Any]] = []
                for window_label, window in window_specs:
                    datetime_range = f"{window['start']}/{window['end']}"
                    items, diagnostics = search_stac_items_with_fallback(
                        sensor=sensor_key,
                        bbox=bbox,
                        datetime_range=datetime_range,
                        max_cloud=max_cloud,
                        limit=settings.stac_max_items,
                        coverage_bbox=cluster_bbox,
                        min_coverage_percent=min_coverage,
                        composite=requested_composite,
                    )
                    diagnostics.update({"window": window_label, "sensor": sensor_key})
                    search_diagnostics.append(diagnostics)
                    window_diagnostics.append(diagnostics)
                    real_candidates.extend(items)
                status = "real-stac-fallback" if any(d.get("fallback_used") for d in window_diagnostics) else "real-stac"
            except Exception as exc:  # noqa: BLE001 - surfaced as provenance/caveat for demo transparency
                errors.append(f"{SENSOR_LABELS.get(sensor_key, sensor_key)} STAC search failed: {exc}")

    if real_candidates:
        status = "real-stac-fallback" if any(d.get("fallback_used") for d in search_diagnostics) else "real-stac"
        candidates = add_roles(real_candidates, windows["burn_window"])

        def _candidate_rank(c: dict[str, Any]) -> tuple[float, float, float]:
            coverage = float(c.get("coverage_percent") if c.get("coverage_percent") is not None else 100.0)
            cloud = float(c.get("cloud_cover") if c.get("cloud_cover") is not None else 100.0)
            # Higher coverage first, then lower cloud. Temporal bracketing is
            # handled separately by choose_pair for the selected pair.
            return (-coverage, cloud, 0.0)

        candidates = sorted(candidates, key=_candidate_rank)
        for c in candidates:
            c["render_recipe"] = render_recipe(c.get("sensor_key", requested_sensor), requested_composite)
            if "render_asset_resolution" not in c:
                try:
                    c["render_asset_resolution"] = resolve_render_assets(c, requested_composite)
                except ValueError as exc:
                    c["render_error"] = str(exc)
            cov = c.get("coverage_percent")
            cov_text = f" with approximately {cov}% AOI bbox coverage" if cov is not None else ""
            provider = c.get("stac_provider_label") or c.get("stac_provider") or "configured"
            c["reason"] = f"Returned by {provider} STAC search and classified relative to the inferred burn window{cov_text}."
    else:
        candidates = []
        status = "real-stac-error" if errors else "real-stac-no-results"

    selected_scenes = choose_scenes(candidates, windows["burn_window"])
    pair = _selected_pair_from_scenes(selected_scenes, requested_composite)
    sensor_label = SENSOR_LABELS.get(requested_sensor, requested_sensor)
    composite_label = COMPOSITE_LABELS.get(requested_composite, requested_composite)
    caveats = [
        "This is imagery-discovery finding. It identifies candidate scenes and render recipes; it does not yet compute dNBR or perform visual validation.",
        "Scene suitability should be checked with cloud masks and asset-level coverage before operational use.",
    ]
    if requested_sensor == "modis":
        caveats.append("MODIS is coarse contextual imagery and is not appropriate for detailed cluster-level perimeter validation.")
    if requested_composite == "fire_front_highlight":
        caveats.append("The fire-front highlight is a natural-colour/SWIR blend for visual interpretation. It is not an active-fire detection algorithm and requires suitable SWIR assets.")
    provider_errors = [
        error
        for diagnostic in search_diagnostics
        for error in diagnostic.get("provider_errors", [])
    ]
    if provider_errors:
        caveats.extend(provider_errors)
    if pair:
        pre_provider = (pair.get("pre") or {}).get("stac_provider_label")
        post_provider = (pair.get("post") or {}).get("stac_provider_label")
        if pre_provider and post_provider and pre_provider != post_provider:
            caveats.append(f"The selected optical pair comes from different STAC catalogs ({pre_provider} and {post_provider}); inspect radiometry and scene metadata before quantitative comparison.")
    if errors:
        caveats.extend(errors)

    return {
        "cluster_id": cluster_id,
        "cluster": cluster,
        "sensor_request": requested_sensor,
        "sensor_label": sensor_label,
        "composite": requested_composite,
        "composite_label": composite_label,
        "composite_description": render_recipe(requested_sensor if requested_sensor != "any" else "sentinel-2", requested_composite)["composite_description"],
        "search_status": status,
        "burn_window": windows["burn_window"],
        "pre_fire_search_window": windows["pre_fire"],
        "post_fire_search_window": windows["post_fire"],
        "during_search_window": windows["during"],
        "event_window": event_window,
        "max_cloud": max_cloud,
        "min_coverage_percent": min_coverage,
        "coverage_method": "AOI bounding-box intersection against the selected cluster bbox",
        "stac_search_diagnostics": search_diagnostics,
        "bbox": bbox,
        "cluster_bbox": cluster_bbox,
        # Render bounds are intentionally tight to the selected AOI/cluster bbox.
        # STAC search can use a padded bbox, but map rendering should not fetch
        # large numbers of tiles outside the investigation area.
        "render_bounds": list(cluster_bbox),
        "clip_bbox": list(cluster_bbox),
        "candidates": candidates,
        "selected_scenes": selected_scenes,
        "selected_pair": pair,
        "source_dataset": "STAC optical imagery search over Sentinel-2/Landsat/MODIS-capable workflow",
        "method": "Resolve sensor/composite intent, infer pre/post windows from the selected real BA300 cluster, search STAC catalogs with provider fallback, resolve renderable STAC assets from asset metadata, estimate AOI coverage, and rank by coverage, cloud cover, and temporal bracketing.",
        "caveats": caveats,
    }


def compute_landcover_impact(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raise ValueError(
        "I cannot resolve land-cover impact from real data yet because ESA WorldCover ingestion is not loaded. "
        "Try BA300 burned-area totals, BA300 cluster selection, or real STAC optical imagery for a selected cluster."
    )


def compute_ghsl_exposure(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raise ValueError(
        "I cannot resolve GHSL exposure from real data yet because GHSL built-up/population layers are not loaded. "
        "Try selecting a real BA300 cluster or finding real optical imagery for that cluster."
    )


def compute_aod_context(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raise ValueError(
        "I cannot resolve CAMS AOD context from real data yet because CAMS ingestion is not loaded. "
        "Try BA300 burned-area totals, real cluster selection, or real optical imagery."
    )


def compute_drought_context(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    raise ValueError(
        "I cannot resolve ERA5 drought context from real data yet because ERA5 ingestion is not loaded. "
        "Try BA300 burned-area totals, real cluster selection, or real optical imagery."
    )


def create_finding_card(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    source_step = inputs.get("uses") or inputs.get("source_step")
    result = ctx.get(source_step, {}) if source_step else ctx
    card_cfg = inputs.get("card", {})
    card_type = FindingType(card_cfg.get("type", "supporting_finding"))
    title = card_cfg.get("title", result.get("title", "Finding card"))
    if result.get("composite_label") and "imagery" in title.lower():
        title = f"{result['composite_label']} imagery finding"
    source_dataset = result.get("source_dataset") or card_cfg.get("source_dataset", "Unknown")
    summary = _summary_for_card(title, result)
    geometry = None
    if "cluster" in result:
        geometry = result["cluster"].get("geometry")
    elif "clusters" in result and result["clusters"]:
        geometry = result["clusters"][0].get("geometry")
    card = FindingCard(
        investigation_id=inv.id,
        type=card_type,
        title=title,
        summary=summary,
        source_dataset=source_dataset,
        geometry=geometry,
        payload=result,
        provenance={
            "skill_id": inputs.get("skill_id"),
            "source_step": source_step,
            "method": result.get("method"),
            "parameters": {
                "aoi": inv.aoi,
                "year": inv.year,
                "confidence_mode": inv.confidence_mode.value,
                "sensor": result.get("sensor_request"),
                "composite": result.get("composite"),
                "max_cloud": result.get("max_cloud"),
            },
        },
        caveats=result.get("caveats", []),
        pinned=bool(card_cfg.get("pinned", False)),
    )
    return {"card": card.model_dump(mode="json"), "finding_id": card.id}


def generate_report_from_finding(inv: Investigation, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": "Report generation is handled by the report endpoint using finding cards explicitly added to the report.",
        "source_dataset": "Report-selected finding cards",
        "method": "Compile report-selected finding with provenance and caveats.",
        "caveats": ["The report should not include contextual finding without explicit user approval."],
    }


def _summary_for_card(title: str, result: dict[str, Any]) -> str:
    if "burned_area_ha" in result:
        return f"Estimated burned area: {result['burned_area_ha']:,.1f} ha ({result['burned_area_km2']:,.2f} km²) for {result['aoi']} in {result['year']}."
    if "monthly" in result:
        peak = result.get("peak_month", "unknown")
        return f"Monthly burned-area time series for {result.get('year')}; peak month: {peak}."
    if "clusters" in result:
        return f"Ranked {result['count']} burn clusters by estimated burned area."
    if "area_ha" in result and "cluster_id" in result:
        window = result.get("burn_window") or {}
        suffix = f" Burn window: {window.get('start')} to {window.get('end')}." if window.get("start") else ""
        return f"Cluster {result['cluster_id']} covers approximately {result['area_ha']:,.1f} ha; dominant land cover: {result.get('dominant_landcover')}.{suffix}"
    if "selected_pair" in result:
        sensor = result.get("sensor_label", "optical")
        composite = result.get("composite_label", "composite")
        pair = result.get("selected_pair")
        if pair:
            pre = pair.get("pre", {}).get("datetime", "pre-fire candidate")
            post = pair.get("post", {}).get("datetime", "post-fire candidate")
            if result.get("composite") == "fire_front_highlight":
                return f"Selected {sensor} {composite.lower()} pre-fire/event pair for cluster {result.get('cluster_id')}: {pre} → {post}."
            return f"Selected {sensor} {composite.lower()} before/after pair for cluster {result.get('cluster_id')}: {pre} → {post}."
        if result.get("composite") == "fire_front_highlight":
            return f"Found {len(result.get('candidates', []))} {sensor} candidates for {composite.lower()} around cluster {result.get('cluster_id')}, but no clean pre-fire/event pair was selected."
        return f"Found {len(result.get('candidates', []))} {sensor} candidates for {composite.lower()} around cluster {result.get('cluster_id')}, but no clean pre/post pair was selected."
    if "landcover_burned_area_ha" in result:
        return f"Land-cover impact summary for cluster {result.get('cluster_id')}; dominant class: {result.get('dominant_landcover')} ."
    if "population_exposure_proxy" in result:
        return f"Potential exposure proxy for cluster {result.get('cluster_id')}: {result.get('population_exposure_proxy')} baseline population units near/intersecting burned area."
    if "max_aod" in result:
        return f"AOD contextual time series for cluster {result.get('cluster_id')}; max demo AOD: {result.get('max_aod')} ."
    if "dry_days_proxy" in result:
        return f"Pre-fire drought context for cluster {result.get('cluster_id')}; dry-days proxy: {result.get('dry_days_proxy')} ."
    return title


REGISTRY: dict[str, ToolFn] = {
    "compute_annual_burned_area": compute_annual_burned_area,
    "compute_monthly_burned_area": compute_monthly_burned_area,
    "rank_burn_clusters": rank_burn_clusters,
    "summarise_selected_cluster": summarise_selected_cluster,
    "search_optical_imagery": search_optical_imagery,
    "compute_landcover_impact": compute_landcover_impact,
    "compute_ghsl_exposure": compute_ghsl_exposure,
    "compute_aod_context": compute_aod_context,
    "compute_drought_context": compute_drought_context,
    "create_finding_card": create_finding_card,
    "generate_report_from_finding": generate_report_from_finding,
}
