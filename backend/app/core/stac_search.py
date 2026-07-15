from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import requests

from app.settings import get_settings

SensorKey = str
CompositeKey = str

SENSOR_COLLECTIONS: dict[str, list[str]] = {
    "sentinel-2": ["sentinel-2-l2a"],
    "landsat": ["landsat-c2-l2"],
}

STAC_PROVIDER_LABELS = {
    "earth-search": "Earth Search",
    "planetary-computer": "Microsoft Planetary Computer",
}

DEFAULT_PROVIDER_ORDER: dict[str, list[str]] = {
    "sentinel-2": ["earth-search", "planetary-computer"],
    "landsat": ["planetary-computer", "earth-search"],
}

SENSOR_LABELS = {
    "sentinel-2": "Sentinel-2 L2A",
    "landsat": "Landsat Collection 2 Level-2",
    "modis": "MODIS surface reflectance",
    "any": "Sentinel-2 or Landsat",
}

COMPOSITE_LABELS = {
    "true_color": "True colour composite",
    "false_color": "False colour composite",
    "fire_front_highlight": "Fire-front highlight composite",
}

COMPOSITE_DESCRIPTIONS = {
    "true_color": "Natural-colour RGB view intended for visual orientation.",
    "false_color": "Near-infrared false colour view intended to separate vegetation and burn scars more clearly than natural colour.",
    "fire_front_highlight": "Natural-colour RGB context blended with shortwave-infrared finding to highlight active fire fronts, hot burn edges, and fresh scars where suitable SWIR assets exist.",
}

RENDER_RECIPES: dict[str, dict[str, dict[str, Any]]] = {
    "sentinel-2": {
        "true_color": {
            "label": "Sentinel-2 true colour",
            "bands": ["red", "green", "blue"],
            "fallback_assets": ["visual"],
            "description": "RGB using red, green, and blue reflectance bands, or the visual asset where available.",
        },
        "false_color": {
            "label": "Sentinel-2 false colour",
            "bands": ["nir", "red", "green"],
            "description": "NIR/red/green composite for vegetation and burn-scar contrast.",
        },
        "fire_front_highlight": {
            "label": "Sentinel-2 fire-front highlight",
            "bands": ["red", "green", "blue"],
            "fallback_assets": ["visual"],
            "blend_bands": ["swir22", "nir", "red"],
            "alternate_blend_bands": ["swir16", "nir", "red"],
            "blend_weight": 0.28,
            "description": "Natural-colour RGB blended with SWIR/NIR/red so fire fronts and hot burn edges read as highlights over recognisable terrain.",
        },
    },
    "landsat": {
        "true_color": {
            "label": "Landsat true colour",
            "bands": ["red", "green", "blue"],
            "description": "RGB using Collection 2 Level-2 surface reflectance assets.",
        },
        "false_color": {
            "label": "Landsat false colour",
            "bands": ["nir08", "red", "green"],
            "description": "NIR/red/green composite for vegetation and burn-scar contrast.",
        },
        "fire_front_highlight": {
            "label": "Landsat fire-front highlight",
            "bands": ["red", "green", "blue"],
            "blend_bands": ["swir22", "nir08", "red"],
            "alternate_blend_bands": ["swir16", "nir08", "red"],
            "blend_weight": 0.28,
            "description": "Natural-colour RGB blended with SWIR/NIR/red. Useful when Sentinel-2 is unavailable or cloudy, but at coarser spatial resolution.",
        },
    },
    "modis": {
        "true_color": {
            "label": "MODIS true colour context",
            "bands": ["red", "green", "blue"],
            "description": "Coarser-resolution contextual visualisation. Not suitable for detailed fire-perimeter inspection.",
        },
        "false_color": {
            "label": "MODIS false colour context",
            "bands": ["nir", "red", "green"],
            "description": "Coarser-resolution false-colour context. Use for broad regional smoke/fire-season context, not cluster-level validation.",
        },
        "fire_front_highlight": {
            "label": "MODIS fire context",
            "bands": ["red", "green", "blue"],
            "blend_bands": ["swir", "nir", "red"],
            "blend_weight": 0.28,
            "description": "Coarse natural-colour fire/smoke context with SWIR highlight. A real MODIS STAC backend must be configured separately.",
        },
    },
}

