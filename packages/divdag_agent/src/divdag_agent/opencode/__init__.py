"""divdag_agent.opencode — vendored agentcli (opencode) async HTTP + SSE client.

Adapted from CubeClaw's long-validated `cube.agentcli.client` +
`sse_parser`. The kernel never imports this; it sits behind the
`AgentBackend` Protocol (`backends/opencode_http.py`).

Two layers:
  - `client.AgentCLIAsyncClient`: HTTP CRUD + robust SSE stream with reconnect.
  - `sse_parser.parse_event`: decodes raw opencode SSE into a `ParsedEvent`.
"""

from __future__ import annotations

from .client import (
    AgentCLIAsyncClient,
    Message,
    MessagePart,
    MessagePartType,
    Session,
    SSEEvent,
    abort_session_sync,
    check_health_sync,
)
from .process_manager import AgentServerProcessManager, ManagedProcess, ProcessStatus
from .sse_parser import EventType, ParsedEvent, parse_event

__all__ = [
    "AgentCLIAsyncClient",
    "AgentServerProcessManager",
    "Event",
    "EventType",
    "ManagedProcess",
    "Message",
    "MessagePart",
    "MessagePartType",
    "ParsedEvent",
    "ProcessStatus",
    "SSEEvent",
    "Session",
    "abort_session_sync",
    "check_health_sync",
    "parse_event",
]
