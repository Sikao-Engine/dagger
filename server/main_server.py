"""Standalone Dagger server entry point.

    uv run server/main_server.py -c path/to/dagger.toml

Copy `config.example.toml` (repo root), point `workspace` at the working
directory you want to open, and pass the file via `-c`. Without `-c`, the
current directory is the workspace (env vars DAGGER_DB_URL / DAGGER_DATA_DIR /
DAGGER_HOST / DAGGER_PORT still apply).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fallback for running with a bare interpreter that has the deps but not the
# dagger_server package installed; with `uv run` the workspace env already has it.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dagger_server.app import main

if __name__ == "__main__":
    main()
