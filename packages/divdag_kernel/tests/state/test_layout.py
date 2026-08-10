"""Layout + StateKey invariants. Pinned to the design spec; any change here is a layout bump."""

from __future__ import annotations

import pytest
from divdag_kernel.state import K, Layer, Scope, StateKey, StateKeyError, layout

# --- StateKey construction invariants (T1.1) ----------------------------------------------


class TestStateKeyInvariants:
    def test_frozen_and_hashable(self) -> None:
        k = K.result("nr_0f3a", 3)
        assert hash(k) == hash(K.result("nr_0f3a", 3))
        with pytest.raises(StateKeyError):
            k.layer = Layer.LOG  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("factory", "kwargs"),
        [
            (StateKey, {"layer": Layer.CONTRACT, "scope": Scope.NODE_RUN, "attempt": 1}),
            (StateKey, {"layer": Layer.SCRATCH, "scope": Scope.NODE_RUN, "attempt": 1}),
            (StateKey, {"layer": Layer.LOG, "scope": Scope.NODE_RUN, "attempt": 1}),
            (StateKey, {"layer": Layer.ARTIFACT, "scope": Scope.RUN}),
            (StateKey, {"layer": Layer.ARTIFACT, "scope": Scope.SHARD, "slot": "summary"}),
            (StateKey, {"layer": Layer.ARTIFACT, "scope": Scope.ITEM, "item_id": "ch_1"}),
        ],
    )
    def test_illegal_combinations_raise(self, factory: type, kwargs: dict[str, object]) -> None:
        with pytest.raises(StateKeyError):
            factory(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "bad_id",
        ["", "a/b", "a\\b", ".", "..", "a/b/c"],
    )
    def test_unsafe_ids_rejected(self, bad_id: str) -> None:
        with pytest.raises(StateKeyError):
            StateKey(Layer.CONTROL, Scope.ITEM, item_id=bad_id, slot="item")

    def test_attempt_must_be_positive(self) -> None:
        with pytest.raises(StateKeyError):
            StateKey(
                Layer.CONTRACT,
                Scope.NODE_RUN,
                node_run_id="nr_1",
                attempt=0,
                slot="result",
            )

    def test_to_from_dict_roundtrip(self) -> None:
        k = K.result("nr_0f3a", 3)
        d = k.to_dict()
        assert d["layer"] == "contract"
        assert d["node_run_id"] == "nr_0f3a"
        assert d["attempt"] == 3
        assert StateKey.from_dict(d) == k

    def test_to_dict_omits_none(self) -> None:
        k = K.artifact_item("ch_1", "summary")
        d = k.to_dict()
        assert "node_run_id" not in d
        assert "attempt" not in d
        assert d["item_id"] == "ch_1"


# --- Layout function: the pinned path map (T1.2) -------------------------------------------


class TestLayoutControl:
    def test_run_json(self) -> None:
        assert str(layout(K.run_config())) == "run.json"

    def test_plan(self) -> None:
        assert str(layout(K.plan())) == "control/plan.json"

    def test_run_cursor(self) -> None:
        assert str(layout(K.cursor())) == "control/cursor.json"

    def test_shard_cursor(self) -> None:
        assert str(layout(K.cursor("shard-02"))) == "control/cursor-shard-02.json"

    def test_items_jsonl(self) -> None:
        assert str(layout(K.items())) == "control/items.jsonl"

    def test_item(self) -> None:
        assert str(layout(K.item("ch_0413"))) == "control/items/ch_0413/item.json"

    def test_node_def(self) -> None:
        assert str(layout(K.node_def("nr_0f3a"))) == "control/nodes/nr_0f3a/node.json"

    def test_node_context(self) -> None:
        assert str(layout(K.node_context("nr_0f3a"))) == "control/nodes/nr_0f3a/context.json"

    def test_latest_attempt_pointer(self) -> None:
        assert str(layout(K.latest_attempt("nr_0f3a"))) == "control/nodes/nr_0f3a/latest_attempt"


class TestLayoutContract:
    def test_task_card(self) -> None:
        assert str(layout(K.task_card("nr_0f3a", 3))) == "contract/nr_0f3a/attempt-3/task_card.json"

    def test_result(self) -> None:
        assert str(layout(K.result("nr_0f3a", 3))) == "contract/nr_0f3a/attempt-3/result.json"

    def test_claim(self) -> None:
        assert str(layout(K.claim("nr_0f3a", 3))) == "contract/nr_0f3a/attempt-3/claim.json"


class TestLayoutScratch:
    def test_scratch_root_is_directory_path(self) -> None:
        assert str(layout(K.scratch_root("nr_0f3a", 3))) == "scratch/nr_0f3a/attempt-3"


class TestLayoutLog:
    def test_transcript(self) -> None:
        assert str(layout(K.transcript("nr_0f3a", 3))) == "log/nr_0f3a/attempt-3/transcript.jsonl"

    def test_commands(self) -> None:
        assert str(layout(K.commands("nr_0f3a", 3))) == "log/nr_0f3a/attempt-3/commands.log"

    def test_progress(self) -> None:
        assert str(layout(K.progress("nr_0f3a", 3))) == "log/nr_0f3a/attempt-3/progress.jsonl"


class TestLayoutArtifact:
    def test_run_artifact(self) -> None:
        assert str(layout(K.artifact_run("report"))) == "artifact/run/report.json"

    def test_shard_artifact(self) -> None:
        assert (
            str(layout(K.artifact_shard("shard-02", "review")))
            == "artifact/shards/shard-02/review.json"
        )

    def test_item_artifact(self) -> None:
        assert (
            str(layout(K.artifact_item("ch_0413", "summary")))
            == "artifact/items/ch_0413/summary.json"
        )

    def test_item_meta(self) -> None:
        assert str(layout(K.artifact_item_meta("ch_0413"))) == "artifact/items/ch_0413/_meta.json"

    def test_slot_with_extension_preserved(self) -> None:
        # When the slot itself contains a '.', it's used verbatim (e.g. summary.md).
        k = StateKey(Layer.ARTIFACT, Scope.ITEM, item_id="ch_1", slot="summary.md")
        assert str(layout(k)) == "artifact/items/ch_1/summary.md"


# --- Non-ASCII and long IDs (T1.2 file-name safety) ----------------------------------------


class TestLayoutEdgeCases:
    def test_non_ascii_item_id(self) -> None:
        # Layout must not destroy non-ASCII information.
        k = K.artifact_item("章_0413", "summary")
        assert str(layout(k)) == "artifact/items/章_0413/summary.json"

    def test_long_id_passes_through(self) -> None:
        long_id = "x" * 200
        k = K.result(long_id, 1)
        assert str(layout(k)) == f"contract/{long_id}/attempt-1/result.json"

    def test_id_with_dashes_ok(self) -> None:
        k = K.artifact_shard("shard-02-abc", "review")
        assert str(layout(k)) == "artifact/shards/shard-02-abc/review.json"
