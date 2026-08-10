"""T5.1: DB schema — all core tables create + key columns present."""

from __future__ import annotations

from sqlalchemy import inspect

from dagger_server.database import (
    create_all,
    make_engine,
    make_session_factory,
    sqlite_url,
)


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_all_core_tables_present(tmp_path) -> None:
    engine = make_engine(sqlite_url(tmp_path / "t.db"))
    create_all(engine)
    tables = _tables(engine)
    expected = {
        "projects",
        "workspaces",
        "runs",
        "shards",
        "node_runs",
        "attempts",
        "ledger_items",
        "milestones",
        "plans",
        "artifacts",
        "review_states",
        "findings",
        "highlights",
        "annotations",
        "dag_templates",
        "executors_cache",
        "agents",
        "events",
    }
    assert expected <= tables, f"missing: {expected - tables}"


def test_run_has_relative_state_root_column(tmp_path) -> None:
    """T5.2 invariant: run.state_root_rel exists (the relative-path column)."""
    engine = make_engine(sqlite_url(tmp_path / "t.db"))
    create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("runs")}
    assert "state_root_rel" in cols
    # And the other *_rel columns.
    assert "workspace_path_rel" in {
        c["name"] for c in inspect(engine).get_columns("shards")
    }
    assert "transcript_path_rel" in {
        c["name"] for c in inspect(engine).get_columns("attempts")
    }
    assert "path_rel" in {c["name"] for c in inspect(engine).get_columns("artifacts")}


def test_foreign_keys_enforced(tmp_path) -> None:
    """SQLite FK enforcement: a node_run with a bogus run_id fails on commit."""
    engine = make_engine(sqlite_url(tmp_path / "t.db"))
    create_all(engine)
    factory = make_session_factory(engine)
    from dagger_server.models import NodeRun

    session = factory()
    session.add(NodeRun(id="n1", run_id="nope", node_key="x", node_type="x"))
    try:
        session.commit()
        raised = False
    except Exception:  # noqa: BLE001
        session.rollback()
        raised = True
    finally:
        session.close()
    assert raised, "foreign key on run_id should have rejected the insert"
