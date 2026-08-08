"""DAG template model: data-driven topology description.

`NodeDef` / `EdgeDef` / `DagTemplate` describe a pipeline shape independent of
shard count or concrete executors. The instantiator combines a template with a
shard plan to produce a concrete NodeRun graph.

`EdgeKind` controls how edges resolve when a template is expanded across shards:
- `INTRA`: same shard, source-before-target.
- `RUN_ENTRY`: run-entry node → shard node (one edge per shard).
- `RUN_ENTRY_ALL`: run-entry node → all shards of the target (fan-out).
- `SERIAL_PREV`: shard[i] target depends on shard[i-1] source (cross-shard serial).
- `LAST`: target depends on the last shard's source (run-level aggregation off last shard).
- `ALL`: target (typically run-scope) depends on all shards of the source (fan-in).

The topology fingerprint lets us detect when a template has changed and reseed
the DB copy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TemplateError(ValueError):
    """Raised by `DagTemplate.validate()` for cycles, dangling edges, duplicate nodes."""


class Scope(StrEnum):
    """Where a node lives in the run/shard hierarchy. (Mirrors state.Scope for the DAG side.)"""

    RUN_ENTRY = "run_entry"  # one instance per run, runs before any shard.
    SHARD = "shard"  # one instance per shard.
    RUN = "run"  # one instance per run, runs after shards (aggregation).
    SHARD_DYNAMIC = "shard_dynamic"  # shard node whose count is discovered at runtime.


class EdgeKind(StrEnum):
    INTRA = "intra"  # same shard, sequential.
    RUN_ENTRY = "run_entry"  # run-entry node → a single shard (paired).
    RUN_ENTRY_ALL = "run_entry_all"  # run-entry node → all shards.
    SERIAL_PREV = "serial_prev"  # shard[i] → shard[i-1] dependency (cross-shard serial).
    LAST = "last"  # run node depends on the last shard's source.
    ALL = "all"  # run node depends on all shards of the source.


@dataclass(frozen=True)
class NodeDef:
    """A node definition in a template."""

    key: str  # unique within template
    node_type: str  # ExecutorSpec.key; validated at schedule time
    scope: Scope
    priority: int = 100  # lower = earlier within a ready wave
    params: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 3
    timeout_seconds: int = 3600

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "node_type": self.node_type,
            "scope": self.scope.value,
            "priority": self.priority,
            "params": dict(self.params),
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class EdgeDef:
    """A directed edge in a template."""

    source: str  # NodeDef.key
    target: str  # NodeDef.key
    kind: EdgeKind = EdgeKind.INTRA
    maps: dict[str, str] = field(default_factory=dict)  # {target_context_key: source_context_key}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "kind": self.kind.value,
        }
        if self.maps:
            d["maps"] = dict(self.maps)
        return d


@dataclass(frozen=True)
class DagTemplate:
    """A complete pipeline description."""

    id: str
    domain_id: str
    nodes: tuple[NodeDef, ...]
    edges: tuple[EdgeDef, ...] = ()
    is_default: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        """Coerce mutable fields to tuples so the template is hashable."""
        if not isinstance(self.nodes, tuple):
            object.__setattr__(self, "nodes", tuple(self.nodes))
        if not isinstance(self.edges, tuple):
            object.__setattr__(self, "edges", tuple(self.edges))

    def validate(self) -> None:
        """Fail-fast validation: cycles, dangling edges, duplicate node keys, scope rules."""
        keys = [n.key for n in self.nodes]
        if len(set(keys)) != len(keys):
            dupes = {k for k in keys if keys.count(k) > 1}
            raise TemplateError(f"duplicate node keys: {sorted(dupes)}")
        if not self.nodes:
            raise TemplateError("template has no nodes")
        keyset = set(keys)
        for e in self.edges:
            if e.source not in keyset:
                raise TemplateError(f"edge source {e.source!r} not in nodes")
            if e.target not in keyset:
                raise TemplateError(f"edge target {e.target!r} not in nodes")
            if e.source == e.target and e.kind is not EdgeKind.SERIAL_PREV:
                raise TemplateError(
                    f"self-edge {e.source!r}→{e.target!r} requires SERIAL_PREV kind"
                )
        # Detect cycles (ignoring SERIAL_PREV self-edges, which are intentional).
        if _has_cycle(self.nodes, self.edges):
            raise TemplateError("template has a cycle")

    def fingerprint(self) -> str:
        """Stable topology hash. Changes when nodes/edges change (used to reseed DB)."""
        payload = json.dumps(
            {
                "nodes": [n.to_dict() for n in self.nodes],
                "edges": [e.to_dict() for e in self.edges],
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def node(self, key: str) -> NodeDef:
        for n in self.nodes:
            if n.key == key:
                return n
        raise KeyError(key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "domain_id": self.domain_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "is_default": self.is_default,
            "version": self.version,
        }


def _has_cycle(nodes: tuple[NodeDef, ...], edges: tuple[EdgeDef, ...]) -> bool:
    """Detect cycles via DFS. SERIAL_PREV self-edges are intentional, not cycles."""
    adj: dict[str, list[str]] = {n.key: [] for n in nodes}
    for e in edges:
        if e.kind is EdgeKind.SERIAL_PREV and e.source == e.target:
            continue
        adj[e.source].append(e.target)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in adj}

    def visit(u: str) -> bool:
        color[u] = GRAY
        for v in adj[u]:
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and visit(v):
                return True
        color[u] = BLACK
        return False

    return any(color[k] == WHITE and visit(k) for k in adj)


__all__ = [
    "DagTemplate",
    "EdgeDef",
    "EdgeKind",
    "NodeDef",
    "Scope",
    "TemplateError",
]
