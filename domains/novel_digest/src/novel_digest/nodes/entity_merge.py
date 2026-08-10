"""entity_merge: deterministic per-shard entity table merge.

Reads every chapter product `<shard_out_dir>/<item_id>.json` and merges entity
records into `entities.json` in the same directory:
- same `name` → one row; `aliases` are the sorted union across chapters;
- `first_seen_chapter` keeps the minimum (chapter ids sort in story order).

Deterministic by construction (sorted inputs, order-free merge), so re-runs
produce byte-identical tables. Writes only the equal-value boolean
`entities_ok` into the context — path products travel by filesystem
convention, not context (the parallel-writes rule, smoke plan D8).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from divdag_kernel.dag import ContextPatch, NodeContext
from divdag_kernel.dag.nodes import ContractError, NodeContract


def merge_entities(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the `entities` lists of chapter products. Pure + deterministic."""
    merged: dict[str, dict[str, Any]] = {}
    for chapter in chapters:
        for ent in chapter.get("entities", []):
            name = str(ent.get("name", ""))
            if not name:
                continue
            cur = merged.get(name)
            if cur is None:
                merged[name] = {
                    "name": name,
                    "type": ent.get("type", "person"),
                    "aliases": sorted(set(ent.get("aliases", []))),
                    "first_seen_chapter": ent.get("first_seen_chapter", ""),
                }
            else:
                cur["aliases"] = sorted(set(cur["aliases"]) | set(ent.get("aliases", [])))
                first_seen = str(ent.get("first_seen_chapter", ""))
                if first_seen and first_seen < str(cur["first_seen_chapter"]):
                    cur["first_seen_chapter"] = first_seen
    return [merged[k] for k in sorted(merged)]


class EntityMergeNode:
    """Builtin handler: shard entity table from chapter products."""

    contract = NodeContract(reads=("shard_out_dir",), writes=("entities_ok",))

    def run(self, ctx: NodeContext) -> ContextPatch:
        shard_out = Path(str(ctx["shard_out_dir"]))
        items = [str(i) for i in (ctx.shard.get("items") or [])]
        chapters: list[dict[str, Any]] = []
        for item_id in items:
            path = Path(shard_out, f"{item_id}.json")
            if not path.exists():
                raise ContractError(
                    f"entity_merge: chapter product missing: {path} "
                    f"(digest must produce <shard_out_dir>/<chapter_id>.json)"
                )
            chapters.append(json.loads(path.read_text(encoding="utf-8")))
        table = {
            "shard_id": ctx.shard.get("shard_id", ""),
            "entities": merge_entities(chapters),
        }
        out_path = Path(shard_out, "entities.json")
        out_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        return ContextPatch(values={"entities_ok": True})


__all__ = ["EntityMergeNode", "merge_entities"]
