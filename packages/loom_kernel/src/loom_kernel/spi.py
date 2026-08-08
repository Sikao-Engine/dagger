"""SPI: the single entry point domains implement to plug into Loom.

A `DomainPlugin` declares everything: items, executors, templates, skills,
handlers, sharder, workspace provider, references, validators, artifact spec,
scanners. Everything except `id` / `item_source` / `executors` is optional —
defaults live in the kernel.

The `DomainRegistry` discovers plugins via `entry_points` (the `loom.domains`
group) and assembles the runtime catalog from all registered plugins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .dag import DagTemplate, NodeRegistry
from .dag.instantiator import ShardPlan
from .executors import ExecutorCatalog, ExecutorSpec
from .planning import Milestone, Sharder, WorkItem, fixed_size
from .state.artifact_spec import ArtifactSpec
from .state.retry import RetryPolicy


class WorkspaceProvider(Protocol):
    """SPI: prepares a physical workspace for a node (worktree / copy-dir / shared / none)."""

    kind: str

    def prepare(self, req: dict[str, Any]) -> dict[str, Any]: ...  # pragma: no cover
    def release(self, handle: dict[str, Any], *, keep: bool) -> None: ...  # pragma: no cover


@dataclass(frozen=True)
class ReferenceSpec:
    """One reference workspace (multi-source comparison pattern, generalized from CubeClaw)."""

    name: str
    provider: str
    base_ref: str = ""
    readonly: bool = True
    description: str = ""


@dataclass(frozen=True)
class SkillSpec:
    """Prompt template + success criterion + retry policy for one agent node type."""

    key: str
    skill_name: str
    prompt_template: str
    success_key: str = "success"
    timeout: int = 14400
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    retry_policy: RetryPolicy = RetryPolicy.FRESH

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "skill_name": self.skill_name,
            "success_key": self.success_key,
            "timeout": self.timeout,
            "requires": list(self.requires),
            "produces": list(self.produces),
            "retry_policy": self.retry_policy.value,
        }


class ResultValidator(Protocol):
    """SPI: domain-specific validation of session_result body. Returns list of error strings."""

    def __call__(self, body: dict[str, Any], *, node_run_id: str) -> list[str]: ...


class DomainPlugin(Protocol):
    """The full SPI a domain implements. Optional members have defaults."""

    id: str
    label: str
    version: str

    # ── required ──
    def item_source(self) -> Any: ...
    def executors(self) -> list[ExecutorSpec]: ...

    # ── optional ──
    def templates(self) -> list[DagTemplate]: ...
    def node_handlers(self, registry: NodeRegistry) -> None: ...
    def sharder(self) -> Sharder | None: ...
    def skills(self) -> list[SkillSpec]: ...
    def result_validators(self) -> dict[str, ResultValidator]: ...
    def workspace_provider(self) -> WorkspaceProvider | None: ...
    def references(self) -> list[ReferenceSpec]: ...
    def state_seeder(self) -> Any | None: ...
    def artifact_spec(self) -> ArtifactSpec | None: ...
    def scanners(self) -> list[Any]: ...
    def web_manifest(self) -> dict[str, Any]: ...


class _DefaultSharder:
    """The fixed_size sharder wrapped to satisfy the Sharder protocol."""

    def suggest(
        self, items: list[WorkItem], milestones: list[Milestone], cfg: dict[str, Any]
    ) -> list[ShardPlan]:
        return fixed_size(items, milestones, cfg)

    def validate(self, plan: list[ShardPlan]) -> list[str]:
        return []


@dataclass
class DomainRegistration:
    """The assembled runtime registration for one domain: plugin + catalog slice."""

    plugin: DomainPlugin
    executors: list[ExecutorSpec] = field(default_factory=list)
    templates: list[DagTemplate] = field(default_factory=list)
    skills: dict[str, SkillSpec] = field(default_factory=dict)
    sharder: Sharder | None = None
    validators: dict[str, ResultValidator] = field(default_factory=dict)
    references: list[ReferenceSpec] = field(default_factory=list)
    artifact_spec: ArtifactSpec | None = None
    scanners: list[Any] = field(default_factory=list)


class DomainRegistry:
    """Runtime registry: holds all discovered domains + their catalog contributions."""

    def __init__(self) -> None:
        self._domains: dict[str, DomainRegistration] = {}

    def register(self, plugin: DomainPlugin) -> DomainRegistration:
        reg = DomainRegistration(
            plugin=plugin,
            executors=list(plugin.executors()),
            templates=list(plugin.templates()) if hasattr(plugin, "templates") else [],
            skills={s.key: s for s in (plugin.skills() if hasattr(plugin, "skills") else [])},
            sharder=plugin.sharder() if hasattr(plugin, "sharder") else None,
            validators=dict(
                plugin.result_validators() if hasattr(plugin, "result_validators") else {}
            ),
            references=list(plugin.references() if hasattr(plugin, "references") else []),
            artifact_spec=plugin.artifact_spec() if hasattr(plugin, "artifact_spec") else None,
            scanners=list(plugin.scanners() if hasattr(plugin, "scanners") else []),
        )
        if reg.sharder is None:
            reg.sharder = _DefaultSharder()
        self._domains[plugin.id] = reg
        return reg

    def get(self, domain_id: str) -> DomainRegistration:
        if domain_id not in self._domains:
            raise KeyError(f"unknown domain: {domain_id!r}")
        return self._domains[domain_id]

    def all(self) -> list[DomainRegistration]:
        return list(self._domains.values())

    def contribute_to(self, catalog: ExecutorCatalog, nodes: NodeRegistry) -> None:
        """Pour every registered domain's executors + handlers into the kernel catalogs."""
        for reg in self._domains.values():
            for spec in reg.executors:
                catalog.register(spec)
            if hasattr(reg.plugin, "node_handlers"):
                reg.plugin.node_handlers(nodes)


def discover_entry_points() -> list[DomainPlugin]:
    """Discover DomainPlugin instances via the `loom.domains` entry-point group.

    Returns plugins in deterministic order (sorted by id).
    """
    plugins: list[DomainPlugin] = []
    try:
        from importlib.metadata import entry_points  # noqa: PLC0415

        eps = entry_points()
        group = eps.select(group="loom.domains")
        for ep in group:
            try:
                obj = ep.load()
            except Exception:  # pragma: no cover - bad plugin shouldn't kill discovery
                continue
            # The entry point should resolve to a DomainPlugin instance (not a class).
            if isinstance(obj, type):
                obj = obj()
            plugins.append(obj)
    except Exception:  # pragma: no cover
        pass
    return sorted(plugins, key=lambda p: p.id)


__all__ = [
    "DomainPlugin",
    "DomainRegistration",
    "DomainRegistry",
    "ReferenceSpec",
    "ResultValidator",
    "SkillSpec",
    "WorkspaceProvider",
    "discover_entry_points",
]
