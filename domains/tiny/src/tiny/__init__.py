"""tiny domain: pure-local batch file summarization.

First end-to-end domain. Zero external dependencies. Input: a directory of
`.txt` files. Output: a per-file summary slot. The template exercises three
topologies: parallel shards + serial accumulation + aggregation.
"""

from __future__ import annotations

from .plugin import plugin

__all__ = ["plugin"]
