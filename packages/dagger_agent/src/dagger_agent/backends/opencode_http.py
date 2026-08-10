"""dagger_agent.backends.opencode_http — real AgentBackend over agentcli serve.

Sits on the vendored `opencode.AgentCLIAsyncClient` + `process_manager`.
Each `ensure_ready` call spawns a fresh `agentcli serve` on an offset port
(unique per runner invocation, per CubeClaw's design), so concurrent nodes
never share a process. `dispose` tears it down.

The trust loop (`session_runner.SessionRunner`) NEVER trusts SSE idle for
success — it waits on the result contract file. This backend only translates
the live event stream into normalized `AgentEvent`s for the transcript +
live SSE.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from ..backend import AgentEvent
from ..opencode import (
    AgentCLIAsyncClient,
    EventType,
    ParsedEvent,
    parse_event,
)
from ..opencode.process_manager import AgentServerProcessManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpencodeEndpoint:
    """Handle returned by ensure_ready: enough to reach the process."""

    host: str
    port: int
    process_key: str  # unique per ensure_ready → one process per runner
    workdir: str


def _to_agent_event(parsed: ParsedEvent) -> AgentEvent | None:
    """Map a decoded SSE ParsedEvent to the normalized AgentEvent.

    Returns None for SKIP/RECONNECTED (caller drops them). idle is forwarded
    as kind="idle" but the session_runner does NOT treat it as success.
    """
    t = parsed.type
    if t in (EventType.SKIP, EventType.RECONNECTED):
        return None
    if t == EventType.TEXT:
        return AgentEvent(kind="text", text=parsed.text or parsed.delta, payload=dict(parsed.raw))
    if t == EventType.TEXT_DELTA:
        return AgentEvent(kind="text", text=parsed.delta, payload=dict(parsed.raw))
    if t == EventType.REASONING:
        return AgentEvent(
            kind="reasoning", text=parsed.text or parsed.delta, payload=dict(parsed.raw)
        )
    if t == EventType.TOOL:
        return AgentEvent(
            kind="tool",
            tool=parsed.tool_name,
            payload={
                "status": parsed.tool_status,
                "title": parsed.tool_title,
                "call_id": parsed.tool_call_id,
                "input": parsed.tool_input,
                **({"raw": parsed.raw} if parsed.raw else {}),
            },
        )
    if t == EventType.PERMISSION:
        return AgentEvent(
            kind="tool",
            tool=parsed.tool_name or "permission",
            payload={
                "permission_id": parsed.permission_id,
                "status": parsed.tool_status,
                "raw": parsed.raw,
            },
        )
    if t == EventType.STEP_START:
        return AgentEvent(kind="step", text="start", payload=dict(parsed.raw))
    if t == EventType.STEP_FINISH:
        return AgentEvent(
            kind="step",
            text=parsed.text,
            payload={"finished": parsed.finished, "cost": parsed.cost, "tokens": parsed.tokens},
        )
    if t == EventType.SESSION_IDLE:
        return AgentEvent(kind="idle", payload=dict(parsed.raw))
    return AgentEvent(kind="error", text=f"unknown event: {t.value}", payload=dict(parsed.raw))


class OpencodeHttpBackend:
    """AgentBackend over a real agentcli serve process.

    One process per ensure_ready (offset port, managed by
    AgentServerProcessManager). Translates the opencode SSE stream into
    normalized AgentEvent.
    """

    backend = "opencode-http"

    def __init__(
        self,
        *,
        process_manager: AgentServerProcessManager,
        host: str = "127.0.0.1",
    ) -> None:
        self._mgr = process_manager
        self._host = host

    async def ensure_ready(self, workdir: str) -> OpencodeEndpoint:
        key = f"dagger-{uuid4().hex[:12]}"
        ok, proc, msg = await self._mgr.ensure_running_unique_async(workdir, key)
        if not ok:
            raise RuntimeError(f"agentcli serve failed to start: {msg}")
        return OpencodeEndpoint(host=self._host, port=proc.port, process_key=key, workdir=workdir)

    async def create_session(self, endpoint: OpencodeEndpoint, *, agent: str | None = None) -> str:
        del agent  # opencode picks the default agent; per-call agent not wired yet
        async with AgentCLIAsyncClient(host=endpoint.host, port=endpoint.port) as c:
            sess = await c.create_session(title=f"Dagger-{endpoint.process_key}")
            return sess.id

    async def send_prompt(self, endpoint: OpencodeEndpoint, session_id: str, prompt: str) -> None:
        async with AgentCLIAsyncClient(host=endpoint.host, port=endpoint.port) as c:
            ok = await c.send_prompt_async(session_id, prompt)
            if not ok:
                raise RuntimeError("prompt_async returned non-204")

    def stream_events(
        self, endpoint: OpencodeEndpoint, session_id: str
    ) -> AsyncIterator[AgentEvent]:
        return self._stream(endpoint, session_id)

    async def _stream(
        self, endpoint: OpencodeEndpoint, session_id: str
    ) -> AsyncIterator[AgentEvent]:
        client = AgentCLIAsyncClient(host=endpoint.host, port=endpoint.port)
        try:
            async for raw in client.stream_events_robust(session_id):
                parsed = parse_event(raw, session_id)
                ev = _to_agent_event(parsed)
                if ev is not None:
                    yield ev
        finally:
            await client.close()

    async def reply_permission(
        self, endpoint: OpencodeEndpoint, permission_id: str, approve: bool
    ) -> None:
        async with AgentCLIAsyncClient(host=endpoint.host, port=endpoint.port) as c:
            await c.respond_permission("", permission_id, "always" if approve else "reject")

    async def abort(self, endpoint: OpencodeEndpoint, session_id: str) -> None:
        async with AgentCLIAsyncClient(host=endpoint.host, port=endpoint.port) as c:
            await c.abort_session(session_id)

    async def dispose(self, endpoint: OpencodeEndpoint) -> None:
        await self._mgr.stop_async(endpoint.process_key)


__all__ = ["OpencodeEndpoint", "OpencodeHttpBackend"]
