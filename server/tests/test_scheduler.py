"""T5.3/T5.4: scheduler reuses run_graph + persists NodeRun/Attempt to DB.

Drives the tiny domain end-to-end through the Scheduler (not HTTP), verifying:
- run_graph is reused (no duplicate readiness logic)
- NodeRun/Attempt rows land in DB with correct statuses
- the StateStore tree is produced and verifies clean
- events are emitted + persisted
- the relative-path invariant holds after a real run
"""

from __future__ import annotations

from pathlib import Path

from loom_server.database import (
    create_all,
    make_engine,
    make_session_factory,
    sqlite_url,
)
from loom_server.domain_runtime import assemble_runtime
from loom_server.events import EventBus
from loom_server.repositories import (
    assert_no_absolute_paths,
    list_attempts,
    list_events,
    list_node_runs,
    list_shards,
)
from loom_server.scheduler import Scheduler, ScheduleRequest


def _make_items(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("a.txt", "b.txt", "c.txt"):
        (root / name).write_text(f"content of {name}", encoding="utf-8")
    return root


def _build_scheduler(tmp_path: Path) -> tuple:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    engine = make_engine(sqlite_url(tmp_path / "s.db"))
    create_all(engine)
    factory = make_session_factory(engine)
    runtime = assemble_runtime()
    bus = EventBus()
    scheduler = Scheduler(runtime=runtime, data_dir=data_dir, bus=bus)
    return scheduler, factory, bus, data_dir


def test_scheduler_runs_tiny_end_to_end(tmp_path: Path) -> None:
    items = _make_items(tmp_path / "items")
    scheduler, factory, _, _ = _build_scheduler(tmp_path)

    req = ScheduleRequest(
        run_id="run_test",
        domain_id="tiny",
        template_id="",
        items_dir=str(items),
        shards_hint=3,
        backend="mock",
        base_ref="",
        config={},
    )
    with factory() as session:
        outcome = scheduler.schedule_and_run(req, session)

    assert outcome.status == "completed"
    # tiny: init + 3 work + report = 5 completed, 0 failed.
    assert outcome.completed == 5
    assert outcome.failed == 0

    with factory() as session:
        nodes = list_node_runs(session, "run_test")
        shards = list_shards(session, "run_test")
        events = list_events(session, "run_test")
    assert len(nodes) == 5
    assert all(n.status == "success" for n in nodes)
    assert len(shards) == 3
    # Events: run.started + 5 node.started + 5 node.succeeded + run.completed = 12.
    types = [e.type for e in events]
    assert "run.started" in types
    assert "run.completed" in types
    assert types.count("node.succeeded") == 5

    # Each agent node has exactly one Attempt row.
    with factory() as session:
        for n in nodes:
            if n.node_type.startswith("tiny.") and n.node_type != "tiny.init":
                atts = list_attempts(session, n.id)
                assert len(atts) == 1
                assert atts[0].status == "success"

    # The relative-path invariant holds after a real run.
    with factory() as session:
        violations = assert_no_absolute_paths(session)
    assert violations == [], violations

    # StateStore tree verifies clean.
    from loom_kernel.state import StateStore

    store = StateStore(scheduler.data_dir / "run_test", run_id="run_test")
    assert store.verify() == []
    assert len(store.query(layer="contract")) == 5


def test_scheduler_persists_state_root_relative(tmp_path: Path) -> None:
    """The run's state_root_rel is relative to data_dir, not absolute."""
    items = _make_items(tmp_path / "items")
    scheduler, factory, _, _ = _build_scheduler(tmp_path)
    req = ScheduleRequest(
        run_id="run_rel",
        domain_id="tiny",
        template_id="",
        items_dir=str(items),
        shards_hint=2,
        backend="mock",
        base_ref="",
        config={},
    )
    with factory() as session:
        outcome = scheduler.schedule_and_run(req, session)
    # state_root_rel must be a relative POSIX path (no drive letter, no leading /).
    rel = outcome.state_root_rel
    assert not (len(rel) >= 2 and rel[1] == ":")
    assert not rel.startswith("/")
    assert rel.startswith("run_rel")


def test_scheduler_reuses_engine_readiness(tmp_path: Path) -> None:
    """The scheduler does NOT reimplement readiness — it calls run_graph.

    We assert by structure: the scheduler's only graph-execution call is
    run_graph (verified by patching it to count invocations).
    """
    import loom_server.scheduler as sched_mod

    items = _make_items(tmp_path / "items")
    scheduler, factory, _, _ = _build_scheduler(tmp_path)
    calls = {"n": 0}
    real = sched_mod.run_graph

    def _spy(**kw):
        calls["n"] += 1
        return real(**kw)

    sched_mod.run_graph = _spy
    try:
        req = ScheduleRequest(
            run_id="run_spy",
            domain_id="tiny",
            template_id="",
            items_dir=str(items),
            shards_hint=2,
            backend="mock",
            base_ref="",
            config={},
        )
        with factory() as session:
            scheduler.schedule_and_run(req, session)
    finally:
        sched_mod.run_graph = real
    assert calls["n"] == 1, "scheduler should call run_graph exactly once"
