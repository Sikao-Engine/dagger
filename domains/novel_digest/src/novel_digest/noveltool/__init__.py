"""noveltool: the deterministic CLI for novel_digest (acceptance Step 4).

Three scaffold contracts (loom_cli.scaffold): JSON output, semantic exit codes
(0 ok / 1 needs-human / 2 needs-review / 3 param-error), idempotent re-runs.

Division of labor: the Agent reads chapters and writes summaries; noveltool
owns enumeration, pointer advance, schema validation, and product persistence.
"""

from __future__ import annotations

__all__: list[str] = []
