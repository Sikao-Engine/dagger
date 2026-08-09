"""Tests for loom_server.config (TOML loading) + web_dist static serving."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from litestar.testing import TestClient

from loom_server.app import create_app
from loom_server.config import DEFAULT_HOST, DEFAULT_PORT, LoomConfig, load_config
from loom_server.database import sqlite_url


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadConfig:
    def test_minimal_config_defaults_from_workspace(self, tmp_path: Path) -> None:
        cfg_path = _write(tmp_path / "loom.toml", 'workspace = "../my-book"\n')
        cfg = load_config(cfg_path)

        assert cfg.workspace == (tmp_path / ".." / "my-book").resolve()
        assert cfg.host == DEFAULT_HOST
        assert cfg.port == DEFAULT_PORT
        assert cfg.resolved_db_url() == sqlite_url(cfg.workspace / "loom.db")
        assert cfg.resolved_data_dir() == cfg.workspace / ".loom"
        assert cfg.web_dist is None

    def test_relative_paths_resolve_against_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # cwd is somewhere else entirely: resolution must not depend on it.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        cfg_path = _write(
            tmp_path / "cfg" / "loom.toml",
            'workspace = "book"\ndata_dir = "state"\nweb_dist = "ui/dist"\n'
            'host = "0.0.0.0"\nport = 9000\ndb_url = "sqlite:///explicit.db"\n',
        )
        cfg = load_config(cfg_path)

        base = (tmp_path / "cfg").resolve()
        assert cfg.workspace == base / "book"
        assert cfg.resolved_data_dir() == base / "state"
        assert cfg.web_dist == base / "ui" / "dist"
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9000
        assert cfg.resolved_db_url() == "sqlite:///explicit.db"

    def test_missing_workspace_is_a_config_error(self, tmp_path: Path) -> None:
        cfg_path = _write(tmp_path / "loom.toml", "port = 8000\n")
        with pytest.raises(ValueError, match="workspace"):
            load_config(cfg_path)

    def test_env_fallback_for_db_and_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOOM_DB_URL", "sqlite:///env.db")
        monkeypatch.setenv("LOOM_DATA_DIR", str(tmp_path / "env_state"))
        cfg = LoomConfig(workspace=tmp_path)
        assert cfg.resolved_db_url() == "sqlite:///env.db"
        assert cfg.resolved_data_dir() == tmp_path / "env_state"


class TestWebDistServing:
    @pytest.fixture
    def web_dist(self, tmp_path: Path) -> Path:
        d = tmp_path / "dist"
        d.mkdir()
        (d / "index.html").write_text("<html>loom-spa</html>", encoding="utf-8")
        (d / "app.js").write_text("console.log('x')", encoding="utf-8")
        return d

    @pytest.fixture
    def client(self, tmp_path: Path, web_dist: Path) -> Any:
        app = create_app(
            db_url=sqlite_url(tmp_path / "t.db"),
            data_dir=tmp_path / "data",
            create_schema=True,
            web_dist=web_dist,
        )
        with TestClient(app=app) as c:
            yield c

    def test_index_served_at_root(self, client: Any) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "loom-spa" in r.text

    def test_static_asset_served(self, client: Any) -> None:
        r = client.get("/app.js")
        assert r.status_code == 200

    def test_spa_deep_link_falls_back_to_index(self, client: Any) -> None:
        r = client.get("/runs/some-run-id")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "loom-spa" in r.text

    def test_api_404_stays_json(self, client: Any) -> None:
        r = client.get("/api/v1/definitely-not-a-route")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")

    def test_api_still_works_with_web_dist(self, client: Any) -> None:
        r = client.get("/api/v1/domains")
        assert r.status_code == 200
