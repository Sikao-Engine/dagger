"""loom_agent.opencode.client — agentcli (opencode) async HTTP / SSE client.

Vendored from CubeClaw's `cube.agentcli.client` (long-validated). Provides
the async client the opencode-http AgentBackend sits on.

SSE format (opencode fork /event global endpoint, opencode-compatible):
    message.part.updated  — text/tool/reasoning part update
    message.part.delta    — incremental text
    session.idle          — task complete (we NEVER trust this for success;
                             the session_runner waits on the result file)

Decoded by `sse_parser.parse_event`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────────────────


class MessagePartType(StrEnum):
    TEXT = "text"
    TOOL = "tool"
    REASONING = "reasoning"
    STEP_START = "step-start"
    STEP_FINISH = "step-finish"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    IMAGE = "image"
    FILE = "file"
    UNKNOWN = "unknown"


@dataclass
class MessagePart:
    type: MessagePartType
    text: str | None = None
    tool_name: str | None = None
    tool_status: str | None = None
    tool_state: dict[str, Any] | None = None
    reason: str | None = None
    cost: float | None = None
    tokens: dict[str, Any] | None = None
    raw_data: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessagePart:
        part_type = data.get("type", "text")
        try:
            msg_type = MessagePartType(part_type)
        except ValueError:
            return cls(type=MessagePartType.UNKNOWN, raw_data=data)

        part = cls(type=msg_type)
        if msg_type == MessagePartType.TEXT:
            part.text = data.get("text")
        elif msg_type == MessagePartType.TOOL:
            part.tool_name = data.get("tool")
            state = data.get("state", {})
            part.tool_status = state.get("status")
            part.tool_state = state
        elif msg_type == MessagePartType.REASONING:
            part.text = data.get("text")
        elif msg_type == MessagePartType.STEP_FINISH:
            part.reason = data.get("reason")
            part.cost = data.get("cost")
            part.tokens = data.get("tokens")
        elif msg_type == MessagePartType.UNKNOWN:
            part.raw_data = data
        return part


@dataclass
class Message:
    id: str
    role: str
    parts: list[MessagePart] = field(default_factory=list)
    created_at: str | None = None

    @property
    def text_content(self) -> str:
        return "".join(p.text for p in self.parts if p.type == MessagePartType.TEXT and p.text)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        info = data.get("info", {})
        return cls(
            id=info.get("id", ""),
            role=info.get("role", "assistant"),
            parts=[MessagePart.from_dict(p) for p in data.get("parts", [])],
            created_at=info.get("createdAt"),
        )


@dataclass
class Session:
    id: str
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    parent_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            id=data.get("id", ""),
            title=data.get("title"),
            created_at=data.get("createdAt"),
            updated_at=data.get("updatedAt"),
            parent_id=data.get("parentID"),
        )


@dataclass
class SSEEvent:
    """Parsed Server-Sent Event."""

    event: str = ""
    data: str = ""
    id: str | None = None

    def json(self) -> Any:
        if not self.data:
            return None
        try:
            return json.loads(self.data)
        except json.JSONDecodeError:
            return None

    @property
    def is_reconnect(self) -> bool:
        return self.event == "__reconnected__"


# ── Sync helpers (no client object needed) ────────────────────────


def check_health_sync(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 3.0,
) -> bool:
    """Sync health check for process-manager startup polling.

    Returns True if /global/health reports healthy=True.
    """
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout),
            trust_env=False,  # don't honor HTTP_PROXY for localhost
        ) as c:
            resp = c.get(f"http://{host}:{port}/global/health")
            return bool(resp.json().get("healthy", False))
    except Exception:
        return False


def abort_session_sync(
    session_id: str,
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 10.0,
) -> bool:
    """Sync abort (for callbacks that can't be async)."""
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout),
            trust_env=False,
        ) as c:
            resp = c.post(f"http://{host}:{port}/session/{session_id}/abort")
            return resp.status_code == 200
    except Exception:
        return False


