from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from app.core.stac_search import normalise_composite, resolve_render_assets
from app.settings import get_settings


class PreviewError(RuntimeError):
    """Raised when STAC map/render configuration cannot be derived."""


_SIGNED_HREF_CACHE: dict[str, tuple[str, datetime]] = {}
_SIGNING_REFRESH_MARGIN = timedelta(minutes=5)


def _parse_expiry(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc) + timedelta(minutes=30)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc) + timedelta(minutes=30)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _uses_planetary_computer_assets() -> bool:
    settings = get_settings()
    provider = settings.stac_provider.strip().lower().replace("_", "-")
    provider_order = getattr(settings, "stac_provider_order", "")
    return (
        provider in {"planetary-computer", "pc"}
        or "planetarycomputer.microsoft.com" in settings.stac_api_url
        or "planetary-computer" in provider_order.lower()
        or "planetarycomputer.microsoft.com" in getattr(settings, "stac_planetary_computer_api_url", "")
    )


def _is_unsigned_azure_blob_href(href: str) -> bool:
    parsed = urlparse(href)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.endswith(".blob.core.windows.net")
        and "sig=" not in parsed.query
    )


def _sign_planetary_computer_href(href: str) -> str:
    if not _uses_planetary_computer_assets() or not _is_unsigned_azure_blob_href(href):
        return href

    now = datetime.now(timezone.utc)
    cached = _SIGNED_HREF_CACHE.get(href)
    if cached and cached[1] - now > _SIGNING_REFRESH_MARGIN:
        return cached[0]

    settings = get_settings()
    try:
        response = requests.get(
            settings.planetary_computer_sign_url,
            params={"href": href},
            timeout=settings.stac_timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise PreviewError(f"Could not sign Planetary Computer asset URL: {exc}") from exc

    data = response.json()
    signed = data.get("href")
    if not isinstance(signed, str) or not signed:
        raise PreviewError("Planetary Computer signing response did not include a signed href.")
    expires = _parse_expiry(data.get("msft:expiry"))
    _SIGNED_HREF_CACHE[href] = (signed, expires)
    return signed



def _bbox_from_geometry(geometry: dict[str, Any] | None) -> tuple[float, float, float, float] | None:
    if not geometry:
        return None
    coords: list[list[float]] = []
    if geometry.get("type") == "Polygon":
        for ring in geometry.get("coordinates", []):
            coords.extend(ring)
    elif geometry.get("type") == "MultiPolygon":
        for poly in geometry.get("coordinates", []):
            for ring in poly:
                coords.extend(ring)
    if not coords:
        return None
    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))



def _pad_bounds(bounds: tuple[float, float, float, float], fraction: float = 0.35) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = bounds
    dx = max(maxx - minx, 1e-6) * fraction
    dy = max(maxy - miny, 1e-6) * fraction
    return (minx - dx, miny - dy, maxx + dx, maxy + dy)



