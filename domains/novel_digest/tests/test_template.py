"""Step 2: DAG topology — the §14.2 template, transcribed verbatim.

Pins: validate() passes, 8 nodes / 9 edges, fingerprint stability, the
SERIAL_PREV edge with its maps, the two ALL fan-in edges, and the run-level
INTRA edge consistency → final_report (kernel K1) instantiated into real
dependencies.
"""

from __future__ import annotations

from loom_kernel.dag import EdgeKind, instantiate
from loom_kernel.dag.instantiator import ShardPlan
from novel_digest.templates import build_template


def _shards(n: int) -> list[ShardPlan]:
    return [ShardPlan(shard_id=f"shard-{i:03d}", index=i, items=(f"ch_{i:04d}",)) for i in range(n)]


class TestTemplateShape:
    def test_validate_passes(self) -> None:
        build_template(".").validate()  # must not raise

    def test_eight_nodes_nine_edges(self) -> None:
        tpl = build_template(".")
        assert len(tpl.nodes) == 8
        assert len(tpl.edges) == 9
        assert [n.key for n in tpl.nodes] == [
            "init",
            "shard_ws",
            "digest",
            "entity_merge",
            "timeline_merge",
            "volume_summary",
            "consistency",
            "final_report",
        ]

    def test_fingerprint_stable(self) -> None:
        assert build_template(".").fingerprint() == build_template(".").fingerprint()
        # Sanity: a topology change must change the fingerprint.
        other = build_template(".")
        object.__setattr__(other, "nodes", other.nodes[:-1])
        assert other.fingerprint() != build_template(".").fingerprint()

    def test_serial_prev_edge_maps(self) -> None:
        tpl = build_template(".")
        serial = [e for e in tpl.edges if e.kind is EdgeKind.SERIAL_PREV]
        assert len(serial) == 1
        assert serial[0].source == serial[0].target == "timeline_merge"
        assert serial[0].maps == {"prev_timeline_path": "timeline_path"}

    def test_two_all_edges_into_consistency(self) -> None:
        tpl = build_template(".")
        alls = [e for e in tpl.edges if e.kind is EdgeKind.ALL]
        assert {(e.source, e.target) for e in alls} == {
            ("entity_merge", "consistency"),
            ("volume_summary", "consistency"),
        }

    def test_ensure_workspace_variants(self) -> None:
        tpl = build_template("/ws")
        init = tpl.node("init")
        shard_ws = tpl.node("shard_ws")
        assert init.node_type == shard_ws.node_type == "ensure_workspace"
        assert init.params["variant"] == "root"
        assert init.params["workspace_root"] == "/ws"
        assert shard_ws.params["variant"] == "shard"


class TestTemplateInstantiation:
    """K1 evidence: the run-level INTRA edge becomes a real dependency."""

    def test_run_level_intra_instantiates(self) -> None:
        tpl = build_template(".")
        graph = instantiate(template=tpl, run_id="run_t", shards=_shards(2))
        assert graph.nodes["run_t__final_report"].dependencies == {"run_t__consistency"}

    def test_full_shape_two_shards(self) -> None:
        tpl = build_template(".")
        graph = instantiate(template=tpl, run_id="run_t", shards=_shards(2))
        assert len(graph.nodes) == 13  # 1 init + 2×5 shard nodes + 2 run nodes
        # Serial chain: timeline_merge s001 waits on s000.
        assert (
            "run_t__timeline_merge__s000" in graph.nodes["run_t__timeline_merge__s001"].dependencies
        )
        # ALL fan-in: consistency waits on every shard's entity_merge + volume_summary.
        assert graph.nodes["run_t__consistency"].dependencies == {
            "run_t__entity_merge__s000",
            "run_t__entity_merge__s001",
            "run_t__volume_summary__s000",
            "run_t__volume_summary__s001",
        }
        # Entry fan-out: every shard_ws waits on init.
        for i in range(2):
            assert graph.nodes[f"run_t__shard_ws__s{i:03d}"].dependencies == {"run_t__init"}
        graph.topological_order()  # acyclic