BAND_ALIASES: dict[str, list[str]] = {
    "blue": ["blue", "b02", "b2", "band2", "sr_b2"],
    "green": ["green", "b03", "b3", "band3", "sr_b3"],
    "red": ["red", "b04", "b4", "band4", "sr_b4"],
    "nir": ["nir", "nir08", "b08", "b8", "b05", "b5", "sr_b5"],
    "nir08": ["nir08", "nir", "b05", "b5", "sr_b5", "b08", "b8"],
    "swir": ["swir", "swir16", "swir22", "swir1", "swir2", "b06", "b6", "b11"],
    "swir16": ["swir16", "swir1", "swir_1", "b06", "b6", "sr_b6", "b11"],
    "swir22": ["swir22", "swir2", "swir_2", "b07", "b7", "sr_b7", "b12"],
    "visual": ["visual"],
}


def parse_iso_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def infer_burn_window(cluster: dict[str, Any], year: int) -> dict[str, str]:
    props = cluster.get("properties", {})
    if props.get("burn_window_start") and props.get("burn_window_end"):
        start = parse_iso_date(str(props["burn_window_start"]))
        end = parse_iso_date(str(props["burn_window_end"]))
    elif props.get("first_burn_date"):
        first = parse_iso_date(str(props["first_burn_date"]))
        start = first - timedelta(days=5)
        end = first + timedelta(days=12)
    else:
        month = int(props.get("month", 8))
        start = date(year, month, 1)
        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat()}


def search_windows(cluster: dict[str, Any], year: int, pre_days: int, post_days: int) -> dict[str, Any]:
    burn = infer_burn_window(cluster, year)
    burn_start = parse_iso_date(burn["start"])
    burn_end = parse_iso_date(burn["end"])
    return {
        "burn_window": burn,
        "pre_fire": {
            "start": (burn_start - timedelta(days=pre_days)).isoformat(),
            "end": (burn_start - timedelta(days=1)).isoformat(),
        },
        "post_fire": {
            "start": (burn_end + timedelta(days=1)).isoformat(),
            "end": (burn_end + timedelta(days=post_days)).isoformat(),
        },
    }


def geometry_bbox(geometry: dict[str, Any]) -> list[float]:
    coords: list[list[float]] = []
    if geometry.get("type") == "Polygon":
        for ring in geometry.get("coordinates", []):
            coords.extend(ring)
    elif geometry.get("type") == "MultiPolygon":
        for poly in geometry.get("coordinates", []):
            for ring in poly:
                coords.extend(ring)
    if not coords:
        raise ValueError("Cluster geometry has no polygon coordinates.")
    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def pad_bbox(bbox: list[float], pad_deg: float = 0.04) -> list[float]:
    return [bbox[0] - pad_deg, bbox[1] - pad_deg, bbox[2] + pad_deg, bbox[3] + pad_deg]


def _bbox_area(bbox: list[float] | tuple[float, float, float, float] | None) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    minx, miny, maxx, maxy = [float(v) for v in bbox]
    return max(0.0, maxx - minx) * max(0.0, maxy - miny)


def bbox_coverage_percent(
    aoi_bbox: list[float] | tuple[float, float, float, float] | None,
    item_bbox: list[float] | tuple[float, float, float, float] | None,
) -> float | None:
    """Approximate AOI coverage percentage using bbox intersection.

    This deliberately avoids adding a hard Shapely dependency to the demo.
    It answers: how much of the selected AOI/cluster bounding box is covered by
    the returned STAC item footprint bbox? For production, replace or augment
    this with polygon-intersection coverage against the actual AOI geometry.
    """
    if not aoi_bbox or not item_bbox or len(aoi_bbox) != 4 or len(item_bbox) != 4:
        return None
    ax1, ay1, ax2, ay2 = [float(v) for v in aoi_bbox]
    bx1, by1, bx2, by2 = [float(v) for v in item_bbox]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = _bbox_area((ix1, iy1, ix2, iy2))
    area = _bbox_area((ax1, ay1, ax2, ay2))
    if area <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * inter / area)), 1)


