"""ExecutorSpec: self-describing node-type catalog entry.

Replaces CubeClaw's `executors/catalog.py` compiled constant. Now: domains
register their executors at startup; the catalog is the lookup table. `platform`
has been generalized to `selectors: dict[str, str]` so domains can prune on any
dimension (GPU/no-GPU, has-api-key, language pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutorSpec:
    """A self-describing entry for one node-type.

    Fields mirror §5.2 of universal_base_architecture.md.
    """

    key: str  # globally unique; "<domain>.<name>" convention
    label: str
    handler_kind: str  # agent | builtin | external | unsupported
    scope: str  # run_entry | shard | run | shard_dynamic
    default_timeout: int = 3600
    required_capability: str | None = None
    node_class: str | None = None  # "module:Class" path for handler_kind=builtin
    skill: str | None = None  # SkillSpec.key for handler_kind=agent
    variant_key: str = "variant"  # supports "<executor>:<variant>" multi-impl
    selectors: dict[str, str] = field(default_factory=dict)
    default_mock: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "handler_kind": self.handler_kind,
            "scope": self.scope,
            "default_timeout": self.default_timeout,
            "required_capability": self.required_capability,
            "node_class": self.node_class,
            "skill": self.skill,
            "variant_key": self.variant_key,
            "selectors": dict(self.selectors),
            "default_mock": self.default_mock,
        }


class ExecutorCatalog:
    """Runtime-registered lookup table for ExecutorSpec.

    Domains call `register()` in their SPI `executors()` hook at startup. The
    scheduler queries by `node_type` (the ExecutorSpec.key) at schedule_run time
    and fail-fast validates that every node_type in a template is registered.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ExecutorSpec] = {}

    def register(self, spec: ExecutorSpec) -> None:
        self._specs[spec.key] = spec

    def get(self, key: str) -> ExecutorSpec | None:
        return self._specs.get(key)

    def require(self, key: str) -> ExecutorSpec:
        spec = self._specs.get(key)
        if spec is None:
            available = sorted(self._specs.keys())
            raise KeyError(f"unknown node_type {key!r}; registered: {available}")
        return spec

    def all(self) -> list[ExecutorSpec]:
        return list(self._specs.values())

    def query(
        self, *, handler_kind: str | None = None, scope: str | None = None
    ) -> list[ExecutorSpec]:
        out: list[ExecutorSpec] = []
        for s in self._specs.values():
            if handler_kind is not None and s.handler_kind != handler_kind:
                continue
            if scope is not None and s.scope != scope:
                continue
            out.append(s)
        return out

    def satisfies_selectors(self, node_type: str, available_selectors: dict[str, str]) -> bool:
        """Does the executor for `node_type` run given the current selectors?

        An executor with no `selectors` always satisfies. An executor with
        selectors requires each one to be present-and-equal in `available_selectors`.
        """
        spec = self.get(node_type)
        if spec is None:
            return False
        if not spec.selectors:
            return True
        return all(available_selectors.get(k) == v for k, v in spec.selectors.items())


__all__ = ["ExecutorCatalog", "ExecutorSpec"]
