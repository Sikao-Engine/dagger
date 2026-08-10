"""TOML config loading for the Dagger server.

A config file decouples a Dagger deployment from the repo checkout: the
`workspace` key points at the working directory being "opened" (runs, state
trees, and — by default — the SQLite DB all live there), and `web_dist`
points at the built frontend bundle to serve.

    uv run server/main_server.py -c path/to/dagger.toml

Config shape (see config.example.toml at the repo root):

    workspace = "../my-book"        # required; opened working directory
    host = "127.0.0.1"             # optional
    port = 8000                    # optional
    db_url = "sqlite:///..."       # optional; default <workspace>/dagger.db
    data_dir = "state"             # optional; default <workspace>/.dagger
    web_dist = "web/dist"          # optional; serve the built UI at /

Relative paths resolve against the config file's directory, so a config is
fully portable. Precedence: CLI flags > config file > env vars > defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .database import sqlite_url

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


@dataclass(frozen=True)
class DaggerConfig:
    """Resolved server configuration (all paths absolute)."""

    workspace: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    db_url: str | None = None
    data_dir: Path | None = None
    web_dist: Path | None = None

    def resolved_db_url(self) -> str:
        """Explicit `db_url`, else `DAGGER_DB_URL` env, else sqlite in the workspace."""
        if self.db_url is not None:
            return self.db_url
        env = os.environ.get("DAGGER_DB_URL")
        return env if env else sqlite_url(self.workspace / "dagger.db")

    def resolved_data_dir(self) -> Path:
        """Explicit `data_dir`, else `DAGGER_DATA_DIR` env, else `<workspace>/.dagger`."""
        if self.data_dir is not None:
            return self.data_dir
        env = os.environ.get("DAGGER_DATA_DIR")
        return Path(env) if env else self.workspace / ".dagger"


def _resolve(base: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def load_config(path: str | Path) -> DaggerConfig:
    """Load a TOML config file into a DaggerConfig.

    Raises FileNotFoundError for a missing file and ValueError for a missing
    `workspace` key — both are config-author errors, not runtime conditions.
    """
    path = Path(path).expanduser().resolve()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    workspace_raw = raw.get("workspace")
    if not workspace_raw:
        raise ValueError(f"{path}: missing required key 'workspace'")

    data_dir_raw = raw.get("data_dir")
    web_dist_raw = raw.get("web_dist")
    return DaggerConfig(
        workspace=_resolve(base, str(workspace_raw)),
        host=str(raw.get("host", os.environ.get("DAGGER_HOST", DEFAULT_HOST))),
        port=int(raw.get("port", os.environ.get("DAGGER_PORT", DEFAULT_PORT))),
        db_url=str(raw["db_url"]) if raw.get("db_url") else None,
        data_dir=_resolve(base, str(data_dir_raw)) if data_dir_raw else None,
        web_dist=_resolve(base, str(web_dist_raw)) if web_dist_raw else None,
    )


__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "DaggerConfig", "load_config"]
