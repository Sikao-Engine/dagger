"""Template + Instantiator: topology validation, edge resolution, dynamic expansion."""

from __future__ import annotations

import pytest
from divdag_kernel.dag import (
    DagTemplate,
    EdgeDef,
    EdgeKind,
    NodeDef,
    Scope,
    TemplateError,
)
from divdag_kernel.dag.instantiator import (
    ShardPlan,
    expand_dynamic,
    instantiate,
)

# --- Template validation (T2.1) ----------------------------------------------------------


class TestTemplateValidation:
    def _tpl(self, **kw) -> DagTemplate:
        nodes = kw.pop(
            "nodes",
            (
                NodeDef("a", "x", Scope.SHARD),
                NodeDef("b", "y", Scope.RUN),
            ),
        )
        edges = kw.pop("edges", ())
        return DagTemplate(id="t", domain_id="d", nodes=nodes, edges=edges)

    def test_duplicate_node_keys_rejected(self) -> None:
        t = self._tpl(nodes=(NodeDef("a", "x", Scope.SHARD), NodeDef("a", "y", Scope.SHARD)))
        with pytest.raises(TemplateError, match="duplicate"):
            t.validate()

    def test_dangling_edge_source_rejected(self) -> None:
        t = self._tpl(edges=(EdgeDef("missing", "a"),))
        with pytest.raises(TemplateError, match="source"):
            t.validate()

    def test_dangling_edge_target_rejected(self) -> None:
        t = self._tpl(edges=(EdgeDef("a", "missing"),))
        with pytest.raises(TemplateError, match="target"):
            t.validate()

    def test_self_edge_requires_serial_prev(self) -> None:
        t = self._tpl(
            nodes=(NodeDef("a", "x", Scope.SHARD),),
            edges=(EdgeDef("a", "a", EdgeKind.INTRA),),
        )
        with pytest.raises(TemplateError, match="SERIAL_PREV"):
            t.validate()

    def test_cycle_detected(self) -> None:
        t = self._tpl(
            nodes=(
                NodeDef("a", "x", Scope.SHARD),
                NodeDef("b", "y", Scope.SHARD),
                NodeDef("c", "z", Scope.SHARD),
            ),
            edges=(
                EdgeDef("a", "b"),
                EdgeDef("b", "c"),
                EdgeDef("c", "a"),  # cycle back
            ),
        )
        with pytest.raises(TemplateError, match="cycle"):
            t.validate()

    def test_fingerprint_stable_and_changes_on_edit(self) -> None:
        t1 = self._tpl()
        t2 = self._tpl()
        assert t1.fingerprint() == t2.fingerprint()
        t3 = self._tpl(nodes=(NodeDef("a", "x", Scope.SHARD), NodeDef("c", "z", Scope.RUN)))
        assert t1.fingerprint() != t3.fingerprint()


# --- Instantiator: edge kind resolution (T2.4) -------------------------------------------


def _shards(n: int) -> list[ShardPlan]:
    return [ShardPlan(shard_id=f"s{i}", index=i) for i in range(n)]


class TestInstantiatorIntra:
    def test_intra_links_same_shard(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("init", "e", Scope.RUN_ENTRY),
                NodeDef("ws", "ws", Scope.SHARD),
                NodeDef("work", "work", Scope.SHARD),
            ),
            edges=(
                EdgeDef("init", "ws", EdgeKind.RUN_ENTRY_ALL),
                EdgeDef("ws", "work", EdgeKind.INTRA),
            ),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(3))
        # Each shard's work node depends on its own ws node.
        for i in range(3):
            ws_id = f"r1__ws__s{i:03d}"
            work_id = f"r1__work__s{i:03d}"
            assert ws_id in graph.nodes[work_id].dependencies


