"""Database engine + session factory.

SQLite via SQLAlchemy 2.0 sync engine. The engine (run_graph) is synchronous, so
sync DB access keeps the whole orchestration on one concurrency model; async
HTTP handlers call sync repos (SQLite local I/O is sub-millisecond for the
single-team scale this targets — see design doc §16).

`create_all` is used by tests; `alembic upgrade head` is the production path
(see server/alembic/).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_engine(db_url: str) -> Engine:
    """Create a SQLAlchemy engine. For SQLite, enables WAL + foreign keys."""
    engine = create_engine(db_url, future=True)
    if db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """Create all tables. For tests/migrations bootstrap."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Context manager yielding a session; commits on success, rolls back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sqlite_url(path: Path) -> str:
    """Build a sqlite URL from a Path (handles Windows backslashes)."""
    return f"sqlite:///{path.as_posix()}"


def relpath_from(base: Path, target: Path) -> str:
    """Return `target` relative to `base` as a POSIX string. Used to satisfy the
    relative-path invariant: every `*_rel` column is computed via this helper so
    no absolute path ever lands in the DB.
    """
    rel = Path(target).resolve().relative_to(Path(base).resolve())
    return PurePosixPath(*rel.parts).as_posix()


__all__ = [
    "create_all",
    "make_engine",
    "make_session_factory",
    "relpath_from",
    "session_scope",
    "sqlite_url",
]
