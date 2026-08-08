"""M-A equivalent end-to-end: engine + mock dispatcher over the real plugin.

Five chapters, two shards, thirteen nodes. Pins: full completion without
failures/skips/conflicts, the SERIAL_PREV timeline accumulation order, the
store's verify() integrity, idempotent re-run (zero dispatches), the K3
result-contract enforcement (produces subset + digest validator), and the
artifact slot round-trip (D9).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from loom_kernel.dag import NodeRegistry
from loom_kernel.dag.instantiator import ShardPlan, instantiate
from loom_kernel.engine import run_graph
from loom_kernel.executors import ExecutorCatalog
from loom_kernel.spi import DomainRegistry
from loom_kernel.state import K, StateStore
from novel_digest.plugin import NovelPlugin
from novel_digest.testing import make_book

SHARD_ITEMS = (("ch_0001", "ch_0002", "ch_0003"), ("ch_0004", "ch_0005"))


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return make_book(tmp_path)


def _assemble(book: Path):
    plugin = NovelPlugin(source_dir=str(book))
    registry = DomainRegistry()
    reg = registry.register(plugin)
    catalog = ExecutorCatalog()
    nodes = NodeRegistry()
    registry.contribute_to(catalog, nodes)
    return reg, catalog, nodes


def _make_dispatcher(reg: Any, calls: list[str]):
    """Mirror of the CLI's mock dispatcher (both share the mock_outputs hook)."""

    def _dispatch(*, node_run, ctx, executor, store, attempt) -> dict[str, Any]:
        calls.append(node_run.node_run_id)
        if reg.mock_outputs is not None:
            out = reg.mock_outputs(node_run.node_type, ctx)
            if out is not None:
                return dict(out)
        skill = reg.skills.get(executor.skill or "")
        if skill is None:
            return {}
        return {k: True for k in sorted(set(skill.produces) | {skill.success_key})}

    return _dispatch


def _plans() -> list[ShardPlan]:
    return [
        ShardPlan(shard_id="shard-000", index=0, items=SHARD_ITEMS[0]),
        ShardPlan(shard_id="shard-001", index=1, items=SHARD_ITEMS[1]),
    ]


def _seed_item_ledger(reg: Any, book: Path, store: StateStore) -> None:
    snap = asyncio.run(reg.plugin.item_source().refresh(type("Ws", (), {"root": str(book)})()))
    for it in snap.items:
        store.write_json(
            K.item(it.id), it.to_dict(), kind="work_item", written_by={"role": "orchestrator"}
        )


