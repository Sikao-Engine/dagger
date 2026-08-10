"""Controllers: domains, executors, templates, runs, nodes, state, sse, planning, agents.

REST surface (design doc §13, phase 1+2+3):
  GET    /api/v1/domains
  GET    /api/v1/executors
  GET    /api/v1/templates?domain=...
  POST   /api/v1/runs              # create + schedule + run synchronously
  GET    /api/v1/runs
  GET    /api/v1/runs/{run_id}
  GET    /api/v1/runs/{run_id}/pipeline
  GET    /api/v1/runs/{run_id}/events
  GET    /api/v1/nodes/{node_run_id}
  GET    /api/v1/nodes/{node_run_id}/attempts
  GET    /api/v1/runs/{run_id}/state
  GET    /api/v1/runs/{run_id}/state/object
  GET    /api/v1/runs/{run_id}/items/{item_id}/artifacts   # T7.1: per-item artifact slots
  GET    /api/v1/runs/{run_id}/items/{item_id}/artifacts/{slot}  # raw bytes for one slot
  # T5.6 SSE (phase 3)
  GET    /api/v1/events/stream
  GET    /api/v1/runs/{run_id}/events/stream
  GET    /api/v1/attempts/{attempt_id}/stream
  GET    /api/v1/attempts/{attempt_id}/transcript
  # Ledger / Planning (phase 3)
  GET    /api/v1/projects/{id}/ledger
  POST   /api/v1/projects/{id}/ledger/refresh
  GET    /api/v1/projects/{id}/plan
  # Agent processes (phase 3, for M6 UI)
  GET    /api/v1/agents/processes
  GET    /api/v1/agents/processes/status
  POST   /api/v1/agents/processes/{key}/stop
  POST   /api/v1/agents/processes/stop-all
"""

from __future__ import annotations

from typing import Annotated, Any

from litestar import Controller, get, post
from litestar.datastructures import State
from litestar.exceptions import NotFoundException
from litestar.params import Parameter
from litestar.response import Response

from ..deps import AppDeps
from ..schemas import (
    ArtifactRefOut,
    ArtifactSlotOut,
    ArtifactSpecOut,
    AttemptOut,
    DomainOut,
    EventOut,
    ExecutorOut,
    ItemArtifactSlotOut,
    ItemArtifactsOut,
    NodeRunOut,
    PipelineNode,
    PipelineOut,
    RunCreate,
    RunOut,
    RunResult,
    ShardOut,
    StateIndexEntry,
    StateObjectOut,
    TemplateOut,
)
from .agents import AgentsController
from .planning import PlanningController
from .sse import SSEController


def _deps(state: State) -> AppDeps:
    return state.deps  # type: ignore[attr-defined]


class CatalogController(Controller):
    path = "/api/v1"
    tags = ["catalog"]

    @get("/domains")
    async def list_domains(self, state: State) -> list[DomainOut]:
        deps = _deps(state)
        out: list[DomainOut] = []
        for reg in deps.runtime.all():
            manifest: dict[str, Any] = {}
            if hasattr(reg.plugin, "web_manifest"):
                try:
                    manifest = reg.plugin.web_manifest() or {}
                except Exception:  # noqa: BLE001 - manifest is best-effort
                    manifest = {}
            out.append(
                DomainOut(
                    id=reg.plugin.id,
                    label=reg.plugin.label,
                    version=reg.plugin.version,
                    executors=[e.to_dict() for e in reg.executors],
                    templates=[t.id for t in reg.templates],
                    web_manifest=manifest,
                    artifact_spec=reg.artifact_spec.to_dict()
                    if reg.artifact_spec
                    else None,
                )
            )
        return out

    @get("/executors")
    async def list_executors(self, state: State) -> list[ExecutorOut]:
        deps = _deps(state)
        return [
            ExecutorOut(
                key=e.key,
                label=e.label,
                handler_kind=e.handler_kind,
                scope=e.scope,
                skill=e.skill,
                selectors=dict(e.selectors),
            )
            for e in deps.runtime.catalog.all()
        ]

    @get("/templates")
    async def list_templates(
        self,
        state: State,
        domain: Annotated[str | None, Parameter(query="domain", required=False)] = None,
    ) -> list[TemplateOut]:
        deps = _deps(state)
        out: list[TemplateOut] = []
        for reg in deps.runtime.all():
            if domain and reg.plugin.id != domain:
                continue
            for t in reg.templates:
                out.append(
                    TemplateOut(
                        id=t.id,
                        domain_id=t.domain_id,
                        nodes=[n.to_dict() for n in t.nodes],
                        edges=[e.to_dict() for e in t.edges],
                        version=getattr(t, "version", 1),
                        is_default=getattr(t, "is_default", False),
                        fingerprint=getattr(t, "_topology_fingerprint", "") or "",
                    )
                )
        return out


