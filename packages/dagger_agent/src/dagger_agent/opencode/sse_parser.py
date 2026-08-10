"""dagger_agent.opencode.sse_parser — unified SSE event decoder.

Vendored from CubeClaw's `cube.agentcli.sse_parser`. Decodes raw
opencode SSE events into structured `ParsedEvent`. Only supports
opencode-compatible native events:

    message.part.updated  → text | tool | reasoning | step-start | step-finish
    message.part.delta    → text_delta
    session.idle          → session_idle  (task complete — but NOT trusted for success)
    session.status        → session_idle  (if status.type == "idle")

Session filtering
-----------------
/event is global (pushes all sessions). Pass the session_id to filter out
other sessions' events (returned as EventType.SKIP).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .client import SSEEvent

logger = logging.getLogger(__name__)


# ── Event types ───────────────────────────────────────────────────


class EventType(StrEnum):
    """Decoded event type."""

    TEXT = "text"
    TEXT_DELTA = "text_delta"
    REASONING = "reasoning"
    TOOL = "tool"
    PERMISSION = "permission"
    STEP_START = "step-start"
    STEP_FINISH = "step-finish"
    SESSION_IDLE = "session_idle"
    RECONNECTED = "reconnected"
    SKIP = "skip"
    UNKNOWN = "unknown"


# ── Parsed result ─────────────────────────────────────────────────


@dataclass
class ParsedEvent:
    """Structured SSE event. All fields default — check only what you care about."""

    type: EventType = EventType.UNKNOWN
    text: str = ""
    delta: str = ""
    tool_name: str = ""
    tool_status: str = ""
    tool_input: str = ""
    tool_output: str = ""
    tool_error: str = ""
    tool_call_id: str = ""
    tool_title: str = ""
    permission_id: str = ""
    finished: bool = False
    cost: float = 0.0
    created_at: float = 0.0
    tokens: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def is_terminal(self) -> bool:
        if self.type == EventType.SESSION_IDLE:
            return True
        if self.type == EventType.STEP_FINISH:
            # tool-calls reason = intermediate step, will continue
            return self.text not in ("tool-calls", "tool_calls")
        return False


# ── Main parser ───────────────────────────────────────────────────


def parse_event(event: SSEEvent, session_id: str = "") -> ParsedEvent:
    """Decode a raw SSEEvent into a ParsedEvent.

    Args:
        event:      raw event from AgentCLIAsyncClient.stream_events*
        session_id: current session; filters non-matching events when non-empty.

    Returns:
        ParsedEvent; type == SKIP means safe to ignore.
    """
    if logger.isEnabledFor(logging.DEBUG):
        preview = event.data[:500] if event.data else "<empty>"
        logger.debug("[RAW SSE] event=%s id=%s data=%s", event.event, event.id or "-", preview)

    # ── reconnect sentinel ────────────────────────────────────────
    if event.event == "__reconnected__":
        parsed = ParsedEvent(
            type=EventType.RECONNECTED,
            text=f"SSE reconnected (attempt {event.data})",
        )
        logger.debug("[PARSED] type=%s text=%s", parsed.type.value, parsed.text)
        return parsed

    data = event.json()
    if not data:
        logger.debug("[PARSED] type=SKIP reason=empty_json")
        return ParsedEvent(type=EventType.SKIP)

    event_type: str = data.get("type", "")

    # ── global filters (heartbeat / server connect) ───────────────
    if event_type in ("server.connected", "server.heartbeat"):
        logger.debug("[PARSED] type=SKIP reason=global_filter event_type=%s", event_type)
        return ParsedEvent(type=EventType.SKIP)

    # ── session filter ────────────────────────────────────────────
    if session_id and not _matches_session(data, session_id):
        logger.debug("[PARSED] type=SKIP reason=session_mismatch event_type=%s", event_type)
        return ParsedEvent(type=EventType.SKIP)

    # ── opencode native events ────────────────────────────────────
    if event_type == "message.part.updated":
        parsed = _parse_part_updated(data)
        _log_parsed(parsed, event_type)
        return parsed

    if event_type in (
        "message.updated",
        "message.created",
        "session.updated",
        "session.created",
        "session.diff",
    ):
        if event_type in ("message.updated", "message.created"):
            props = data.get("properties", {})
            info = props.get("info", {}) if props else {}
            if not info:
                info = data.get("info", {})
            role = info.get("role", "")
            model_id = info.get("modelID", "")
            agent = info.get("agent", "")
            if role == "assistant" and (model_id or agent):
                logger.info(
                    "[SSE] %s: role=%s agent=%s model=%s",
                    event_type,
                    role,
                    agent or "?",
                    model_id or "?",
                )
        else:
            logger.debug("[PARSED] type=SKIP reason=ignored_event event_type=%s", event_type)
        return ParsedEvent(type=EventType.SKIP)

    if event_type == "message.part.delta":
        parsed = _parse_part_delta(data)
        _log_parsed(parsed, event_type)
        return parsed

    if event_type in ("session.idle", "session.status"):
        parsed = _parse_session_status(data, event_type)
        _log_parsed(parsed, event_type)
        return parsed

    if event_type in ("session.permission", "permission", "permission.asked"):
        props = data.get("properties", {})
        perm_id = data.get("id", data.get("permissionID", "")) or props.get(
            "id", props.get("permissionID", "")
        )
        parsed = ParsedEvent(type=EventType.PERMISSION, permission_id=perm_id, raw=data)
        _log_parsed(parsed, event_type)
        return parsed

    return ParsedEvent(type=EventType.UNKNOWN, raw=data)


# ── Session matching ──────────────────────────────────────────────


def _matches_session(data: dict[str, Any], session_id: str) -> bool:
    """True if the event belongs to session_id (or carries no sessionID)."""
    props = data.get("properties", {})
    sid: str | None = props.get("sessionID") or props.get("session_id") or data.get("sessionID")
    if not sid:
        info = props.get("info", {}) if props else {}
        sid = info.get("sessionID")
    return not sid or sid == session_id


def _log_parsed(parsed: ParsedEvent, event_type: str) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    parts = [f"type={parsed.type.value}", f"sse_type={event_type}"]
    if parsed.delta:
        preview = parsed.delta[:80].replace("\n", "\\n")
        parts.append(f"delta={preview!r}")
    if parsed.tool_name:
        parts.append(f"tool={parsed.tool_name}")
    if parsed.tool_status:
        parts.append(f"status={parsed.tool_status}")
    if parsed.finished:
        parts.append("finished=True")
    logger.debug("[PARSED] %s", "  ".join(parts))


# ── part.updated parser ───────────────────────────────────────────


def _parse_part_updated(data: dict[str, Any]) -> ParsedEvent:
    props = data.get("properties", {})
    part = props.get("part", {})
    delta = props.get("delta", "")
    part_type = part.get("type", "")

    if part_type == "text":
        return ParsedEvent(
            type=EventType.TEXT,
            delta=delta,
            text=part.get("text", ""),
            raw=data,
        )

    if part_type == "tool":
        state = part.get("state", {})
        tool_name = part.get("tool", "unknown")
        status = state.get("status", "")
        title = state.get("title", tool_name)
        call_id = part.get("callID", part.get("id", ""))
        tool_input = ""
        if isinstance(state.get("input"), dict):
            tool_input = json.dumps(state["input"], ensure_ascii=False)
        elif isinstance(state.get("input"), str):
            tool_input = state["input"]

        if tool_name in ("permission", "question", "ask") and status in ("pending", "running"):
            return ParsedEvent(
                type=EventType.PERMISSION,
                tool_name=tool_name,
                tool_status=status,
                tool_title=title,
                permission_id=state.get("id", "") or part.get("id", ""),
                raw=data,
            )

        return ParsedEvent(
            type=EventType.TOOL,
            tool_name=tool_name,
            tool_status=status,
            tool_title=title,
            tool_call_id=call_id,
            tool_input=tool_input,
            raw=data,
        )

    if part_type == "reasoning":
        return ParsedEvent(
            type=EventType.REASONING,
            text=part.get("text", ""),
            delta=delta,
            raw=data,
        )

    if part_type == "step-start":
        msg_info = props.get("message", {}) or {}
        model_id = msg_info.get("modelID", "")
        agent = msg_info.get("agent", "")
        if model_id or agent:
            logger.info("[SSE] step-start: agent=%s model=%s", agent or "?", model_id or "?")
        return ParsedEvent(type=EventType.STEP_START, raw=data)

    if part_type == "step-finish":
        reason = part.get("reason", "")
        cost = part.get("cost", 0.0) or 0.0
        tokens = part.get("tokens", {}) or {}
        finished = reason not in ("tool-calls", "tool_calls")
        logger.info(
            "[SSE] step-finish: reason=%r terminal=%s cost=$%.4f",
            reason,
            finished,
            float(cost),
        )
        return ParsedEvent(
            type=EventType.STEP_FINISH,
            text=reason,
            finished=finished,
            cost=float(cost),
            tokens=tokens,
            raw=data,
        )

    if part_type in ("retry", "agent", "subtask", "compaction", "patch", "snapshot"):
        logger.debug("[SSE] %s part (skipped)", part_type)
        return ParsedEvent(type=EventType.SKIP, raw=data)

    if part_type:
        logger.warning("[SSE] unknown part_type=%r in message.part.updated", part_type)
    return ParsedEvent(type=EventType.SKIP)


def _parse_part_delta(data: dict[str, Any]) -> ParsedEvent:
    props = data.get("properties", {})
    delta = props.get("delta", "")
    field_name = props.get("field", "")
    if delta and field_name in ("text", "reasoning"):
        return ParsedEvent(type=EventType.TEXT_DELTA, delta=delta, text=delta, raw=data)
    return ParsedEvent(type=EventType.SKIP)


def _parse_session_status(data: dict[str, Any], event_type: str) -> ParsedEvent:
    if event_type == "session.status":
        props = data.get("properties", {})
        status = props.get("status", {})
        status_type = status.get("type", "") if isinstance(status, dict) else ""
        if status_type != "idle":
            return ParsedEvent(type=EventType.SKIP)
    # session.idle OR session.status with type=idle
    return ParsedEvent(type=EventType.SESSION_IDLE, finished=True, raw=data)


__all__ = ["EventType", "ParsedEvent", "parse_event"]
