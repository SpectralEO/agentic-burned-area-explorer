from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class FindingType(str, Enum):
    primary = "primary_finding"
    supporting = "supporting_finding"
    contextual = "contextual_finding"
    validation = "validation_finding"
    caveat = "caveat"
    synthesis = "synthesis"


class ConfidenceMode(str, Enum):
    all = "all"
    high = "high"
    moderate_or_high = "moderate_or_high"


class Investigation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = "Greece wildfire investigation, 2025"
    aoi: str = "greece"
    year: int = 2025
    confidence_mode: ConfidenceMode = ConfidenceMode.all
    selected_cluster_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FindingCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    investigation_id: str
    type: FindingType
    title: str
    summary: str
    source_dataset: str
    geometry: dict[str, Any] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    pinned: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SuggestedAction(BaseModel):
    id: str
    label: str
    skill_id: str
    requires: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCallTrace(BaseModel):
    step_id: str
    tool: str
    status: Literal["ok", "skipped", "error"]
    message: str = ""
    output_preview: dict[str, Any] = Field(default_factory=dict)


class AgentRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    investigation_id: str
    user_message: str
    selected_skill_id: str | None = None
    answer: str
    trace: list[ToolCallTrace] = Field(default_factory=list)
    created_finding_ids: list[str] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    agent_mode: str = "rule_based"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateInvestigationRequest(BaseModel):
    title: str | None = None
    aoi: str = "greece"
    year: int = 2025


class AgentQueryRequest(BaseModel):
    investigation_id: str
    message: str


class AgentActionRequest(BaseModel):
    investigation_id: str
    action_id: str
    skill_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    answer: str
    selected_skill_id: str | None
    finding_cards: list[FindingCard] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    trace: list[ToolCallTrace] = Field(default_factory=list)
    agent_mode: str = "rule_based"


class SelectClusterRequest(BaseModel):
    cluster_id: str


class PinFindingRequest(BaseModel):
    pinned: bool


class ImagerySelectionRequest(BaseModel):
    role: Literal["pre", "post", "before", "during", "after"]
    candidate_index: int



class ReportGenerateRequest(BaseModel):
    investigation_id: str
    include_unpinned: bool = False
