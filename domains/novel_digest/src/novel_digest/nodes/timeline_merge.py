"""timeline_merge: serial cross-shard timeline accumulation.

Reads `prev_timeline_path` from the context (delivered by the SERIAL_PREV edge
with `maps={"prev_timeline_path": "timeline_path"}`; absent on the first
shard), appends this shard's per-chapter `timeline_delta` events in item order,
and writes `<shard_out_dir>/timeline.json`. The accumulated path is emitted as
`timeline_path`, which the next shard picks up as its `prev_timeline_path`.

`timeline_path` values differ per shard by design; they only flow along INTRA
(same shard, to volume_summary) and SERIAL_PREV (mapped to prev_timeline_path)
edges, so no parallel-write conflict can occur (smoke plan D8).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loom_kernel.dag import ContextPatch, NodeContext
from loom_kernel.dag.nodes import ContractError, NodeContract


def accumulate_timeline(
    prev_events: list[dict[str, Any]], chapters: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """prev events + each chapter's timeline_delta, in order. Pure."""
    events = list(prev_events)
    for chapter in chapters:
        events.extend(chapter.get("timeline_delta", []))
    return events


class TimelineMergeNode:
    """Builtin handler: accumulate the global timeline one shard at a time."""

    contract = NodeContract(
        reads=("shard_out_dir",),
        writes=("timeline_ok", "timeline_path"),
    )

    def run(self, ctx: NodeContext) -> ContextPatch:
        shard_out = Path(str(ctx["shard_out_dir"]))
        prev_events: list[dict[str, Any]] = []
        prev_raw = ctx.get("prev_timeline_path")  # first shard has none — optional read
        if prev_raw:
            prev_path = Path(str(prev_raw))
            if prev_path.exists():
                prev_body = json.loads(prev_path.read_text(encoding="utf-8"))
                prev_events = list(prev_body.get("events", []))
        items = [str(i) for i in (ctx.shard.get("items") or [])]
        chapters: list[dict[str, Any]] = []
        for item_id in items:
            path = Path(shard_out, f"{item_id}.json")
            if not path.exists():
                raise ContractError(
                    f"timeline_merge: chapter product missing: {path} "
                    f"(digest must produce <shard_out_dir>/<chapter_id>.json)"
                )
            chapters.append(json.loads(path.read_text(encoding="utf-8")))
        events = accumulate_timeline(prev_events, chapters)
        out_path = Path(shard_out, "timeline.json")
        out_path.write_text(
            json.dumps(
                {
                    "shard_id": ctx.shard.get("shard_id", ""),
                    "events": events,
                    "event_count": len(events),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ContextPatch(values={"timeline_ok": True, "timeline_path": str(out_path)})


__all__ = ["TimelineMergeNode", "accumulate_timeline"]
