from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


TemporalGranularity = Literal["day", "month", "year"]
TemporalDisplayMode = Literal["period", "cumulative"]
TemporalContextScope = Literal["selected-month", "selected-year", "loaded-range", "all-available"]


class BurnedAreaTemporalQuery(BaseModel):
    geography_type: Literal["country", "administrative_region", "selected_aoi", "selected_cluster"]
    geography_id: str | None = None
    geometry: dict[str, Any] | None = None
    granularity: TemporalGranularity
    cursor: date
    display_mode: TemporalDisplayMode = "period"
    cumulative_start: date | None = None
    context_scope: TemporalContextScope | None = None
    minimum_cp: float | None = Field(default=None, ge=0, le=1)
    minimum_lfp: float | None = Field(default=None, ge=0, le=1)
    minimum_bf: float | None = Field(default=None, ge=0, le=1)


class ResolvedTemporalWindow(BaseModel):
    active_start: date
    active_end: date
    context_start: date
    context_end: date
    granularity: TemporalGranularity
    display_mode: TemporalDisplayMode
    source_product: str
    derivation_method: str


class BurnedAreaMetrics(BaseModel):
    burned_area_occurrence_ha: float
    unique_burned_surface_ha: float
    cluster_count: int


class MapRasterLayer(BaseModel):
    type: Literal["raster"] = "raster"
    tiles: list[str] = Field(default_factory=list)
    bounds: list[float] = Field(default_factory=list)
    opacity: float


class BurnedAreaTimelineResponse(BaseModel):
    resolved_window: ResolvedTemporalWindow
    metrics: BurnedAreaMetrics
    layers: dict[Literal["active", "context"], MapRasterLayer]
    clusters: dict[str, Any]
    ui_context: dict[str, Any]
    provenance: dict[str, Any]
    caveats: list[str]


class DatasetStatusEntry(BaseModel):
    configured: bool
    discovered: bool | None = None
    downloaded: bool | None = None
    validated: bool | None = None
    processed: bool | None = None
    queryable: bool | None = None
    source_mode: str | None = None
    available_from: str | None = None
    available_to: str | None = None
    ingested_months: list[str] = Field(default_factory=list)
    missing_months: list[str] = Field(default_factory=list)
    last_synced: str | None = None
    last_sync: str | None = None
    months_cached: int | None = None
    version: str | None = None
    boundary_count: int | None = None
    path: str | None = None
    missing: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class AnalyticsDatasetStatus(BaseModel):
    ba300_monthly_v4: DatasetStatusEntry
    worldcover_2021: DatasetStatusEntry
    natura2000: DatasetStatusEntry
    ramsar: DatasetStatusEntry


class Ba300PeriodRequest(BaseModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}$")
    aoi_path: str = "app/data/aoi/greece.geojson"
    limit: int | None = Field(default=None, ge=1, le=120)


class Ba300DiscoverRequest(Ba300PeriodRequest):
    pass


class Ba300SyncRequest(Ba300PeriodRequest):
    source: Literal["auto", "stac-download", "sentinel-hub", "local"] | None = None
    force: bool = False
    dry_run: bool = False
    preprocess: bool = True


class Ba300PreprocessRequest(Ba300PeriodRequest):
    force: bool = False
    dry_run: bool = False


class Ba300ImportRequest(BaseModel):
    input_path: str
    aoi_path: str = "app/data/aoi/greece.geojson"
    force: bool = False
    dry_run: bool = False
    limit: int | None = Field(default=None, ge=1, le=120)


class Ba300OperationResponse(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)
    imported: list[dict[str, Any]] = Field(default_factory=list)
    status: str | None = None
    input: str | None = None
