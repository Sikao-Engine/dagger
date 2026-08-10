"""SQLAlchemy ORM models for DivDag (domain-agnostic core tables).

Schema follows `doc/design/universal_base_architecture.md` §12. Domain-private
data goes in JSON columns or domain-prefixed tables; core tables carry NO
domain-specific columns.

Path invariant (T5.2): every column that holds a filesystem location is named
`*_rel` and stores a path **relative** to a run/workspace root — never absolute.
The repository layer enforces this and `test_repositories.py` asserts it.
Absolute paths would couple the DB to a machine and break archive relocation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all DivDag ORM tables."""


# ── Project / Workspace ──────────────────────────────────────────────────────


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="project", cascade="all, delete"
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # root_path is the workspace root; stored absolute is acceptable here since a
    # workspace is machine-bound by nature (it points at a checkout). Run/shard
    # *state* paths are the ones that must be relative.
    root_path: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    project: Mapped[Project] = relationship(back_populates="workspaces")
    runs: Mapped[list[Run]] = relationship(
        back_populates="workspace", cascade="all, delete"
    )


# ── Run / Shard / NodeRun / Attempt ──────────────────────────────────────────


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    template_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created")
    lifecycle: Mapped[str] = mapped_column(String(32), default="single")
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    cursor_start: Mapped[str] = mapped_column(String(128), default="")
    cursor_end: Mapped[str] = mapped_column(String(128), default="")
    base_ref: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    role: Mapped[str] = mapped_column(String(32), default="single")
    instance_id: Mapped[str | None] = mapped_column(String(64))
    candidate_id: Mapped[str | None] = mapped_column(String(64))
    # state_root_rel: relative to the configured data_dir. Never absolute.
    state_root_rel: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    workspace: Mapped[Workspace | None] = relationship(back_populates="runs")
    shards: Mapped[list[Shard]] = relationship(
        back_populates="run", cascade="all, delete"
    )
    node_runs: Mapped[list[NodeRun]] = relationship(
        back_populates="run", cascade="all, delete"
    )
    events: Mapped[list[Event]] = relationship(
        back_populates="run", cascade="all, delete"
    )


class Shard(Base):
    __tablename__ = "shards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    index_num: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="created")
    items: Mapped[list[str]] = mapped_column(JSON, default=list)
    base_ref: Mapped[str] = mapped_column(Text, default="")
    # workspace_path_rel: relative to workspaces_dir. Never absolute.
    workspace_path_rel: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="shards")
    node_runs: Mapped[list[NodeRun]] = relationship(
        back_populates="shard", cascade="all, delete"
    )

    __table_args__ = (Index("ix_shards_run_id", "run_id"),)


class NodeRun(Base):
    __tablename__ = "node_runs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    shard_id: Mapped[str | None] = mapped_column(ForeignKey("shards.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type: Mapped[str] = mapped_column(String(128), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    run: Mapped[Run] = relationship(back_populates="node_runs")
    shard: Mapped[Shard | None] = relationship(back_populates="node_runs")
    attempts: Mapped[list[Attempt]] = relationship(
        back_populates="node_run", cascade="all, delete"
    )

    __table_args__ = (
        Index("ix_node_runs_run_id", "run_id"),
        Index("ix_node_runs_shard_id", "shard_id"),
        Index("ix_node_runs_status", "status"),
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_run_id: Mapped[str] = mapped_column(ForeignKey("node_runs.id"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running")
    runner: Mapped[str] = mapped_column(String(32), default="engine")
    backend: Mapped[str] = mapped_column(String(32), default="mock")
    session_id: Mapped[str | None] = mapped_column(String(128))
    prompt: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # transcript_path_rel: relative to the run state root. Never absolute.
    transcript_path_rel: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    node_run: Mapped[NodeRun] = relationship(back_populates="attempts")

    __table_args__ = (Index("ix_attempts_node_run_id", "node_run_id"),)


# ── Ledger / Milestones / Plans ──────────────────────────────────────────────


class LedgerItem(Base):
    __tablename__ = "ledger_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="unseen")
    first_seen_run: Mapped[str | None] = mapped_column(String(64))
    resolved_run: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_ledger_project_seq", "project_id", "seq"),
        Index("ix_ledger_item_id", "item_id"),
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    boundary_item_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Review / Artifacts ───────────────────────────────────────────────────────


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    shard_id: Mapped[str | None] = mapped_column(String(64))
    item_id: Mapped[str | None] = mapped_column(String(128))
    slot: Mapped[str] = mapped_column(String(64), default="")
    # path_rel: relative to the run state root. Never absolute.
    path_rel: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (Index("ix_artifacts_run_id", "run_id"),)


class ReviewState(Base):
    __tablename__ = "review_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    reviewer: Mapped[str] = mapped_column(String(128), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (Index("ix_review_run_item", "run_id", "item_id", unique=True),)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    item_id: Mapped[str | None] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    locator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(64), default="scanner")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    item_id: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32), default="auto")
    severity: Mapped[str] = mapped_column(String(32), default="info")
    status: Mapped[str] = mapped_column(String(32), default="open")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(32), default="item")
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    author: Mapped[str] = mapped_column(String(128), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Orchestration surroundings ───────────────────────────────────────────────


class DagTemplate(Base):
    __tablename__ = "dag_templates"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    edges: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (Index("ix_templates_domain", "domain_id"),)


class ExecutorCache(Base):
    __tablename__ = "executors_cache"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=0)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    selectors: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="offline")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), default="")
    entity_id: Mapped[str | None] = mapped_column(String(128))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    run: Mapped[Run | None] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_events_run_id", "run_id"),
        Index("ix_events_type_created", "type", "created_at"),
    )


__all__ = [
    "AgentRow",
    "Annotation",
    "Artifact",
    "Attempt",
    "Base",
    "DagTemplate",
    "Event",
    "ExecutorCache",
    "Finding",
    "Highlight",
    "LedgerItem",
    "Milestone",
    "NodeRun",
    "Plan",
    "Project",
    "ReviewState",
    "Run",
    "Shard",
    "Workspace",
]