def preview_bounds_4326(payload: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return padded cluster bounds for static render/export previews."""
    raw_bounds = _bbox_from_geometry((payload.get("cluster") or {}).get("geometry"))
    if raw_bounds is None:
        scenes = payload.get("selected_scenes") or {}
        pair = payload.get("selected_pair") or {}
        item = (
            scenes.get("before")
            or scenes.get("during")
            or scenes.get("after")
            or pair.get("pre")
            or pair.get("post")
            or {}
        )
        item_bbox = item.get("bbox") or []
        if len(item_bbox) != 4:
            raise PreviewError("No cluster geometry or item bbox is available to locate the preview on the map.")
        raw_bounds = (float(item_bbox[0]), float(item_bbox[1]), float(item_bbox[2]), float(item_bbox[3]))
    return _pad_bounds(raw_bounds)



def maplibre_image_coordinates(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    minx, miny, maxx, maxy = bounds
    return [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]]



def _normalise_href(href: str) -> str:
    if href.startswith("s3://"):
        rest = href.removeprefix("s3://")
        bucket, _, key = rest.partition("/")
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return _sign_planetary_computer_href(href)



def _role_name(role: str) -> str:
    value = (role or "").strip().lower().replace("_", "-")
    if value in {"pre", "pre-fire", "before"}:
        return "before"
    if value in {"during", "during-window", "event", "active", "active-fire"}:
        return "during"
    return "after"


def _candidate_role_for_scene(role_key: str) -> str:
    return {
        "before": "pre-fire",
        "during": "during-window",
        "after": "post-fire",
    }[role_key]



def role_candidates(payload: dict[str, Any], role: str) -> list[dict[str, Any]]:
    role_key = _role_name(role)
    expected = _candidate_role_for_scene(role_key)
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        return []
    return [c for c in candidates if isinstance(c, dict) and c.get("role") == expected]



def selected_candidate_index(payload: dict[str, Any], role: str) -> int:
    role_key = _role_name(role)
    scenes = payload.get("selected_scenes") or {}
    selected = scenes.get(role_key) if isinstance(scenes, dict) else None
    pair = payload.get("selected_pair") or {}
    if not isinstance(selected, dict):
        if role_key == "before":
            selected = pair.get("pre") or {}
        elif role_key == "during" and isinstance(pair.get("post"), dict) and pair["post"].get("role") == "during-window":
            selected = pair.get("post") or {}
        elif role_key == "after":
            selected = pair.get("post") or {}
        else:
            selected = {}
    selected_id = selected.get("item_id")
    candidates = role_candidates(payload, role_key)
    for idx, candidate in enumerate(candidates):
        if candidate.get("item_id") == selected_id:
            return idx
    return 0



def candidate_for_role(payload: dict[str, Any], role: str, candidate_index: int | None = None) -> dict[str, Any]:
    role_key = _role_name(role)
    if candidate_index is not None:
        candidates = role_candidates(payload, role_key)
        if not candidates:
            raise PreviewError(f"No {role_key} candidates are available for this finding card.")
        if candidate_index < 0 or candidate_index >= len(candidates):
            raise PreviewError(f"Candidate index {candidate_index} is out of range for {role_key} imagery.")
        return candidates[candidate_index]

    scenes = payload.get("selected_scenes") or {}
    item = scenes.get(role_key) if isinstance(scenes, dict) else None
    if isinstance(item, dict):
        return item

    pair = payload.get("selected_pair") or {}
    if role_key == "before":
        item = pair.get("pre")
    elif role_key == "during" and isinstance(pair.get("post"), dict) and pair["post"].get("role") == "during-window":
        item = pair.get("post")
    elif role_key == "after":
        item = pair.get("post")
    else:
        item = None
    if not isinstance(item, dict):
        raise PreviewError(f"No selected {role_key} STAC item is available for this finding card.")
    return item



def _asset_href_map(item: dict[str, Any], composite: str) -> dict[str, str]:
    assets = item.get("assets") or {}
    try:
        resolved = item.get("render_asset_resolution") or resolve_render_assets(item, composite)
    except ValueError as exc:
        raise PreviewError(str(exc)) from exc
    keys = [str(key) for key in resolved.get("asset_keys") or []]
    visual = bool(resolved.get("visual"))
    if not keys:
        raise PreviewError(f"Cannot render {composite}: no renderable asset keys were resolved.")
    if visual:
        href = assets.get(keys[0])
        if not href:
            raise PreviewError(f"Selected visual asset {keys[0]} is missing an href.")
        params = {"visual": _normalise_href(str(href))}
    else:
        if len(keys) < 3:
            raise PreviewError("Composite rendering requires three asset keys.")
        params = {
            "r": _normalise_href(str(assets[keys[0]])),
            "g": _normalise_href(str(assets[keys[1]])),
            "b": _normalise_href(str(assets[keys[2]])),
        }
    if normalise_composite(composite) == "fire_front_highlight":
        blend_keys = [str(key) for key in resolved.get("blend_asset_keys") or []]
        if len(blend_keys) < 3:
            raise PreviewError("Fire-front highlight requires three SWIR highlight asset keys.")
        try:
            blend_weight = float(resolved.get("blend_weight", 0.28))
        except (TypeError, ValueError):
            blend_weight = 0.28
        params.update({
            "blend_r": _normalise_href(str(assets[blend_keys[0]])),
            "blend_g": _normalise_href(str(assets[blend_keys[1]])),
            "blend_b": _normalise_href(str(assets[blend_keys[2]])),
            "blend_weight": f"{max(0.0, min(1.0, blend_weight)):.2f}",
        })
    return params



def _format_stretch_value(value: Any) -> str | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return f"{numeric:.8f}"


def _stretch_query_params_from_channels(
    channels: Any,
    *,
    prefix: str = "",
) -> dict[str, str]:
    if not isinstance(channels, dict):
        return {}
    params: dict[str, str] = {}
    for channel in ("r", "g", "b"):
        stats = channels.get(channel)
        if not isinstance(stats, dict):
            continue
        lo = _format_stretch_value(stats.get("min"))
        hi = _format_stretch_value(stats.get("max"))
        if lo is None or hi is None:
            continue
        params[f"{prefix}{channel}_min"] = lo
        params[f"{prefix}{channel}_max"] = hi
    return params


def _aoi_stretch_params(
    params: dict[str, str],
    *,
    bbox: str,
    tiler_stats_base: str | None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Ask the tiler for AOI-wide stretch ranges to keep map tiles coherent."""
    if not tiler_stats_base:
        return {}, {"status": "not_requested", "method": "per-tile-percentile"}

    settings = get_settings()
    stats_params = dict(params)
    stats_params.update({
        "bbox": bbox,
        "width": "640",
    })

    try:
        response = requests.get(
            f"{tiler_stats_base.rstrip('/')}/stats.json",
            params=stats_params,
            timeout=settings.stac_timeout_seconds,
        )
        response.raise_for_status()
        stats = response.json()
    except requests.RequestException as exc:
        return {}, {
            "status": "unavailable",
            "method": "per-tile-percentile",
            "reason": str(exc),
        }
    except ValueError as exc:
        return {}, {
            "status": "unavailable",
            "method": "per-tile-percentile",
            "reason": f"Invalid tiler stretch stats response: {exc}",
        }

    stretch_params = _stretch_query_params_from_channels(stats.get("channels"))
    stretch_params.update(_stretch_query_params_from_channels(stats.get("blend_channels"), prefix="blend_"))
    if not stretch_params:
        return {}, {
            "status": "unavailable",
            "method": "per-tile-percentile",
            "reason": "Tiler did not return usable AOI stretch ranges.",
        }

    return stretch_params, {
        "status": "ok",
        "method": stats.get("stretch_method") or "aoi-percentile",
        "percentiles": stats.get("percentiles"),
        "stats_width": stats.get("width"),
        "renderer_version": stats.get("renderer_version"),
    }


def _item_bbox(item: dict[str, Any], fallback_bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    bbox = item.get("bbox") or []
    if len(bbox) == 4:
        return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    return fallback_bounds



def tiler_tile_url_for_payload(
    payload: dict[str, Any],
    *,
    role: str,
    candidate_index: int | None,
    tiler_base: str,
    tiler_stats_base: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return tile-layer metadata plus the selected candidate item."""
    role_key = _role_name(role)
    item = candidate_for_role(payload, role_key, candidate_index=candidate_index)
    if item.get("source") != "stac":
        raise PreviewError("Map tiling requires real STAC items with accessible COG assets. This finding card appears to be mock metadata.")

    composite = normalise_composite(str(payload.get("composite") or item.get("composite") or "true_color"))
    params = _asset_href_map(item, composite)
    # Bound rendering to the selected AOI/cluster, not the full STAC scene.
    # `bounds` limits what MapLibre asks for. `clip_bbox` is also sent to the
    # tiler so partially intersecting WebMercator tiles are masked outside AOI.
    render_bounds = payload.get("render_bounds") or payload.get("cluster_bbox")
    if isinstance(render_bounds, list) and len(render_bounds) == 4:
        layer_bounds = tuple(float(v) for v in render_bounds)
    else:
        layer_bounds = preview_bounds_4326(payload)

    clip_bounds = payload.get("clip_bbox") or payload.get("cluster_bbox") or list(layer_bounds)
    if isinstance(clip_bounds, list) and len(clip_bounds) == 4:
        clip_bbox = ",".join(f"{float(v):.8f}" for v in clip_bounds)
    else:
        clip_bbox = ",".join(f"{float(v):.8f}" for v in layer_bounds)

    params.update({
        "composite": composite,
        "sensor": str(item.get("sensor_key") or item.get("sensor") or payload.get("sensor_request") or "optical"),
        "item_id": str(item.get("item_id") or "unknown"),
        "role": role_key,
        "clip_bbox": clip_bbox,
    })
    stretch_params, stretch_metadata = _aoi_stretch_params(params, bbox=clip_bbox, tiler_stats_base=tiler_stats_base)
    params.update(stretch_params)
    query = urlencode(params, doseq=False, safe=":/{}.,")
    base = tiler_base.rstrip("/")
    tile_url = f"{base}/tiles/{{z}}/{{x}}/{{y}}.png?{query}"

    scene_bounds = _item_bbox(item, layer_bounds)
    minzoom = 7 if str(item.get("sensor_key") or item.get("sensor") or "").startswith("sentinel") else 6
    maxzoom = 14 if str(item.get("sensor_key") or item.get("sensor") or "").startswith("sentinel") else 13
    layer = {
        "kind": "raster_tile",
        "tiles": [tile_url],
        "tile_size": 256,
        "attribution": "Optical imagery via public STAC assets; rendered by local Burned Area Explorer composite tiler.",
        "item_id": item.get("item_id"),
        "datetime": item.get("datetime"),
        "sensor": item.get("sensor"),
        "composite": composite,
        "bounds": list(layer_bounds),
        "clip_bbox": [float(v) for v in clip_bbox.split(",")],
        "scene_bounds": list(scene_bounds),
        "coverage_percent": item.get("coverage_percent"),
        "coverage_method": item.get("coverage_method"),
        "stretch": stretch_metadata,
        "minzoom": minzoom,
        "maxzoom": maxzoom,
    }
    return layer, item



def tiler_render_url_for_payload(
    payload: dict[str, Any],
    *,
    role: str,
    candidate_index: int | None,
    tiler_base: str,
    width: int = 900,
) -> tuple[str, dict[str, Any]]:
    role_key = _role_name(role)
    item = candidate_for_role(payload, role_key, candidate_index=candidate_index)
    if item.get("source") != "stac":
        raise PreviewError("Static render export requires real STAC items with accessible COG assets.")
    composite = normalise_composite(str(payload.get("composite") or item.get("composite") or "true_color"))
    params = _asset_href_map(item, composite)
    render_bounds = payload.get("render_bounds") or payload.get("cluster_bbox")
    if isinstance(render_bounds, list) and len(render_bounds) == 4:
        bounds = tuple(float(v) for v in render_bounds)
    else:
        bounds = preview_bounds_4326(payload)
    params.update({
        "composite": composite,
        "sensor": str(item.get("sensor_key") or item.get("sensor") or payload.get("sensor_request") or "optical"),
        "item_id": str(item.get("item_id") or "unknown"),
        "role": role_key,
        "bbox": ",".join(f"{x:.8f}" for x in bounds),
        "width": str(max(320, min(int(width), 1800))),
    })
    query = urlencode(params, doseq=False, safe=":/{}.,")
    return f"{tiler_base.rstrip('/')}/render.png?{query}", item



def update_selected_candidate(payload: dict[str, Any], role: str, candidate_index: int) -> dict[str, Any]:
    role_key = _role_name(role)
    candidates = role_candidates(payload, role_key)
    if not candidates:
        raise PreviewError(f"No {role_key} candidates are available for this finding card.")
    if candidate_index < 0 or candidate_index >= len(candidates):
        raise PreviewError(f"Candidate index {candidate_index} is out of range for {role_key} imagery.")
    updated = dict(payload)
    scenes = dict(updated.get("selected_scenes") or {})
    scenes[role_key] = candidates[candidate_index]
    updated["selected_scenes"] = scenes
    before = scenes.get("before")
    if normalise_composite(str(updated.get("composite") or "")) == "fire_front_highlight":
        comparison = scenes.get("during") or scenes.get("after")
        comparison_label = "event scene" if scenes.get("during") else "post-fire scene"
    else:
        comparison = scenes.get("after")
        comparison_label = "post-fire scene"
    if before and comparison:
        updated["selected_pair"] = {
            "pre": before,
            "post": comparison,
            "selection_reason": f"User-selected pre-fire scene and {comparison_label} from candidate quicklooks.",
        }
    else:
        updated["selected_pair"] = None
    return updated
