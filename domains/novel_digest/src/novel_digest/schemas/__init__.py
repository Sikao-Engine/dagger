"""Domain state-object schemas (acceptance Step 1).

Registers three kinds into the kernel's SCHEMA_REGISTRY at import time:
- `novel_chapter` — one chapter's digest product (summary / entities /
  timeline_delta / digest_ok).
- `novel_volume_summary` — per-volume rollup.
- `novel_consistency_report` — the run-level contradiction list.

Registration is idempotent (the kernel registry accepts re-registering the same
version), so repeated imports across host processes are safe. The JSON files
next to this module are the single source of truth; prompts reference them by
kind name instead of inlining schema text (anti-pattern per acceptance §1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loom_kernel.state.schema import SCHEMA_REGISTRY

NOVEL_CHAPTER = "novel_chapter"
NOVEL_VOLUME_SUMMARY = "novel_volume_summary"
NOVEL_CONSISTENCY_REPORT = "novel_consistency_report"

_SCHEMA_DIR = Path(__file__).parent


def _load(name: str) -> dict[str, Any]:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def register_schemas() -> None:
    """Register (or idempotently re-register) all domain kinds."""
    SCHEMA_REGISTRY.register(NOVEL_CHAPTER, version=1, schema=_load("chapter.json"))
    SCHEMA_REGISTRY.register(NOVEL_VOLUME_SUMMARY, version=1, schema=_load("volume_summary.json"))
    SCHEMA_REGISTRY.register(
        NOVEL_CONSISTENCY_REPORT, version=1, schema=_load("consistency_report.json")
    )


register_schemas()

__all__ = [
    "NOVEL_CHAPTER",
    "NOVEL_CONSISTENCY_REPORT",
    "NOVEL_VOLUME_SUMMARY",
    "register_schemas",
]
