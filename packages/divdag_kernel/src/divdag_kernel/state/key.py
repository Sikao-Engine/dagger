"""StateKey: the coordinate system for every state object.

A `StateKey` is a frozen, hashable value uniquely identifying a state object.
The only legal way to obtain a path is `StateStore.path(key)`, which calls the
pure `layout()` function. IDs (`node_run_id`, `shard_id`, `item_id`) are opaque
strings — they carry no semantic meaning to the kernel, only to the domain.

Illegal combinations (e.g. ARTIFACT layer without item/slot context, CONTRACT
without a node_run_id) raise at construction time.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

# Sentinel for "dynamic shard expansion" — reserved patch key produced by an
# entry node that returns a list of shards for the scheduler to expand into.
SHARDS_PATCH_KEY = "__shards__"


class Layer(str, Enum):
    """State ownership layers. See state_layer_architecture.md §3."""

    CONTROL = "control"  # Orchestrator-only writes; node input + context snapshot.
    CONTRACT = "contract"  # Agent writes the result file; orchestrator writes task_card.
    SCRATCH = "scratch"  # Agent / skill free read-write; GC-able.
    ARTIFACT = "artifact"  # Agent append-only + CLI; immutable once written.
    LOG = "log"  # Orchestrator (transcript) + command executor; ephemeral.


class Scope(str, Enum):
    """Where a state object lives in the run/shard/item hierarchy."""

    RUN = "run"
    SHARD = "shard"
    NODE = "node"
    ITEM = "item"
    NODE_RUN = "node_run"  # node-scoped but keyed by node_run_id (contract/scratch/log)


class StateKeyError(ValueError):
    """Raised when a StateKey is constructed with an illegal combination of fields."""


class StateKey:
    """Frozen, hashable coordinate for one state object.

    Fields:
        layer:    which ownership layer (control/contract/scratch/artifact/log).
        scope:    run / shard / node / item.
        node_run_id: opaque node id. Required for CONTRACT, SCRATCH, LOG layers.
        shard_id:    opaque shard id. Required when scope=SHARD or when an item
                     needs its shard context (some layouts key items under shard).
        item_id:     opaque item id. Required for ARTIFACT scope=ITEM.
        attempt:     attempt number (1-based). Required for CONTRACT layer;
                     required for SCRATCH/LOG when scope=NODE_RUN.
        slot:        artifact slot name ("summary", "result", "cursor", ...).
                     Required for ARTIFACT layer; required for CONTRACT result.

    The constructor validates the above invariants. Use `K` for readable
    construction of common keys.
    """

    # Declared so mypy knows the attribute types (frozen at __init__ time).
    layer: Layer
    scope: Scope
    node_run_id: str | None
    shard_id: str | None
    item_id: str | None
    attempt: int | None
    slot: str
    _frozen: ClassVar[bool] = False

    def __init__(
        self,
        layer: Layer | str,
        scope: Scope | str,
        *,
        node_run_id: str | None = None,
        shard_id: str | None = None,
        item_id: str | None = None,
        attempt: int | None = None,
        slot: str = "",
    ) -> None:
        layer_e = layer if isinstance(layer, Layer) else Layer(layer)
        scope_e = scope if isinstance(scope, Scope) else Scope(scope)
        self._validate(layer_e, scope_e, node_run_id, shard_id, item_id, attempt, slot)
        self.layer = layer_e
        self.scope = scope_e
        self.node_run_id = node_run_id
        self.shard_id = shard_id
        self.item_id = item_id
        self.attempt = attempt
        self.slot = slot
        self._frozen = True  # type: ignore[misc]

    # --- immutability ---
    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise StateKeyError(f"StateKey is frozen; cannot set {name!r}")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise StateKeyError(f"StateKey is frozen; cannot delete {name!r}")

    # --- equality / hash / repr ---
    def _tuple(self) -> tuple[Layer, Scope, str | None, str | None, str | None, int | None, str]:
        return (
            self.layer,
            self.scope,
            self.node_run_id,
            self.shard_id,
            self.item_id,
            self.attempt,
            self.slot,
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, StateKey):
            return self._tuple() == other._tuple()
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._tuple())

    def __repr__(self) -> str:
        parts = [f"layer={self.layer.value}", f"scope={self.scope.value}"]
        if self.node_run_id is not None:
            parts.append(f"node_run_id={self.node_run_id!r}")
        if self.shard_id is not None:
            parts.append(f"shard_id={self.shard_id!r}")
        if self.item_id is not None:
            parts.append(f"item_id={self.item_id!r}")
        if self.attempt is not None:
            parts.append(f"attempt={self.attempt}")
        if self.slot:
            parts.append(f"slot={self.slot!r}")
        return f"StateKey({', '.join(parts)})"

    def to_dict(self) -> dict[str, object]:
        """Serialize for index/journal. None values are omitted to keep records compact."""
        d: dict[str, object] = {
            "layer": self.layer.value,
            "scope": self.scope.value,
        }
        if self.node_run_id is not None:
            d["node_run_id"] = self.node_run_id
        if self.shard_id is not None:
            d["shard_id"] = self.shard_id
        if self.item_id is not None:
            d["item_id"] = self.item_id
        if self.attempt is not None:
            d["attempt"] = self.attempt
        if self.slot:
            d["slot"] = self.slot
        return d

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> StateKey:
        nrid = d.get("node_run_id")
        shid = d.get("shard_id")
        iid = d.get("item_id")
        att = d.get("attempt")
        return cls(
            layer=str(d["layer"]),
            scope=str(d["scope"]),
            node_run_id=str(nrid) if isinstance(nrid, str) else None,
            shard_id=str(shid) if isinstance(shid, str) else None,
            item_id=str(iid) if isinstance(iid, str) else None,
            attempt=int(att) if isinstance(att, (int, str)) else None,
            slot=str(d.get("slot", "")),
        )

    # --- invariant validation ---
    @staticmethod
    def _validate(
        layer: Layer,
        scope: Scope,
        node_run_id: str | None,
        shard_id: str | None,
        item_id: str | None,
        attempt: int | None,
        slot: str,
    ) -> None:
        # IDs must be safe file-name segments when present: no path separators,
        # no empty string (use None instead).
        for name, v in (
            ("node_run_id", node_run_id),
            ("shard_id", shard_id),
            ("item_id", item_id),
        ):
            if v is not None:
                if not v:
                    raise StateKeyError(f"{name} must be non-empty when present")
                if "/" in v or "\\" in v or v in (".", ".."):
                    raise StateKeyError(f"{name} must be a safe path segment: {v!r}")
        if attempt is not None and attempt < 1:
            raise StateKeyError(f"attempt must be >= 1, got {attempt}")
        if slot and ("/" in slot or "\\" in slot or slot in (".", "..")):
            raise StateKeyError(f"slot must be a safe path segment: {slot!r}")

        # Layer-specific requirements.
        if layer is Layer.CONTROL:
            if attempt is not None:
                raise StateKeyError("control layer does not use attempt")
        elif layer is Layer.CONTRACT:
            if not node_run_id:
                raise StateKeyError("contract layer requires node_run_id")
            if attempt is None:
                raise StateKeyError("contract layer requires attempt")
            if scope not in (Scope.NODE, Scope.NODE_RUN):
                raise StateKeyError("contract layer scope must be node or node_run")
        elif layer is Layer.SCRATCH:
            if not node_run_id:
                raise StateKeyError("scratch layer requires node_run_id")
            if attempt is None:
                raise StateKeyError("scratch layer requires attempt")
            if scope is not Scope.NODE_RUN:
                raise StateKeyError("scratch layer scope must be node_run")
        elif layer is Layer.LOG:
            if not node_run_id:
                raise StateKeyError("log layer requires node_run_id")
            if attempt is None:
                raise StateKeyError("log layer requires attempt")
            if scope is not Scope.NODE_RUN:
                raise StateKeyError("log layer scope must be node_run")
        elif layer is Layer.ARTIFACT:
            if scope is Scope.ITEM:
                if not item_id:
                    raise StateKeyError("artifact scope=item requires item_id")
                if not slot:
                    raise StateKeyError("artifact scope=item requires slot")
            elif scope is Scope.SHARD:
                if not shard_id:
                    raise StateKeyError("artifact scope=shard requires shard_id")
                if not slot:
                    raise StateKeyError("artifact scope=shard requires slot")
            elif scope is Scope.RUN:
                if not slot:
                    raise StateKeyError("artifact scope=run requires slot")
            else:
                raise StateKeyError(f"artifact layer does not support scope={scope.value}")
            if attempt is not None:
                raise StateKeyError("artifact layer does not use attempt")


class K:
    """Semantic constructors for common StateKeys.

    This is the **only** place business code should touch StateKey directly.
    Keeping the names here tight keeps the coordinate system readable.
    """

    # --- control layer ---
    @staticmethod
    def run_config() -> StateKey:
        return StateKey(Layer.CONTROL, Scope.RUN, slot="run")

    @staticmethod
    def plan() -> StateKey:
        return StateKey(Layer.CONTROL, Scope.RUN, slot="plan")

    @staticmethod
    def cursor(shard_id: str | None = None) -> StateKey:
        if shard_id is None:
            return StateKey(Layer.CONTROL, Scope.RUN, slot="cursor")
        return StateKey(Layer.CONTROL, Scope.SHARD, shard_id=shard_id, slot="cursor")

    @staticmethod
    def items() -> StateKey:
        return StateKey(Layer.CONTROL, Scope.RUN, slot="items")

    @staticmethod
    def item(item_id: str) -> StateKey:
        return StateKey(Layer.CONTROL, Scope.ITEM, item_id=item_id, slot="item")

    @staticmethod
    def node_def(node_run_id: str) -> StateKey:
        return StateKey(Layer.CONTROL, Scope.NODE, node_run_id=node_run_id, slot="node")

    @staticmethod
    def node_context(node_run_id: str) -> StateKey:
        return StateKey(Layer.CONTROL, Scope.NODE, node_run_id=node_run_id, slot="context")

    # --- contract layer ---
    @staticmethod
    def task_card(node_run_id: str, attempt: int) -> StateKey:
        return StateKey(
            Layer.CONTRACT,
            Scope.NODE_RUN,
            node_run_id=node_run_id,
            attempt=attempt,
            slot="task_card",
        )

    @staticmethod
    def result(node_run_id: str, attempt: int) -> StateKey:
        return StateKey(
            Layer.CONTRACT,
            Scope.NODE_RUN,
            node_run_id=node_run_id,
            attempt=attempt,
            slot="result",
        )

    @staticmethod
    def claim(node_run_id: str, attempt: int) -> StateKey:
        return StateKey(
            Layer.CONTRACT,
            Scope.NODE_RUN,
            node_run_id=node_run_id,
            attempt=attempt,
            slot="claim",
        )

    @staticmethod
    def latest_attempt(node_run_id: str) -> StateKey:
        return StateKey(
            Layer.CONTROL,
            Scope.NODE,
            node_run_id=node_run_id,
            slot="latest_attempt",
        )

    # --- scratch / log ---
    @staticmethod
    def scratch_root(node_run_id: str, attempt: int) -> StateKey:
        return StateKey(
            Layer.SCRATCH,
            Scope.NODE_RUN,
            node_run_id=node_run_id,
            attempt=attempt,
            slot="root",
        )

    @staticmethod
    def transcript(node_run_id: str, attempt: int) -> StateKey:
        return StateKey(
            Layer.LOG,
            Scope.NODE_RUN,
            node_run_id=node_run_id,
            attempt=attempt,
            slot="transcript",
        )

    @staticmethod
    def commands(node_run_id: str, attempt: int) -> StateKey:
        return StateKey(
            Layer.LOG,
            Scope.NODE_RUN,
            node_run_id=node_run_id,
            attempt=attempt,
            slot="commands",
        )

    @staticmethod
    def progress(node_run_id: str, attempt: int) -> StateKey:
        return StateKey(
            Layer.LOG,
            Scope.NODE_RUN,
            node_run_id=node_run_id,
            attempt=attempt,
            slot="progress",
        )

    # --- artifact layer ---
    @staticmethod
    def artifact_run(slot: str) -> StateKey:
        return StateKey(Layer.ARTIFACT, Scope.RUN, slot=slot)

    @staticmethod
    def artifact_shard(shard_id: str, slot: str) -> StateKey:
        return StateKey(Layer.ARTIFACT, Scope.SHARD, shard_id=shard_id, slot=slot)

    @staticmethod
    def artifact_item(item_id: str, slot: str) -> StateKey:
        return StateKey(Layer.ARTIFACT, Scope.ITEM, item_id=item_id, slot=slot)

    @staticmethod
    def artifact_item_meta(item_id: str) -> StateKey:
        return StateKey(Layer.ARTIFACT, Scope.ITEM, item_id=item_id, slot="_meta")


__all__ = ["SHARDS_PATCH_KEY", "K", "Layer", "Scope", "StateKey", "StateKeyError"]
