"""Standalone Loom server entry point.

    uv run server/main_server.py -c path/to/loom.toml

Copy `config.example.toml` (repo root), point `workspace` at the working
directory you want to open, and pass the file via `-c`. Without `-c`, the
current directory is the workspace (env vars LOOM_DB_URL / LOOM_DATA_DIR /
LOOM_HOST / LOOM_PORT still apply).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fallback for running with a bare interpreter that has the deps but not the
# loom_server package installed; with `uv run` the workspace env already has it.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from loom_server.app import main

if __name__ == "__main__":
    main()