def footprint_from_bbox(bbox: list[float]) -> dict[str, Any]:
    minx, miny, maxx, maxy = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]
        ]],
    }


def normalise_sensor(sensor: str | None) -> str:
    value = (sensor or "any").strip().lower().replace("_", "-")
    aliases = {
        "s2": "sentinel-2",
        "sentinel": "sentinel-2",
        "sentinel2": "sentinel-2",
        "sentinel-2": "sentinel-2",
        "landsat": "landsat",
        "l8": "landsat",
        "l9": "landsat",
        "modis": "modis",
        "terra": "modis",
        "aqua": "modis",
        "any": "any",
        "auto": "any",
    }
    return aliases.get(value, "any")


def normalise_composite(composite: str | None) -> str:
    value = (composite or "true_color").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "rgb": "true_color",
        "natural": "true_color",
        "natural_color": "true_color",
        "natural_colour": "true_color",
        "true_color": "true_color",
        "true_colour": "true_color",
        "false_color": "false_color",
        "false_colour": "false_color",
        "nir": "false_color",
        "swir": "fire_front_highlight",
        "shortwave_infrared": "fire_front_highlight",
        "fire_front": "fire_front_highlight",
        "fire_front_highlight": "fire_front_highlight",
        "highlight": "fire_front_highlight",
    }
    return aliases.get(value, "true_color")


def sensor_order(sensor: str) -> list[str]:
    sensor = normalise_sensor(sensor)
    if sensor == "any":
        return ["sentinel-2", "landsat"]
    return [sensor]


def render_recipe(sensor: str, composite: str) -> dict[str, Any]:
    sensor = normalise_sensor(sensor)
    composite = normalise_composite(composite)
    return {
        "sensor": sensor,
        "composite": composite,
        "composite_label": COMPOSITE_LABELS[composite],
        "composite_description": COMPOSITE_DESCRIPTIONS[composite],
        "recipe": RENDER_RECIPES.get(sensor, RENDER_RECIPES["sentinel-2"]).get(composite, RENDER_RECIPES["sentinel-2"]["true_color"]),
    }


def _normalise_provider(provider: str | None) -> str:
    value = (provider or "").strip().lower().replace("_", "-")
    aliases = {
        "earthsearch": "earth-search",
        "element84": "earth-search",
        "earth-search": "earth-search",
        "pc": "planetary-computer",
        "microsoft-planetary-computer": "planetary-computer",
        "planetary-computer": "planetary-computer",
    }
    return aliases.get(value, value)


