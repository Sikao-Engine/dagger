# divdag_server

DivDag HTTP server + scheduler + DB layer (M5).

Built on `divdag_kernel` (StateStore + DAG engine) and `divdag_agent` (SessionRunner).
Stack: Litestar + SQLAlchemy + SQLite + Alembic.

## Run

```bash
uv run alembic -c server/alembic.ini upgrade head
uv run python -m divdag_server  # serves on :8000 (needs uvicorn: uv sync --extra serve)
```

## Tests

```bash
uv run python -m pytest server -q
```
