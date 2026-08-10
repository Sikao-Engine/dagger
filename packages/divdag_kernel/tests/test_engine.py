"""Engine tests: topology progression, retries, failure propagation, dynamic expansion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from divdag_kernel.dag import (
    ContextPatch,
    DagTemplate,
    EdgeDef,
    EdgeKind,
    NodeDef,
    NodeRegistry,
    Scope,
    instantiate,
)
from divdag_kernel.dag.nodes import NodeContract
from divdag_kernel.engine import (
    EngineHooks,
    NodeFailed,
    run_graph,
)
from divdag_kernel.executors import ExecutorCatalog, ExecutorSpec
from divdag_kernel.state import K, StateStore


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
            __import__("divdag_kernel").dag.instantiator.ShardPlan(
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
            __import__("divdag_kernel").dag.instantiator.ShardPlan(
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
        shards = [__import__("divdag_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
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
        shards = [__import__("divdag_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
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
        shards = [__import__("divdag_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
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
        shards = [__import__("divdag_kernel").dag.instantiator.ShardPlan(shard_id="s0", index=0)]
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


# ---------------------------------------------------------------------------
# K3 / K4 / K8 / D8 additions: agent result-contract enforcement, shard view
# enrichment, edge-aware context propagation, and the parallel-writes rule.
# ---------------------------------------------------------------------------

from divdag_kernel.dag.instantiator import ShardPlan  # noqa: E402
from divdag_kernel.spi import SkillSpec  # noqa: E402


def _shards(n: int, items_per_shard: int = 1) -> list[ShardPlan]:
    return [
        ShardPlan(
            shard_id=f"s{i}",
            index=i,
            items=tuple(f"item-{i}-{j}" for j in range(items_per_shard)),
        )
        for i in range(n)
    ]


class TestAgentResultContract:
    """K3: with skills wired in, agent outputs are checked against produces."""

    def test_agent_writing_undeclared_key_fails(
        self, catalog, nodes, store, tmp_path: Path
    ) -> None:
        tpl = _tiny_template()
        graph = instantiate(template=tpl, run_id="run_e2e", shards=_shards(1))
        dispatcher = _ScriptedDispatcher({"work": {"work_ok": True, "rogue_key": 1}})
        skills = {
            "tiny-work": SkillSpec(
                key="tiny-work",
                skill_name="tiny-work",
                prompt_template="...",
                success_key="work_ok",
                produces=("work_ok",),
            )
        }
        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=dispatcher,
            max_node_retries=2,
            skills=skills,
        )
        assert "run_e2e__work__s000" in result.failed
        # The rogue write was retried (2 attempts), not accepted silently.
        assert dispatcher.calls.count("run_e2e__work__s000") == 2

    def test_success_key_is_allowed_even_when_not_in_produces(
        self, catalog, nodes, store, tmp_path: Path
    ) -> None:
        tpl = _tiny_template()
        graph = instantiate(template=tpl, run_id="run_e2e", shards=_shards(1))
        dispatcher = _ScriptedDispatcher({"work": {"work_ok": True}})
        skills = {
            "tiny-work": SkillSpec(
                key="tiny-work",
                skill_name="tiny-work",
                prompt_template="...",
                success_key="work_ok",
                produces=(),  # success_key alone must pass
            )
        }
        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=dispatcher,
            skills=skills,
        )
        assert "run_e2e__work__s000" in result.completed

    def test_legacy_behavior_without_skills(self, catalog, nodes, store, tmp_path: Path) -> None:
        """Hosts that pass no skills get the old (unenforced) behavior."""
        tpl = _tiny_template()
        graph = instantiate(template=tpl, run_id="run_e2e", shards=_shards(1))
        # An extra undeclared key passes unchecked when no skills map is wired.
        dispatcher = _ScriptedDispatcher({"work": {"work_ok": True, "anything": 1}})
        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=dispatcher,
        )
        assert "run_e2e__work__s000" in result.completed


class TestResultValidators:
    """K3: the domain ResultValidator SPI runs against the full result body."""

    def test_validator_errors_fail_the_node_and_retry(
        self, catalog, nodes, store, tmp_path: Path
    ) -> None:
        tpl = _tiny_template()
        graph = instantiate(template=tpl, run_id="run_e2e", shards=_shards(1))
        dispatcher = _ScriptedDispatcher({"work": {"work_ok": True, "chapters_done": 1}})
        calls = {"n": 0}

        def _reject(body, *, node_run_id, context=None):
            calls["n"] += 1
            return ["chapters_done off by one"]

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=dispatcher,
            max_node_retries=2,
            validators={"tiny.work": _reject},
        )
        assert "run_e2e__work__s000" in result.failed
        assert calls["n"] == 2  # once per attempt

    def test_validator_receives_shard_context(self, catalog, nodes, store, tmp_path: Path) -> None:
        tpl = _tiny_template()
        graph = instantiate(template=tpl, run_id="run_e2e", shards=_shards(1, items_per_shard=3))
        dispatcher = _ScriptedDispatcher({"work": {"work_ok": True, "chapters_done": 3}})
        seen_contexts: list[dict] = []

        def _check_count(body, *, node_run_id, context=None):
            seen_contexts.append(dict(context or {}))
            expected = (context or {}).get("shard", {}).get("item_count")
            if body["outputs"].get("chapters_done") != expected:
                return [f"chapters_done != shard.item_count ({expected})"]
            return []

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=dispatcher,
            validators={"tiny.work": _check_count},
        )
        assert "run_e2e__work__s000" in result.completed
        assert seen_contexts and seen_contexts[0]["shard"]["item_count"] == 3


class TestShardViewEnrichment:
    """K4: agent nodes see shard.item_count / first_item / last_item in ctx."""

    def test_shard_view_has_item_info(self, catalog, nodes, store, tmp_path: Path) -> None:
        tpl = _tiny_template()
        graph = instantiate(template=tpl, run_id="run_e2e", shards=_shards(2, items_per_shard=3))
        seen: dict[str, dict] = {}

        class _CtxProbe:
            def __call__(self, *, node_run, ctx, executor, store, attempt):
                seen[node_run.node_run_id] = dict(ctx.shard)
                return {"work_ok": True}

        run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_CtxProbe(),
        )
        view = seen["run_e2e__work__s001"]
        assert view["shard_id"] == "s1"
        assert view["index"] == 1
        assert view["item_count"] == 3
        assert view["items"] == ["item-1-0", "item-1-1", "item-1-2"]
        assert view["first_item"] == {"id": "item-1-0"}
        assert view["last_item"] == {"id": "item-1-2"}


class TestEdgeAwarePropagation:
    """K8: context flows along edges with per-kind targeting (no broadcast leaks)."""

    def _two_step_template(self) -> DagTemplate:
        return DagTemplate(
            id="pipe",
            domain_id="d",
            nodes=(
                NodeDef("produce", "tiny.work", Scope.SHARD, priority=10),
                NodeDef("consume", "tiny.consume", Scope.SHARD, priority=20),
                NodeDef("report", "tiny.report", Scope.RUN, priority=50),
            ),
            edges=(
                EdgeDef("produce", "consume", EdgeKind.INTRA),
                EdgeDef("consume", "report", EdgeKind.ALL),
            ),
        )

    def _catalog_with_consume(self) -> ExecutorCatalog:
        cat = _make_catalog()
        cat.register(
            ExecutorSpec(key="tiny.consume", label="consume", handler_kind="agent", scope="shard")
        )
        return cat

    def _nodes_with_consume_report(self) -> NodeRegistry:
        class _ConsumeReport:
            contract = NodeContract(reads=("consumed_ok",), writes=("report_ok",))

            def run(self, ctx) -> ContextPatch:
                return ContextPatch(values={"report_ok": True})

        reg = NodeRegistry()
        reg.register("tiny.report", _ConsumeReport())
        return reg

    def test_intra_delivers_same_shard_only(self, store, tmp_path: Path) -> None:
        """Distinct per-shard values must not collide in sibling contexts."""
        tpl = self._two_step_template()
        cat = self._catalog_with_consume()
        nodes = self._nodes_with_consume_report()
        shards = [
            ShardPlan(shard_id="s0", index=0, items=("a", "b", "c")),
            ShardPlan(shard_id="s1", index=1, items=("d", "e")),
        ]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)
        seen: dict[str, dict] = {}

        class _Dispatcher:
            def __call__(self, *, node_run, ctx, executor, store, attempt):
                if node_run.node_key == "produce":
                    # Per-shard-distinct value: would false-conflict under broadcast.
                    return {"count": len(ctx.shard["items"])}
                seen[node_run.node_run_id] = ctx.values()
                return {"consumed_ok": True}

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=cat,
            node_registry=nodes,
            agent_dispatcher=_Dispatcher(),
        )
        assert not result.failed
        # consume[s0] saw only produce[s0]'s count; consume[s1] only produce[s1]'s.
        assert seen["run_e2e__consume__s000"]["count"] == 3
        assert seen["run_e2e__consume__s001"]["count"] == 2

    def test_serial_prev_delivers_next_shard_only(self, store, tmp_path: Path) -> None:
        tpl = DagTemplate(
            id="serial",
            domain_id="d",
            nodes=(NodeDef("acc", "tiny.acc", Scope.SHARD, priority=10),),
            edges=(EdgeDef("acc", "acc", EdgeKind.SERIAL_PREV, maps={"prev_total": "total"}),),
        )
        cat = ExecutorCatalog()
        cat.register(ExecutorSpec(key="tiny.acc", label="acc", handler_kind="agent", scope="shard"))
        shards = [ShardPlan(shard_id=f"s{i}", index=i, items=(f"i{i}",)) for i in range(3)]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)
        seen: dict[str, dict] = {}

        class _Acc:
            def __call__(self, *, node_run, ctx, executor, store, attempt):
                seen[node_run.node_run_id] = ctx.values()
                prev = ctx.get("prev_total", 0)
                return {"total": prev + 1}

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=cat,
            node_registry=NodeRegistry(),
            agent_dispatcher=_Acc(),
        )
        assert not result.failed
        # The serial chain accumulated: 1, 2, 3 — each shard saw only its predecessor.
        assert seen["run_e2e__acc__s000"].get("prev_total") is None
        assert seen["run_e2e__acc__s001"]["prev_total"] == 1
        assert seen["run_e2e__acc__s002"]["prev_total"] == 2


class TestParallelWritesRule:
    """D8: ALL fan-in merges equal values; differing values raise a conflict."""

    def test_all_fanin_equal_values_merge(self, nodes, store, tmp_path: Path) -> None:
        tpl = self._all_fanin_template()
        cat = self._all_fanin_catalog()
        shards = [ShardPlan(shard_id=f"s{i}", index=i, items=(f"i{i}",)) for i in range(3)]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)
        seen: dict[str, dict] = {}

        class _Bool:
            def __call__(self, *, node_run, ctx, executor, store, attempt):
                seen[node_run.node_run_id] = ctx.values()
                return {"merge_ok": True} if node_run.node_key == "merge" else {"flag_ok": True}

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=cat,
            node_registry=nodes,
            agent_dispatcher=_Bool(),
        )
        assert not result.failed
        assert seen["run_e2e__merge"]["flag_ok"] is True

    def test_all_fanin_differing_values_raise_conflict(self, nodes, store, tmp_path: Path) -> None:
        from divdag_kernel.dag import ContextConflictError

        tpl = self._all_fanin_template()
        cat = self._all_fanin_catalog()
        shards = [ShardPlan(shard_id=f"s{i}", index=i, items=(f"i{i}",)) for i in range(2)]
        graph = instantiate(template=tpl, run_id="run_e2e", shards=shards)

        class _Distinct:
            def __call__(self, *, node_run, ctx, executor, store, attempt):
                if node_run.node_key == "flag":
                    return {"flag_ok": node_run.shard_index}  # distinct per shard
                return {"merge_ok": True}

        import pytest

        with pytest.raises(ContextConflictError):
            run_graph(
                graph=graph,
                template=tpl,
                store=store,
                catalog=cat,
                node_registry=nodes,
                agent_dispatcher=_Distinct(),
            )

    def _all_fanin_template(self) -> DagTemplate:
        return DagTemplate(
            id="fanin",
            domain_id="d",
            nodes=(
                NodeDef("flag", "tiny.flag", Scope.SHARD, priority=10),
                NodeDef("merge", "tiny.merge", Scope.RUN, priority=50),
            ),
            edges=(EdgeDef("flag", "merge", EdgeKind.ALL),),
        )

    def _all_fanin_catalog(self) -> ExecutorCatalog:
        cat = ExecutorCatalog()
        cat.register(
            ExecutorSpec(key="tiny.flag", label="flag", handler_kind="agent", scope="shard")
        )
        cat.register(
            ExecutorSpec(key="tiny.merge", label="merge", handler_kind="agent", scope="run")
        )
        return cat