def _split_csv(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def stac_provider_order(sensor: str) -> list[str]:
    settings = get_settings()
    sensor = normalise_sensor(sensor)
    configured_order = [_normalise_provider(p) for p in _split_csv(settings.stac_provider_order)]
    if configured_order:
        return _unique(configured_order)

    defaults = list(DEFAULT_PROVIDER_ORDER.get(sensor, ["earth-search", "planetary-computer"]))
    primary = _normalise_provider(settings.stac_provider)
    default_primary_url = {
        "earth-search": settings.stac_earth_search_api_url,
        "planetary-computer": settings.stac_planetary_computer_api_url,
    }.get(primary)
    if primary == "planetary-computer" or (primary and settings.stac_api_url != default_primary_url):
        return _unique([primary, *defaults])
    return _unique(defaults)


def _provider_api_url(provider: str) -> str:
    settings = get_settings()
    provider = _normalise_provider(provider)
    if provider == _normalise_provider(settings.stac_provider):
        return settings.stac_api_url
    if provider == "planetary-computer":
        return settings.stac_planetary_computer_api_url
    if provider == "earth-search":
        return settings.stac_earth_search_api_url
    return settings.stac_api_url


def _provider_collections(provider: str, sensor: str) -> list[str]:
    provider = _normalise_provider(provider)
    sensor = normalise_sensor(sensor)
    if provider not in STAC_PROVIDER_LABELS:
        return []
    return list(SENSOR_COLLECTIONS.get(sensor, []))


def _normalise_token(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _band_tokens_from_asset(asset_key: str, metadata: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    metadata = metadata or {}
    common_names: list[str] = []
    tokens = [_normalise_token(asset_key)]
    for band in metadata.get("eo_bands") or metadata.get("bands") or []:
        if not isinstance(band, dict):
            continue
        common_name = _normalise_token(str(band.get("common_name") or ""))
        name = _normalise_token(str(band.get("name") or ""))
        if common_name:
            common_names.append(common_name)
            tokens.append(common_name)
        if name:
            tokens.append(name)
    return _unique(common_names), _unique([t for t in tokens if t])


def asset_band_index(item: dict[str, Any]) -> dict[str, Any]:
    assets = item.get("assets") or {}
    metadata = item.get("asset_metadata") or {}
    common_to_key: dict[str, str] = {}
    token_to_key: dict[str, str] = {}
    key_common_names: dict[str, list[str]] = {}

    for key in assets.keys():
        common_names, tokens = _band_tokens_from_asset(str(key), metadata.get(key))
        key_common_names[str(key)] = common_names
        for name in common_names:
            common_to_key.setdefault(name, str(key))
        for token in tokens:
            token_to_key.setdefault(token, str(key))

    return {
        "common_to_key": common_to_key,
        "token_to_key": token_to_key,
        "key_common_names": key_common_names,
    }


def resolve_asset_key(item: dict[str, Any], requested_band: str) -> str | None:
    index = asset_band_index(item)
    requested = _normalise_token(requested_band)
    aliases = _unique([requested, *BAND_ALIASES.get(requested, [])])

    for alias in aliases:
        key = index["common_to_key"].get(alias)
        if key:
            return key
    for alias in aliases:
        key = index["token_to_key"].get(alias)
        if key:
            return key
    return None


def resolve_render_assets(item: dict[str, Any], composite: str) -> dict[str, Any]:
    assets = item.get("assets") or {}
    sensor = item.get("sensor_key") or item.get("sensor") or "sentinel-2"
    recipe_cfg = item.get("render_recipe") or render_recipe(sensor, composite)
    recipe = recipe_cfg.get("recipe", recipe_cfg)
    composite_key = normalise_composite(composite)

    def resolve_sequence(
        bands: list[str],
        method: str,
    ) -> tuple[list[str] | None, dict[str, str], dict[str, list[str]], list[str]]:
        keys: list[str] = []
        band_map: dict[str, str] = {}
        common_names: dict[str, list[str]] = {}
        missing: list[str] = []
        index = asset_band_index(item)
        for band in bands:
            key = resolve_asset_key(item, band)
            if key and assets.get(key):
                keys.append(key)
                band_map[band] = key
                common_names[band] = list(index["key_common_names"].get(key, []))
            else:
                missing.append(band)
        if not missing and len(keys) >= 3:
            return keys, band_map, common_names, missing
        attempts.append({"method": method, "missing": missing})
        return None, band_map, common_names, missing

    attempts: list[dict[str, Any]] = []

    if composite_key in {"true_color", "fire_front_highlight"}:
        for key in recipe.get("fallback_assets", []):
            resolved = resolve_asset_key(item, str(key))
            if resolved and assets.get(resolved):
                visual_resolution = {
                    "asset_keys": [resolved],
                    "band_map": {"visual": resolved},
                    "common_names": {},
                    "visual": True,
                    "method": "stac-asset-metadata visual fallback",
                }
                if composite_key == "true_color":
                    return visual_resolution
                break
        else:
            visual_resolution = None

        if composite_key == "true_color":
            if assets.get("visual"):
                return {
                    "asset_keys": ["visual"],
                    "band_map": {"visual": "visual"},
                    "common_names": {},
                    "visual": True,
                    "method": "stac visual asset fallback",
                }
        elif visual_resolution is not None:
            blend_resolution = _resolve_blend_sequence(item, recipe, attempts)
            if blend_resolution is not None:
                visual_resolution.update(blend_resolution)
                return visual_resolution

    band_sequences: list[tuple[str, list[str]]] = []
    if recipe.get("bands"):
        band_sequences.append(("stac-asset-metadata primary recipe", list(recipe.get("bands") or [])))
    if recipe.get("alternate_bands"):
        band_sequences.append(("stac-asset-metadata alternate recipe", list(recipe.get("alternate_bands") or [])))

    for method, bands in band_sequences:
        resolved_keys, band_map, common_names, _missing = resolve_sequence(bands, method)
        if not resolved_keys:
            continue
        resolution = {
            "asset_keys": resolved_keys,
            "band_map": band_map,
            "common_names": common_names,
            "visual": False,
            "method": method,
        }
        if composite_key == "fire_front_highlight":
            blend_resolution = _resolve_blend_sequence(item, recipe, attempts)
            if blend_resolution is None:
                continue
            resolution.update(blend_resolution)
        return resolution

    available = ", ".join(sorted(str(k) for k in assets.keys())[:22]) or "none"
    missing = attempts[0]["missing"] if attempts else list(recipe.get("bands") or [])
    raise ValueError(f"Cannot render {composite_key}: missing asset(s) {missing}. Available assets: {available}.")


def _resolve_blend_sequence(
    item: dict[str, Any],
    recipe: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    assets = item.get("assets") or {}
    index = asset_band_index(item)
    blend_sequences: list[tuple[str, list[str]]] = []
    if recipe.get("blend_bands"):
        blend_sequences.append(("stac-asset-metadata SWIR highlight recipe", list(recipe.get("blend_bands") or [])))
    if recipe.get("alternate_blend_bands"):
        blend_sequences.append(("stac-asset-metadata alternate SWIR highlight recipe", list(recipe.get("alternate_blend_bands") or [])))

    for method, bands in blend_sequences:
        keys: list[str] = []
        band_map: dict[str, str] = {}
        common_names: dict[str, list[str]] = {}
        missing: list[str] = []
        for band in bands:
            key = resolve_asset_key(item, band)
            if key and assets.get(key):
                keys.append(key)
                band_map[band] = key
                common_names[band] = list(index["key_common_names"].get(key, []))
            else:
                missing.append(band)
        if not missing and len(keys) >= 3:
            return {
                "blend_asset_keys": keys,
                "blend_band_map": band_map,
                "blend_common_names": common_names,
                "blend_method": method,
                "blend_weight": float(recipe.get("blend_weight", 0.28)),
            }
        attempts.append({"method": method, "missing": missing})
    return None


def _to_rfc3339_interval(datetime_range: str) -> str:
    """Convert YYYY-MM-DD/YYYY-MM-DD into an explicit RFC3339 interval.

    A few STAC APIs accept date-only intervals, but others are stricter. Using
    explicit UTC instants makes the demo's raw /search calls more portable.
    """
    if "T" in datetime_range:
        return datetime_range
    start, end = datetime_range.split("/", 1)
    return f"{start}T00:00:00Z/{end}T23:59:59Z"


def _cloud_value(item: dict[str, Any]) -> float | None:
    value = item.get("cloud_cover")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def search_stac_items(
    *,
    sensor: str,
    bbox: list[float],
    datetime_range: str,
    max_cloud: float,
    limit: int,
    coverage_bbox: list[float] | None = None,
    min_coverage_percent: float = 0.0,
    composite: str | None = None,
) -> list[dict[str, Any]]:
    items, _diagnostics = search_stac_items_with_fallback(
        sensor=sensor,
        bbox=bbox,
        datetime_range=datetime_range,
        max_cloud=max_cloud,
        limit=limit,
        coverage_bbox=coverage_bbox,
        min_coverage_percent=min_coverage_percent,
        composite=composite,
    )
    return items


def search_stac_items_with_fallback(
    *,
    sensor: str,
    bbox: list[float],
    datetime_range: str,
    max_cloud: float,
    limit: int,
    coverage_bbox: list[float] | None = None,
    min_coverage_percent: float = 0.0,
    composite: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = get_settings()
    sensor = normalise_sensor(sensor)
    if sensor == "modis":
        if not settings.stac_modis_api_url or not settings.stac_modis_collections:
            return [], {
                "sensor": sensor,
                "providers_attempted": [],
                "provider_order": [],
                "provider_errors": ["MODIS STAC search requested, but MODIS API URL/collections are not configured."],
                "result_counts": {},
            }
        api_url = settings.stac_modis_api_url
        collections = [c.strip() for c in settings.stac_modis_collections.split(",") if c.strip()]
        provider = "modis-configured"
        diagnostics = {
            "sensor": sensor,
            "provider_order": [provider],
            "providers_attempted": [{"provider": provider, "api_url": api_url, "collections": collections}],
            "provider_errors": [],
            "result_counts": {},
        }
        try:
            items = _search_stac_items_for_provider(
                sensor=sensor,
                provider=provider,
                api_url=api_url,
                collections=collections,
                bbox=bbox,
                datetime_range=datetime_range,
                max_cloud=max_cloud,
                limit=limit,
                coverage_bbox=coverage_bbox,
                min_coverage_percent=min_coverage_percent,
                composite=composite,
            )
        except Exception as exc:  # noqa: BLE001 - returned as finding-card provenance
            diagnostics["provider_errors"].append(f"MODIS configured STAC search failed: {exc}")
            return [], diagnostics
        diagnostics["result_counts"][provider] = len(items)
        if items:
            diagnostics["selected_provider"] = provider
        return items, diagnostics

    provider_order = stac_provider_order(sensor)
    diagnostics: dict[str, Any] = {
        "sensor": sensor,
        "provider_order": provider_order,
        "providers_attempted": [],
        "provider_errors": [],
        "result_counts": {},
    }

    for provider in provider_order:
        api_url = _provider_api_url(provider)
        collections = _provider_collections(provider, sensor)
        if not collections:
            diagnostics["provider_errors"].append(f"{provider}: no default collections are configured for {SENSOR_LABELS.get(sensor, sensor)}.")
            continue
        diagnostics["providers_attempted"].append({"provider": provider, "api_url": api_url, "collections": collections})
        try:
            items = _search_stac_items_for_provider(
                sensor=sensor,
                provider=provider,
                api_url=api_url,
                collections=collections,
                bbox=bbox,
                datetime_range=datetime_range,
                max_cloud=max_cloud,
                limit=limit,
                coverage_bbox=coverage_bbox,
                min_coverage_percent=min_coverage_percent,
                composite=composite,
            )
        except Exception as exc:  # noqa: BLE001 - returned as finding-card provenance
            diagnostics["provider_errors"].append(f"{STAC_PROVIDER_LABELS.get(provider, provider)} STAC search failed: {exc}")
            diagnostics["result_counts"][provider] = 0
            continue

        diagnostics["result_counts"][provider] = len(items)
        if items:
            first_attempt = diagnostics["providers_attempted"][0]["provider"] if diagnostics["providers_attempted"] else provider
            diagnostics["selected_provider"] = provider
            diagnostics["fallback_used"] = provider != first_attempt
            return items, diagnostics

    return [], diagnostics


def _search_stac_items_for_provider(
    *,
    sensor: str,
    provider: str,
    api_url: str,
    collections: list[str],
    bbox: list[float],
    datetime_range: str,
    max_cloud: float,
    limit: int,
    coverage_bbox: list[float] | None = None,
    min_coverage_percent: float = 0.0,
    composite: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()

    # Keep the POST body intentionally conservative. Earth Search and other
    # STAC APIs do not all implement the same query/filter extensions. The
    # earlier version sent `query: {"eo:cloud_cover": {"lt": ...}}`, which can
    # return HTTP 400 on APIs that do not advertise/accept that extension. We
    # therefore search by collection/bbox/datetime and apply cloud filtering
    # client-side after normalising returned Items.
    body: dict[str, Any] = {
        "collections": collections,
        "bbox": [round(float(v), 6) for v in bbox],
        "datetime": _to_rfc3339_interval(datetime_range),
        "limit": max(int(limit), 1),
    }
    response = requests.post(f"{api_url.rstrip('/')}/search", json=body, timeout=settings.stac_timeout_seconds)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text[:800] if response.text else "No response body"
        raise RuntimeError(f"STAC /search failed with HTTP {response.status_code}: {detail}") from exc

    features = response.json().get("features", [])
    items = [normalise_stac_feature(feature, sensor, provider=provider, api_url=api_url) for feature in features]
    for item in items:
        coverage = bbox_coverage_percent(coverage_bbox, item.get("bbox")) if coverage_bbox else None
        item["coverage_percent"] = coverage
        item["coverage_method"] = "AOI bounding-box intersection"
    filtered = [
        item
        for item in items
        if (_cloud_value(item) is None or _cloud_value(item) <= max_cloud)
        and (item.get("coverage_percent") is None or float(item.get("coverage_percent") or 0) >= float(min_coverage_percent))
    ]
    if composite:
        renderable: list[dict[str, Any]] = []
        render_errors: list[str] = []
        for item in filtered:
            try:
                item["render_asset_resolution"] = resolve_render_assets(item, composite)
            except ValueError as exc:
                item["render_error"] = str(exc)
                render_errors.append(f"{item.get('item_id') or 'unknown item'}: {exc}")
                continue
            renderable.append(item)
        if filtered and not renderable:
            detail = "; ".join(render_errors[:3]) or f"missing assets for {normalise_composite(composite)}"
            raise RuntimeError(f"STAC /search returned {len(filtered)} cloud/coverage candidate(s), but none could render the requested composite: {detail}")
        return renderable
    return filtered


def _normalise_stac_asset_metadata(assets: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, asset in assets.items():
        if not isinstance(asset, dict) or not asset.get("href"):
            continue
        eo_bands = asset.get("eo:bands") or asset.get("bands") or []
        raster_bands = asset.get("raster:bands") or []
        metadata[key] = {
            "href": asset.get("href"),
            "type": asset.get("type"),
            "title": asset.get("title"),
            "description": asset.get("description"),
            "roles": list(asset.get("roles") or []),
            "eo_bands": eo_bands if isinstance(eo_bands, list) else [],
            "raster_bands": raster_bands if isinstance(raster_bands, list) else [],
        }
    return metadata


def normalise_stac_feature(
    feature: dict[str, Any],
    sensor: str,
    *,
    provider: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    props = feature.get("properties", {})
    assets = feature.get("assets", {}) or {}
    asset_links = {
        key: asset.get("href")
        for key, asset in assets.items()
        if isinstance(asset, dict) and asset.get("href")
    }
    cloud = props.get("eo:cloud_cover")
    if cloud is None:
        cloud = props.get("landsat:cloud_cover_land") or props.get("s2:cloud_shadow_percentage")
    return {
        "item_id": feature.get("id"),
        "collection": feature.get("collection"),
        "sensor_key": normalise_sensor(sensor),
        "sensor": SENSOR_LABELS.get(normalise_sensor(sensor), sensor),
        "datetime": props.get("datetime"),
        "cloud_cover": round(float(cloud), 2) if cloud is not None else None,
        "coverage_percent": None,
        "coverage_method": None,
        "geometry": feature.get("geometry"),
        "bbox": feature.get("bbox"),
        "assets": asset_links,
        "asset_metadata": _normalise_stac_asset_metadata(assets),
        "source": "stac",
        "stac_provider": _normalise_provider(provider) if provider else None,
        "stac_provider_label": STAC_PROVIDER_LABELS.get(_normalise_provider(provider), provider) if provider else None,
        "stac_api_url": api_url,
    }


def choose_scenes(candidates: list[dict[str, Any]], burn_window: dict[str, str]) -> dict[str, dict[str, Any]]:
    if not candidates:
        return {}
    burn_start = parse_iso_date(burn_window["start"])
    burn_end = parse_iso_date(burn_window["end"])
    event_target_ordinal = (burn_start.toordinal() + burn_end.toordinal()) / 2.0

    def item_date(item: dict[str, Any]) -> date | None:
        dt = item.get("datetime")
        if not dt:
            return None
        return parse_iso_date(str(dt))

    pre = [c for c in candidates if item_date(c) and item_date(c) < burn_start]
    post = [c for c in candidates if item_date(c) and item_date(c) > burn_end]
    event = [c for c in candidates if item_date(c) and burn_start <= item_date(c) <= burn_end]

    def cloud(c: dict[str, Any]) -> float:
        value = c.get("cloud_cover")
        return float(value) if value is not None else 100.0

    def coverage(c: dict[str, Any]) -> float:
        value = c.get("coverage_percent")
        return float(value) if value is not None else 100.0

    def pre_score(c: dict[str, Any]) -> float:
        d = item_date(c)
        temporal = abs((burn_start - d).days) if d else 999
        # Penalise low AOI coverage more strongly than modest cloud/temporal differences.
        return (100.0 - coverage(c)) * 1.4 + cloud(c) * 1.0 + temporal * 0.12

    def post_score(c: dict[str, Any]) -> float:
        d = item_date(c)
        temporal = abs((d - burn_end).days) if d else 999
        return (100.0 - coverage(c)) * 1.4 + cloud(c) * 1.0 + temporal * 0.12

    def event_score(c: dict[str, Any]) -> float:
        d = item_date(c)
        temporal = abs(d.toordinal() - event_target_ordinal) if d else 999
        return (100.0 - coverage(c)) * 1.4 + cloud(c) * 1.0 + temporal * 0.12

    selected: dict[str, dict[str, Any]] = {}
    if pre:
        selected["before"] = sorted(pre, key=pre_score)[0]
    if event:
        selected["during"] = sorted(event, key=event_score)[0]
    if post:
        selected["after"] = sorted(post, key=post_score)[0]
    return selected


def choose_pair(candidates: list[dict[str, Any]], burn_window: dict[str, str], *, prefer_event: bool = False) -> dict[str, Any] | None:
    scenes = choose_scenes(candidates, burn_window)
    before = scenes.get("before")
    comparison = scenes.get("during") if prefer_event and scenes.get("during") else scenes.get("after")
    if not before or not comparison:
        return None
    post_label = "event scene" if prefer_event and scenes.get("during") else "post-fire scene"
    return {
        "pre": before,
        "post": comparison,
        "selection_reason": f"Best-ranked pre-fire scene and {post_label}, prioritising AOI coverage, then cloud cover and temporal proximity.",
    }


def add_roles(candidates: list[dict[str, Any]], burn_window: dict[str, str]) -> list[dict[str, Any]]:
    burn_start = parse_iso_date(burn_window["start"])
    burn_end = parse_iso_date(burn_window["end"])
    out = []
    for c in candidates:
        role = "candidate"
        dt = c.get("datetime")
        if dt:
            d = parse_iso_date(str(dt))
            if d < burn_start:
                role = "pre-fire"
            elif d > burn_end:
                role = "post-fire"
            else:
                role = "during-window"
        out.append({**c, "role": role})
    return out
