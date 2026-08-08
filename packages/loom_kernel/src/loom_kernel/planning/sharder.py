"""Sharder: split an ordered WorkItem list into shards.

Three built-in strategies:
- `fixed_size`: every N items per shard (CubeClaw default).
- `milestone_aligned`: prefer to cut at Milestone boundaries.
- `weighted`: balance a payload field (word_count / diff_size) across shards.

Domains can register their own Sharder via SPI; the default is `fixed_size`.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Protocol

from ..dag.instantiator import ShardPlan
from .item import Milestone, WorkItem

__all__ = ["ShardPlan", "Sharder", "fixed_size", "milestone_aligned", "weighted"]


@dataclass(frozen=True)
class _ShardItem:
    item: WorkItem


class Sharder(Protocol):
    """SPI: suggest a shard plan for an ordered item list."""

    def suggest(
        self, items: list[WorkItem], milestones: list[Milestone], cfg: dict[str, Any]
    ) -> list[ShardPlan]: ...

    def validate(self, plan: list[ShardPlan]) -> list[str]:
        """Return warnings (empty list = ok). Default impl checks basic invariants."""
        warnings: list[str] = []
        seen: set[str] = set()
        for sh in plan:
            for iid in sh.items:
                if iid in seen:
                    warnings.append(f"item {iid!r} appears in multiple shards")
                seen.add(iid)
        if not plan:
            warnings.append("plan has zero shards")
        return warnings


def fixed_size(
    items: list[WorkItem], milestones: list[Milestone], cfg: dict[str, Any]
) -> list[ShardPlan]:
    """Every `cfg['size']` items per shard. Default size = 10 if unset."""
    size = max(1, int(cfg.get("size", 10)))
    if not items:
        return []
    plans: list[ShardPlan] = []
    for i in range(0, len(items), size):
        chunk = items[i : i + size]
        plans.append(
            ShardPlan(
                shard_id=f"shard-{i // size:03d}",
                index=i // size,
                items=tuple(it.id for it in chunk),
            )
        )
    return plans


def milestone_aligned(
    items: list[WorkItem], milestones: list[Milestone], cfg: dict[str, Any]
) -> list[ShardPlan]:
    """Cut at milestone boundaries. Falls back to fixed_size if no milestones."""
    if not milestones:
        return fixed_size(items, milestones, cfg)
    max_per_shard = int(cfg.get("max_per_shard", 50))
    by_seq = {it.seq: it for it in items}
    # Build cut points: milestone seqs, sorted, plus start/end.
    cut_seqs = sorted({0, *(m.boundary_seq for m in milestones), len(items)})
    plans: list[ShardPlan] = []
    idx = 0
    for a, b in pairwise(cut_seqs):
        chunk = [by_seq[s] for s in range(a, b) if s in by_seq]
        # If chunk too large, fall back to fixed_size for that section.
        if len(chunk) > max_per_shard:
            plans.extend(fixed_size(chunk, [], {"size": max_per_shard}))
            idx = len(plans)
            continue
        if not chunk:
            continue
        plans.append(
            ShardPlan(
                shard_id=f"shard-{idx:03d}",
                index=idx,
                items=tuple(it.id for it in chunk),
            )
        )
        idx += 1
    return plans


def weighted(
    items: list[WorkItem], milestones: list[Milestone], cfg: dict[str, Any]
) -> list[ShardPlan]:
    """Balance a weight field across shards so each shard's total weight ~ target."""
    weight_key = str(cfg.get("weight_key", "word_count"))
    target_weight = float(cfg.get("target_weight", 80000))
    if not items:
        return []
    plans: list[ShardPlan] = []
    current: list[WorkItem] = []
    current_weight = 0.0
    idx = 0
    for it in items:
        w = float(it.payload.get(weight_key, 1))
        if current and current_weight + w > target_weight:
            plans.append(
                ShardPlan(
                    shard_id=f"shard-{idx:03d}",
                    index=idx,
                    items=tuple(i.id for i in current),
                )
            )
            idx += 1
            current = []
            current_weight = 0.0
        current.append(it)
        current_weight += w
    if current:
        plans.append(
            ShardPlan(
                shard_id=f"shard-{idx:03d}",
                index=idx,
                items=tuple(i.id for i in current),
            )
        )
    return plans


__all__ = ["Sharder", "fixed_size", "milestone_aligned", "weighted"]
