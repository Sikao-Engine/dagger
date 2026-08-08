"""In-memory execution engine for NodeRunGraph.

Topology advancement, readiness, failure propagation, retry, dynamic shard
expansion. Each step writes node/context/result to StateStore control/contract
layers so a crash lets a later run resume from state (M2 doesn't need DB; the
StateStore *is* the recovery substrate).

The engine is synchronous and single-threaded by design. Concurrency lives at
the M5 scheduler layer (which multiplexes across shards via anyio); the engine
itself is the unit-of-work primitive.

Agent nodes are dispatched via an injected `AgentDispatcher` callback so the
engine stays free of HTTP/async. Builtin nodes run their NodeHandler directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .dag import ContextPatch, NodeContext, NodeRegistry, apply_edge_map
from .dag.instantiator import NodeRun, NodeRunGraph, ShardPlan, expand_dynamic
from .dag.template import DagTemplate, Scope
from .executors import ExecutorCatalog, ExecutorSpec
from .state import K, StateStore
from .state.retry import RetryPolicy
from .state.schema import SchemaError


class EngineError(RuntimeError):
    """Raised on engine-level invariant violations."""


class NodeFailed(EngineError):
    """A node exhausted its retries or returned a hard failure."""

    def __init__(self, node_run_id: str, reason: str) -> None:
        super().__init__(f"node {node_run_id!r} failed: {reason}")
        self.node_run_id = node_run_id
        self.reason = reason


class AgentDispatcher(Protocol):
    """Callback the engine uses to run an agent node.

    Receives the node run + resolved context + the SkillSpec. Returns the
    session_result body dict (validated against the contract).
    """

    def __call__(
        self,
        *,
        node_run: NodeRun,
        ctx: NodeContext,
        executor: ExecutorSpec,
        store: StateStore,
        attempt: int,
    ) -> dict[str, Any]: ...


@dataclass
class EngineHooks:
    """Optional callbacks the engine invokes at lifecycle points."""

    on_node_start: Callable[[str], None] | None = None
    on_node_success: Callable[[str, dict[str, Any]], None] | None = None
    on_node_failure: Callable[[str, str], None] | None = None
    on_dynamic_expand: Callable[[str, list[ShardPlan]], None] | None = None


@dataclass
class EngineRun:
    """The result of running a graph to completion (or to a hard failure)."""

    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    context_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)


def run_graph(
    *,
    graph: NodeRunGraph,
    template: DagTemplate,
    store: StateStore,
    catalog: ExecutorCatalog,
    node_registry: NodeRegistry,
    agent_dispatcher: AgentDispatcher | None = None,
    hooks: EngineHooks | None = None,
    max_node_retries: int = 3,
) -> EngineRun:
    """Run a NodeRunGraph to completion.

    Topology-driven: ready nodes run; their outputs feed downstream context; the
    next wave becomes ready. Failures propagate: a failed node blocks its
    descendants (they are marked skipped). Dynamic-shard nodes expand when their
    seed returns`.
    """
    result = EngineRun()
    # Per-node accumulated ancestor context patches (already edge-mapped).
    context_inputs: dict[str, list[ContextPatch]] = {nid: [] for nid in graph.nodes}
    # Node-level done set: ids whose result is committed as success.
    done: set[str] = set()
    # Failed nodes — descendants are skipped.
    failed: set[str] = set()

    # Save the run config + plan once for crash recovery.
    store.write_json(
        K.run_config(),
        {
            "run_id": graph.run_id,
            "template_id": template.id,
            "domain_id": template.domain_id,
        },
        kind="plan",
        written_by={"role": "orchestrator"},
    )

    # Iterate to fixpoint: keep running ready nodes until none remain.
    # We recompute ready after each node; small DAGs make this fine.
    while True:
        ready = _ready_nodes(graph, done, failed)
        if not ready:
            break
        # Process by priority (lowest first) for stable ordering.
        ready.sort(key=lambda nid: (graph.nodes[nid].params.get("_priority", 100), nid))
        progressed = False
        for nid in ready:
            node = graph.nodes[nid]
            if _is_dynamic_seed(node, template) and agent_dispatcher is None:
                # Dynamic seeds need an agent to discover shards; with no dispatcher
                # we treat them as no-ops.
                done.add(nid)
                progressed = True
                continue
            try:
                outputs = _run_one_node(
                    node=node,
                    template=template,
                    graph=graph,
                    store=store,
                    catalog=catalog,
                    node_registry=node_registry,
                    agent_dispatcher=agent_dispatcher,
                    context_inputs=context_inputs,
                    max_retries=max_node_retries,
                    hooks=hooks,
                )
            except NodeFailed as exc:
                failed.add(nid)
                result.failed.append(nid)
                if hooks and hooks.on_node_failure:
                    hooks.on_node_failure(nid, exc.reason)
                # Mark all descendants skipped.
                for desc in _descendants(graph, nid):
                    if desc not in done and desc not in failed:
                        result.skipped.append(desc)
                        failed.add(desc)
                progressed = True
                continue
            # Success: write result, propagate context patch.
            result.completed.append(nid)
            result.context_outputs[nid] = outputs
            done.add(nid)
            if hooks and hooks.on_node_success:
                hooks.on_node_success(nid, outputs)
            # Dynamic shard expansion check.
            shards_patch = outputs.get("__shards__")
            if isinstance(shards_patch, list) and shards_patch:
                _do_dynamic_expand(
                    graph=graph,
                    template=template,
                    node=node,
                    shards_data=shards_patch,
                    hooks=hooks,
                )
                # Re-seed context_inputs for new nodes.
                for new_nid in graph.nodes:
                    context_inputs.setdefault(new_nid, [])
            # Propagate this node's outputs to descendants per edges.
            _propagate(
                node=node,
                outputs=outputs,
                graph=graph,
                template=template,
                context_inputs=context_inputs,
            )
            progressed = True
        if not progressed:
            break

    return result


def _ready_nodes(graph: NodeRunGraph, done: set[str], failed: set[str]) -> list[str]:
    """Nodes whose deps are all done AND not already processed."""
    out: list[str] = []
    for nid, node in graph.nodes.items():
        if nid in done or nid in failed:
            continue
        # A node is ready if all its dependencies are done (success).
        # If any dependency is failed, the node is blocked (handled elsewhere).
        if any(dep in failed for dep in node.dependencies):
            continue
        if node.dependencies <= done:
            out.append(nid)
    return out


def _descendants(graph: NodeRunGraph, nid: str) -> list[str]:
    """All transitive descendants of `nid` (nodes that depend on it directly or indirectly)."""
    out: list[str] = []
    stack = [nid]
    seen: set[str] = set()
    while stack:
        cur = stack.pop()
        for other_id, other in graph.nodes.items():
            if cur in other.dependencies and other_id not in seen:
                seen.add(other_id)
                out.append(other_id)
                stack.append(other_id)
    return out


def _is_dynamic_seed(node: NodeRun, template: DagTemplate) -> bool:
    return node.is_dynamic_seed and node.scope is Scope.SHARD_DYNAMIC


def _do_dynamic_expand(
    *,
    graph: NodeRunGraph,
    template: DagTemplate,
    node: NodeRun,
    shards_data: list[Any],
    hooks: EngineHooks | None,
) -> None:
    """Expand a dynamic seed into per-shard nodes based on the returned shards list."""
    plans: list[ShardPlan] = []
    for i, sd in enumerate(shards_data):
        if isinstance(sd, dict):
            sid = str(sd.get("shard_id") or f"dyn-{i:03d}")
            items = tuple(str(x) for x in sd.get("items", []))
        else:
            sid = str(sd)
            items = ()
        plans.append(ShardPlan(shard_id=sid, index=i, items=items))
    expand_dynamic(
        graph=graph,
        template=template,
        seed_node_key=node.node_key,
        shards=plans,
    )
    if hooks and hooks.on_dynamic_expand:
        hooks.on_dynamic_expand(node.node_run_id, plans)


def _run_one_node(
    *,
    node: NodeRun,
    template: DagTemplate,
    graph: NodeRunGraph,
    store: StateStore,
    catalog: ExecutorCatalog,
    node_registry: NodeRegistry,
    agent_dispatcher: AgentDispatcher | None,
    context_inputs: dict[str, list[ContextPatch]],
    max_retries: int,
    hooks: EngineHooks | None,
) -> dict[str, Any]:
    """Run one node to success or failure. Handles retries + state writes."""
    executor = catalog.require(node.node_type)
    # Build the resolved context: run_config → shard_seed → merged ancestor patches → node params.
    ctx = _resolve_context(node=node, graph=graph, context_inputs=context_inputs)
    # Validate the contract: required reads must be present.
    contract = node_registry.contract_for(node.node_type)
    # Only enforce reads/writes for builtin nodes (handlers with explicit contracts).
    # Agent nodes have no handler registered; their contract comes from SkillSpec.produces,
    # which is enforced at the dispatcher layer (where SkillSpec is available).
    is_builtin = executor.handler_kind == "builtin"
    if is_builtin:
        contract.assert_reads_present(ctx)

    if hooks and hooks.on_node_start:
        hooks.on_node_start(node.node_run_id)

    # Idempotent skip: if a success result already exists for the latest attempt, return it.
    latest = store.latest_attempt(node.node_run_id)
    if latest > 0:
        prior = store.read_json(K.result(node.node_run_id, latest))
        if prior and prior.get("status") == "success" and prior.get("success") is True:
            return dict(prior.get("outputs", {}))

    # Determine retry policy from the executor's skill (if agent) or default FRESH.
    policy = RetryPolicy.FRESH
    if executor.handler_kind == "agent" and executor.skill:
        # Look up SkillSpec via a domain registry hook (not available here directly;
        # the dispatcher carries it). The engine just defaults to FRESH; the
        # dispatcher is free to override on its side.
        pass

    attempt = 1
    last_error = ""
    while attempt <= max_retries:
        store.begin_attempt(node.node_run_id, policy=policy if attempt == 1 else RetryPolicy.FRESH)
        try:
            outputs = _dispatch_node(
                node=node,
                executor=executor,
                ctx=ctx,
                store=store,
                attempt=attempt,
                node_registry=node_registry,
                agent_dispatcher=agent_dispatcher,
                last_error=last_error,
            )
        except SchemaError as exc:
            last_error = f"schema: {exc.errors}"
            attempt += 1
            continue
        except NodeFailed as exc:
            last_error = exc.reason
            attempt += 1
            continue
        # Write the result contract.
        result_body = {
            "status": "success",
            "success": True,
            "node_run_id": node.node_run_id,
            "node_type": node.node_type,
            "skill": executor.skill or "",
            "outputs": outputs,
            "summary": "",
        }
        store.write_json(
            K.result(node.node_run_id, attempt),
            result_body,
            kind="session_result",
            written_by={"role": "orchestrator"},
        )
        if is_builtin:
            contract.assert_writes_allowed(outputs)
        return outputs
    raise NodeFailed(node.node_run_id, last_error or "max retries exhausted")


def _resolve_context(
    *,
    node: NodeRun,
    graph: NodeRunGraph,
    context_inputs: dict[str, list[ContextPatch]],
) -> NodeContext:
    """Merge ancestor patches (de-conflicted) + run config + shard seed + node params."""
    patches = context_inputs.get(node.node_run_id, [])
    merged = ContextPatch.merge(*patches) if patches else ContextPatch(values={})
    return NodeContext(
        run_config={"run_id": graph.run_id, "template_id": graph.template_id},
        shard_seed={
            "shard_id": node.shard_id or "",
            "shard_index": node.shard_index if node.shard_index is not None else -1,
        },
        ancestor_patches=dict(merged.values),
        node_params={k: v for k, v in node.params.items() if not k.startswith("_")},
        shard={
            "shard_id": node.shard_id or "",
            "index": node.shard_index if node.shard_index is not None else 0,
        },
    )


def _dispatch_node(
    *,
    node: NodeRun,
    executor: ExecutorSpec,
    ctx: NodeContext,
    store: StateStore,
    attempt: int,
    node_registry: NodeRegistry,
    agent_dispatcher: AgentDispatcher | None,
    last_error: str,
) -> dict[str, Any]:
    """Run a node via its handler_kind: builtin → NodeHandler; agent → dispatcher."""
    if executor.handler_kind == "builtin":
        handler = node_registry.handler_for(node.node_type)
        if handler is None:
            raise NodeFailed(node.node_run_id, f"no handler for builtin {node.node_type!r}")
        patch = handler.run(ctx)
        return dict(patch.values)
    if executor.handler_kind == "agent":
        if agent_dispatcher is None:
            raise NodeFailed(node.node_run_id, "no agent dispatcher configured")
        return agent_dispatcher(
            node_run=node,
            ctx=ctx,
            executor=executor,
            store=store,
            attempt=attempt,
        )
    if executor.handler_kind == "unsupported":
        raise NodeFailed(node.node_run_id, f"executor {node.node_type!r} is unsupported")
    raise NodeFailed(node.node_run_id, f"unknown handler_kind {executor.handler_kind!r}")


def _propagate(
    *,
    node: NodeRun,
    outputs: dict[str, Any],
    graph: NodeRunGraph,
    template: DagTemplate,
    context_inputs: dict[str, list[ContextPatch]],
) -> None:
    """Push this node's outputs to descendant nodes per outgoing edges (with maps)."""
    patch = ContextPatch(values=dict(outputs), source_node_run_id=node.node_run_id)
    for edge in template.edges:
        if edge.source != node.node_key:
            continue
        # For each shard of the target, the patch is delivered (possibly mapped).
        target_scope = template.node(edge.target).scope
        if target_scope in (Scope.RUN, Scope.RUN_ENTRY):
            t_id = f"{graph.run_id}__{edge.target}"
            mapped = apply_edge_map(patch, edge.maps)
            context_inputs.setdefault(t_id, []).append(mapped)
        elif target_scope is Scope.SHARD:
            for sh in graph.shards:
                t_id = f"{graph.run_id}__{edge.target}__s{sh.index:03d}"
                mapped = apply_edge_map(patch, edge.maps)
                context_inputs.setdefault(t_id, []).append(mapped)
        elif target_scope is Scope.SHARD_DYNAMIC:
            # Dynamic targets are expanded later; record patch on the seed for now.
            t_id = f"{graph.run_id}__{edge.target}"
            mapped = apply_edge_map(patch, edge.maps)
            context_inputs.setdefault(t_id, []).append(mapped)


__all__ = [
    "AgentDispatcher",
    "EngineError",
    "EngineHooks",
    "EngineRun",
    "NodeFailed",
    "run_graph",
]
