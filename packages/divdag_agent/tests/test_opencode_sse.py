"""sse_parser: decode raw opencode SSE into ParsedEvent (pure unit tests)."""

from __future__ import annotations

import json

from divdag_agent.opencode import EventType, SSEEvent, parse_event


def _sse(event: str, data: dict | str) -> SSEEvent:
    return SSEEvent(event=event, data=data if isinstance(data, str) else json.dumps(data))


class TestParseEvent:
    def test_empty_data_skipped(self) -> None:
        assert parse_event(SSEEvent(event="x", data="")).type == EventType.SKIP

    def test_heartbeat_skipped(self) -> None:
        ev = _sse("server.heartbeat", {"type": "server.heartbeat"})
        assert parse_event(ev).type == EventType.SKIP

    def test_reconnect_sentinel(self) -> None:
        parsed = parse_event(SSEEvent(event="__reconnected__", data="2"))
        assert parsed.type == EventType.RECONNECTED
        assert "attempt 2" in parsed.text

    def test_session_mismatch_skipped(self) -> None:
        ev = _sse(
            "message.part.updated",
            {
                "type": "message.part.updated",
                "sessionID": "other",
                "properties": {"part": {"type": "text"}},
            },
        )
        assert parse_event(ev, session_id="mine").type == EventType.SKIP

    def test_text_part(self) -> None:
        ev = _sse(
            "message.part.updated",
            {
                "type": "message.part.updated",
                "sessionID": "s1",
                "properties": {"part": {"type": "text", "text": "hello"}, "delta": "hel"},
            },
        )
        parsed = parse_event(ev, session_id="s1")
        assert parsed.type == EventType.TEXT
        assert parsed.text == "hello"
        assert parsed.delta == "hel"

    def test_tool_part(self) -> None:
        ev = _sse(
            "message.part.updated",
            {
                "type": "message.part.updated",
                "properties": {
                    "part": {"type": "tool", "tool": "edit", "state": {"status": "completed"}}
                },
            },
        )
        parsed = parse_event(ev)
        assert parsed.type == EventType.TOOL
        assert parsed.tool_name == "edit"
        assert parsed.tool_status == "completed"

    def test_permission_tool_becomes_permission(self) -> None:
        ev = _sse(
            "message.part.updated",
            {
                "type": "message.part.updated",
                "properties": {
                    "part": {
                        "type": "tool",
                        "tool": "permission",
                        "state": {"status": "pending", "id": "perm-1"},
                    }
                },
            },
        )
        parsed = parse_event(ev)
        assert parsed.type == EventType.PERMISSION
        assert parsed.permission_id == "perm-1"

    def test_step_finish_terminal(self) -> None:
        ev = _sse(
            "message.part.updated",
            {
                "type": "message.part.updated",
                "properties": {"part": {"type": "step-finish", "reason": "stop", "cost": 0.01}},
            },
        )
        parsed = parse_event(ev)
        assert parsed.type == EventType.STEP_FINISH
        assert parsed.finished is True
        assert parsed.cost == 0.01

    def test_step_finish_tool_calls_not_terminal(self) -> None:
        ev = _sse(
            "message.part.updated",
            {
                "type": "message.part.updated",
                "properties": {"part": {"type": "step-finish", "reason": "tool-calls"}},
            },
        )
        parsed = parse_event(ev)
        assert parsed.finished is False

    def test_session_idle(self) -> None:
        parsed = parse_event(
            _sse("session.idle", {"type": "session.idle", "sessionID": "s1"}), "s1"
        )
        assert parsed.type == EventType.SESSION_IDLE
        assert parsed.is_terminal() is True

    def test_session_status_non_idle_skipped(self) -> None:
        ev = _sse(
            "session.status",
            {"type": "session.status", "properties": {"status": {"type": "running"}}},
        )
        assert parse_event(ev).type == EventType.SKIP

    def test_part_delta_text(self) -> None:
        ev = _sse(
            "message.part.delta",
            {"type": "message.part.delta", "properties": {"delta": "wor", "field": "text"}},
        )
        parsed = parse_event(ev)
        assert parsed.type == EventType.TEXT_DELTA
        assert parsed.delta == "wor"

    def test_unknown_event(self) -> None:
        parsed = parse_event(_sse("x", {"type": "something.new"}))
        assert parsed.type == EventType.UNKNOWN


class TestToAgentEvent:
    def test_skip_dropped(self) -> None:
        from divdag_agent.backends.opencode_http import _to_agent_event

        assert _to_agent_event(parse_event(SSEEvent(event="", data=""))) is None

    def test_text_maps(self) -> None:
        from divdag_agent.backends.opencode_http import _to_agent_event

        parsed = parse_event(
            _sse(
                "message.part.updated",
                {
                    "type": "message.part.updated",
                    "properties": {"part": {"type": "text", "text": "hi"}},
                },
            )
        )
        ev = _to_agent_event(parsed)
        assert ev is not None
        assert ev.kind == "text"
        assert ev.text == "hi"

    def test_idle_maps_but_not_success(self) -> None:
        from divdag_agent.backends.opencode_http import _to_agent_event

        parsed = parse_event(_sse("session.idle", {"type": "session.idle"}))
        ev = _to_agent_event(parsed)
        assert ev is not None
        assert ev.kind == "idle"
