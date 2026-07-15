from __future__ import annotations

from hashlib import sha1
from io import BytesIO
from math import atan, degrees, isfinite, pi, sinh
import json
import logging
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

logger = logging.getLogger("wildfire_finding_agent.tiler")

CACHE_DIR = Path(os.getenv("WEA_TILER_CACHE_DIR", "/tmp/wea-tiler-cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
(CACHE_DIR / "tiles").mkdir(exist_ok=True)
(CACHE_DIR / "renders").mkdir(exist_ok=True)
(CACHE_DIR / "stats").mkdir(exist_ok=True)
TILE_RENDERER_VERSION = "aoi-stretch-v3"
STRETCH_PERCENTILES = (2.0, 98.0)

app = FastAPI(
    title="Burned Area Explorer Custom Composite Tiler",
    description="Local tile service for rendering STAC COG assets into true-colour, false-colour, and SWIR/fire-front composites.",
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _transparent_band_tile(num_bands: int = 1, *, tile_size: int = 256) -> tuple[np.ndarray, np.ndarray]:
    return np.zeros((num_bands, tile_size, tile_size), dtype="float32"), np.zeros((tile_size, tile_size), dtype="uint8")



def _normalise_href(href: str) -> str:
    if href.startswith("s3://"):
        rest = href.removeprefix("s3://")
        bucket, _, key = rest.partition("/")
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return href



def _rio_imports():
    try:
        import rasterio
        from rio_tiler.io import COGReader
        return rasterio, COGReader
    except Exception as exc:  # pragma: no cover
        raise HTTPException(500, f"Tiler dependencies are not installed: {exc}") from exc



def _read_cog_tile(href: str, z: int, x: int, y: int, *, indexes: tuple[int, ...] = (1,), tile_size: int = 256) -> tuple[np.ndarray, np.ndarray]:
    rasterio, COGReader = _rio_imports()
    href = _normalise_href(href)
    try:
        with rasterio.Env(
            AWS_NO_SIGN_REQUEST="YES",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_HTTP_MULTIRANGE="YES",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff,.TIF,.TIFF,.jp2,.JP2,.jpg,.jpeg,.png",
        ):
            with COGReader(href) as cog:
                img = cog.tile(x, y, z, indexes=indexes, tilesize=tile_size)
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if "outside" in message and "bound" in message:
            return _transparent_band_tile(num_bands=len(indexes), tile_size=tile_size)
        logger.exception("Could not read tile from asset %s at z=%s x=%s y=%s", href, z, x, y)
        raise HTTPException(422, f"Could not read tile from asset {href}: {exc}") from exc

    data = np.asarray(img.data, dtype="float32")
    mask = np.asarray(img.mask, dtype="uint8") if getattr(img, "mask", None) is not None else np.full(data.shape[-2:], 255, dtype="uint8")
    return data, mask



def _stretch_range_from_array(arr: np.ndarray) -> tuple[float, float] | None:
    arr = np.asarray(arr, dtype="float32").copy()
    arr[~np.isfinite(arr)] = np.nan
    arr[arr <= 0] = np.nan
    valid = arr[np.isfinite(arr)]
    if valid.size < 16:
        return None
    lo, hi = np.nanpercentile(valid, STRETCH_PERCENTILES)
    if not isfinite(float(lo)) or not isfinite(float(hi)) or hi <= lo:
        lo, hi = float(np.nanmin(valid)), float(np.nanmax(valid))
    if hi <= lo:
        return None
    return float(lo), float(hi)


def _valid_range(lo: float | None, hi: float | None) -> tuple[float, float] | None:
    if lo is None or hi is None:
        return None
    lo_f = float(lo)
    hi_f = float(hi)
    if not isfinite(lo_f) or not isfinite(hi_f) or hi_f <= lo_f:
        return None
    return lo_f, hi_f


def _channel_ranges_from_query(
    r_min: float | None,
    r_max: float | None,
    g_min: float | None,
    g_max: float | None,
    b_min: float | None,
    b_max: float | None,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None, tuple[float, float] | None]:
    return (
        _valid_range(r_min, r_max),
        _valid_range(g_min, g_max),
        _valid_range(b_min, b_max),
    )


def _stretch(arr: np.ndarray, value_range: tuple[float, float] | None = None) -> np.ndarray:
    arr = np.asarray(arr, dtype="float32").copy()
    arr[~np.isfinite(arr)] = np.nan
    arr[arr <= 0] = np.nan
    selected_range = value_range or _stretch_range_from_array(arr)
    if selected_range is None:
        return np.zeros(arr.shape, dtype="uint8")
    lo, hi = selected_range
    out = np.clip((arr - lo) / (hi - lo), 0, 1)
    out = np.nan_to_num(out, nan=0.0)
    return (out * 255).astype("uint8")



def _rgb_from_single_visual(
    visual: str,
    z: int,
    x: int,
    y: int,
    *,
    ranges: tuple[tuple[float, float] | None, tuple[float, float] | None, tuple[float, float] | None] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    data, mask = _read_cog_tile(visual, z, x, y, indexes=(1, 2, 3))
    if data.shape[0] < 3:
        raise HTTPException(422, "Visual asset did not return at least three bands.")
    ranges = ranges or (None, None, None)
    rgb = np.stack([_stretch(data[i], ranges[i]) for i in range(3)], axis=0)
    alpha = mask.astype("uint8")
    if not np.any(alpha):
        signal = np.any(np.isfinite(data[:3]) & (np.abs(data[:3]) > 0), axis=0)
        if np.any(signal):
            alpha = signal.astype("uint8") * 255
    return rgb, alpha



def _rgb_from_three_assets(
    r: str,
    g: str,
    b: str,
    z: int,
    x: int,
    y: int,
    *,
    ranges: tuple[tuple[float, float] | None, tuple[float, float] | None, tuple[float, float] | None] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    channels: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    ranges = ranges or (None, None, None)
    for idx, href in enumerate([r, g, b]):
        data, mask = _read_cog_tile(href, z, x, y, indexes=(1,))
        channels.append(_stretch(data[0], ranges[idx]))
        masks.append(mask)
    alpha = np.minimum.reduce(masks).astype("uint8")
    return np.stack(channels[:3], axis=0), alpha



def _encode_png(rgb: np.ndarray, alpha: np.ndarray) -> bytes:
    rgb = np.transpose(rgb, (1, 2, 0)).astype("uint8")
    if alpha.shape != rgb.shape[:2]:
        alpha = np.full(rgb.shape[:2], 255, dtype="uint8")
    rgba = np.dstack([rgb, alpha]).astype("uint8")
    img = Image.fromarray(rgba, mode="RGBA")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()



def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(x) for x in value.split(",")]
    if len(parts) != 4:
        raise HTTPException(422, "bbox must contain four comma-separated coordinates.")
    return parts[0], parts[1], parts[2], parts[3]


def _tile_bounds_4326(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return WebMercator slippy-tile bounds in lon/lat."""
    n = 2.0 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = degrees(atan(sinh(pi * (1 - 2 * y / n))))
    south = degrees(atan(sinh(pi * (1 - 2 * (y + 1) / n))))
    return west, south, east, north


def _bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 <= bx1 or ax1 >= bx2 or ay2 <= by1 or ay1 >= by2)


def _alpha_mask_for_clip_bbox(
    *,
    z: int,
    x: int,
    y: int,
    clip_bbox: tuple[float, float, float, float],
    tile_size: int = 256,
) -> np.ndarray:
    """Return a 0/255 alpha mask for pixels inside a lon/lat clip bbox.

    This keeps the slippy-map tiler implementation, but prevents partially
    intersecting WebMercator tiles from painting imagery outside the AOI bbox.
    """
    west, south, east, north = _tile_bounds_4326(z, x, y)
    xs = np.linspace(west, east, tile_size, endpoint=False) + (east - west) / (2 * tile_size)
    ys = np.linspace(north, south, tile_size, endpoint=False) + (south - north) / (2 * tile_size)
    xx, yy = np.meshgrid(xs, ys)
    minx, miny, maxx, maxy = clip_bbox
    inside = (xx >= minx) & (xx <= maxx) & (yy >= miny) & (yy <= maxy)
    return inside.astype("uint8") * 255



def _window_for_bounds(src, bounds_4326: tuple[float, float, float, float] | None):
    if bounds_4326 is None:
        return None
    try:
        rasterio, _ = _rio_imports()
        from rasterio.warp import transform_bounds
        from rasterio.windows import Window, from_bounds

        if src.crs:
            bounds = transform_bounds("EPSG:4326", src.crs, *bounds_4326, densify_pts=21)
        else:
            bounds = bounds_4326
        window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        col_off = max(0, int(window.col_off))
        row_off = max(0, int(window.row_off))
        col_max = min(src.width, int(window.col_off + window.width))
        row_max = min(src.height, int(window.row_off + window.height))
        if col_max <= col_off or row_max <= row_off:
            return None
        return Window(col_off, row_off, col_max - col_off, row_max - row_off)
    except Exception:
        return None



def _target_shape(src, window, width: int) -> tuple[int, int]:
    width = max(320, min(int(width), 2000))
    if window is not None and window.width > 0:
        ratio = float(window.height) / float(window.width)
    else:
        ratio = float(src.height) / float(src.width)
    height = max(220, min(1400, int(width * ratio)))
    return height, width



def _read_single_asset_crop(href: str, *, bounds_4326: tuple[float, float, float, float] | None, width: int, indexes: list[int] | None = None) -> np.ndarray:
    rasterio, _ = _rio_imports()
    href = _normalise_href(href)
    try:
        with rasterio.Env(
            AWS_NO_SIGN_REQUEST="YES",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_HTTP_MULTIRANGE="YES",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff,.TIF,.TIFF,.jp2,.JP2,.jpg,.jpeg,.png",
        ):
            with rasterio.open(href) as src:
                window = _window_for_bounds(src, bounds_4326)
                if window is None:
                    raise HTTPException(422, "Requested bbox does not intersect the source asset.")
                h, w = _target_shape(src, window, width)
                if indexes is None:
                    indexes = list(range(1, min(src.count, 3) + 1))
                data = src.read(indexes=indexes, window=window, out_shape=(len(indexes), h, w), masked=True)
                return data.astype("float32").filled(float("nan"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Could not read preview window from asset {href}: {exc}") from exc



def _render_static_from_visual(visual: str, bbox: tuple[float, float, float, float], width: int) -> bytes:
    data = _read_single_asset_crop(visual, bounds_4326=bbox, width=width, indexes=[1, 2, 3])
    if data.shape[0] < 3:
        raise HTTPException(422, "Visual asset did not return at least three bands.")
    if np.nanmax(data) > 255 or data.dtype.kind == "f":
        rgb = np.stack([_stretch(data[i]) for i in range(3)], axis=0)
    else:
        rgb = np.clip(np.nan_to_num(data[:3], nan=0), 0, 255).astype("uint8")
    alpha = np.where(np.isfinite(data[0]), 255, 0).astype("uint8")
    return _encode_png(rgb, alpha)



def _render_static_from_three(r: str, g: str, b: str, bbox: tuple[float, float, float, float], width: int) -> tuple[np.ndarray, np.ndarray]:
    channels = []
    masks = []
    for href in [r, g, b]:
        arr = _read_single_asset_crop(href, bounds_4326=bbox, width=width, indexes=[1])[0]
        channels.append(_stretch(arr))
        masks.append(np.where(np.isfinite(arr), 255, 0).astype("uint8"))
    alpha = np.minimum.reduce(masks).astype("uint8")
    return np.stack(channels[:3], axis=0), alpha



def _stretch_ranges_from_visual(
    visual: str,
    bbox: tuple[float, float, float, float],
    width: int,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None, tuple[float, float] | None]:
    data = _read_single_asset_crop(visual, bounds_4326=bbox, width=width, indexes=[1, 2, 3])
    if data.shape[0] < 3:
        raise HTTPException(422, "Visual asset did not return at least three bands.")
    return tuple(_stretch_range_from_array(data[idx]) for idx in range(3))  # type: ignore[return-value]


def _stretch_ranges_from_three(
    r: str,
    g: str,
    b: str,
    bbox: tuple[float, float, float, float],
    width: int,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None, tuple[float, float] | None]:
    ranges: list[tuple[float, float] | None] = []
    for href in [r, g, b]:
        arr = _read_single_asset_crop(href, bounds_4326=bbox, width=width, indexes=[1])[0]
        ranges.append(_stretch_range_from_array(arr))
    return ranges[0], ranges[1], ranges[2]


def _channels_payload(
    ranges: tuple[tuple[float, float] | None, tuple[float, float] | None, tuple[float, float] | None],
) -> dict[str, dict[str, float]]:
    payload: dict[str, dict[str, float]] = {}
    for name, value_range in zip(("r", "g", "b"), ranges, strict=True):
        if value_range is None:
            continue
        lo, hi = value_range
        payload[name] = {"min": float(lo), "max": float(hi)}
    return payload


def _cache_key(prefix: str, payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha1(blob).hexdigest()



def _serve_cached_png(folder: str, key_payload: dict):
    key = _cache_key(folder, key_payload)
    path = CACHE_DIR / folder / f"{key}.png"
    if path.exists():
        return Response(path.read_bytes(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400", "X-Cache": "HIT"}), path
    return None, path



def _serve_cached_json(folder: str, key_payload: dict):
    key = _cache_key(folder, key_payload)
    path = CACHE_DIR / folder / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")), path
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring invalid cached JSON file %s", path)
    return None, path


def _write_png(path: Path, png: bytes) -> Response:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400", "X-Cache": "MISS"})


def _write_json(path: Path, payload: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return payload


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats.json")
def stretch_stats(
    bbox: str,
    width: int = 640,
    visual: str | None = None,
    r: str | None = None,
    g: str | None = None,
    b: str | None = None,
    blend_r: str | None = None,
    blend_g: str | None = None,
    blend_b: str | None = None,
    composite: str = "custom",
    sensor: str = "optical",
    item_id: str = "unknown",
    role: str = "candidate",
) -> dict:
    """Return AOI-wide percentile stretch ranges for coherent slippy-map tiles."""
    bbox_tuple = _parse_bbox(bbox)
    stats_width = max(320, min(int(width), 1200))
    cache_payload = {
        "renderer_version": TILE_RENDERER_VERSION,
        "bbox": bbox_tuple,
        "width": stats_width,
        "visual": visual,
        "r": r,
        "g": g,
        "b": b,
        "blend_r": blend_r,
        "blend_g": blend_g,
        "blend_b": blend_b,
        "composite": composite,
        "sensor": sensor,
        "item_id": item_id,
        "role": role,
    }
    cached, cache_path = _serve_cached_json("stats", cache_payload)
    if cached is not None:
        return cached

    if visual:
        ranges = _stretch_ranges_from_visual(visual, bbox_tuple, stats_width)
    elif r and g and b:
        ranges = _stretch_ranges_from_three(r, g, b, bbox_tuple, stats_width)
    else:
        raise HTTPException(422, "Provide either visual=<href> or r=<href>&g=<href>&b=<href>.")

    channels = _channels_payload(ranges)
    if not channels:
        raise HTTPException(422, "Could not calculate valid stretch ranges for the requested AOI.")

    payload: dict[str, object] = {
        "renderer_version": TILE_RENDERER_VERSION,
        "stretch_method": "aoi-percentile",
        "percentiles": list(STRETCH_PERCENTILES),
        "bbox": list(bbox_tuple),
        "width": stats_width,
        "channels": channels,
        "composite": composite,
        "sensor": sensor,
        "item_id": item_id,
        "role": role,
    }

    if blend_r and blend_g and blend_b:
        try:
            blend_ranges = _stretch_ranges_from_three(blend_r, blend_g, blend_b, bbox_tuple, stats_width)
            blend_channels = _channels_payload(blend_ranges)
            if blend_channels:
                payload["blend_channels"] = blend_channels
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not calculate blend stretch ranges for %s: %s", item_id, exc)
            payload["blend_error"] = str(exc)

    return _write_json(cache_path, payload)


@app.get("/tiles/{z}/{x}/{y}.png")
def composite_tile(
    z: int,
    x: int,
    y: int,
    visual: Annotated[str | None, Query(description="Single RGB/visual COG asset href")] = None,
    r: Annotated[str | None, Query(description="Red/display-R channel COG href")] = None,
    g: Annotated[str | None, Query(description="Green/display-G channel COG href")] = None,
    b: Annotated[str | None, Query(description="Blue/display-B channel COG href")] = None,
    blend_r: str | None = None,
    blend_g: str | None = None,
    blend_b: str | None = None,
    blend_weight: float = 0.33,
    clip_bbox: str | None = None,
    r_min: float | None = None,
    r_max: float | None = None,
    g_min: float | None = None,
    g_max: float | None = None,
    b_min: float | None = None,
    b_max: float | None = None,
    blend_r_min: float | None = None,
    blend_r_max: float | None = None,
    blend_g_min: float | None = None,
    blend_g_max: float | None = None,
    blend_b_min: float | None = None,
    blend_b_max: float | None = None,
    composite: str = "custom",
    sensor: str = "optical",
    item_id: str = "unknown",
    role: str = "candidate",
) -> Response:
    main_ranges = _channel_ranges_from_query(r_min, r_max, g_min, g_max, b_min, b_max)
    blend_ranges = _channel_ranges_from_query(blend_r_min, blend_r_max, blend_g_min, blend_g_max, blend_b_min, blend_b_max)
    cache_payload = {
        "renderer_version": TILE_RENDERER_VERSION,
        "z": z,
        "x": x,
        "y": y,
        "visual": visual,
        "r": r,
        "g": g,
        "b": b,
        "blend_r": blend_r,
        "blend_g": blend_g,
        "blend_b": blend_b,
        "blend_weight": blend_weight,
        "clip_bbox": clip_bbox,
        "main_ranges": main_ranges,
        "blend_ranges": blend_ranges,
        "composite": composite,
        "sensor": sensor,
        "item_id": item_id,
        "role": role,
    }
    cached, cache_path = _serve_cached_png("tiles", cache_payload)
    if cached is not None:
        return cached

    parsed_clip_bbox = _parse_bbox(clip_bbox) if clip_bbox else None
    if parsed_clip_bbox is not None:
        tile_bbox = _tile_bounds_4326(z, x, y)
        if not _bbox_intersects(tile_bbox, parsed_clip_bbox):
            return _write_png(cache_path, _encode_png(
                np.zeros((3, 256, 256), dtype="uint8"),
                np.zeros((256, 256), dtype="uint8"),
            ))

    if visual:
        rgb, alpha = _rgb_from_single_visual(visual, z, x, y, ranges=main_ranges)
    elif r and g and b:
        rgb, alpha = _rgb_from_three_assets(r, g, b, z, x, y, ranges=main_ranges)
    else:
        raise HTTPException(422, "Provide either visual=<href> or r=<href>&g=<href>&b=<href>.")

    if blend_r and blend_g and blend_b:
        try:
            blend_rgb, blend_alpha = _rgb_from_three_assets(blend_r, blend_g, blend_b, z, x, y, ranges=blend_ranges)
            w = max(0.0, min(1.0, float(blend_weight)))
            rgb = np.clip((1.0 - w) * rgb.astype("float32") + w * blend_rgb.astype("float32"), 0, 255).astype("uint8")
            alpha = np.minimum(alpha, blend_alpha)
        except Exception:
            pass

    if parsed_clip_bbox is not None:
        alpha = np.minimum(alpha, _alpha_mask_for_clip_bbox(z=z, x=x, y=y, clip_bbox=parsed_clip_bbox))

    return _write_png(cache_path, _encode_png(rgb, alpha))


@app.get("/render.png")
def render_preview(
    bbox: str,
    width: int = 900,
    visual: str | None = None,
    r: str | None = None,
    g: str | None = None,
    b: str | None = None,
    blend_r: str | None = None,
    blend_g: str | None = None,
    blend_b: str | None = None,
    blend_weight: float = 0.33,
    composite: str = "custom",
    sensor: str = "optical",
    item_id: str = "unknown",
    role: str = "candidate",
) -> Response:
    """Render one static AOI-bounded PNG for finding cards and reports.

    This endpoint receives an explicit bbox and width. It is not a slippy-map
    tile endpoint, so it must not use tile-coordinate logic.
    """
    bbox_tuple = _parse_bbox(bbox)
    cache_payload = {
        "bbox": bbox_tuple,
        "width": width,
        "visual": visual,
        "r": r,
        "g": g,
        "b": b,
        "blend_r": blend_r,
        "blend_g": blend_g,
        "blend_b": blend_b,
        "blend_weight": blend_weight,
        "composite": composite,
        "sensor": sensor,
        "item_id": item_id,
        "role": role,
    }
    cached, cache_path = _serve_cached_png("renders", cache_payload)
    if cached is not None:
        return cached

    if visual:
        png = _render_static_from_visual(visual, bbox_tuple, width)
        return _write_png(cache_path, png)
    if not (r and g and b):
        raise HTTPException(422, "Provide either visual=<href> or r=<href>&g=<href>&b=<href>.")

    rgb, alpha = _render_static_from_three(r, g, b, bbox_tuple, width)
    if blend_r and blend_g and blend_b:
        try:
            blend_rgb, blend_alpha = _render_static_from_three(blend_r, blend_g, blend_b, bbox_tuple, width)
            w = max(0.0, min(1.0, float(blend_weight)))
            rgb = np.clip((1.0 - w) * rgb.astype("float32") + w * blend_rgb.astype("float32"), 0, 255).astype("uint8")
            alpha = np.minimum(alpha, blend_alpha)
        except Exception:
            pass
    return _write_png(cache_path, _encode_png(rgb, alpha))
