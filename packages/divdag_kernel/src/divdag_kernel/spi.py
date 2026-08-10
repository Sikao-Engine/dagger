"""SPI: the single entry point domains implement to plug into DivDag.

A `DomainPlugin` declares everything: items, executors, templates, skills,
handlers, sharder, workspace provider, references, validators, artifact spec,
scanners. Everything except `id` / `item_source` / `executors` is optional —
defaults live in the kernel.

The `DomainRegistry` discovers plugins via `entry_points` (the `divdag.domains`
group) and assembles the runtime catalog from all registered plugins.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .dag import DagTemplate, NodeContext, NodeRegistry
from .dag.instantiator import ShardPlan
from .dag.nodes.ensure_workspace import ENSURE_WORKSPACE_CONTRACT, EnsureWorkspaceNode
from .executors import ExecutorCatalog, ExecutorSpec
from .planning import Milestone, Sharder, WorkItem, fixed_size
from .review import IntentDiffProvider, Scanner
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
    """SPI: domain-specific validation of a session_result body.

    Returns a list of error strings (empty = valid). ``context`` carries the
    node's resolved context (the flattened ``NodeContext.values()`` plus the
    ``shard`` view) so validators can check counts against the shard
    composition — e.g. ``outputs.chapters_done == shard.item_count`` (the
    classic off-by-one / missed-chapter bug). Hosts without a live context
    (e.g. server-side re-validation) may pass None.
    """

    def __call__(
        self,
        body: dict[str, Any],
        *,
        node_run_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[str]: ...


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
    def scanners(self) -> list[Scanner]: ...
    def intent_diff(self) -> IntentDiffProvider | None: ...
    def mock_outputs(self, node_type: str, ctx: NodeContext) -> dict[str, Any] | None: ...
    def web_manifest(self) -> dict[str, Any]: ...


#: Kernel-provided executors, poured into every ExecutorCatalog before any
#: domain contribution (domains may override the same keys — last write wins).
#: ``scope="any"`` because ensure_workspace is instantiated at both RUN_ENTRY
#: and SHARD scope; the variant params pick the behavior. ExecutorSpec.scope
#: cannot express "both" today — see the smoke report's design-tension log.
KERNEL_EXECUTORS: tuple[ExecutorSpec, ...] = (
    ExecutorSpec(
        key="ensure_workspace",
        label="Ensure workspace",
        handler_kind="builtin",
        scope="any",
        node_class="divdag_kernel.dag.nodes.ensure_workspace:EnsureWorkspaceNode",
    ),
)


def register_kernel_nodes(nodes: NodeRegistry) -> None:
    """Register the kernel's builtin node handlers (ensure_workspace today)."""
    nodes.register("ensure_workspace", EnsureWorkspaceNode(), contract=ENSURE_WORKSPACE_CONTRACT)


#: Type of the optional ``mock_outputs`` plugin hook: given a node_type and the
#: resolved context, return domain-shaped mock outputs for the mock dispatcher
#: (mock data is domain knowledge). None means "fall back to generic synthesis".
MockOutputsHook = Callable[[str, NodeContext], "dict[str, Any] | None"]


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
    scanners: list[Scanner] = field(default_factory=list)
    intent_diff: IntentDiffProvider | None = None
    mock_outputs: MockOutputsHook | None = None


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
            intent_diff=plugin.intent_diff() if hasattr(plugin, "intent_diff") else None,
            mock_outputs=(plugin.mock_outputs if hasattr(plugin, "mock_outputs") else None),
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
        """Pour kernel builtins, then every registered domain, into the catalogs.

        Kernel executors/handlers (ensure_workspace) come first so hosts (CLI,
        server) get them with zero wiring; a domain may override the same key
        afterwards (last write wins — documented extension point).
        """
        for spec in KERNEL_EXECUTORS:
            catalog.register(spec)
        register_kernel_nodes(nodes)
        for reg in self._domains.values():
            for spec in reg.executors:
                catalog.register(spec)
            if hasattr(reg.plugin, "node_handlers"):
                reg.plugin.node_handlers(nodes)


def discover_entry_points() -> list[DomainPlugin]:
    """Discover DomainPlugin instances via the `divdag.domains` entry-point group.

    Returns plugins in deterministic order (sorted by id).
    """
    plugins: list[DomainPlugin] = []
    try:
        from importlib.metadata import entry_points  # noqa: PLC0415

        eps = entry_points()
        group = eps.select(group="divdag.domains")
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
    "KERNEL_EXECUTORS",
    "DomainPlugin",
    "DomainRegistration",
    "DomainRegistry",
    "MockOutputsHook",
    "ReferenceSpec",
    "ResultValidator",
    "SkillSpec",
    "WorkspaceProvider",
    "discover_entry_points",
    "register_kernel_nodes",
]
