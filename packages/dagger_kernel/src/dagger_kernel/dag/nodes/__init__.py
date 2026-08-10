"""Node contracts and handlers.

A `NodeContract` declares which context keys a node reads and writes. The
registry fail-fast-validates: a node reading an undeclared (missing) key raises
immediately; a node writing an undeclared key is rejected.

`NodeHandler` is the SPI for builtin nodes (deterministic code paths like
entity_merge / timeline_merge). Agent nodes don't need a handler — they go
through the session_runner. `NodeRegistry` is the runtime lookup table.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Protocol

from ..context import ContextPatch, NodeContext


class ContractError(ValueError):
    """Raised when a node violates its declared reads/writes."""


@dataclass(frozen=True)
class NodeContract:
    """Static declaration of a node's I/O surface."""

    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()

    def assert_reads_present(self, ctx: NodeContext) -> None:
        for k in self.reads:
            if k not in ctx.values():
                raise ContractError(f"node requires context key {k!r} which is absent")

    def assert_writes_allowed(self, outputs: dict[str, Any]) -> None:
        bad = [k for k in outputs if k not in self.writes]
        if bad:
            raise ContractError(
                f"node attempted to write undeclared keys: {bad} (declared writes: {self.writes})"
            )

    def to_dict(self) -> dict[str, list[str]]:
        return {"reads": list(self.reads), "writes": list(self.writes)}


class NodeHandler(Protocol):
    """SPI for builtin (non-Agent) nodes. Pure deterministic code, no I/O side effects."""

    contract: NodeContract

    def run(self, ctx: NodeContext) -> ContextPatch:  # pragma: no cover - protocol
        ...


@dataclass
class NodeRuntime:
    """Per-node-run runtime state held by the engine between executions."""

    node_key: str
    node_type: str
    contract: NodeContract
    handler: NodeHandler | None = None  # None for agent-kind nodes.


class NodeRegistry:
    """Lookup table for NodeHandler implementations, keyed by node_type.

    Handlers are registered at startup by domains via `register()`. Agent-kind
    nodes don't register a handler (their executor_kind is "agent").
    """

    def __init__(self) -> None:
        self._handlers: dict[str, NodeHandler] = {}
        self._contracts: dict[str, NodeContract] = {}

    def register(
        self,
        node_type: str,
        handler: NodeHandler | None = None,
        *,
        contract: NodeContract | None = None,
    ) -> None:
        if handler is not None:
            self._handlers[node_type] = handler
            if contract is None:
                contract = getattr(handler, "contract", NodeContract())
        if contract is not None:
            self._contracts[node_type] = contract

    def has(self, node_type: str) -> bool:
        return node_type in self._handlers or node_type in self._contracts

    def contract_for(self, node_type: str) -> NodeContract:
        return self._contracts.get(node_type, NodeContract())

    def handler_for(self, node_type: str) -> NodeHandler | None:
        return self._handlers.get(node_type)

    def load_handler_from_path(self, node_type: str, path: str) -> None:
        """Import a handler from a "module:Class" path and register it."""
        module_name, _, attr = path.partition(":")
        if not attr:
            raise ValueError(f"handler path must be 'module:Class', got {path!r}")
        module = importlib.import_module(module_name)
        cls = getattr(module, attr)
        instance = cls()
        contract = getattr(instance, "contract", NodeContract())
        self.register(node_type, instance, contract=contract)

    def all(self) -> dict[str, NodeContract]:
        return dict(self._contracts)


__all__ = ["ContractError", "NodeContract", "NodeHandler", "NodeRegistry", "NodeRuntime"]
