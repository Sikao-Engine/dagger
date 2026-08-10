"""The two builtin merge nodes: deterministic behavior + contract fail-fast."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dagger_kernel.dag import NodeContext
from dagger_kernel.dag.nodes import ContractError
from novel_digest.nodes.entity_merge import EntityMergeNode, merge_entities
from novel_digest.nodes.timeline_merge import TimelineMergeNode, accumulate_timeline
from novel_digest.testing import make_chapter_product, write_product


def _ctx(
    shard_out: Path, items: list[str], shard_id: str = "shard-000", **extra: object
) -> NodeContext:
    return NodeContext(
        shard_seed={"shard_id": shard_id, "shard_index": 0},
        ancestor_patches={"shard_out_dir": str(shard_out), **extra},
        shard={
            "shard_id": shard_id,
            "index": 0,
            "item_count": len(items),
            "items": items,
            "first_item": {"id": items[0]} if items else None,
            "last_item": {"id": items[-1]} if items else None,
        },
    )


class TestMergeEntitiesPure:
    def test_aliases_union_and_first_seen_min(self) -> None:
        a = make_chapter_product("ch_0002")
        a["entities"] = [
            {
                "name": "韩立",
                "type": "person",
                "aliases": ["韩老魔"],
                "first_seen_chapter": "ch_0002",
            }
        ]
        b = make_chapter_product("ch_0001")
        b["entities"] = [
            {
                "name": "韩立",
                "type": "person",
                "aliases": ["厉飞雨"],
                "first_seen_chapter": "ch_0001",
            }
        ]
        merged = merge_entities([a, b])
        assert merged == [
            {
                "name": "韩立",
                "type": "person",
                "aliases": ["厉飞雨", "韩老魔"],
                "first_seen_chapter": "ch_0001",
            }
        ]

    def test_deterministic_under_input_shuffle(self) -> None:
        chapters = [make_chapter_product(f"ch_{i:04d}") for i in (3, 1, 2)]
        assert merge_entities(chapters) == merge_entities(list(reversed(chapters)))


class TestEntityMergeNode:
    def test_merges_shard_products(self, tmp_path: Path) -> None:
        out = tmp_path / "shard-000"
        for cid in ("ch_0001", "ch_0002"):
            write_product(out, cid, make_chapter_product(cid))
        node = EntityMergeNode()
        patch = node.run(_ctx(out, ["ch_0001", "ch_0002"]))
        assert patch.values == {"entities_ok": True}
        table = json.loads((out / "entities.json").read_text(encoding="utf-8"))
        assert table["shard_id"] == "shard-000"
        assert [e["name"] for e in table["entities"]] == ["韩立"]

    def test_missing_chapter_product_fails_fast(self, tmp_path: Path) -> None:
        node = EntityMergeNode()
        with pytest.raises(ContractError, match="chapter product missing"):
            node.run(_ctx(tmp_path / "nowhere", ["ch_0001"]))

    def test_contract_fail_fast_on_missing_reads(self) -> None:
        node = EntityMergeNode()
        with pytest.raises(ContractError, match="shard_out_dir"):
            node.contract.assert_reads_present(NodeContext())


class TestTimelineMergeNode:
    def test_first_shard_without_prev(self, tmp_path: Path) -> None:
        out = tmp_path / "shard-000"
        for cid in ("ch_0001", "ch_0002", "ch_0003"):
            write_product(out, cid, make_chapter_product(cid))
        node = TimelineMergeNode()
        patch = node.run(_ctx(out, ["ch_0001", "ch_0002", "ch_0003"]))
        assert patch.values["timeline_ok"] is True
        body = json.loads(Path(patch.values["timeline_path"]).read_text(encoding="utf-8"))
        assert body["event_count"] == 3
        assert [e["chapter"] for e in body["events"]] == [1, 2, 3]

    def test_serial_accumulation_reads_prev(self, tmp_path: Path) -> None:
        out0 = tmp_path / "shard-000"
        out1 = tmp_path / "shard-001"
        for cid in ("ch_0001", "ch_0002", "ch_0003"):
            write_product(out0, cid, make_chapter_product(cid))
        for cid in ("ch_0004", "ch_0005"):
            write_product(out1, cid, make_chapter_product(cid))
        node = TimelineMergeNode()
        first = node.run(_ctx(out0, ["ch_0001", "ch_0002", "ch_0003"], shard_id="shard-000"))
        second = node.run(
            _ctx(
                out1,
                ["ch_0004", "ch_0005"],
                shard_id="shard-001",
                prev_timeline_path=first.values["timeline_path"],
            )
        )
        body = json.loads(Path(second.values["timeline_path"]).read_text(encoding="utf-8"))
        assert body["event_count"] == 5  # 3 accumulated + 2 own
        assert [e["chapter"] for e in body["events"]] == [1, 2, 3, 4, 5]

    def test_accumulate_timeline_pure(self) -> None:
        prev = [{"event": "e0", "chapter": 1, "participants": [], "anchors": []}]
        chapters = [make_chapter_product("ch_0002")]
        events = accumulate_timeline(prev, chapters)
        assert [e["chapter"] for e in events] == [1, 2]
