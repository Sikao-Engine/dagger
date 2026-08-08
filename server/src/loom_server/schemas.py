"""Pydantic DTOs for the REST surface.

These are the wire contract: request bodies + response models. Kept separate
from ORM models so the DB schema can evolve without breaking clients, and so
`GET` responses never leak ORM internals (e.g. lazy-loaded relationships).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Domains / Executors / Templates ──────────────────────────────────────────


class DomainOut(_Base):
    id: str
    label: str
    version: str
    executors: list[dict[str, Any]] = Field(default_factory=list)
    templates: list[str] = Field(default_factory=list)
    web_manifest: dict[str, Any] = Field(default_factory=dict)
    artifact_spec: dict[str, Any] | None = None


class ExecutorOut(_Base):
    key: str
    label: str
    handler_kind: str
    scope: str
    skill: str | None = None
    selectors: dict[str, Any] = Field(default_factory=dict)


class TemplateOut(_Base):
    id: str
    domain_id: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    version: int = 1
    is_default: bool = False
    fingerprint: str = ""


# ── Run lifecycle ────────────────────────────────────────────────────────────


class RunCreate(BaseModel):
    """POST /api/v1/runs body."""

    domain_id: str
    template_id: str | None = None
    items_dir: str = ""
    shards: int = 3
    backend: str = "mock"
    base_ref: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class RunOut(_Base):
    id: str
    domain_id: str
    template_id: str
    status: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    state_root_rel: str = ""
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class NodeRunOut(_Base):
    id: str
    run_id: str
    node_key: str
    node_type: str
    status: str
    priority: int = 100
    dependencies: list[str] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    shard_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AttemptOut(_Base):
    id: str
    node_run_id: str
    attempt: int
    status: str
    backend: str = "mock"
    transcript_path_rel: str = ""
    result: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ShardOut(_Base):
    id: str
    run_id: str
    index_num: int
    status: str
    items: list[str] = Field(default_factory=list)
    base_ref: str = ""


class PipelineNode(BaseModel):
    """One node in the pipeline view (graph + status)."""

    id: str
    node_key: str
    node_type: str
    scope: str
    status: str
    shard_id: str | None = None
    shard_index: int | None = None
    dependencies: list[str] = Field(default_factory=list)
    priority: int = 100


class PipelineOut(BaseModel):
    run_id: str
    template_id: str
    status: str
    shards: list[ShardOut] = Field(default_factory=list)
    nodes: list[PipelineNode] = Field(default_factory=list)
    completed: int = 0
    failed: int = 0
    skipped: int = 0


class RunResult(BaseModel):
    """Summary returned after schedule+run."""

    run_id: str
    status: str
    completed: int
    failed: int
    skipped: int
    state_root_rel: str


# ── State read ───────────────────────────────────────────────────────────────


class StateIndexEntry(BaseModel):
    kind: str
    path: str
    layer: str
    scope: str
    node_run_id: str = ""
    shard_id: str = ""
    item_id: str = ""
    attempt: int = 0
    slot: str = ""
    size: int = 0
    sha256: str = ""
    written_at: str = ""


class StateObjectOut(BaseModel):
    key: dict[str, Any]
    kind: str
    path_rel: str
    body: dict[str, Any] | None = None


# ── Artifacts / Review (T7.1) ──────────────────────────────────────────────


class ArtifactSlotOut(BaseModel):
    name: str
    label: str
    view: str
    description: str = ""
    optional: bool = False


class ArtifactSpecOut(BaseModel):
    slots: list[ArtifactSlotOut] = Field(default_factory=list)
    default_view: str = "tabs"
    label: str = ""


class ArtifactRefOut(BaseModel):
    key: dict[str, Any]
    kind: str
    path: str
    sha256: str
    size: int
    written_at: str = ""


class ItemArtifactSlotOut(BaseModel):
    """One slot in the item-artifacts view: declared spec + the actual ref."""

    slot: ArtifactSlotOut
    ref: ArtifactRefOut | None = None
    undeclared: bool = False


class ItemArtifactsOut(BaseModel):
    """GET /api/v1/runs/{run_id}/items/{item_id}/artifacts response."""

    run_id: str
    item_id: str
    spec: ArtifactSpecOut | None = None
    slots: list[ItemArtifactSlotOut] = Field(default_factory=list)


class EventOut(_Base):
    id: int
    type: str
    entity_type: str
    entity_id: str | None = None
    run_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ErrorOut(BaseModel):
    detail: str
    code: str = "error"


# ── Ledger / Milestones / Plans ──────────────────────────────────────────────


class LedgerItemOut(_Base):
    id: int
    project_id: str
    item_id: str
    seq: int
    title: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "unseen"
    first_seen_run: str | None = None
    resolved_run: str | None = None


class LedgerRefreshResult(BaseModel):
    project_id: str
    domain_id: str
    items_upserted: int
    milestones_upserted: int


class MilestoneOut(_Base):
    id: int
    project_id: str
    name: str
    boundary_item_id: str | None = None
    status: str = "open"


class PlanOut(BaseModel):
    project_id: str
    snapshot: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    refreshed_at: datetime


class PlanSnapshot(BaseModel):
    """GET /projects/{id}/plan body: ledger progress + milestones + suggestions."""

    project_id: str
    total_items: int
    by_status: dict[str, int] = Field(default_factory=dict)
    milestones: list[MilestoneOut] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    latest_plan: PlanOut | None = None


# ── Agent processes (agentcli serve) ────────────────────────────────────────


class ManagedProcessOut(BaseModel):
    path: str
    port: int
    pid: int | None = None
    status: str
    session_id: str | None = None
    started_at: str | None = None
    last_error: str | None = None
    key: str | None = None


__all__ = [
    "ArtifactRefOut",
    "ArtifactSlotOut",
    "ArtifactSpecOut",
    "AttemptOut",
    "DomainOut",
    "ErrorOut",
    "EventOut",
    "ExecutorOut",
    "ItemArtifactSlotOut",
    "ItemArtifactsOut",
    "LedgerItemOut",
    "LedgerRefreshResult",
    "ManagedProcessOut",
    "MilestoneOut",
    "NodeRunOut",
    "PipelineNode",
    "PipelineOut",
    "PlanOut",
    "PlanSnapshot",
    "RunCreate",
    "RunOut",
    "RunResult",
    "ShardOut",
    "StateIndexEntry",
    "StateObjectOut",
    "TemplateOut",
]
