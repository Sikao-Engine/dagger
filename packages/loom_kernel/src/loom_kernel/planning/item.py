"""WorkItem, Milestone, ItemLedgerSnapshot.

`seq` is the single hard requirement: global monotonic ordering. It drives
shard boundaries, resume pointers, and progress percentages. Domains with no
natural order (batch translate of independent docs) just assign seq = input order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkItem:
    """One work item: a commit, chapter, file, row, etc."""

    id: str
    seq: int
    title: str
    payload: dict[str, Any] = field(default_factory=dict)
    labels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seq": self.seq,
            "title": self.title,
            "payload": dict(self.payload),
            "labels": list(self.labels),
        }


@dataclass(frozen=True)
class Milestone:
    """A boundary work item that shards prefer to align to (e.g. volume end)."""

    name: str
    boundary_item_id: str
    boundary_seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "boundary_item_id": self.boundary_item_id,
            "boundary_seq": self.boundary_seq,
        }


@dataclass
class ItemLedgerSnapshot:
    """Output of ItemSource.refresh()."""

    items: list[WorkItem]
    milestones: list[Milestone] = field(default_factory=list)
    frontier_item_id: str | None = None  # last completed item
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "milestones": [m.to_dict() for m in self.milestones],
            "frontier_item_id": self.frontier_item_id,
            "meta": dict(self.meta),
        }


__all__ = ["ItemLedgerSnapshot", "Milestone", "WorkItem"]
