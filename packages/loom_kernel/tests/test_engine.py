"""Engine tests: topology progression, retries, failure propagation, dynamic expansion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loom_kernel.dag import (
    ContextPatch,
    DagTemplate,
    EdgeDef,
    EdgeKind,
    NodeDef,
    NodeRegistry,
    Scope,
    instantiate,
)
from loom_kernel.dag.nodes import NodeContract
from loom_kernel.engine import (
    EngineHooks,
    NodeFailed,
    run_graph,
)
from loom_kernel.executors import ExecutorCatalog, ExecutorSpec
from loom_kernel.state import K, StateStore


class _NoopHandler:
    contract = NodeContract(writes=("initialized",))

    def run(self, ctx) -> ContextPatch:
        return ContextPatch(values={"initialized": True})


def _make_catalog() -> ExecutorCatalog:
    cat = ExecutorCatalog()
    cat.register(
        ExecutorSpec(
            key="tiny.init",
            label="init",
            handler_kind="builtin",
            scope="run_entry",
            node_class="tests.engine:_NoopHandler",
        )
    )
    cat.register(
        ExecutorSpec(
            key="tiny.work",
            label="work",
            handler_kind="agent",
            scope="shard",
            skill="tiny-work",
        )
    )
    cat.register(
        ExecutorSpec(
            key="tiny.report",
            label="report",
            handler_kind="builtin",
            scope="run",
            node_class="tests.engine:_ReportHandler",
        )
    )
    return cat


class _ReportHandler:
    contract = NodeContract(reads=("work_ok",), writes=("report_ok", "final_count"))

    def run(self, ctx) -> ContextPatch:
        return ContextPatch(values={"report_ok": True, "final_count": ctx.get("work_ok", 0)})


@pytest.fixture
def catalog() -> ExecutorCatalog:
    return _make_catalog()


@pytest.fixture
def nodes() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register("tiny.init", _NoopHandler())
    reg.register("tiny.report", _ReportHandler())
    return reg


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "run", run_id="run_e2e")


def _tiny_template() -> DagTemplate:
    return DagTemplate(
        id="tiny_default",
        domain_id="tiny",
        nodes=(
            NodeDef("init", "tiny.init", Scope.RUN_ENTRY, priority=0),
            NodeDef("work", "tiny.work", Scope.SHARD, priority=10),
            NodeDef("report", "tiny.report", Scope.RUN, priority=50),
        ),
        edges=(
            EdgeDef("init", "work", EdgeKind.RUN_ENTRY_ALL),
            EdgeDef("work", "report", EdgeKind.ALL),
        ),
    )


class _ScriptedDispatcher:
    """A test-only AgentDispatcher: returns a canned outputs dict per node_key."""

    def __init__(self, scripts: dict[str, dict[str, Any]]) -> None:
        self._scripts = scripts
        self.calls: list[str] = []

    def __call__(
        self,
        *,
        node_run,
        ctx,
        executor,
        store,
        attempt,
    ) -> dict[str, Any]:
        self.calls.append(node_run.node_run_id)
        out = self._scripts.get(node_run.node_key)
        if out is None:
            raise NodeFailed(node_run.node_run_id, "no script")
        return dict(out)


class TestEngineHappyPath:
    def test_runs_full_graph_to_completion(self, catalog, nodes, store, tmp_path: Path) -> None:
        tpl = _tiny_template()
        shards = [
            __import__("loom_kernel").dag.instantiator.ShardPlan(
                shard_id=f"s{i}", index=i, items=(f"item-{i}",)
            )
            for i in range(2)
        ]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)
        dispatcher = _ScriptedDispatcher({"work": {"work_ok": True}})
        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=dispatcher,
        )
        assert len(result.completed) == 4  # init + 2 work + report
        assert not result.failed
        # The report node saw at least one work output propagated through.
        report_out = result.context_outputs["run_e2e__report"]
        assert report_out["report_ok"] is True

    def test_writes_result_to_contract_layer(self, catalog, nodes, store, tmp_path: Path) -> None:
        tpl = _tiny_template()
        shards = [
            __import__("loom_kernel").dag.instantiator.ShardPlan(
                shard_id="s0", index=0, items=("i0",)
            )
        ]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)
        dispatcher = _ScriptedDispatcher({"work": {"work_ok": True}})
        run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=dispatcher,
        )
        # The work node's result.json should be on disk in contract/.
        work_id = "run_e2e__work__s000"
        env = store.read_envelope(K.result(work_id, 1))
        assert env is not None
        assert env.body["status"] == "success"
        assert env.body["success"] is True
        assert env.body["outputs"]["work_ok"] is True


class TestEngineRetries:
    def test_retries_until_success(self, catalog, nodes, store, tmp_path: Path) -> None:
        tpl = _tiny_template()
        shards = [__import__("loom_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)

        # Dispatcher fails the first 2 attempts then succeeds.
        attempts = {"count": 0}

        class _RetryDispatcher:
            def __call__(self, *, node_run, ctx, executor, store, attempt):
                if node_run.node_key == "work":
                    attempts["count"] += 1
                    if attempts["count"] < 3:
                        raise NodeFailed(node_run.node_run_id, "flaky")
                    return {"work_ok": True}
                raise NodeFailed(node_run.node_run_id, "no script")

        run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_RetryDispatcher(),
            max_node_retries=5,
        )
        assert attempts["count"] == 3

    def test_failure_propagates_to_descendants(self, catalog, nodes, store, tmp_path: Path) -> None:
        tpl = _tiny_template()
        shards = [__import__("loom_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)

        class _AlwaysFail:
            def __call__(self, *, node_run, ctx, executor, store, attempt):
                raise NodeFailed(node_run.node_run_id, "broken")

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_AlwaysFail(),
            max_node_retries=1,
        )
        # work failed; report (descendant) skipped.
        assert "run_e2e__work__s000" in result.failed
        assert "run_e2e__report" in result.skipped


class TestEngineIdempotentResume:
    def test_skips_already_successful_node(self, catalog, nodes, store, tmp_path: Path) -> None:
        tpl = _tiny_template()
        shards = [__import__("loom_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)
        # Pre-write a success result for the work node.
        work_id = "run_e2e__work__s000"
        store.begin_attempt(work_id)
        store.write_json(
            K.result(work_id, 1),
            {
                "status": "success",
                "success": True,
                "node_run_id": work_id,
                "node_type": "tiny.work",
                "skill": "tiny-work",
                "outputs": {"work_ok": True},
            },
            kind="session_result",
        )

        # Dispatcher would fail if called — proves we skipped.
        class _BoomDispatcher:
            def __call__(self, **kw):
                raise AssertionError("should not be called — idempotent skip")

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_BoomDispatcher(),
        )
        assert "run_e2e__work__s000" in result.completed


class TestEngineHooks:
    def test_hooks_fire_on_start_success_failure(
        self, catalog, nodes, store, tmp_path: Path
    ) -> None:
        tpl = _tiny_template()
        shards = [__import__("loom_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)
        starts: list[str] = []
        succs: list[str] = []
        fails: list[str] = []

        def _on_start(nid: str) -> None:
            starts.append(nid)

        def _on_success(nid: str, out: dict[str, Any]) -> None:
            succs.append(nid)

        def _on_failure(nid: str, reason: str) -> None:
            fails.append(nid)

        hooks = EngineHooks(
            on_node_start=_on_start,
            on_node_success=_on_success,
            on_node_failure=_on_failure,
        )
        run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_ScriptedDispatcher({"work": {"work_ok": True}}),
            hooks=hooks,
        )
        assert starts  # at least one node started
        assert succs  # at least one succeeded
        assert not fails
