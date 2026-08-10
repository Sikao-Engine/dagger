"""Instantiator tests: edge-kind resolution, incl. run-level INTRA (K1).

Pinned semantics:
- INTRA between two RUN/RUN_ENTRY nodes links the single instances (run-level
  sequential edge — the §14.2 `consistency -> final_report` case).
- INTRA between SHARD nodes links same-shard instances.
- INTRA mixing SHARD and RUN scopes raises InstantiateError.
- The tiny template's expansion is unchanged (regression guard).
"""

from __future__ import annotations

import pytest
from dagger_kernel.dag import (
    DagTemplate,
    EdgeDef,
    EdgeKind,
    NodeDef,
    Scope,
    instantiate,
)
from dagger_kernel.dag.instantiator import InstantiateError, ShardPlan


def _shards(n: int) -> list[ShardPlan]:
    return [ShardPlan(shard_id=f"s{i}", index=i, items=(f"item-{i}",)) for i in range(n)]


class TestRunLevelIntra:
    """K1: INTRA edges between run-scoped nodes link the single instances."""

    def test_run_to_run_intra_links_single_instances(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("consistency", "d.check", Scope.RUN, priority=40),
                NodeDef("final_report", "d.report", Scope.RUN, priority=50),
            ),
            edges=(EdgeDef("consistency", "final_report"),),  # default kind = INTRA
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(2))
        assert graph.nodes["r1__final_report"].dependencies == {"r1__consistency"}

    def test_run_entry_to_run_intra_links_single_instances(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("init", "d.init", Scope.RUN_ENTRY, priority=0),
                NodeDef("report", "d.report", Scope.RUN, priority=50),
            ),
            edges=(EdgeDef("init", "report", EdgeKind.INTRA),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(1))
        assert graph.nodes["r1__report"].dependencies == {"r1__init"}

    def test_shard_to_run_intra_still_raises(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("work", "d.work", Scope.SHARD),
                NodeDef("report", "d.report", Scope.RUN),
            ),
            edges=(EdgeDef("work", "report", EdgeKind.INTRA),),
        )
        with pytest.raises(InstantiateError, match="INTRA"):
            instantiate(template=tpl, run_id="r1", shards=_shards(2))

    def test_shard_to_shard_intra_unchanged(self) -> None:
        tpl = DagTemplate(
            id="t",
            domain_id="d",
            nodes=(
                NodeDef("a", "d.a", Scope.SHARD),
                NodeDef("b", "d.b", Scope.SHARD),
            ),
            edges=(EdgeDef("a", "b", EdgeKind.INTRA),),
        )
        graph = instantiate(template=tpl, run_id="r1", shards=_shards(2))
        assert graph.nodes["r1__b__s000"].dependencies == {"r1__a__s000"}
        assert graph.nodes["r1__b__s001"].dependencies == {"r1__a__s001"}


class TestTinyTemplateRegression:
    """The tiny walking-skeleton template expands exactly as before K1."""

    def test_tiny_expansion(self) -> None:
        tpl = DagTemplate(
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
        graph = instantiate(template=tpl, run_id="run_e2e", shards=_shards(3))
        assert set(graph.nodes) == {
            "run_e2e__init",
            "run_e2e__work__s000",
            "run_e2e__work__s001",
            "run_e2e__work__s002",
            "run_e2e__report",
        }
        for i in range(3):
            assert graph.nodes[f"run_e2e__work__s{i:03d}"].dependencies == {"run_e2e__init"}
        assert graph.nodes["run_e2e__report"].dependencies == {
            "run_e2e__work__s000",
            "run_e2e__work__s001",
            "run_e2e__work__s002",
        }
        assert graph.topological_order()  # no cycle


class TestNovelDigestShapeExpansion:
    """The §14.2 shape (which K1 unblocks) expands: SERIAL_PREV + ALL + run INTRA."""

    def test_serial_prev_and_all_and_run_intra(self) -> None:
        tpl = DagTemplate(
            id="novel_digest_default",
            domain_id="novel_digest",
            nodes=(
                NodeDef("init", "ensure_workspace", Scope.RUN_ENTRY, params={"variant": "root"}),
                NodeDef("shard_ws", "ensure_workspace", Scope.SHARD, params={"variant": "shard"}),
                NodeDef("timeline_merge", "tm", Scope.SHARD, priority=21),
                NodeDef("volume_summary", "vs", Scope.SHARD, priority=30),
                NodeDef("consistency", "cc", Scope.RUN, priority=40),
                NodeDef("final_report", "fr", Scope.RUN, priority=50),
            ),
            edges=(
                EdgeDef("init", "shard_ws", EdgeKind.RUN_ENTRY_ALL),
                EdgeDef(
                    "timeline_merge",
                    "timeline_merge",
                    EdgeKind.SERIAL_PREV,
                    maps={"prev_timeline_path": "timeline_path"},
                ),
                EdgeDef("timeline_merge", "volume_summary"),
                EdgeDef("volume_summary", "consistency", EdgeKind.ALL),
                EdgeDef("consistency", "final_report"),
            ),
        )
        tpl.validate()
        graph = instantiate(template=tpl, run_id="r9", shards=_shards(3))
        # SERIAL_PREV: tm[s1] waits on tm[s0]; tm[s0] does not wait on any tm.
        assert "r9__timeline_merge__s000" in graph.nodes["r9__timeline_merge__s001"].dependencies
        assert not any(
            d.startswith("r9__timeline_merge")
            for d in graph.nodes["r9__timeline_merge__s000"].dependencies
        )
        # ALL: consistency waits on every shard's volume_summary.
        assert graph.nodes["r9__consistency"].dependencies == {
            f"r9__volume_summary__s{i:03d}" for i in range(3)
        }
        # Run-level INTRA (K1): final_report waits on the single consistency.
        assert graph.nodes["r9__final_report"].dependencies == {"r9__consistency"}
