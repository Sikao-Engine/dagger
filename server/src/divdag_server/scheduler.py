"""Scheduler: drives a run to completion by reusing the kernel's `run_graph`.

Design doc §13 risk "双份就绪逻辑": the server does NOT re-implement readiness
calculation. It wraps `run_graph` (the M2 engine) as its unit-of-work primitive,
and layers DB persistence + event emission on top via `EngineHooks` + a custom
`AgentDispatcher`. Crash recovery: the engine already checkpoints to StateStore;
a later `--resume` re-runs `run_graph` which idempotently-skips completed nodes.

The dispatcher is sync (matching the engine's `AgentDispatcher` protocol). For
the mock backend it writes a success result directly; real backends
(SessionRunner + opencode-http) swap in behind the same boundary in a later phase.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from divdag_agent import OpencodeHttpBackend, SessionRunner
from divdag_agent.taskcard import TaskCard
from divdag_kernel.dag.instantiator import NodeRun, NodeRunGraph, ShardPlan, instantiate
from divdag_kernel.engine import EngineHooks, EngineRun, run_graph
from divdag_kernel.planning import fixed_size
from divdag_kernel.planning.item import ItemLedgerSnapshot
from divdag_kernel.state import K, StateStore
from sqlalchemy.orm import Session

from .database import relpath_from
from .domain_runtime import DomainRuntime, configure_domain
from .events import (
    EventBus,
    make_node_failed,
    make_node_started,
    make_node_succeeded,
    make_run_completed,
    make_run_started,
)
from .repositories import (
    create_attempt,
    create_run,
    create_shard,
    set_attempt_status,
    set_node_run_status,
    set_run_status,
    upsert_node_run,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ScheduleRequest:
    """The parsed POST /runs body + resolved paths."""

    run_id: str
    domain_id: str
    template_id: str
    items_dir: str
    shards_hint: int
    backend: str
    base_ref: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleOutcome:
    run_id: str
    status: str
    completed: int
    failed: int
    skipped: int
    state_root_rel: str
    graph: NodeRunGraph
    engine_run: EngineRun


class Scheduler:
    """Wraps run_graph with DB persistence + event emission.

    One instance per process; `schedule_and_run` is the entry point. The DB
    session is supplied per call (so the caller controls transaction scope).
    """

    def __init__(
        self,
        *,
        runtime: DomainRuntime,
        data_dir: Path,
        bus: EventBus,
        process_manager: Any = None,
    ) -> None:
        self.runtime = runtime
        self.data_dir = Path(data_dir)
        self.bus = bus
        self.process_manager = process_manager

    def schedule_and_run(
        self, req: ScheduleRequest, session: Session
    ) -> ScheduleOutcome:
        """Plan → persist → run → persist results. Returns the outcome."""
        reg = self.runtime.get(req.domain_id)

        # Pass runtime params to the domain (e.g. tiny's source_dir).
        if req.items_dir:
            configure_domain(self.runtime, req.domain_id, source_dir=req.items_dir)

        # Build the item ledger (tiny is sync-scan; the SPI is async so we bridge).
        src = reg.plugin.item_source()
        snap = _refresh_sync(src, req.items_dir)
        items = snap.items
        if not items:
            raise ValueError(f"no items found in {req.items_dir!r}")

        # Shard plan.
        size = max(1, len(items) // max(1, req.shards_hint) or 1)
        plans = fixed_size(items, snap.milestones, {"size": size})
        if not plans:
            plans = [
                ShardPlan(
                    shard_id="shard-000", index=0, items=tuple(i.id for i in items)
                )
            ]

        # StateStore — relative root so the DB stores a relative path.
        run_root = self.data_dir / req.run_id
        store = StateStore(run_root, run_id=req.run_id)
        state_root_rel = relpath_from(self.data_dir, store.state_root)

        # Persist Run + Shards.
        create_run(
            session,
            run_id=req.run_id,
            domain_id=req.domain_id,
            template_id=req.template_id,
            items=[_item_dict(i) for i in items],
            state_root_rel=state_root_rel,
            config=req.config,
            base_ref=req.base_ref,
        )
        for p in plans:
            create_shard(
                session,
                shard_id=p.shard_id,
                run_id=req.run_id,
                index_num=p.index,
                items=list(p.items),
                base_ref=p.base_ref,
            )

        # Instantiate the graph.
        tpl = self._resolve_template(reg, req.template_id)
        tpl.validate()
        graph = instantiate(
            template=tpl,
            run_id=req.run_id,
            shards=plans,
            node_registry=self.runtime.nodes,
        )
        # Persist initial NodeRun rows.
        for nid, nr in graph.nodes.items():
            upsert_node_run(session, _node_run_row(nid, nr, req.run_id))

        # Wire dispatcher + hooks. Hooks capture run_id + session so node events
        # are persisted alongside their NodeRun status updates.
        dispatcher = _PersistingDispatcher(
            store=store,
            bus=self.bus,
            session=session,
            run_id=req.run_id,
            data_dir=self.data_dir,
            reg=reg,
            backend=req.backend,
            process_manager=self.process_manager,
        )
        run_id = req.run_id
        bus = self.bus

        def _on_start(nid: str) -> None:
            set_node_run_status(session, nid, "running", started_at=_utcnow())
            bus.emit(lambda seq: make_node_started(seq, nid, run_id), session)

        def _on_success(nid: str, out: dict[str, Any]) -> None:
            set_node_run_status(
                session, nid, "success", result={"outputs": out}, finished_at=_utcnow()
            )
            bus.emit(lambda seq: make_node_succeeded(seq, nid, run_id, out), session)

        def _on_failure(nid: str, reason: str) -> None:
            set_node_run_status(
                session, nid, "failed", error={"reason": reason}, finished_at=_utcnow()
            )
            bus.emit(lambda seq: make_node_failed(seq, nid, run_id, reason), session)

        hooks = EngineHooks(
            on_node_start=_on_start,
            on_node_success=_on_success,
            on_node_failure=_on_failure,
        )

        set_run_status(session, req.run_id, "running", started_at=_utcnow())
        self.bus.emit(
            lambda seq: make_run_started(
                seq, req.run_id, req.domain_id, req.template_id
            ),
            session,
        )
        session.flush()

        engine_run = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=self.runtime.catalog,
            node_registry=self.runtime.nodes,
            agent_dispatcher=dispatcher,
            hooks=hooks,
        )
        store.save_index()

        status = "completed" if not engine_run.failed else "failed"
        set_run_status(session, req.run_id, status, finished_at=_utcnow())
        self.bus.emit(
            lambda seq: make_run_completed(
                seq,
                req.run_id,
                completed=len(engine_run.completed),
                failed=len(engine_run.failed),
                skipped=len(engine_run.skipped),
            ),
            session,
        )
        # The scheduler is the unit of work: commit its transaction so callers
        # don't need to (SQLAlchemy 2.0 `with Session()` does not auto-commit).
        session.commit()
        return ScheduleOutcome(
            run_id=req.run_id,
            status=status,
            completed=len(engine_run.completed),
            failed=len(engine_run.failed),
            skipped=len(engine_run.skipped),
            state_root_rel=state_root_rel,
            graph=graph,
            engine_run=engine_run,
        )

    # ── helpers ──

    def _resolve_template(self, reg: Any, template_id: str | None) -> Any:
        templates = reg.templates
        if template_id:
            for t in templates:
                if t.id == template_id:
                    return t
            raise ValueError(
                f"template {template_id!r} not found in domain {reg.plugin.id!r}"
            )
        if not templates:
            raise ValueError(f"domain {reg.plugin.id!r} declares no templates")
        return templates[0]


# ── dispatcher ───────────────────────────────────────────────────────────────


@dataclass
class _PersistingDispatcher:
    """AgentDispatcher: persists an Attempt row + writes the result contract.

    Two backend paths:
      - ``mock`` (default): synthesizes a success result per executor skill.
      - ``opencode-http``: drives the real SessionRunner (prompt → SSE → wait
        for the result file), which spawns a agentcli serve process per
        attempt. The Attempt row is persisted from the SessionOutcome.

    Both paths write the result contract via the StateStore so the engine
    reads it back to confirm success.
    """

    store: StateStore
    bus: EventBus
    session: Session
    run_id: str
    data_dir: Path
    reg: Any
    backend: str = "mock"
    process_manager: Any = None

    def __call__(
        self,
        *,
        node_run: NodeRun,
        ctx: Any,
        executor: Any,
        store: StateStore,
        attempt: int,
    ) -> dict[str, Any]:
        if self.backend == "opencode-http" and self.process_manager is not None:
            return self._run_opencode(node_run, executor, store, attempt)
        return self._run_mock(node_run, executor, store, attempt)

    def _run_mock(
        self, node_run: NodeRun, executor: Any, store: StateStore, attempt: int
    ) -> dict[str, Any]:
        outputs = _mock_outputs_for(executor)
        transcript_rel = relpath_from(
            self.data_dir, store.path(K.transcript(node_run.node_run_id, attempt))
        )
        attempt_id = f"{node_run.node_run_id}__a{attempt}"
        create_attempt(
            self.session,
            attempt_id=attempt_id,
            node_run_id=node_run.node_run_id,
            attempt=attempt,
            backend="mock",
            transcript_path_rel=transcript_rel,
        )
        store.write_json(
            K.result(node_run.node_run_id, attempt),
            {
                "status": "success",
                "success": True,
                "node_run_id": node_run.node_run_id,
                "node_type": node_run.node_type,
                "skill": executor.skill or "",
                "outputs": outputs,
            },
            kind="session_result",
            written_by={"role": "agent", "backend": "mock"},
        )
        # Mock also materializes one artifact per declared slot, so the T7.1
        # review endpoint returns real data on a mock run. Real backends write
        # their own artifacts; the dispatcher only seeds mock content here.
        self._seed_mock_artifacts(node_run, store)
        set_attempt_status(
            self.session,
            attempt_id,
            "success",
            result={"outputs": outputs},
            finished_at=_utcnow(),
        )
        return outputs

    def _seed_mock_artifacts(self, node_run: NodeRun, store: StateStore) -> None:
        """For each declared slot, write a mock per-item artifact if the node
        is item-scoped (shard work nodes carry item_ids in the DB Shard row)."""
        spec = getattr(self.reg, "artifact_spec", None)
        if spec is None:
            return
        items: list[str] = []
        if node_run.shard_id:
            from .repositories import get_shard

            shard = get_shard(self.session, node_run.shard_id)
            if shard is not None:
                items = list(shard.items)
        for slot in spec.slots:
            for item_id in items:
                content = (
                    f"# {item_id} — {slot.label}\n\n"
                    f"Mock {slot.view} artifact for slot `{slot.name}` "
                    f"(node {node_run.node_key}).\n"
                ).encode()
                store.write_bytes(
                    K.artifact_item(item_id, slot.name),
                    content,
                    kind="artifact",
                    written_by={
                        "role": "agent",
                        "backend": "mock",
                        "node_run_id": node_run.node_run_id,
                    },
                )

    def _run_opencode(
        self, node_run: NodeRun, executor: Any, store: StateStore, attempt: int
    ) -> dict[str, Any]:
        """Real path: SessionRunner + OpencodeHttpBackend (spawns agentcli serve)."""
        skill = getattr(executor, "skill", "") or ""
        skill_spec = _find_skill(self.reg, skill)
        declared_writes = skill_spec.produces if skill_spec else None
        success_key = (skill_spec.success_key if skill_spec else "success") or "success"
        attempt_id = f"{node_run.node_run_id}__a{attempt}"
        transcript_rel = relpath_from(
            self.data_dir, store.path(K.transcript(node_run.node_run_id, attempt))
        )
        create_attempt(
            self.session,
            attempt_id=attempt_id,
            node_run_id=node_run.node_run_id,
            attempt=attempt,
            backend="opencode-http",
            transcript_path_rel=transcript_rel,
        )
        self.session.flush()

        result_path = str(store.path(K.result(node_run.node_run_id, attempt)))
        card = TaskCard(
            node=node_run.node_key,
            shard=node_run.shard_id or "",
            attempt=attempt,
            write_targets={"result": result_path},
            success_criterion=f"{success_key}=true",
        )
        backend = OpencodeHttpBackend(process_manager=self.process_manager)
        runner = SessionRunner(
            backend=backend, store=store, max_retries=3, keepalive_interval_seconds=2
        )
        outcome = _run_session_sync(
            runner,
            node_run_id=node_run.node_run_id,
            node_type=node_run.node_type,
            skill=skill,
            declared_writes=declared_writes,
            task_card=card,
            workdir=str(store.state_root),
        )
        outputs = outcome.result.outputs if outcome.result else {}
        status = "success" if outcome.success else "failed"
        set_attempt_status(
            self.session,
            attempt_id,
            status,
            result={"outputs": outputs, "attempts": outcome.attempts},
            finished_at=_utcnow(),
        )
        if not outcome.success:
            # Write a failure result so the engine's failure hook fires.
            store.write_json(
                K.result(node_run.node_run_id, attempt),
                {
                    "status": "failed",
                    "success": False,
                    "node_run_id": node_run.node_run_id,
                    "node_type": node_run.node_type,
                    "skill": skill,
                    "error": outcome.error,
                },
                kind="session_result",
                written_by={"role": "agent", "backend": "opencode-http"},
            )
            return {}
        return outputs


def _run_session_sync(
    runner: SessionRunner,
    *,
    node_run_id: str,
    node_type: str,
    skill: str,
    declared_writes: tuple[str, ...] | None,
    task_card: TaskCard,
    workdir: str,
) -> Any:
    """Bridge async SessionRunner.run to a sync call (scheduler runs in a worker thread)."""

    async def _do() -> Any:
        return await runner.run(
            node_run_id=node_run_id,
            node_type=node_type,
            skill=skill,
            declared_writes=declared_writes,
            task_card=task_card,
            workdir=workdir,
        )

    return asyncio.run(_do())


def _find_skill(reg: Any, skill: str) -> Any:
    if not skill:
        return None
    try:
        for s in reg.plugin.skills():
            if s.skill_name == skill or s.key == skill:
                return s
    except Exception:  # noqa: BLE001, S110 - skill lookup must not break dispatch
        pass
    return None


def _mock_outputs_for(executor: Any) -> dict[str, Any]:
    """Synthesize success outputs for an agent executor (mock backend)."""
    skill = getattr(executor, "skill", "") or ""
    if "work" in skill:
        return {"work_ok": True}
    if "report" in skill:
        return {"report_ok": True}
    return {}


def _refresh_sync(src: Any, items_dir: str) -> ItemLedgerSnapshot:
    """Bridge an async ItemSource.refresh to a sync call (tiny is sync-scan)."""

    async def _do() -> ItemLedgerSnapshot:
        return await src.refresh(type("Ws", (), {"root": items_dir})())

    return asyncio.run(_do())


def _item_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "seq": item.seq,
        "title": item.title,
        "payload": dict(getattr(item, "payload", {})),
    }


def _node_run_row(nid: str, nr: NodeRun, run_id: str) -> Any:
    from .models import NodeRun as NodeRunRow

    return NodeRunRow(
        id=nid,
        run_id=run_id,
        shard_id=nr.shard_id,
        node_key=nr.node_key,
        node_type=nr.node_type,
        status="pending",
        priority=int(nr.params.get("_priority", 100)),
        dependencies=sorted(nr.dependencies),
        payload={k: v for k, v in nr.params.items() if not k.startswith("_")},
    )


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:8]}"


__all__ = [
    "ScheduleOutcome",
    "ScheduleRequest",
    "Scheduler",
    "new_run_id",
]