class RunsController(Controller):
    path = "/api/v1"
    tags = ["runs"]

    @post("/runs", status_code=201)
    async def create_run(self, state: State, data: RunCreate) -> RunResult:
        """Create + schedule + run a domain template end-to-end (synchronous)."""
        import anyio

        from ..scheduler import ScheduleRequest, new_run_id

        deps = _deps(state)
        run_id = new_run_id()
        req = ScheduleRequest(
            run_id=run_id,
            domain_id=data.domain_id,
            template_id=data.template_id or "",
            items_dir=data.items_dir,
            shards_hint=data.shards,
            backend=data.backend,
            base_ref=data.base_ref,
            config=data.config,
        )

        def _run_in_thread() -> Any:
            with deps.session_factory() as session:
                return deps.scheduler.schedule_and_run(req, session)

        try:
            outcome = await anyio.to_thread.run_sync(_run_in_thread)
        except (ValueError, KeyError) as exc:
            raise NotFoundException(detail=str(exc)) from exc
        return RunResult(
            run_id=outcome.run_id,
            status=outcome.status,
            completed=outcome.completed,
            failed=outcome.failed,
            skipped=outcome.skipped,
            state_root_rel=outcome.state_root_rel,
        )

    @get("/runs")
    async def list_runs(self, state: State) -> list[RunOut]:
        from ..repositories import list_runs

        deps = _deps(state)
        with deps.session_factory() as session:
            return [RunOut.model_validate(r) for r in list_runs(session)]

    @get("/runs/{run_id:str}")
    async def get_run(self, state: State, run_id: str) -> RunOut:
        from ..repositories import get_run

        deps = _deps(state)
        with deps.session_factory() as session:
            run = get_run(session, run_id)
        if run is None:
            raise NotFoundException(detail=f"run {run_id!r} not found")
        return RunOut.model_validate(run)

    @get("/runs/{run_id:str}/pipeline")
    async def get_pipeline(self, state: State, run_id: str) -> PipelineOut:
        from ..repositories import get_run, list_node_runs, list_shards

        deps = _deps(state)
        with deps.session_factory() as session:
            run = get_run(session, run_id)
            if run is None:
                raise NotFoundException(detail=f"run {run_id!r} not found")
            shards = list_shards(session, run_id)
            nodes = list_node_runs(session, run_id)
        completed = sum(1 for n in nodes if n.status == "success")
        failed = sum(1 for n in nodes if n.status == "failed")
        skipped = sum(1 for n in nodes if n.status == "skipped")
        return PipelineOut(
            run_id=run_id,
            template_id=run.template_id,
            status=run.status,
            shards=[ShardOut.model_validate(s) for s in shards],
            nodes=[
                PipelineNode(
                    id=n.id,
                    node_key=n.node_key,
                    node_type=n.node_type,
                    scope=_scope_of(n),
                    status=n.status,
                    shard_id=n.shard_id,
                    shard_index=None,
                    dependencies=list(n.dependencies),
                    priority=n.priority,
                )
                for n in nodes
            ],
            completed=completed,
            failed=failed,
            skipped=skipped,
        )

    @get("/runs/{run_id:str}/events")
    async def get_events(self, state: State, run_id: str) -> list[EventOut]:
        from ..repositories import list_events

        deps = _deps(state)
        with deps.session_factory() as session:
            return [
                EventOut.model_validate(e) for e in list_events(session, run_id=run_id)
            ]


class NodesController(Controller):
    path = "/api/v1"
    tags = ["nodes"]

    @get("/nodes/{node_run_id:str}")
    async def get_node(self, state: State, node_run_id: str) -> NodeRunOut:
        from ..repositories import get_node_run

        deps = _deps(state)
        with deps.session_factory() as session:
            nr = get_node_run(session, node_run_id)
        if nr is None:
            raise NotFoundException(detail=f"node_run {node_run_id!r} not found")
        return NodeRunOut.model_validate(nr)

    @get("/nodes/{node_run_id:str}/attempts")
    async def list_attempts(self, state: State, node_run_id: str) -> list[AttemptOut]:
        from ..repositories import list_attempts

        deps = _deps(state)
        with deps.session_factory() as session:
            return [
                AttemptOut.model_validate(a)
                for a in list_attempts(session, node_run_id)
            ]


