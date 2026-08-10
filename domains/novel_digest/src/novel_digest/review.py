"""IntentDiffProvider for novel_digest (acceptance Step 5; kernel K5 protocol).

Left pane = the original chapter excerpt; right pane = the generated summary.
Both come straight from the filesystem: the chapter path rides in
`item.payload["path"]`; the digest product lives at
`<digest_root>/<item_id>.json` (a shard_out_dir by convention).
"""

from __future__ import annotations

import json
from pathlib import Path

from divdag_kernel.planning import WorkItem

EXCERPT_CHARS = 500


class NovelIntentDiff:
    """Left: original excerpt. Right: digest summary. None when unavailable."""

    def __init__(self, source_dir: str | Path = ".", digest_root: str | Path | None = None) -> None:
        self.source_dir = Path(source_dir)
        self.digest_root = Path(digest_root) if digest_root is not None else self.source_dir

    def intent(self, item: WorkItem) -> str | None:
        path_raw = item.payload.get("path")
        path = Path(str(path_raw)) if path_raw else Path(self.source_dir, f"{item.id}.txt")
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")[:EXCERPT_CHARS]
        except OSError:
            return None

    def outcome(self, item: WorkItem) -> str | None:
        path = Path(self.digest_root, f"{item.id}.json")
        if not path.exists():
            return None
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        summary = body.get("summary")
        return str(summary) if summary else None


__all__ = ["EXCERPT_CHARS", "NovelIntentDiff"]
