"""divdag_cli: orchestration CLI entry points.

`divdag run` — run a domain's default template end-to-end (mock or real backend).
`divdag state` — ls/cat/verify/gc/archive a run's state tree.
`divdag config` — show parsed config.
`divdag domains` — list installed domains.
`divdag_cli.scaffold` — helpers for domain-specific deterministic CLIs.
"""

from __future__ import annotations

from .main import cli
from .state_cli import cli as state_cli

__all__ = ["cli", "state_cli"]