class StateController(Controller):
    path = "/api/v1"
    tags = ["state"]

    @get("/runs/{run_id:str}/state")
    async def get_state_index(self, state: State, run_id: str) -> list[StateIndexEntry]:
        from ..repositories import get_run

        deps = _deps(state)
        with deps.session_factory() as session:
            run = get_run(session, run_id)
        if run is None or not run.state_root_rel:
            raise NotFoundException(detail=f"run {run_id!r} has no state")
        store = deps.store_for(run_id, run.state_root_rel)
        return [
            StateIndexEntry(
                kind=e.kind,
                path=e.path,
                layer=e.layer,
                scope=e.scope,
                node_run_id=e.node_run_id,
                shard_id=e.shard_id,
                item_id=e.item_id,
                attempt=e.attempt,
                slot=e.slot,
                size=e.size,
                sha256=e.sha256,
                written_at=e.written_at,
            )
            for e in store.index
        ]

    @get("/runs/{run_id:str}/state/object")
    async def get_state_object(
        self,
        state: State,
        run_id: str,
        layer: Annotated[str, Parameter(query="layer")],
        node_run_id: Annotated[
            str | None, Parameter(query="node_run_id", required=False)
        ] = None,
        shard_id: Annotated[
            str | None, Parameter(query="shard_id", required=False)
        ] = None,
        attempt: Annotated[
            int | None, Parameter(query="attempt", required=False)
        ] = None,
        slot: Annotated[str | None, Parameter(query="slot", required=False)] = None,
    ) -> StateObjectOut:
        from ..repositories import get_run

        deps = _deps(state)
        with deps.session_factory() as session:
            run = get_run(session, run_id)
        if run is None or not run.state_root_rel:
            raise NotFoundException(detail=f"run {run_id!r} has no state")
        store = deps.store_for(run_id, run.state_root_rel)
        # Query the index for the matching entry (avoids reconstructing a StateKey
        # with an illegal combo — the index is the source of truth for what exists).
        matches = store.query(
            layer=layer, node_run_id=node_run_id, shard_id=shard_id, slot=slot
        )
        # Filter by attempt if given (query() doesn't take attempt).
        if attempt is not None:
            matches = [m for m in matches if (m.key.attempt or 0) == attempt]
        if not matches:
            raise NotFoundException(
                detail="no state object matches the given coordinates"
            )
        ref = matches[0]
        env = store.read_envelope(ref.key)
        body = store.read_json(ref.key)
        return StateObjectOut(
            key=ref.key.to_dict(),
            kind=env.kind if env else ref.kind,
            path_rel=ref.rel,
            body=body,
        )

    @get("/runs/{run_id:str}/items/{item_id:str}/artifacts")
    async def get_item_artifacts(
        self, state: State, run_id: str, item_id: str
    ) -> ItemArtifactsOut:
        """T7.1: per-item artifacts grouped by the domain's ArtifactSpec slots."""
        from divdag_kernel.state import group_refs_by_slot
        from divdag_kernel.state.artifact_spec import StateStoreArtifactStore

        from ..repositories import get_run

        deps = _deps(state)
        with deps.session_factory() as session:
            run = get_run(session, run_id)
        if run is None or not run.state_root_rel:
            raise NotFoundException(detail=f"run {run_id!r} has no state")
        store = deps.store_for(run_id, run.state_root_rel)
        spec = deps.runtime.get(run.domain_id).artifact_spec
        refs = StateStoreArtifactStore(store).item_artifacts(run_id, item_id)
        slots = group_refs_by_slot(refs, spec)
        return ItemArtifactsOut(
            run_id=run_id,
            item_id=item_id,
            spec=ArtifactSpecOut(**spec.to_dict()) if spec else None,
            slots=[
                ItemArtifactSlotOut(
                    slot=ArtifactSlotOut(**s["slot"]),
                    ref=ArtifactRefOut(**s["ref"]) if s.get("ref") else None,
                    undeclared=bool(s.get("undeclared")),
                )
                for s in slots
            ],
        )

    @get("/runs/{run_id:str}/items/{item_id:str}/artifacts/{slot:str}")
    async def get_item_artifact_bytes(
        self, state: State, run_id: str, item_id: str, slot: str
    ) -> Response:
        """Raw bytes of one item artifact slot. Content-Type is application/octet-stream.

        The front-end `EvidenceViewer` fetches the raw bytes and lets the slot's
        `view` decide how to render (code / prose / markdown / diff). The
        server never parses artifact content — it's opaque bytes from the
        kernel's perspective.
        """
        from divdag_kernel.state import StateStore
        from divdag_kernel.state.artifact_spec import StateStoreArtifactStore

        from ..repositories import get_run

        deps = _deps(state)
        with deps.session_factory() as session:
            run = get_run(session, run_id)
        if run is None or not run.state_root_rel:
            raise NotFoundException(detail=f"run {run_id!r} has no state")
        store: StateStore = deps.store_for(run_id, run.state_root_rel)
        adapter = StateStoreArtifactStore(store)
        for r in adapter.item_artifacts(run_id, item_id):
            if r.key.slot == slot:
                data = adapter.artifact_bytes(r)
                return Response(
                    content=data,
                    media_type="application/octet-stream",
                    headers={"X-DivDag-Slot": slot, "X-DivDag-Sha256": r.sha256},
                )
        raise NotFoundException(
            detail=f"no artifact for item {item_id!r} slot {slot!r} in run {run_id!r}"
        )


def _scope_of(node_run: Any) -> str:
    """Best-effort scope label for the pipeline view (DB doesn't store scope)."""
    if node_run.shard_id:
        return "shard"
    if node_run.node_key.endswith(".init") or node_run.priority == 0:
        return "run_entry"
    return "run"


__all__ = [
    "AgentsController",
    "CatalogController",
    "NodesController",
    "PlanningController",
    "RunsController",
    "SSEController",
    "StateController",
]
