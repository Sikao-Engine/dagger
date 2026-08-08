"""SessionRunner + MockBackend: the trust loop end-to-end (mock-only)."""

from __future__ import annotations

from pathlib import Path

import pytest
from loom_agent import SessionRunner
from loom_agent.backend import AgentEvent
from loom_agent.backends.mock import MockBackend, MockScript
from loom_agent.taskcard import TaskCard
from loom_kernel.state import K, StateStore


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "run", run_id="run_agent")


class TestMockBackend:
    async def test_creates_session_and_streams_events(
        self, store: StateStore, tmp_path: Path
    ) -> None:
        backend = MockBackend(store=store)
        backend.register(
            "tiny.work",
            MockScript(
                events=[AgentEvent(kind="text", text="working...")],
                result_body={
                    "status": "success",
                    "success": True,
                    "node_run_id": "nr_work",
                    "node_type": "tiny.work",
                    "skill": "tiny-work",
                    "outputs": {"work_ok": True},
                },
            ),
        )
        # Pre-create the contract dir so the mock can find the nrid.
        store.begin_attempt("nr_work")
        endpoint = await backend.ensure_ready(str(tmp_path))
        sid = await backend.create_session(endpoint)
        backend.bind_session_node_type(sid, "tiny.work")
        await backend.send_prompt(endpoint, sid, "go")
        events: list[AgentEvent] = []
        async for ev in backend.stream_events(endpoint, sid):
            events.append(ev)
        assert len(events) == 1
        assert events[0].text == "working..."
        # The result file should have been written.
        env = store.read_envelope(K.result("nr_work", 1))
        assert env is not None
        assert env.body["success"] is True


class TestSessionRunner:
    async def test_success_path_writes_result(self, store: StateStore, tmp_path: Path) -> None:
        backend = MockBackend(store=store)
        backend.register(
            "tiny.work",
            MockScript(
                events=[AgentEvent(kind="text", text="done")],
                result_body={
                    "status": "success",
                    "success": True,
                    "node_run_id": "nr_work",
                    "node_type": "tiny.work",
                    "skill": "tiny-work",
                    "outputs": {"work_ok": True},
                },
            ),
        )
        # Allocate the attempt so the mock can find the nrid.
        runner = SessionRunner(
            backend=backend, store=store, max_retries=1, keepalive_interval_seconds=0
        )
        outcome = await runner.run(
            node_run_id="nr_work",
            node_type="tiny.work",
            skill="tiny-work",
            declared_writes=None,  # agent nodes: trust SkillSpec.produces elsewhere
            task_card=TaskCard(
                node="work",
                shard="s0",
                attempt=1,
                write_targets={"result": str(store.path(K.result("nr_work", 1)))},
                success_criterion="work_ok=true",
            ),
            workdir=str(tmp_path),
        )
        assert outcome.success is True
        assert outcome.attempts == 1
        assert outcome.result is not None
        assert outcome.result.outputs["work_ok"] is True

    async def test_retry_until_success(self, store: StateStore, tmp_path: Path) -> None:
        # First call writes a failure; second writes success.
        call_count = {"n": 0}

        class _ScriptedBackend(MockBackend):
            async def stream_events(self, endpoint, sid):
                session = self._sessions.get(sid, {})
                node_type = session.get("node_type", "")
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # Write a failure result on the first call.
                    self._write_result(
                        node_type=node_type,
                        body={
                            "status": "failed",
                            "success": False,
                            "node_run_id": "nr_work",
                            "node_type": "tiny.work",
                            "skill": "tiny-work",
                            "error": "flaky",
                        },
                    )
                    yield AgentEvent(kind="error", text="flaky")
                else:
                    self._write_result(
                        node_type=node_type,
                        body={
                            "status": "success",
                            "success": True,
                            "node_run_id": "nr_work",
                            "node_type": "tiny.work",
                            "skill": "tiny-work",
                            "outputs": {"work_ok": True},
                        },
                    )
                    yield AgentEvent(kind="text", text="ok")

        backend = _ScriptedBackend(store=store)
        runner = SessionRunner(
            backend=backend, store=store, max_retries=3, keepalive_interval_seconds=0
        )
        outcome = await runner.run(
            node_run_id="nr_work",
            node_type="tiny.work",
            skill="tiny-work",
            declared_writes=None,
            task_card=TaskCard(node="work", attempt=1, success_criterion="work_ok=true"),
            workdir=str(tmp_path),
        )
        assert outcome.success is True
        assert call_count["n"] == 2  # first failed, second succeeded


class TestKernelInvariants:
    def test_missing_status_rejected(self) -> None:
        from loom_agent.contract import check_kernel_invariants

        errs = check_kernel_invariants({"success": True}, node_run_id="x", node_type="t", skill="s")
        assert any("status" in e for e in errs)

    def test_success_false_without_error_rejected(self) -> None:
        from loom_agent.contract import check_kernel_invariants

        errs = check_kernel_invariants(
            {"status": "failed", "success": False},
            node_run_id="x",
            node_type="t",
            skill="s",
        )
        assert any("error" in e for e in errs)

    def test_undeclared_outputs_rejected(self) -> None:
        from loom_agent.contract import check_kernel_invariants

        errs = check_kernel_invariants(
            {
                "status": "success",
                "success": True,
                "node_run_id": "x",
                "node_type": "t",
                "skill": "s",
                "outputs": {"work_ok": True, "rogue": 1},
            },
            node_run_id="x",
            node_type="t",
            skill="s",
            declared_writes=("work_ok",),
        )
        assert any("rogue" in e for e in errs)

    def test_happy_path_no_errors(self) -> None:
        from loom_agent.contract import check_kernel_invariants

        errs = check_kernel_invariants(
            {
                "status": "success",
                "success": True,
                "node_run_id": "x",
                "node_type": "t",
                "skill": "s",
                "outputs": {"work_ok": True},
            },
            node_run_id="x",
            node_type="t",
            skill="s",
            declared_writes=("work_ok",),
        )
        assert errs == []


class TestTaskCard:
    def test_roundtrip(self) -> None:
        from loom_agent.taskcard import TaskCard, render_task_card_prompt

        card = TaskCard(
            node="work",
            shard="s0",
            attempt=1,
            write_targets={"result": "/path/result.json"},
            success_criterion="work_ok=true",
        )
        body = card.to_body()
        assert body["node"] == "work"
        assert body["write_targets"]["result"] == "/path/result.json"
        prompt = render_task_card_prompt("/path/task_card.json")
        assert "task_card" in prompt
        assert "success_criterion" in prompt