# ── Async Client ──────────────────────────────────────────────────


class AgentCLIAsyncClient:
    """Async agentcli client with built-in robust SSE.

    Example::

        async with AgentCLIAsyncClient(port=4096) as client:
            sess = await client.create_session("My Task")
            await client.send_prompt_async(sess.id, "write tests")
            async for event in client.stream_events_robust(sess.id):
                parsed = parse_event(event, sess.id)
                if parsed.type == EventType.TEXT:
                    ...
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4096,
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self._base_url = f"http://{host}:{port}"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AgentCLIAsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        await self.close()
        return False

    # ── Health ────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base_url}/global/health")
            data = resp.json()
            healthy = data.get("healthy", False)
            if not healthy:
                logger.warning("[opencode] health_check: healthy=False resp=%s", data)
            return bool(healthy)
        except httpx.ConnectError as exc:
            logger.warning("[opencode] health_check: cannot connect %s — %s", self._base_url, exc)
            return False
        except Exception as exc:
            logger.warning("[opencode] health_check: %s: %s", type(exc).__name__, exc)
            return False

    # ── Session CRUD ──────────────────────────────────────────────

    async def create_session(self, title: str | None = None) -> Session:
        body = {"title": title} if title else {}
        resp = await self._client.post(f"{self._base_url}/session", json=body)
        resp.raise_for_status()
        return Session.from_dict(resp.json())

    async def delete_session(self, session_id: str) -> bool:
        resp = await self._client.delete(f"{self._base_url}/session/{session_id}")
        return resp.status_code == 200

    async def get_messages(self, session_id: str, limit: int = 10) -> list[Message]:
        resp = await self._client.get(
            f"{self._base_url}/session/{session_id}/message",
            params={"limit": limit},
        )
        resp.raise_for_status()
        return [Message.from_dict(m) for m in resp.json()]

    async def get_session_transcript(self, session_id: str, limit: int = 0) -> list[dict[str, Any]]:
        """Full message list (with parts) for audit. limit=0 = all."""
        params: dict[str, Any] = {}
        if limit > 0:
            params["limit"] = limit
        resp = await self._client.get(
            f"{self._base_url}/session/{session_id}/message",
            params=params,
        )
        resp.raise_for_status()
        raw = resp.json()
        if raw and isinstance(raw[0], dict) and "info" in raw[0]:
            return raw
        return [{"info": m, "parts": []} for m in raw]

    # ── Messaging ─────────────────────────────────────────────────

    async def send_prompt_async(
        self,
        session_id: str,
        text: str,
        agent: str | None = None,
        model: str | None = None,
    ) -> bool:
        """Fire-and-forget prompt (HTTP 204). The Agent streams its reply via SSE."""
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if agent:
            body["agent"] = agent
        if model:
            body["model"] = model
        resp = await self._client.post(
            f"{self._base_url}/session/{session_id}/prompt_async", json=body
        )
        return resp.status_code == 204

    async def abort_session(self, session_id: str) -> bool:
        resp = await self._client.post(f"{self._base_url}/session/{session_id}/abort")
        return resp.status_code == 200

    # ── Permission ────────────────────────────────────────────────

    async def respond_permission(
        self,
        session_id: str,
        permission_id: str,
        response: str = "always",
        remember: bool = True,
    ) -> bool:
        """Respond to an opencode permission request.

        opencode serve accepts ``once`` / ``always`` / ``reject``. ``remember``
        is kept for call-site compatibility (True → always, False → once).
        """
        reply = response
        if response == "allow":
            reply = "always" if remember else "once"
        elif response == "deny":
            reply = "reject"
        if reply not in {"once", "always", "reject"}:
            reply = "always"

        resp = await self._client.post(
            f"{self._base_url}/permission/{permission_id}/reply",
            json={"reply": reply},
        )
        if resp.status_code == 200:
            return True
        if resp.status_code not in {404, 405}:
            resp.raise_for_status()
            return False

        legacy = await self._client.post(
            f"{self._base_url}/session/{session_id}/permissions/{permission_id}",
            json={"response": reply},
        )
        if legacy.status_code == 200:
            return True
        legacy.raise_for_status()
        return False

    # ── SSE Streaming ─────────────────────────────────────────────

    async def stream_events(
        self,
        session_id: str,
        timeout: float = 14400.0,
    ) -> AsyncIterator[SSEEvent]:
        """Stream SSE from the global /event endpoint.

        Note: /event pushes ALL sessions' events; pair with
        `sse_parser.parse_event(event, session_id)` to filter.
        """
        url = f"{self._base_url}/event"
        stream_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0, read=timeout),
            trust_env=False,
        )
        response_ctx = None
        try:
            response_ctx = stream_client.stream("GET", url)
            response = await response_ctx.__aenter__()
            response.raise_for_status()
            async for event in _parse_sse_stream(response):
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            return
        finally:
            if response_ctx is not None:
                with contextlib.suppress(Exception):
                    await response_ctx.__aexit__(None, None, None)
            with contextlib.suppress(Exception):
                await stream_client.aclose()

    async def stream_events_robust(
        self,
        session_id: str,
        timeout: float = 14400.0,
        max_reconnects: int = 5,
        reconnect_delay: float = 2.0,
        on_reconnect: Callable[[int], None] | None = None,
    ) -> AsyncIterator[SSEEvent]:
        """SSE stream with auto-reconnect.

        On disconnect, emits a ``SSEEvent(event="__reconnected__")`` sentinel
        before retrying. Reconnects up to `max_reconnects` times with
        linear backoff (reconnect_delay × attempt).
        """
        reconnects = 0
        while reconnects <= max_reconnects:
            try:
                async for event in self.stream_events(session_id, timeout):
                    reconnects = 0
                    yield event
                return
            except (
                httpx.ReadError,
                httpx.RemoteProtocolError,
                httpx.ConnectError,
                httpx.ReadTimeout,
            ) as exc:
                reconnects += 1
                if reconnects > max_reconnects:
                    logger.error(
                        "[SSE] max reconnects reached for session %s: %s",
                        session_id[:16],
                        exc,
                    )
                    raise
                logger.warning(
                    "[SSE] reconnecting session %s (%d/%d): %s",
                    session_id[:16],
                    reconnects,
                    max_reconnects,
                    exc,
                )
                if on_reconnect:
                    on_reconnect(reconnects)
                await asyncio.sleep(reconnect_delay * reconnects)
                yield SSEEvent(event="__reconnected__", data=str(reconnects))


# ── SSE Stream Parser (internal) ──────────────────────────────────


async def _parse_sse_stream(
    response: httpx.Response,
) -> AsyncIterator[SSEEvent]:
    """Parse an HTTP response body into an SSEEvent stream."""
    current = SSEEvent()
    data_lines: list[str] = []

    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r\n")

        if not line:
            if data_lines or current.event:
                current.data = "\n".join(data_lines)
                yield current
                current = SSEEvent()
                data_lines = []
            continue

        if line.startswith(":"):
            continue  # SSE comment (heartbeat)

        if ":" in line:
            field_name, _, value = line.partition(":")
            value = value.lstrip(" ")
        else:
            field_name = line
            value = ""

        if field_name == "event":
            current.event = value
        elif field_name == "data":
            data_lines.append(value)
        elif field_name == "id":
            current.id = value

    if data_lines or current.event:
        current.data = "\n".join(data_lines)
        yield current


__all__ = [
    "AgentCLIAsyncClient",
    "Message",
    "MessagePart",
    "MessagePartType",
    "SSEEvent",
    "Session",
    "abort_session_sync",
    "check_health_sync",
]