class TestInstantiatorSerialPrev:
    def test_serial_prev_chains_across_shards(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(NodeDef("work", "work", Scope.SHARD),),
            edges=(EdgeDef("work", "work", EdgeKind.SERIAL_PREV),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(3))
        # shard 1 work depends on shard 0 work, shard 2 depends on shard 1.
        assert "r1__work__s000" in graph.nodes["r1__work__s001"].dependencies
        assert "r1__work__s001" in graph.nodes["r1__work__s002"].dependencies
        # shard 0 has no serial-prev dependency (it's first).
        assert "r1__work__s000" not in graph.nodes["r1__work__s000"].dependencies

    def test_serial_prev_with_single_shard_is_no_op(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(NodeDef("work", "work", Scope.SHARD),),
            edges=(EdgeDef("work", "work", EdgeKind.SERIAL_PREV),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(1))
        assert graph.nodes["r1__work__s000"].dependencies == set()


class TestInstantiatorAll:
    def test_all_fans_into_run_scope(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("work", "work", Scope.SHARD),
                NodeDef("report", "report", Scope.RUN),
            ),
            edges=(EdgeDef("work", "report", EdgeKind.ALL),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(3))
        report = graph.nodes["r1__report"]
        for i in range(3):
            assert f"r1__work__s{i:03d}" in report.dependencies


class TestInstantiatorLast:
    def test_last_links_to_final_shard_only(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("work", "work", Scope.SHARD),
                NodeDef("fixup", "fixup", Scope.RUN),
            ),
            edges=(EdgeDef("work", "fixup", EdgeKind.LAST),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(3))
        fixup = graph.nodes["r1__fixup"]
        assert "r1__work__s002" in fixup.dependencies
        assert "r1__work__s000" not in fixup.dependencies


class TestInstantiatorRunEntryAll:
    def test_run_entry_all_links_to_every_shard(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("init", "init", Scope.RUN_ENTRY),
                NodeDef("work", "work", Scope.SHARD),
            ),
            edges=(EdgeDef("init", "work", EdgeKind.RUN_ENTRY_ALL),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(2))
        for i in range(2):
            assert "r1__init" in graph.nodes[f"r1__work__s{i:03d}"].dependencies


class TestInstantiatorDynamic:
    def test_dynamic_seed_starts_unscheduled(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("scan", "scan", Scope.SHARD_DYNAMIC),
                NodeDef("report", "report", Scope.RUN),
            ),
            edges=(EdgeDef("scan", "report", EdgeKind.ALL),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(1))
        # Only the seed exists initially.
        assert graph.nodes["r1__scan"].is_dynamic_seed

    def test_expand_dynamic_adds_shard_nodes(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(NodeDef("scan", "scan", Scope.SHARD_DYNAMIC),),
            edges=(),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(1))
        new = expand_dynamic(
            graph=graph,
            template=tpl,
            seed_node_key="scan",
            shards=[ShardPlan(shard_id="s0", index=0), ShardPlan(shard_id="s1", index=1)],
        )
        assert len(new) == 2
        assert "r1__scan__s000" in graph.nodes
        assert "r1__scan__s001" in graph.nodes

    def test_expand_dynamic_is_idempotent(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(NodeDef("scan", "scan", Scope.SHARD_DYNAMIC),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(1))
        plan = [ShardPlan(shard_id="s0", index=0)]
        expand_dynamic(graph=graph, template=tpl, seed_node_key="scan", shards=plan)
        # Second call produces no new nodes.
        new = expand_dynamic(graph=graph, template=tpl, seed_node_key="scan", shards=plan)
        assert new == []


# --- Topological order + readiness (used by the engine) ----------------------------------


class TestGraphOrdering:
    def test_topological_order_respects_dependencies(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("init", "init", Scope.RUN_ENTRY),
                NodeDef("work", "work", Scope.SHARD),
                NodeDef("report", "report", Scope.RUN),
            ),
            edges=(
                EdgeDef("init", "work", EdgeKind.RUN_ENTRY_ALL),
                EdgeDef("work", "report", EdgeKind.ALL),
            ),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(2))
        order = graph.topological_order()
        # init before every work; every work before report.
        assert order.index("r1__init") < order.index("r1__work__s000")
        assert order.index("r1__work__s001") < order.index("r1__report")

    def test_ready_nodes_advances_as_deps_complete(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("init", "init", Scope.RUN_ENTRY),
                NodeDef("work", "work", Scope.SHARD),
                NodeDef("report", "report", Scope.RUN),
            ),
            edges=(
                EdgeDef("init", "work", EdgeKind.RUN_ENTRY_ALL),
                EdgeDef("work", "report", EdgeKind.ALL),
            ),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(2))
        done: set[str] = set()
        assert graph.ready_nodes(done) == ["r1__init"]
        done.add("r1__init")
        ready = graph.ready_nodes(done)
        assert "r1__work__s000" in ready and "r1__work__s001" in ready
        done.update(n for n in ready if n.startswith("r1__work"))
        assert graph.ready_nodes(done) == ["r1__report"]


# --- Context merge + edge maps (T2.3) ----------------------------------------------------


class TestContextMerge:
    def test_merge_left_to_right(self) -> None:
        from divdag_kernel.dag import ContextPatch

        a = ContextPatch(values={"x": 1}, source_node_run_id="a")
        b = ContextPatch(values={"y": 2}, source_node_run_id="b")
        merged = ContextPatch.merge(a, b)
        assert merged.values == {"x": 1, "y": 2}

    def test_parallel_conflict_raises(self) -> None:
        from divdag_kernel.dag import ContextConflictError, ContextPatch

        a = ContextPatch(values={"ok": True}, source_node_run_id="a")
        b = ContextPatch(values={"ok": False}, source_node_run_id="b")
        with pytest.raises(ContextConflictError) as exc:
            ContextPatch.merge(a, b)
        assert exc.value.key == "ok"

    def test_apply_edge_map_renames_keys(self) -> None:
        from divdag_kernel.dag import ContextPatch, apply_edge_map

        patch = ContextPatch(values={"timeline_path": "/x"}, source_node_run_id="a")
        mapped = apply_edge_map(patch, {"prev_timeline_path": "timeline_path"})
        assert mapped.values == {"prev_timeline_path": "/x"}

    def test_apply_edge_map_passthrough_unmapped(self) -> None:
        from divdag_kernel.dag import ContextPatch, apply_edge_map

        patch = ContextPatch(values={"a": 1, "b": 2}, source_node_run_id="x")
        mapped = apply_edge_map(patch, {"downstream_a": "a"})
        # 'b' passes through unchanged; 'a' is renamed to downstream_a.
        assert mapped.values == {"downstream_a": 1, "b": 2}
