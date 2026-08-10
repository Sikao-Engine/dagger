"""ExecutorSpec registry: runtime-registered catalog (replaces CubeClaw's compiled constant)."""

from __future__ import annotations

from .catalog import ExecutorCatalog, ExecutorSpec

__all__ = ["ExecutorCatalog", "ExecutorSpec"]
