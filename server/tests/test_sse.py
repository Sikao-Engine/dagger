"""SSE broker: catch-up replay + live stream + run filtering."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dagger_server.events import (
    EventBus,
    make_node_started,
    make_run_completed,
    make_run_started,
)
from dagger_server.sse import SSEBroker


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def broker(bus: EventBus) -> SSEBroker:
    return SSEBroker(bus)


class TestCatchUp:
    async def test_replays_buffered_in_order(
        self, broker: SSEBroker, bus: EventBus
    ) -> None:
        bus.emit(lambda seq: make_run_started(seq, "r1", "tiny", "t"), None)
        bus.emit(lambda seq: make_node_started(seq, "n1", "r1"), None)
        bus.emit(lambda seq: make_node_started(seq, "n2", "r1"), None)

        seen: list[dict] = []
        async for msg in broker.stream():
            seen.append(json.loads(msg["data"]))
            if len(seen) == 3:
                break
        assert [e["type"] for e in seen] == [
            "run.started",
            "node.started",
            "node.started",
        ]
        assert [e["seq"] for e in seen] == [1, 2, 3]

    async def test_last_seq_skips_already_seen(
        self, broker: SSEBroker, bus: EventBus
    ) -> None:
        bus.emit(lambda seq: make_run_started(seq, "r1", "tiny", "t"), None)
        bus.emit(lambda seq: make_node_started(seq, "n1", "r1"), None)
        bus.emit(lambda seq: make_node_started(seq, "n2", "r1"), None)

        # Client already saw seq 2 → only seq 3 should be replayed.
        seen: list[dict] = []
        async for msg in broker.stream(last_seq=2):
            seen.append(json.loads(msg["data"]))
            if len(seen) == 1:
                break
        assert len(seen) == 1
        assert seen[0]["seq"] == 3

    async def test_run_filter_excludes_other_runs(
        self, broker: SSEBroker, bus: EventBus
    ) -> None:
        bus.emit(lambda seq: make_node_started(seq, "n1", "r1"), None)
        bus.emit(lambda seq: make_node_started(seq, "n2", "r2"), None)
        bus.emit(lambda seq: make_node_started(seq, "n3", "r1"), None)

        seen: list[dict] = []
        async for msg in broker.stream(run_id="r1"):
            seen.append(json.loads(msg["data"]))
            if len(seen) == 2:
                break
        assert [e["entity_id"] for e in seen] == ["n1", "n3"]


class TestLiveStream:
    async def test_live_event_delivered_after_catchup(
        self, broker: SSEBroker, bus: EventBus
    ) -> None:
        # One buffered event for catch-up.
        bus.emit(lambda seq: make_run_started(seq, "r1", "tiny", "t"), None)

        async def _emit_later() -> None:
            await asyncio.sleep(0.05)
            bus.emit(lambda seq: make_run_completed(seq, "r1", 1, 0, 0), None)

        task = asyncio.create_task(_emit_later())
        seen: list[dict] = []
        try:
            async for msg in broker.stream():
                seen.append(json.loads(msg["data"]))
                if len(seen) == 2:
                    break
        finally:
            task.cancel()
        assert [e["type"] for e in seen] == ["run.started", "run.completed"]


class TestAttemptStream:
    async def test_replays_transcript_lines(self, broker: SSEBroker, tmp_path) -> None:
        from dagger_kernel.state import K, StateStore

        store = StateStore(tmp_path / "run", run_id="r1")
        store.begin_attempt("n1")
        path = store.path(K.transcript("n1", 1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"kind": "text", "text": "hi"})
            + "\n"
            + json.dumps({"kind": "tool", "tool": "edit"})
            + "\n",
            encoding="utf-8",
        )
        msgs: list[str] = []
        async for msg in broker.stream_attempt(
            store=store, node_run_id="n1", attempt=1, is_running=False
        ):
            msgs.append(msg["data"])
        assert len(msgs) == 2
        assert json.loads(msgs[0])["kind"] == "text"

    async def test_empty_when_no_transcript(self, broker: SSEBroker, tmp_path) -> None:
        from dagger_kernel.state import StateStore

        store = StateStore(tmp_path / "run", run_id="r1")
        msgs = [
            m
            async for m in broker.stream_attempt(
                store=store, node_run_id="n1", attempt=1, is_running=False
            )
        ]
        assert msgs == []


class TestSSEEndpoint:
    """End-to-end via TestClient: catch-up events readable from the SSE stream.

    Uses ``?catch_up_only=1`` so the stream ends after replaying buffered events
    (the live loop would block forever in a synchronous test client).
    """

    def test_global_stream_replays_buffered(self, client, items_dir: Path) -> None:
        import json as _json

        res = client.post(
            "/api/v1/runs",
            json={
                "domain_id": "tiny",
                "items_dir": str(items_dir),
                "shards": 1,
                "backend": "mock",
            },
        )
        assert res.status_code == 201
        run_id = res.json()["run_id"]

        seen_types: list[str] = []
        res = client.get(
            f"/api/v1/runs/{run_id}/events/stream?catch_up_only=1",
        )
        assert res.status_code == 200
        for line in res.text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = _json.loads(line[len("data:") :].strip())
            seen_types.append(payload["type"])
        assert "run.started" in seen_types
        assert "run.completed" in seen_types

    def test_global_stream_last_event_id_skips(self, client, items_dir: Path) -> None:
        import json as _json

        res = client.post(
            "/api/v1/runs",
            json={
                "domain_id": "tiny",
                "items_dir": str(items_dir),
                "shards": 1,
                "backend": "mock",
            },
        )
        run_id = res.json()["run_id"]
        # Last-Event-ID: 1 → seq 1 (run.started) skipped.
        res = client.get(
            f"/api/v1/runs/{run_id}/events/stream?catch_up_only=1",
            headers={"Last-Event-ID": "1"},
        )
        seqs: list[int] = []
        for line in res.text.splitlines():
            if line.startswith("data:"):
                seqs.append(_json.loads(line[len("data:") :].strip())["seq"])
        assert 1 not in seqs
        assert seqs  # some events remain
