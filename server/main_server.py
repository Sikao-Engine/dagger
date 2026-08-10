"""Standalone DivDag server entry point.

    uv run server/main_server.py -c path/to/divdag.toml

Copy `config.example.toml` (repo root), point `workspace` at the working
directory you want to open, and pass the file via `-c`. Without `-c`, the
current directory is the workspace (env vars DIVDAG_DB_URL / DIVDAG_DATA_DIR /
DIVDAG_HOST / DIVDAG_PORT still apply).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fallback for running with a bare interpreter that has the deps but not the
# divdag_server package installed; with `uv run` the workspace env already has it.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from divdag_server.app import main

if __name__ == "__main__":
    main()
