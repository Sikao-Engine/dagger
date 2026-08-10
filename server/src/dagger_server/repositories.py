"""Repository layer: the only place ORM rows are created/queried.

Invariant (T5.2): any column ending in `_rel` stores a path **relative** to a
run/workspace root — never absolute. Callers compute relative paths via
`database.relpath_from(base, target)` and pass the resulting string in. The
`assert_no_absolute_paths` helper scans the DB and is exercised by
`test_repositories.py` so a regression can't slip in.

DB stores `run_id` + relative StateKey coordinates; the absolute resolution
happens only at the StateStore layer (kernel), never here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Artifact,
    Attempt,
    DagTemplate,
    Event,
    ExecutorCache,
    LedgerItem,
    Milestone,
    NodeRun,
    Plan,
    Project,
    Run,
    Shard,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── relative-path invariant guard ────────────────────────────────────────────

REL_COLUMNS: dict[str, tuple[str, ...]] = {
    "runs": ("state_root_rel",),
    "shards": ("workspace_path_rel",),
    "attempts": ("transcript_path_rel",),
    "artifacts": ("path_rel",),
}


def assert_no_absolute_paths(session: Session) -> list[str]:
    """Scan every `*_rel` column for absolute paths. Returns list of violations.

    A value is "absolute" if it starts with a drive letter (`X:\\` / `X:/`) on
    Windows or `/` on POSIX. Relative POSIX paths like `state/run_x/...` are fine.
    """
    violations: list[str] = []
    models = {"runs": Run, "shards": Shard, "attempts": Attempt, "artifacts": Artifact}
    for table, cols in REL_COLUMNS.items():
        model = models[table]
        for row in session.execute(select(model)).scalars():
            for col in cols:
                val = getattr(row, col, "") or ""
                if not val:
                    continue
                if _is_absolute(val):
                    violations.append(f"{table}.{row.id}.{col}={val!r}")
    return violations


def _is_absolute(val: str) -> bool:
    if len(val) >= 2 and val[1] == ":" and (val[2:3] in ("\\", "/") or len(val) == 2):
        return True
    return val.startswith("/")


# ── Templates / Executors cache ──────────────────────────────────────────────


def upsert_template(session: Session, tpl: DagTemplate) -> None:
    session.merge(tpl)


def list_templates(session: Session, domain_id: str | None = None) -> list[DagTemplate]:
    stmt = select(DagTemplate)
    if domain_id:
        stmt = stmt.where(DagTemplate.domain_id == domain_id)
    return list(session.execute(stmt).scalars())


def sync_executors_cache(session: Session, specs: list[dict[str, Any]]) -> None:
    session.query(ExecutorCache).delete()
    for spec in specs:
        session.add(ExecutorCache(key=spec["key"], spec=spec))


def list_executors(session: Session) -> list[ExecutorCache]:
    return list(session.execute(select(ExecutorCache)).scalars())


# ── Run / Shard / NodeRun / Attempt ──────────────────────────────────────────


def create_run(
    session: Session,
    *,
    run_id: str,
    domain_id: str,
    template_id: str,
    items: list[dict[str, Any]],
    state_root_rel: str,
    config: dict[str, Any] | None = None,
    base_ref: str = "",
) -> Run:
    run = Run(
        id=run_id,
        domain_id=domain_id,
        template_id=template_id,
        status="created",
        items=items,
        state_root_rel=state_root_rel,
        config=config or {},
        base_ref=base_ref,
    )
    session.add(run)
    return run


def get_run(session: Session, run_id: str) -> Run | None:
    return session.get(Run, run_id)


def list_runs(session: Session) -> list[Run]:
    return list(session.execute(select(Run).order_by(Run.created_at.desc())).scalars())


def set_run_status(
    session: Session,
    run_id: str,
    status: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    run = session.get(Run, run_id)
    if run is None:
        return
    run.status = status
    if started_at is not None:
        run.started_at = started_at
    if finished_at is not None:
        run.finished_at = finished_at


def create_shard(
    session: Session,
    *,
    shard_id: str,
    run_id: str,
    index_num: int,
    items: list[str],
    base_ref: str = "",
    workspace_path_rel: str = "",
) -> Shard:
    shard = Shard(
        id=shard_id,
        run_id=run_id,
        index_num=index_num,
        status="created",
        items=items,
        base_ref=base_ref,
        workspace_path_rel=workspace_path_rel,
    )
    session.add(shard)
    return shard


def list_shards(session: Session, run_id: str) -> list[Shard]:
    return list(
        session.execute(
            select(Shard).where(Shard.run_id == run_id).order_by(Shard.index_num)
        ).scalars()
    )


def get_shard(session: Session, shard_id: str) -> Shard | None:
    return session.execute(
        select(Shard).where(Shard.id == shard_id)
    ).scalar_one_or_none()


def upsert_node_run(session: Session, row: NodeRun) -> None:
    session.merge(row)


def list_node_runs(session: Session, run_id: str) -> list[NodeRun]:
    return list(
        session.execute(
            select(NodeRun)
            .where(NodeRun.run_id == run_id)
            .order_by(NodeRun.priority, NodeRun.id)
        ).scalars()
    )


def get_node_run(session: Session, node_run_id: str) -> NodeRun | None:
    return session.get(NodeRun, node_run_id)


def set_node_run_status(
    session: Session,
    node_run_id: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    retry_count: int | None = None,
) -> None:
    row = session.get(NodeRun, node_run_id)
    if row is None:
        return
    row.status = status
    if result is not None:
        row.result = result
    if error is not None:
        row.error = error
    if started_at is not None:
        row.started_at = started_at
    if finished_at is not None:
        row.finished_at = finished_at
    if retry_count is not None:
        row.retry_count = retry_count


def create_attempt(
    session: Session,
    *,
    attempt_id: str,
    node_run_id: str,
    attempt: int,
    backend: str = "mock",
    transcript_path_rel: str = "",
) -> Attempt:
    row = Attempt(
        id=attempt_id,
        node_run_id=node_run_id,
        attempt=attempt,
        status="running",
        backend=backend,
        transcript_path_rel=transcript_path_rel,
    )
    session.add(row)
    return row


def set_attempt_status(
    session: Session,
    attempt_id: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    finished_at: datetime | None = None,
) -> None:
    row = session.get(Attempt, attempt_id)
    if row is None:
        return
    row.status = status
    if result is not None:
        row.result = result
    if finished_at is not None:
        row.finished_at = finished_at


def list_attempts(session: Session, node_run_id: str) -> list[Attempt]:
    return list(
        session.execute(
            select(Attempt)
            .where(Attempt.node_run_id == node_run_id)
            .order_by(Attempt.attempt)
        ).scalars()
    )


def get_attempt(session: Session, attempt_id: str) -> Attempt | None:
    return session.get(Attempt, attempt_id)


# ── Ledger / Milestones / Plans / Projects ────────────────────────────────────


def get_or_create_project(
    session: Session, *, project_id: str, name: str = ""
) -> Project:
    proj = session.get(Project, project_id)
    if proj is not None:
        return proj
    proj = Project(id=project_id, name=name or project_id)
    session.add(proj)
    session.flush()
    return proj


def upsert_ledger_items(
    session: Session,
    *,
    project_id: str,
    items: list[dict[str, Any]],
    first_seen_run: str | None = None,
) -> int:
    """Insert new ledger items, update existing by (project_id, item_id).

    Each item dict has: id, seq, title, payload. Returns the count of rows touched.
    """
    touched = 0
    for it in items:
        existing = session.execute(
            select(LedgerItem).where(
                LedgerItem.project_id == project_id,
                LedgerItem.item_id == it["id"],
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                LedgerItem(
                    project_id=project_id,
                    item_id=it["id"],
                    seq=int(it.get("seq", 0)),
                    title=str(it.get("title", "")),
                    payload=dict(it.get("payload", {})),
                    status="unseen",
                    first_seen_run=first_seen_run,
                )
            )
        else:
            existing.seq = int(it.get("seq", existing.seq))
            existing.title = str(it.get("title", existing.title))
            existing.payload = dict(it.get("payload", existing.payload))
        touched += 1
    session.flush()
    return touched


def list_ledger_items(
    session: Session,
    *,
    project_id: str,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[LedgerItem]:
    stmt = (
        select(LedgerItem)
        .where(LedgerItem.project_id == project_id)
        .order_by(LedgerItem.seq)
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(LedgerItem.status == status)
    return list(session.execute(stmt).scalars())


def set_ledger_item_status(
    session: Session, *, item_db_id: int, status: str, resolved_run: str | None = None
) -> None:
    row = session.get(LedgerItem, item_db_id)
    if row is None:
        return
    row.status = status
    if resolved_run is not None:
        row.resolved_run = resolved_run


def upsert_milestones(
    session: Session, *, project_id: str, milestones: list[dict[str, Any]]
) -> int:
    # Replace-all semantics: wipe + reinsert (milestones are a small set).
    session.query(Milestone).filter(Milestone.project_id == project_id).delete()
    for m in milestones:
        session.add(
            Milestone(
                project_id=project_id,
                name=str(m.get("name", "")),
                boundary_item_id=m.get("boundary_item_id"),
                status=str(m.get("status", "open")),
            )
        )
    session.flush()
    return len(milestones)


def list_milestones(session: Session, *, project_id: str) -> list[Milestone]:
    return list(
        session.execute(
            select(Milestone).where(Milestone.project_id == project_id)
        ).scalars()
    )


def save_plan(
    session: Session,
    *,
    project_id: str,
    snapshot: dict[str, Any],
    suggestions: list[dict[str, Any]],
) -> Plan:
    plan = Plan(
        project_id=project_id,
        snapshot=snapshot,
        suggestions=suggestions,
        refreshed_at=_utcnow(),
    )
    session.add(plan)
    session.flush()
    return plan


def get_latest_plan(session: Session, *, project_id: str) -> Plan | None:
    return session.execute(
        select(Plan)
        .where(Plan.project_id == project_id)
        .order_by(Plan.refreshed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_events(
    session: Session, run_id: str | None = None, limit: int = 100
) -> list[Event]:
    stmt = select(Event).order_by(Event.created_at.desc(), Event.id.desc()).limit(limit)
    if run_id:
        stmt = stmt.where(Event.run_id == run_id)
    return list(session.execute(stmt).scalars())


__all__ = [
    "REL_COLUMNS",
    "assert_no_absolute_paths",
    "create_attempt",
    "create_run",
    "create_shard",
    "get_attempt",
    "get_latest_plan",
    "get_node_run",
    "get_or_create_project",
    "get_run",
    "get_shard",
    "list_attempts",
    "list_events",
    "list_executors",
    "list_ledger_items",
    "list_milestones",
    "list_node_runs",
    "list_runs",
    "list_shards",
    "list_templates",
    "save_plan",
    "set_attempt_status",
    "set_ledger_item_status",
    "set_node_run_status",
    "set_run_status",
    "sync_executors_cache",
    "upsert_ledger_items",
    "upsert_milestones",
    "upsert_node_run",
    "upsert_template",
]
