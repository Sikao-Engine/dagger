"""T5.2: repository layer — CRUD + the relative-path invariant.

`assert_no_absolute_paths` is the guard: every `*_rel` column must hold a
relative POSIX path. We seed a run with a relative path (good) and verify the
guard passes, then assert the guard would catch an absolute path (defensive).
"""

from __future__ import annotations

from loom_server.database import (
    create_all,
    make_engine,
    make_session_factory,
    sqlite_url,
)
from loom_server.repositories import (
    assert_no_absolute_paths,
    create_attempt,
    create_run,
    create_shard,
    get_run,
    list_runs,
    set_run_status,
)


def _factory(tmp_path):
    engine = make_engine(sqlite_url(tmp_path / "r.db"))
    create_all(engine)
    return make_session_factory(engine)


def test_create_and_get_run(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        create_run(
            s,
            run_id="run_1",
            domain_id="tiny",
            template_id="tiny_default",
            items=[{"id": "a", "seq": 0}],
            state_root_rel="run_1/state",
        )
        s.commit()
    with factory() as s:
        run = get_run(s, "run_1")
        assert run is not None
        assert run.domain_id == "tiny"
        assert run.state_root_rel == "run_1/state"
        assert run.status == "created"


def test_relative_path_invariant_holds(tmp_path) -> None:
    """A run seeded with a relative path passes the absolute-path guard."""
    factory = _factory(tmp_path)
    with factory() as s:
        create_run(
            s,
            run_id="run_ok",
            domain_id="tiny",
            template_id="t",
            items=[],
            state_root_rel="run_ok/state",
        )
        create_shard(
            s,
            shard_id="sh_0",
            run_id="run_ok",
            index_num=0,
            items=["a"],
            workspace_path_rel="workspaces/run_ok/sh_0",
        )
        s.commit()
    with factory() as s:
        violations = assert_no_absolute_paths(s)
    assert violations == [], f"unexpected absolute-path violations: {violations}"


def test_relative_path_invariant_catches_absolute(tmp_path) -> None:
    """If an absolute path sneaks into a *_rel column, the guard flags it."""
    from loom_server.models import NodeRun

    factory = _factory(tmp_path)
    with factory() as s:
        run = create_run(
            s,
            run_id="run_bad",
            domain_id="tiny",
            template_id="t",
            items=[],
            state_root_rel="run_bad/state",
        )
        s.add(NodeRun(id="n1", run_id="run_bad", node_key="x", node_type="x"))
        s.flush()
        create_attempt(
            s,
            attempt_id="att_1",
            node_run_id="n1",
            attempt=1,
            transcript_path_rel="C:/abs/path/transcript.jsonl",
        )
        # Directly corrupt the run's rel column to simulate a regression.
        run.state_root_rel = "/abs/loom/run_bad/state"
        s.commit()
    with factory() as s:
        violations = assert_no_absolute_paths(s)
    # Both the absolute run state_root and the absolute transcript path are caught.
    assert any("run_bad" in v for v in violations)
    assert any("att_1" in v for v in violations)


def test_set_run_status(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        create_run(
            s,
            run_id="run_s",
            domain_id="tiny",
            template_id="t",
            items=[],
            state_root_rel="run_s/state",
        )
        s.commit()
    with factory() as s:
        set_run_status(s, "run_s", "completed")
        s.commit()
    with factory() as s:
        assert get_run(s, "run_s").status == "completed"


def test_list_runs_ordered(tmp_path) -> None:
    factory = _factory(tmp_path)
    with factory() as s:
        for i in range(3):
            create_run(
                s,
                run_id=f"run_{i}",
                domain_id="tiny",
                template_id="t",
                items=[],
                state_root_rel=f"run_{i}/state",
            )
        s.commit()
    with factory() as s:
        runs = list_runs(s)
    assert len(runs) == 3
