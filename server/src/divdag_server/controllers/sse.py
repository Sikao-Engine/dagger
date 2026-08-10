"""SSE controllers (T5.6): global / run-level / attempt-level event streams.

  GET /api/v1/events/stream                  # global (all events)
  GET /api/v1/runs/{run_id}/events/stream    # run-filtered
  GET /api/v1/attempts/{attempt_id}/stream   # attempt Agent events (transcript tail)
  GET /api/v1/attempts/{attempt_id}/transcript  # raw transcript lines (JSON array)

Reconnect: clients send `Last-Event-ID` (a seq); the broker replays buffered
events with seq > last before going live. Backpressure: drop-oldest queue.
"""

from __future__ import annotations

from typing import Annotated, Any

from litestar import Controller, get
from litestar.datastructures import State
from litestar.exceptions import NotFoundException
from litestar.params import Parameter
from litestar.response import ServerSentEvent

from ..deps import AppDeps
from ..repositories import get_attempt, get_node_run, get_run


def _deps(state: State) -> AppDeps:
    return state.deps  # type: ignore[attr-defined]


def _parse_last_event_id(last_id: str | None) -> int:
    if not last_id:
        return 0
    try:
        return int(last_id)
    except ValueError:
        return 0


class SSEController(Controller):
    path = "/api/v1"
    tags = ["sse"]

    @get("/events/stream")
    async def stream_global(
        self,
        state: State,
        last_event_id: Annotated[
            str | None, Parameter(header="Last-Event-ID", required=False)
        ] = None,
        catch_up_only: Annotated[
            int, Parameter(query="catch_up_only", required=False)
        ] = 0,
    ) -> ServerSentEvent:
        deps = _deps(state)
        last_seq = _parse_last_event_id(last_event_id)
        return ServerSentEvent(
            deps.broker.stream(last_seq=last_seq, catch_up_only=bool(catch_up_only)),
            event_type="divdag",
        )

    @get("/runs/{run_id:str}/events/stream")
    async def stream_run(
        self,
        state: State,
        run_id: str,
        last_event_id: Annotated[
            str | None, Parameter(header="Last-Event-ID", required=False)
        ] = None,
        catch_up_only: Annotated[
            int, Parameter(query="catch_up_only", required=False)
        ] = 0,
    ) -> ServerSentEvent:
        deps = _deps(state)
        last_seq = _parse_last_event_id(last_event_id)
        return ServerSentEvent(
            deps.broker.stream(
                run_id=run_id, last_seq=last_seq, catch_up_only=bool(catch_up_only)
            ),
            event_type="divdag",
        )

    @get("/attempts/{attempt_id:str}/stream")
    async def stream_attempt(self, state: State, attempt_id: str) -> ServerSentEvent:
        deps = _deps(state)
        with deps.session_factory() as session:
            attempt = get_attempt(session, attempt_id)
            if attempt is None:
                raise NotFoundException(detail=f"attempt {attempt_id!r} not found")
            nr = get_node_run(session, attempt.node_run_id)
            if nr is None:
                raise NotFoundException(detail="node_run not found")
            run = get_run(session, nr.run_id)
            if run is None or not run.state_root_rel:
                raise NotFoundException(detail="run state not found")
            state_root_rel = run.state_root_rel
            node_run_id = attempt.node_run_id
            attempt_num = attempt.attempt
            is_running = attempt.status == "running"
            run_id = run.id
        store = deps.store_for(run_id, state_root_rel)
        return ServerSentEvent(
            deps.broker.stream_attempt(
                store=store,
                node_run_id=node_run_id,
                attempt=attempt_num,
                is_running=is_running,
            ),
            event_type="attempt",
        )

    @get("/attempts/{attempt_id:str}/transcript")
    async def get_transcript(
        self, state: State, attempt_id: str
    ) -> list[dict[str, Any]]:
        import json

        deps = _deps(state)
        with deps.session_factory() as session:
            attempt = get_attempt(session, attempt_id)
            if attempt is None:
                raise NotFoundException(detail=f"attempt {attempt_id!r} not found")
            nr = get_node_run(session, attempt.node_run_id)
            if nr is None:
                raise NotFoundException(detail="node_run not found")
            run = get_run(session, nr.run_id)
            if run is None or not run.state_root_rel:
                raise NotFoundException(detail="run state not found")
            run_id = run.id
            state_root_rel = run.state_root_rel
            attempt_num = attempt.attempt
            node_run_id = attempt.node_run_id
        from divdag_kernel.state import K

        store = deps.store_for(run_id, state_root_rel)
        path = store.path(K.transcript(node_run_id, attempt_num))
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"raw": line})
        return out


__all__ = ["SSEController"]
