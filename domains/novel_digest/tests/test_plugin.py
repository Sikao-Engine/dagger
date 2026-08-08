"""SPI assembly: the full NovelPlugin surface, wired through DomainRegistry."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from loom_kernel.dag import NodeContext, NodeRegistry
from loom_kernel.executors import ExecutorCatalog
from loom_kernel.review import Scanner
from loom_kernel.spi import DomainRegistry
from loom_kernel.state import K
from novel_digest.items import ChapterSource
from novel_digest.plugin import NovelPlugin, validate_digest_result
from novel_digest.review import NovelIntentDiff
from novel_digest.testing import make_book, make_chapter_product, write_product


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return make_book(tmp_path)


def _reg(book: Path):
    registry = DomainRegistry()
    reg = registry.register(NovelPlugin(source_dir=str(book)))
    catalog = ExecutorCatalog()
    nodes = NodeRegistry()
    registry.contribute_to(catalog, nodes)
    return reg, catalog, nodes


class TestSpiAssembly:
    def test_full_surface(self, book: Path) -> None:
        reg, catalog, nodes = _reg(book)
        plugin = reg.plugin
        assert plugin.id == "novel_digest"
        # Executors: 6 domain + the kernel's ensure_workspace.
        assert {e.key for e in reg.executors} == {
            "digest",
            "entity_merge",
            "timeline_merge",
            "volume_summary",
            "consistency_check",
            "final_report",
        }
        assert catalog.require("ensure_workspace").handler_kind == "builtin"
        # Handlers: domain merges + kernel builtin.
        assert nodes.handler_for("entity_merge") is not None
        assert nodes.handler_for("timeline_merge") is not None
        assert nodes.handler_for("ensure_workspace") is not None
        # Skills / validators / sharder.
        assert set(reg.skills) == {
            "novel-digest",
            "novel-volume-summary",
            "novel-consistency",
            "novel-final-report",
        }
        assert set(reg.validators) == {"digest"}
        assert reg.sharder is not None
        # Review surface.
        assert len(reg.scanners) == 5
        assert all(isinstance(s, Scanner) for s in reg.scanners)
        assert reg.intent_diff is not None
        assert reg.mock_outputs is not None
        # Template.
        assert reg.templates[0].id == "novel_digest_default"
        assert reg.templates[0].domain_id == "novel_digest"

    def test_artifact_spec_slots_match_k_coordinates(self, book: Path) -> None:
        reg, _, _ = _reg(book)
        spec = reg.artifact_spec
        assert spec is not None
        assert [s.name for s in spec.slots] == ["raw", "summary", "entities", "timeline", "issues"]
        for slot in spec.slots:
            key = K.artifact_item("ch_0001", slot.name)  # must not raise
            assert key.slot == slot.name

    def test_web_manifest(self, book: Path) -> None:
        reg, _, _ = _reg(book)
        manifest = reg.plugin.web_manifest()
        assert manifest["id"] == "novel_digest"
        assert manifest["label"] == "Novel Digest"
        assert manifest["bundle"] == "domains/novel_digest/index.ts"
        assert "itemRowExtra" in manifest["slots"]
        assert "reviewDetailTabs" in manifest["slots"]
        assert "/timeline" in manifest["routes"]

    def test_intent_diff_both_sides(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        write_product(out, "ch_0001", make_chapter_product("ch_0001"))
        provider = NovelIntentDiff(source_dir=book, digest_root=out)
        snap = asyncio.run(ChapterSource(book).refresh(type("Ws", (), {"root": book})()))
        item = snap.items[0]
        left = provider.intent(item)
        right = provider.outcome(item)
        assert left and "第1章" in left
        assert right and "摘要" in right

    def test_mock_outputs_shapes(self, book: Path) -> None:
        plugin = NovelPlugin(source_dir=str(book))
        ctx = NodeContext(
            shard={
                "shard_id": "shard-000",
                "index": 0,
                "item_count": 3,
                "items": ["a", "b", "c"],
            },
            ancestor_patches={},
        )
        assert plugin.mock_outputs("volume_summary", ctx) == {"volume_ok": True}
        assert plugin.mock_outputs("consistency_check", ctx) == {"consistency_ok": True}
        assert plugin.mock_outputs("final_report", ctx) == {"report_ok": True}
        assert plugin.mock_outputs("unknown_type", ctx) is None


class TestDigestValidator:
    def test_accepts_matching_count(self) -> None:
        body = {"outputs": {"digest_ok": True, "chapters_done": 3}}
        ctx = {"shard": {"item_count": 3}}
        assert validate_digest_result(body, node_run_id="n", context=ctx) == []

    def test_rejects_off_by_one(self) -> None:
        body = {"outputs": {"digest_ok": True, "chapters_done": 2}}
        ctx = {"shard": {"item_count": 3}}
        errors = validate_digest_result(body, node_run_id="n", context=ctx)
        assert any("chapters_done" in e for e in errors)

    def test_rejects_not_ok(self) -> None:
        body = {"outputs": {"digest_ok": False, "chapters_done": 3}}
        errors = validate_digest_result(body, node_run_id="n", context=None)
        assert any("digest_ok" in e for e in errors)
