"""Shared fixtures for divdag_server tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

from divdag_server.app import create_app
from divdag_server.database import sqlite_url


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "divdag_data"
    d.mkdir()
    return d


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def app(data_dir: Path, db_path: Path) -> Any:
    return create_app(db_url=sqlite_url(db_path), data_dir=data_dir, create_schema=True)


@pytest.fixture
def client(app: Any) -> Any:
    with TestClient(app=app) as c:
        yield c


@pytest.fixture
def items_dir(tmp_path: Path) -> Path:
    """A directory of .txt files for the tiny domain to scan."""
    d = tmp_path / "items"
    d.mkdir()
    for name in ("alpha.txt", "beta.txt", "gamma.txt"):
        (d / name).write_text(f"content of {name}", encoding="utf-8")
    return d


def make_items(
    root: Path, names: tuple[str, ...] = ("a.txt", "b.txt", "c.txt")
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).write_text(f"content of {name}", encoding="utf-8")
    return root
