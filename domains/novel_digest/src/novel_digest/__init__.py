"""novel_digest: Loom's second domain — long-novel digest pipeline.

Pipeline: chapter digest → entity merge → timeline merge (serial across shards)
→ volume summary → consistency check → final report.

This package root intentionally does NOT import `plugin` (or anything else):
the entry-point loader imports `novel_digest.plugin` directly, and keeping the
root side-effect-free lets hosts import submodules (e.g. `novel_digest.schemas`
for the contract doc generator) without triggering full SPI assembly.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
