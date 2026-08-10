"""Litestar app assembly for divdag_server.

`create_app(db_url, data_dir, web_dist)` builds the singletons (deps), creates
the DB schema if missing, wires the controllers, and — when `web_dist` points
at a built frontend bundle — serves the SPA at `/`.

Run it against a workspace described by a TOML config:

    uv run server/main_server.py -c path/to/divdag.toml
    # or: python -m divdag_server -c path/to/divdag.toml

Without `-c`, behavior is unchanged: env vars DIVDAG_DB_URL / DIVDAG_DATA_DIR /
DIVDAG_HOST / DIVDAG_PORT with `./divdag.db` + `./.divdag` defaults.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from litestar import Litestar, MediaType, Request, Response
from litestar.datastructures import State
from litestar.exceptions import NotFoundException
from litestar.openapi import OpenAPIConfig
from litestar.response import File
from litestar.static_files import StaticFilesConfig

from .config import DivDagConfig, load_config
from .controllers import (
    AgentsController,
    CatalogController,
    NodesController,
    PlanningController,
    RunsController,
    SSEController,
    StateController,
)
from .database import create_all
from .deps import build_deps


def create_app(
    *,
    db_url: str | None = None,
    data_dir: Path | str | None = None,
    create_schema: bool = True,
    web_dist: Path | str | None = None,
) -> Litestar:
    """Build the Litestar app.

    Args:
        db_url: SQLAlchemy URL. Defaults to `DIVDAG_DB_URL` env or `./divdag.db`.
        data_dir: Where run state trees live. Defaults to `DIVDAG_DATA_DIR` or `./.divdag`.
        create_schema: If True (default), create tables on startup (for tests/dev).
                       Production uses `alembic upgrade head`.
        web_dist: Built frontend bundle (`pnpm build` output). When given, the
                  SPA is served at `/` with deep-link fallback to index.html.
    """
    config = DivDagConfig(
        workspace=Path.cwd(),
        db_url=db_url,
        data_dir=Path(data_dir) if data_dir is not None else None,
        web_dist=Path(web_dist) if web_dist is not None else None,
    )
    db_url = config.resolved_db_url()
    data_dir = config.resolved_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    deps = build_deps(db_url=db_url, data_dir=data_dir)
    if create_schema:
        create_all(deps.engine)

    kwargs: dict[str, Any] = {}
    if config.web_dist is not None:
        kwargs["static_files_config"] = [
            StaticFilesConfig(path="/", directories=[config.web_dist], html_mode=True)
        ]
        index_html = config.web_dist / "index.html"

        def spa_fallback(request: Request, exc: NotFoundException) -> Response:
            """Deep links (e.g. /runs/<id>) must serve the SPA shell; API 404s stay JSON.

            The static-files mount at `/` rewrites scope["path"] (leading slash
            stripped), so match `api/` with and without it.
            """
            if request.url.path.lstrip("/").startswith("api/"):
                return Response(
                    content={"detail": f"not found: {request.url.path}"},
                    status_code=404,
                    media_type=MediaType.JSON,
                )
            return File(
                path=index_html,
                filename="index.html",
                media_type="text/html",
                content_disposition_type="inline",
            )

        kwargs["exception_handlers"] = {NotFoundException: spa_fallback}

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
            title="DivDag API",
            version="0.1.0",
            path="/api/v1/schema",
        ),
        debug=True,
        **kwargs,
    )
    return app


def _serve(config: DivDagConfig, *, host: str, port: int) -> None:
    if config.web_dist is not None and not (config.web_dist / "index.html").is_file():
        raise SystemExit(
            f"web_dist not built: {config.web_dist} (no index.html).\n"
            "Build the frontend first:  cd web && pnpm install && pnpm build\n"
            "…or drop the web_dist key from your config to run API-only."
        )
    app = create_app(
        db_url=config.resolved_db_url(),
        data_dir=config.resolved_data_dir(),
        web_dist=config.web_dist,
    )
    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit("uvicorn not installed; run `uv sync` first") from exc
    print(f"divdag workspace: {config.workspace}")
    print(f"divdag data dir:  {config.resolved_data_dir()}")
    print(f"serving on      http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)  # type: ignore[arg-type]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="divdag-server",
        description="Run the DivDag server against a workspace (see config.example.toml).",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="TOML config file. Without it, env vars / ./divdag.db + ./.divdag defaults apply.",
    )
    parser.add_argument("--host", default=None, help="Bind host (overrides config/env).")
    parser.add_argument("--port", type=int, default=None, help="Bind port (overrides config/env).")
    args = parser.parse_args(argv)

    if args.config is not None:
        config = load_config(args.config)
    else:
        config = DivDagConfig(workspace=Path.cwd())
    host = args.host or config.host
    port = args.port or config.port
    _serve(config, host=host, port=port)


if __name__ == "__main__":
    main()


__all__: list[Any] = ["create_app", "main"]
