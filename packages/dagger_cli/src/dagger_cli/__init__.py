"""dagger_cli: orchestration CLI entry points.

`dagger run` — run a domain's default template end-to-end (mock or real backend).
`dagger state` — ls/cat/verify/gc/archive a run's state tree.
`dagger config` — show parsed config.
`dagger domains` — list installed domains.
`dagger_cli.scaffold` — helpers for domain-specific deterministic CLIs.
"""

from __future__ import annotations

from .main import cli
from .state_cli import cli as state_cli

__all__ = ["cli", "state_cli"]
