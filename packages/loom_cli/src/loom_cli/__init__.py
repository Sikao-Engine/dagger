"""loom_cli: orchestration CLI entry points.

`loom run` — run a domain's default template end-to-end (mock or real backend).
`loom state` — ls/cat/verify/gc/archive a run's state tree.
`loom config` — show parsed config.
`loom domains` — list installed domains.
`loom_cli.scaffold` — helpers for domain-specific deterministic CLIs.
"""

from __future__ import annotations

from .main import cli
from .state_cli import cli as state_cli

__all__ = ["cli", "state_cli"]
