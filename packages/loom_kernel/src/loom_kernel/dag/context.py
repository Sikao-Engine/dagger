"""NodeContext: 4-layer priority merge along edges.

Context flows **along edges**, not via a global blackboard. A node's context is:
  run config  →  shard seed  →  ancestor patches  →  node params
where later layers overwrite earlier ones, and parallel branches writing the same
key with *different* values raise `ContextConflictError` (static conflict
detection — a CubeClaw design that we preserve).

Edge `maps` rewrites keys as context crosses an edge, keeping nodes generic:
  EdgeDef("a", "b", maps={"b_downstream_key": "a_upstream_key"})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ContextConflictError(ValueError):
    """Two parallel branches wrote the same key with different values."""

    def __init__(self, key: str, left: Any, right: Any) -> None:
        super().__init__(
            f"parallel branches wrote context key {key!r} with conflicting values: "
            f"{left!r} vs {right!r}"
        )
        self.key = key
        self.left = left
        self.right = right


@dataclass
class ContextPatch:
    """A node's contribution to downstream context (its `outputs` merged with params)."""

    values: dict[str, Any] = field(default_factory=dict)
    source_node_run_id: str = ""

    @staticmethod
    def merge(*patches: ContextPatch) -> ContextPatch:
        """Merge patches left-to-right. Raises on conflicting parallel writes.

        Within a single patch (single source), later keys overwrite earlier —
        that's the same-source case and is fine. Across *parallel* patches (multiple
        sources contributing to the same target), different values for the same key
        is a conflict.
        """
        merged_vals: dict[str, Any] = {}
        sources: list[str] = []
        for p in patches:
            sources.append(p.source_node_run_id)
            for k, v in p.values.items():
                if k in merged_vals and merged_vals[k] != v:
                    # Conflict between parallel sources.
                    raise ContextConflictError(k, merged_vals[k], v)
                merged_vals[k] = v
        # source_node_run_id is only meaningful for single-source patches.
        src = sources[0] if len(set(sources)) == 1 else ""
        return ContextPatch(values=merged_vals, source_node_run_id=src)

    def to_dict(self) -> dict[str, Any]:
        return {"values": dict(self.values), "source_node_run_id": self.source_node_run_id}


@dataclass
class NodeContext:
    """A node's resolved context: 4 layers merged.

    Layers (low → high priority):
      1. `run_config`: run-level configuration snapshot.
      2. `shard_seed`: per-shard seed values (e.g. shard_index, item_range).
      3. `ancestor_patches`: merged outputs from upstream nodes (already de-conflicted).
      4. `node_params`: this node's NodeDef.params (highest priority).

    Access via `ctx["key"]` / `ctx.get(key, default)`.
    """

    run_config: dict[str, Any] = field(default_factory=dict)
    shard_seed: dict[str, Any] = field(default_factory=dict)
    ancestor_patches: dict[str, Any] = field(default_factory=dict)
    node_params: dict[str, Any] = field(default_factory=dict)
    # Convenience view onto run/shard/item for prompt rendering.
    run: dict[str, Any] = field(default_factory=dict)
    shard: dict[str, Any] = field(default_factory=dict)
    item: dict[str, Any] = field(default_factory=dict)

    def values(self) -> dict[str, Any]:
        """Flatten the 4 layers in priority order."""
        out: dict[str, Any] = {}
        out.update(self.run_config)
        out.update(self.shard_seed)
        out.update(self.ancestor_patches)
        out.update(self.node_params)
        return out

    def __getitem__(self, key: str) -> Any:
        return self.values()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values().get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_config": dict(self.run_config),
            "shard_seed": dict(self.shard_seed),
            "ancestor_patches": dict(self.ancestor_patches),
            "node_params": dict(self.node_params),
            "run": dict(self.run),
            "shard": dict(self.shard),
            "item": dict(self.item),
        }


def apply_edge_map(patch: ContextPatch, edge_maps: dict[str, str]) -> ContextPatch:
    """Rewrite patch keys per an edge's `maps` {downstream_key: upstream_key}.

    Keys not in `maps` pass through unchanged. This lets a generic downstream node
    read its inputs under canonical names regardless of which upstream produced them.
    """
    if not edge_maps:
        return patch
    new_vals: dict[str, Any] = {}
    # Reverse map: upstream_key -> downstream_key. Multiple downstream keys may
    # read from one upstream key (broadcast). A downstream key with no upstream
    # match keeps its original name (passthrough).
    for k, v in patch.values.items():
        mapped = False
        for downstream, upstream in edge_maps.items():
            if upstream == k:
                new_vals[downstream] = v
                mapped = True
        if not mapped:
            new_vals[k] = v
    return ContextPatch(values=new_vals, source_node_run_id=patch.source_node_run_id)


__all__ = [
    "ContextConflictError",
    "ContextPatch",
    "NodeContext",
    "apply_edge_map",
]