class TestWalkthrough:
    def test_full_run_two_shards(self, book: Path, tmp_path: Path) -> None:
        reg, catalog, nodes = _assemble(book)
        run_id = "run_walk"
        store = StateStore(tmp_path / "state", run_id=run_id)
        _seed_item_ledger(reg, book, store)

        # Spy on timeline_merge to observe the prev_timeline_path injection.
        real_tm = nodes.handler_for("timeline_merge")
        assert real_tm is not None
        spy_seen: dict[str, dict[str, Any]] = {}

        class _TimelineSpy:
            contract = real_tm.contract

            def run(self, ctx):  # type: ignore[no-untyped-def]
                spy_seen[str(ctx["shard_id"])] = {"prev": ctx.get("prev_timeline_path")}
                return real_tm.run(ctx)

        nodes.register("timeline_merge", _TimelineSpy())

        tpl = reg.templates[0]
        tpl.validate()
        graph = instantiate(template=tpl, run_id=run_id, shards=_plans(), node_registry=nodes)
        assert len(graph.nodes) == 13

        calls: list[str] = []
        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_make_dispatcher(reg, calls),
            skills=reg.skills,
            validators=reg.validators,
        )
        store.save_index()

        # Full completion: no failures, no skips, no ContextConflictError.
        assert len(result.completed) == 13
        assert not result.failed
        assert not result.skipped

        # SERIAL_PREV order: timeline_merge s001 ran after s000 ...
        t0_id = f"{run_id}__timeline_merge__s000"
        t1_id = f"{run_id}__timeline_merge__s001"
        assert result.completed.index(t1_id) > result.completed.index(t0_id)
        # ... and s001's ctx carried prev_timeline_path pointing at s000's product.
        prev = spy_seen["shard-001"]["prev"]
        assert prev is not None and str(prev).endswith("timeline.json")
        assert "shard-000" in str(prev)
        # Accumulation: s001's timeline contains s000's events followed by its own.
        t0_body = json.loads(Path(str(prev)).read_text(encoding="utf-8"))
        t1_body = json.loads(
            Path(str(result.context_outputs[t1_id]["timeline_path"])).read_text(encoding="utf-8")
        )
        assert [e["chapter"] for e in t1_body["events"]] == [
            *[e["chapter"] for e in t0_body["events"]],
            4,
            5,
        ]

        # The mock digest wrote real chapter products; merge nodes consumed them.
        shard0 = book / run_id / "shard-000"
        assert (shard0 / "ch_0001.json").exists()
        assert (shard0 / "entities.json").exists()
        assert (shard0 / "timeline.json").exists()

        # §14.3 state tree shape: control/items + contract results.
        assert store.path(K.item("ch_0001")).exists()
        contract_results = store.query(layer="contract", kind="session_result")
        assert len(contract_results) == 13

        # The digest validator genuinely ran (chapters_done == shard item count).
        digest0 = store.read_json(K.result(f"{run_id}__digest__s000", 1))
        assert digest0 is not None
        assert digest0["outputs"]["chapters_done"] == 3

        # D9: artifact slot write → query round-trip with the declared slot name.
        store.write_bytes(
            K.artifact_item("ch_0001", "summary"),
            "# 摘要\n\nmock slot content".encode(),
            kind="artifact",
            written_by={"role": "agent", "backend": "mock"},
        )
        refs = store.query(layer="artifact", item_id="ch_0001", slot="summary")
        assert len(refs) == 1
        assert refs[0].path.read_bytes().startswith(b"# ")

        # Integrity: sha256 + index consistent.
        store.save_index()
        assert store.verify() == []

        # Idempotent re-run: same store, fresh graph → zero dispatches.
        graph2 = instantiate(template=tpl, run_id=run_id, shards=_plans(), node_registry=nodes)
        calls.clear()
        result2 = run_graph(
            graph=graph2,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_make_dispatcher(reg, calls),
            skills=reg.skills,
            validators=reg.validators,
        )
        assert calls == []
        assert len(result2.completed) == 13

    def test_undeclared_output_key_is_rejected(self, book: Path, tmp_path: Path) -> None:
        """K3: an agent writing a key outside produces fails the node (retryable)."""
        reg, catalog, nodes = _assemble(book)
        store = StateStore(tmp_path / "state", run_id="run_walk")
        tpl = reg.templates[0]
        graph = instantiate(template=tpl, run_id="run_walk", shards=_plans(), node_registry=nodes)

        def _rogue(*, node_run, ctx, executor, store, attempt) -> dict[str, Any]:
            if node_run.node_type == "digest":
                return {"digest_ok": True, "chapters_done": 3, "rogue_key": 1}
            out = reg.mock_outputs(node_run.node_type, ctx)
            return dict(out) if out is not None else {}

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_rogue,
            max_node_retries=1,
            skills=reg.skills,
            validators=reg.validators,
        )
        assert "run_walk__digest__s000" in result.failed
        assert "run_walk__entity_merge__s000" in result.skipped
        assert "run_walk__final_report" in result.skipped

    def test_validator_catches_missed_chapter(self, book: Path, tmp_path: Path) -> None:
        """K3: the digest ResultValidator catches the off-by-one (漏章) case."""
        reg, catalog, nodes = _assemble(book)
        store = StateStore(tmp_path / "state", run_id="run_walk")
        tpl = reg.templates[0]
        graph = instantiate(template=tpl, run_id="run_walk", shards=_plans(), node_registry=nodes)

        def _off_by_one(*, node_run, ctx, executor, store, attempt) -> dict[str, Any]:
            if node_run.node_type == "digest":
                values = ctx.values()
                count = int(ctx.shard["item_count"]) - 1  # one chapter short
                return {
                    "digest_ok": True,
                    "chapters_done": count,
                    "shard_out_dir": str(values.get("shard_out_dir", "")),
                    "run_out_dir": str(values.get("run_out_dir", "")),
                    "workspace_root": str(values.get("workspace_root", "")),
                }
            out = reg.mock_outputs(node_run.node_type, ctx)
            return dict(out) if out is not None else {}

        result = run_graph(
            graph=graph,
            template=tpl,
            store=store,
            catalog=catalog,
            node_registry=nodes,
            agent_dispatcher=_off_by_one,
            max_node_retries=2,
            skills=reg.skills,
            validators=reg.validators,
        )
        assert "run_walk__digest__s000" in result.failed
        assert "run_walk__digest__s001" in result.failed
