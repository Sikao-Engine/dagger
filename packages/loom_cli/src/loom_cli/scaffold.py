"""Deterministic CLI scaffold for domain-specific tools.

Domains ship their own CLIs (e.g. `noveltool status/next/fill`) reusing this
scaffold. Three contracts:
  1. All output is JSON (`--json` default on).
  2. Semantic exit codes: 0 ok / 1 needs-human / 2 needs-review / 3 param-error.
  3. Idempotent: re-running the same command is a no-op.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

EXIT_OK = 0
EXIT_NEEDS_HUMAN = 1
EXIT_NEEDS_REVIEW = 2
EXIT_PARAM_ERROR = 3


@dataclass
class CommandResult:
    """Standard result envelope for domain CLI commands."""

    ok: bool
    data: dict[str, Any] | None = None
    error: str = ""
    next_hint: str = ""

    def to_json(self) -> str:
        payload: dict[str, Any] = {"ok": self.ok}
        if self.data is not None:
            payload["data"] = self.data
        if self.error:
            payload["error"] = self.error
        if self.next_hint:
            payload["next"] = self.next_hint
        return json.dumps(payload, default=str, ensure_ascii=False, indent=2)

    @property
    def exit_code(self) -> int:
        if not self.ok:
            return EXIT_NEEDS_HUMAN
        return EXIT_OK


def emit(result: CommandResult) -> int:
    """Print a CommandResult as JSON and return its exit code."""
    sys.stdout.write(result.to_json() + "\n")
    return result.exit_code


def die(message: str, *, exit_code: int = EXIT_PARAM_ERROR) -> int:
    """Print an error JSON and exit with the given code."""
    sys.stderr.write(json.dumps({"ok": False, "error": message}, ensure_ascii=False) + "\n")
    return exit_code


__all__ = [
    "EXIT_NEEDS_HUMAN",
    "EXIT_NEEDS_REVIEW",
    "EXIT_OK",
    "EXIT_PARAM_ERROR",
    "CommandResult",
    "die",
    "emit",
]
