"""Instantiator: template × shard plan → concrete NodeRun graph.

This is the single place the abstract topology becomes concrete. Each NodeDef
expands into one NodeRun per shard (or one for run-scope nodes). Edges resolve
into dependencies between NodeRuns based on their EdgeKind.

Dynamic shards: a SHARD_DYNAMIC node starts unscheduled; when the entry node's
result contains `__shards__`, the scheduler calls `expand_dynamic()` to add the
concrete shard nodes (existing NodeRun ids stay stable for idempotent re-runs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import ContextPatch
from .nodes import NodeRegistry
from .template import DagTemplate, EdgeDef, EdgeKind, NodeDef, Scope


class InstantiateError(ValueError):
    """Raised when a template + shard plan cannot be expanded."""


@dataclass(frozen=True)
class ShardPlan:
    """One shard of a run: item range + workspace variant + base_ref."""

    shard_id: str
    index: int
    items: tuple[str, ...] = ()  # WorkItem ids
    base_ref: str = ""
    variant: str = "shard"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "index": self.index,
            "items": list(self.items),
            "base_ref": self.base_ref,
            "variant": self.variant,
            "meta": dict(self.meta),
        }


@dataclass
class NodeRun:
    """A concrete node instance in an expanded DAG."""

    node_run_id: str
    node_key: str  # template NodeDef.key
    node_type: str  # ExecutorSpec.key
    scope: Scope
    shard_id: str | None = None
    shard_index: int | None = None
    dependencies: set[str] = field(default_factory=set)  # node_run_ids this depends on
    params: dict[str, Any] = field(default_factory=dict)
    context_patch: ContextPatch = field(default_factory=ContextPatch)
    is_dynamic_seed: bool = False  # True if this is the SHARD_DYNAMIC node awaiting expansion.

    @property
    def is_run_scope(self) -> bool:
        return self.scope in (Scope.RUN, Scope.RUN_ENTRY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_run_id": self.node_run_id,
            "node_key": self.node_key,
            "node_type": self.node_type,
            "scope": self.scope.value,
            "shard_id": self.shard_id,
            "shard_index": self.shard_index,
            "dependencies": sorted(self.dependencies),
            "params": dict(self.params),
            "is_dynamic_seed": self.is_dynamic_seed,
        }


@dataclass
class NodeRunGraph:
    """The expanded DAG: nodes + edges resolved into dependencies."""

    template_id: str
    run_id: str
    shards: tuple[ShardPlan, ...]
    nodes: dict[str, NodeRun] = field(default_factory=dict)
    # Per-node context inputs (merged ancestor patches, pre-edge-map).
    context_inputs: dict[str, list[ContextPatch]] = field(default_factory=dict)

    def topological_order(self) -> list[str]:
        """Return node_run_ids in dependency order (raises on cycle)."""
        visited: set[str] = set()
        order: list[str] = []

        def visit(nid: str, stack: set[str]) -> None:
            if nid in visited:
                return
            if nid in stack:
                raise InstantiateError(f"cycle at {nid!r}")
            stack.add(nid)
            for dep in self.nodes[nid].dependencies:
                visit(dep, stack)
            stack.discard(nid)
            visited.add(nid)
            order.append(nid)

        for nid in self.nodes:
            visit(nid, set())
        return order

    def ready_nodes(self, done: set[str]) -> list[str]:
        """Nodes whose dependencies are all in `done`, excluding already-done."""
        out: list[str] = []
        for nid, node in self.nodes.items():
            if nid in done:
                continue
            if node.dependencies <= done:
                out.append(nid)
        # Sort by priority-then-key for stable scheduling.
        return sorted(out, key=lambda nid: (self._priority(nid), nid))

    def _priority(self, nid: str) -> int:
        # We don't have NodeDef here directly, but params may carry it; default 100.
        return int(self.nodes[nid].params.get("_priority", 100))

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "run_id": self.run_id,
            "shards": [s.to_dict() for s in self.shards],
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
        }


def instantiate(
    *,
    template: DagTemplate,
    run_id: str,
    shards: list[ShardPlan],
    node_registry: NodeRegistry | None = None,
) -> NodeRunGraph:
    """Expand a template into a NodeRunGraph for the given shards.

    Selector-based pruning (the `selectors` field of ExecutorSpec) happens later
    at schedule time, not here — the instantiator is selector-agnostic.
    """
    template.validate()
    if not shards:
        raise InstantiateError("cannot instantiate with zero shards")
    shards_t = tuple(shards)
    graph = NodeRunGraph(
        template_id=template.id,
        run_id=run_id,
        shards=shards_t,
    )

    # 1. Expand nodes into NodeRuns.
    for ndef in template.nodes:
        _expand_node(graph, ndef, shards_t, run_id)

    # 2. Resolve edges into dependencies + record context inputs.
    for edge in template.edges:
        _resolve_edge(graph, edge, template, shards_t)

    return graph


def _node_run_id(node_key: str, shard_index: int | None, run_id: str) -> str:
    """Stable, opaque id: run_id + node_key + shard suffix.

    Uses `__` separators so the id is a safe file-name segment on Windows
    (where `:` is reserved) and POSIX alike.
    """
    if shard_index is None:
        return f"{run_id}__{node_key}"
    return f"{run_id}__{node_key}__s{shard_index:03d}"


def _expand_node(
    graph: NodeRunGraph,
    ndef: NodeDef,
    shards: tuple[ShardPlan, ...],
    run_id: str,
) -> None:
    if ndef.scope is Scope.RUN_ENTRY or ndef.scope is Scope.RUN:
        nrid = _node_run_id(ndef.key, None, run_id)
        graph.nodes[nrid] = NodeRun(
            node_run_id=nrid,
            node_key=ndef.key,
            node_type=ndef.node_type,
            scope=ndef.scope,
            params={**ndef.params, "_priority": ndef.priority},
        )
    elif ndef.scope is Scope.SHARD:
        for sh in shards:
            nrid = _node_run_id(ndef.key, sh.index, run_id)
            graph.nodes[nrid] = NodeRun(
                node_run_id=nrid,
                node_key=ndef.key,
                node_type=ndef.node_type,
                scope=ndef.scope,
                shard_id=sh.shard_id,
                shard_index=sh.index,
                params={**ndef.params, "_priority": ndef.priority},
            )
    elif ndef.scope is Scope.SHARD_DYNAMIC:
        # The seed node runs once; concrete shards are expanded later via
        # expand_dynamic(). We still create one node so dependencies can reference it.
        nrid = _node_run_id(ndef.key, None, run_id)
        graph.nodes[nrid] = NodeRun(
            node_run_id=nrid,
            node_key=ndef.key,
            node_type=ndef.node_type,
            scope=ndef.scope,
            params={**ndef.params, "_priority": ndef.priority},
            is_dynamic_seed=True,
        )
    else:  # pragma: no cover - exhaustive enum
        raise InstantiateError(f"unknown scope: {ndef.scope!r}")


def _resolve_edge(
    graph: NodeRunGraph,
    edge: EdgeDef,
    template: DagTemplate,
    shards: tuple[ShardPlan, ...],
) -> None:
    src_scope = template.node(edge.source).scope
    tgt_scope = template.node(edge.target).scope

    if edge.kind is EdgeKind.INTRA:
        # Same shard: src[s] -> tgt[s] for every shard.
        if src_scope is not Scope.SHARD or tgt_scope is not Scope.SHARD:
            raise InstantiateError(
                f"INTRA edge {edge.source}->{edge.target} requires both nodes SHARD-scoped"
            )
        for sh in shards:
            s_id = _node_run_id(edge.source, sh.index, graph.run_id)
            t_id = _node_run_id(edge.target, sh.index, graph.run_id)
            if s_id in graph.nodes and t_id in graph.nodes:
                graph.nodes[t_id].dependencies.add(s_id)

    elif edge.kind is EdgeKind.RUN_ENTRY:
        # run_entry src -> single shard tgt (paired by index). Not commonly used
        # directly; RUN_ENTRY_ALL is the typical fan-out. We model RUN_ENTRY as
        # "src -> tgt of shard 0 only" — semantics: an entry that hands off to the
        # first shard specifically.
        if tgt_scope is not Scope.SHARD:
            raise InstantiateError(
                f"RUN_ENTRY edge {edge.source}->{edge.target} requires target SHARD-scoped"
            )
        s_id = _node_run_id(edge.source, None, graph.run_id)
        if shards:
            t_id = _node_run_id(edge.target, shards[0].index, graph.run_id)
            if t_id in graph.nodes:
                graph.nodes[t_id].dependencies.add(s_id)

    elif edge.kind is EdgeKind.RUN_ENTRY_ALL:
        # run_entry src -> tgt of every shard.
        if tgt_scope is not Scope.SHARD:
            raise InstantiateError(
                f"RUN_ENTRY_ALL edge {edge.source}->{edge.target} requires target SHARD-scoped"
            )
        s_id = _node_run_id(edge.source, None, graph.run_id)
        for sh in shards:
            t_id = _node_run_id(edge.target, sh.index, graph.run_id)
            if t_id in graph.nodes:
                graph.nodes[t_id].dependencies.add(s_id)

    elif edge.kind is EdgeKind.SERIAL_PREV:
        # shard[i] tgt depends on shard[i-1] src (cross-shard serial).
        if edge.source == edge.target:
            # Self-edge: shard[i] depends on shard[i-1] of the same node.
            for i in range(1, len(shards)):
                s_id = _node_run_id(edge.source, shards[i - 1].index, graph.run_id)
                t_id = _node_run_id(edge.target, shards[i].index, graph.run_id)
                if s_id in graph.nodes and t_id in graph.nodes:
                    graph.nodes[t_id].dependencies.add(s_id)
        else:
            for i in range(1, len(shards)):
                s_id = _node_run_id(edge.source, shards[i - 1].index, graph.run_id)
                t_id = _node_run_id(edge.target, shards[i].index, graph.run_id)
                if s_id in graph.nodes and t_id in graph.nodes:
                    graph.nodes[t_id].dependencies.add(s_id)

    elif edge.kind is EdgeKind.LAST:
        # run-scope tgt depends on the last shard's src.
        s_id = _node_run_id(edge.source, shards[-1].index, graph.run_id)
        t_id = _node_run_id(edge.target, None, graph.run_id)
        if s_id in graph.nodes and t_id in graph.nodes:
            graph.nodes[t_id].dependencies.add(s_id)

    elif edge.kind is EdgeKind.ALL:
        # run-scope tgt depends on src of every shard.
        if tgt_scope is not Scope.RUN:
            raise InstantiateError(
                f"ALL edge {edge.source}->{edge.target} requires target RUN-scoped"
            )
        t_id = _node_run_id(edge.target, None, graph.run_id)
        for sh in shards:
            s_id = _node_run_id(edge.source, sh.index, graph.run_id)
            if s_id in graph.nodes and t_id in graph.nodes:
                graph.nodes[t_id].dependencies.add(s_id)

    else:  # pragma: no cover - exhaustive enum
        raise InstantiateError(f"unknown edge kind: {edge.kind!r}")


def expand_dynamic(
    *,
    graph: NodeRunGraph,
    template: DagTemplate,
    seed_node_key: str,
    shards: list[ShardPlan],
) -> list[NodeRun]:
    """Expand a SHARD_DYNAMIC node into per-shard nodes after the seed returns `__shards__`.

    Returns the newly-created NodeRuns. Existing NodeRun ids are unchanged, so a
    re-run that finds the seed already expanded is idempotent (caller checks).
    """
    new_nodes: list[NodeRun] = []
    seed_id = _node_run_id(seed_node_key, None, graph.run_id)
    seed = graph.nodes.get(seed_id)
    if seed is None:
        raise InstantiateError(f"dynamic seed node not found: {seed_node_key!r}")
    ndef = template.node(seed_node_key)
    for sh in shards:
        nrid = _node_run_id(seed_node_key, sh.index, graph.run_id)
        if nrid in graph.nodes:
            continue
        node = NodeRun(
            node_run_id=nrid,
            node_key=seed_node_key,
            node_type=ndef.node_type,
            scope=Scope.SHARD,
            shard_id=sh.shard_id,
            shard_index=sh.index,
            params={**ndef.params, "_priority": ndef.priority},
        )
        graph.nodes[nrid] = node
        new_nodes.append(node)
    return new_nodes


__all__ = [
    "InstantiateError",
    "NodeRun",
    "NodeRunGraph",
    "ShardPlan",
    "expand_dynamic",
    "instantiate",
]
