"""Builtin NodeHandlers for novel_digest (deterministic merge nodes)."""

from __future__ import annotations

from dagger_kernel.dag import NodeRegistry

from .entity_merge import EntityMergeNode
from .timeline_merge import TimelineMergeNode


def register_handlers(registry: NodeRegistry) -> None:
    """Register both merge handlers (called via the SPI `node_handlers` hook)."""
    registry.register("entity_merge", EntityMergeNode())
    registry.register("timeline_merge", TimelineMergeNode())


__all__ = ["EntityMergeNode", "TimelineMergeNode", "register_handlers"]
