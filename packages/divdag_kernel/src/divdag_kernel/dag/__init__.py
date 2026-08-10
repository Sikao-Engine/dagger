"""DAG orchestration kernel: template, context, instantiator, node contracts.

Rewritten from CubeClaw's `dag/` rather than copied. Removed: `TaskType` enum,
`platform` hardcoded field. Added: `Scope.SHARD_DYNAMIC` for runtime shard expansion.
"""

from __future__ import annotations

from .context import ContextConflictError, ContextPatch, NodeContext, apply_edge_map
from .instantiator import InstantiateError, instantiate
from .nodes import NodeContract, NodeHandler, NodeRegistry
from .template import DagTemplate, EdgeDef, EdgeKind, NodeDef, Scope, TemplateError

__all__ = [
    "ContextConflictError",
    "ContextPatch",
    "DagTemplate",
    "EdgeDef",
    "EdgeKind",
    "InstantiateError",
    "NodeContext",
    "NodeContract",
    "NodeDef",
    "NodeHandler",
    "NodeRegistry",
    "Scope",
    "TemplateError",
    "apply_edge_map",
    "instantiate",
]
