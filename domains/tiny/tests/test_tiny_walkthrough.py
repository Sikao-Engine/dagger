"""E2E: loom run --domain tiny produces a complete, verifiable state tree.

This is the M4 walking-skeleton acceptance test. Uses the mock dispatcher
(shortcuts the real SessionRunner); a real-backend run is a manual check.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from loom_kernel.dag import NodeRegistry
from loom_kernel.dag.instantiator import instantiate
from loom_kernel.dag.nodes import NodeContract
from loom_kernel.engine import run_graph
from loom_kernel.executors import ExecutorCatalog
from loom_kernel.planning import fixed_size
from loom_kernel.planning.item import WorkItem
from loom_kernel.state import K, StateStore
from tiny.plugin import TinyPlugin


class _NoopInit:
    contract = NodeContract(writes=("initialized",))

    def run(self, ctx):
        from loom_kernel.dag import ContextPatch

        return ContextPatch(values={"initialized": True})


def _mock_dispatcher(store: StateStore):
    """A dispatcher that writes success for work/report nodes."""

    def _dispatch(*, node_run, ctx, executor, store, attempt):
        outputs = {"work_ok": True} if node_run.node_key == "work" else {"report_ok": True}
        store.write_json(
            K.result(node_run.node_run_id, attempt),
            {
                "status": "success",
                "success": True,
                "node_run_id": node_run.node_run_id,
                "node_type": node_run.node_type,
                "skill": executor.skill or "",
                "outputs": outputs,
            },
            kind="session_result",
            written_by={"role": "agent", "backend": "mock"},
        )
        return outputs

    return _dispatch


def _make_test_data(root: Path) -> list[WorkItem]:
    for name in ("a.txt", "b.txt", "c.txt"):
        (root / name).write_text(f"content of {name}", encoding="utf-8")
    return [
        WorkItem(id=p.stem, seq=i, title=p.stem, payload={"path": str(p)})
        for i, p in enumerate(sorted(root.glob("*.txt")))
    ]


def test_tiny_end_to_end(tmp_path: Path) -> None:
    # 1. Create source data.
    src = tmp_path / "items"
    src.mkdir()
    items = _make_test_data(src)

    # 2. Assemble domain via the plugin.
    plugin = TinyPlugin(source_dir=src)
    catalog = ExecutorCatalog()
    for spec in plugin.executors():
        catalog.register(spec)
    nodes = NodeRegistry()
    nodes.register("tiny.init", _NoopInit())
    template = plugin.templates()[0]
    template.validate()

    # 3. Shard + instantiate.
    plans = fixed_size(items, [], {"size": 1})
    assert len(plans) == 3
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    store = StateStore(tmp_path / "run", run_id=run_id)
    graph = instantiate(template=template, run_id=run_id, shards=plans, node_registry=nodes)

    # 4. Run.
    result = run_graph(
        graph=graph,
        template=template,
        store=store,
        catalog=catalog,
        node_registry=nodes,
        agent_dispatcher=_mock_dispatcher(store),
    )
    store.save_index()

    # 5. Assertions: 5 nodes completed (init + 3 work + report), state tree intact.
    assert len(result.completed) == 5
    assert not result.failed
    assert not result.skipped

    # The contract layer holds one result.json per node.
    contract_artifacts = store.query(layer="contract")
    assert len(contract_artifacts) == 5
    kinds = {a.kind for a in contract_artifacts}
    assert kinds == {"session_result"}

    # verify() passes — sha256 + index consistent.
    problems = store.verify()
    assert problems == []

    # Each result body has success=True.
    for a in contract_artifacts:
        env = store.read_envelope(a.key)
        assert env is not None
        assert env.body["success"] is True


def test_tiny_resume_skips_completed(tmp_path: Path) -> None:
    """Re-running an already-completed run is idempotent (no re-dispatch)."""
    src = tmp_path / "items"
    src.mkdir()
    items = _make_test_data(src)
    plugin = TinyPlugin(source_dir=src)
    catalog = ExecutorCatalog()
    for spec in plugin.executors():
        catalog.register(spec)
    nodes = NodeRegistry()
    nodes.register("tiny.init", _NoopInit())
    template = plugin.templates()[0]
    plans = fixed_size(items, [], {"size": 1})
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    store = StateStore(tmp_path / "run", run_id=run_id)
    graph = instantiate(template=template, run_id=run_id, shards=plans, node_registry=nodes)

    # First run completes everything.
    calls = {"n": 0}

    def _counting_dispatch(*, node_run, ctx, executor, store, attempt):
        calls["n"] += 1
        return _mock_dispatcher(store)(
            node_run=node_run, ctx=ctx, executor=executor, store=store, attempt=attempt
        )

    run_graph(
        graph=graph,
        template=template,
        store=store,
        catalog=catalog,
        node_registry=nodes,
        agent_dispatcher=_counting_dispatch,
    )
    first_calls = calls["n"]

    # Second run: idempotent skip; the dispatcher is never called for completed nodes.
    graph2 = instantiate(template=template, run_id=run_id, shards=plans, node_registry=nodes)
    run_graph(
        graph=graph2,
        template=template,
        store=store,
        catalog=catalog,
        node_registry=nodes,
        agent_dispatcher=_counting_dispatch,
    )
    # No new dispatch calls (all 5 nodes were already success).
    assert calls["n"] == first_calls
