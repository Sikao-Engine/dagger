"""AgentBackend Protocol + unified AgentEvent.

This is the backend abstraction seam. The kernel never imports a backend — the
runtime config picks one. New backends (opencode-http, claude-code, …) implement
this Protocol and translate their native event stream into `AgentEvent`.

`AgentEvent.kind` is the normalized set the session_runner and the transcript
archiver care about: text | tool | reasoning | step | idle | error.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentEvent:
    """One normalized event from an Agent stream."""

    kind: str  # text | tool | reasoning | step | idle | error | progress
    text: str = ""
    tool: str = ""  # tool name when kind=tool
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.text:
            d["text"] = self.text
        if self.tool:
            d["tool"] = self.tool
        if self.payload:
            d["payload"] = dict(self.payload)
        if self.ts:
            d["ts"] = self.ts
        return d


@dataclass(frozen=True)
class AgentSession:
    """A handle to a live Agent session: endpoint + session id."""

    endpoint: Any
    session_id: str
    backend: str = ""
    started_at: str = ""


class AgentBackend(Protocol):
    """The backend SPI.

    `ensure_ready` is called once per workdir (may spawn a per-workdir process).
    `create_session` opens a fresh session for one prompt.
    `stream_events` yields the normalized event stream until the session ends.
    `reply_permission` is for tools requiring human approval (auto-approved in CI).
    `abort` cancels a session.
    `dispose` tears down the workdir-level resource (process / port).
    """

    backend: str

    async def ensure_ready(self, workdir: str) -> Any: ...  # pragma: no cover
    async def create_session(
        self, endpoint: Any, *, agent: str | None = None
    ) -> str: ...  # pragma: no cover
    async def send_prompt(
        self, endpoint: Any, session_id: str, prompt: str
    ) -> None: ...  # pragma: no cover
    def stream_events(
        self, endpoint: Any, session_id: str
    ) -> AsyncIterator[AgentEvent]: ...  # pragma: no cover
    async def reply_permission(
        self, endpoint: Any, permission_id: str, approve: bool
    ) -> None: ...  # pragma: no cover
    async def abort(self, endpoint: Any, session_id: str) -> None: ...  # pragma: no cover
    async def dispose(self, endpoint: Any) -> None: ...  # pragma: no cover


__all__ = ["AgentBackend", "AgentEvent", "AgentSession"]
