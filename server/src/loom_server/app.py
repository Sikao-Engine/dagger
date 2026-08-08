"""Litestar app assembly for loom_server.

`create_app(db_url, data_dir)` builds the singletons (deps), creates the DB
schema if missing, and wires the controllers. `python -m loom_server` serves
via uvicorn (requires the `serve` extra).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from litestar import Litestar
from litestar.datastructures import State
from litestar.openapi import OpenAPIConfig

from .controllers import (
    AgentsController,
    CatalogController,
    NodesController,
    PlanningController,
    RunsController,
    SSEController,
    StateController,
)
from .database import create_all, sqlite_url
from .deps import build_deps


def create_app(
    *,
    db_url: str | None = None,
    data_dir: Path | str | None = None,
    create_schema: bool = True,
) -> Litestar:
    """Build the Litestar app.

    Args:
        db_url: SQLAlchemy URL. Defaults to `LOOM_DB_URL` env or `./loom.db`.
        data_dir: Where run state trees live. Defaults to `LOOM_DATA_DIR` or `./.loom`.
        create_schema: If True (default), create tables on startup (for tests/dev).
                       Production uses `alembic upgrade head`.
    """
    if db_url is None:
        db_url = os.environ.get("LOOM_DB_URL", sqlite_url(Path("./loom.db")))
    if data_dir is None:
        data_dir = Path(os.environ.get("LOOM_DATA_DIR", "./.loom"))
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    deps = build_deps(db_url=db_url, data_dir=data_dir)
    if create_schema:
        create_all(deps.engine)

    app = Litestar(
        route_handlers=[
            CatalogController,
            RunsController,
            NodesController,
            StateController,
            SSEController,
            PlanningController,
            AgentsController,
        ],
        state=State({"deps": deps}),
        openapi_config=OpenAPIConfig(
            title="Loom API",
            version="0.1.0",
            path="/api/v1/schema",
        ),
        debug=True,
    )
    return app


def _serve(host: str, port: int) -> None:
    app = create_app()
    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "uvicorn not installed; install with `uv sync --extra serve`"
        ) from exc
    uvicorn.run(app, host=host, port=port)  # type: ignore[arg-type]


def main() -> None:
    host = os.environ.get("LOOM_HOST", "127.0.0.1")
    port = int(os.environ.get("LOOM_PORT", "8000"))
    _serve(host, port)


if __name__ == "__main__":
    main()


__all__: list[Any] = ["create_app", "main"]
