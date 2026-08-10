"""Domain runtime assembly: discover plugins via entry_points + assemble catalogs.

This is the server's equivalent of the CLI's registry builder, but it NEVER
imports a concrete domain module statically — discovery is purely via the
`divdag.domains` entry-point group (the SPI contract). The import-linter rule
`Server must not import concrete domain modules` enforces this at CI time.

A domain that needs a runtime parameter (e.g. tiny's `source_dir`) receives it
via `configure_domain(id, **kwargs)`, which mutates the plugin instance in place
before its `item_source()` is called. No host code names the domain module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from divdag_kernel.dag import NodeRegistry
from divdag_kernel.executors import ExecutorCatalog
from divdag_kernel.spi import DomainRegistry, discover_entry_points


@dataclass
class DomainRuntime:
    """The assembled runtime: catalogs + registries ready to drive the engine."""

    domains: DomainRegistry
    catalog: ExecutorCatalog
    nodes: NodeRegistry

    def get(self, domain_id: str) -> Any:
        return self.domains.get(domain_id)

    def all(self) -> list[Any]:
        return self.domains.all()


def assemble_runtime() -> DomainRuntime:
    """Discover all installed domains and pour their contributions into the kernel."""
    catalog = ExecutorCatalog()
    nodes = NodeRegistry()
    domains = DomainRegistry()
    for plugin in discover_entry_points():
        domains.register(plugin)
    domains.contribute_to(catalog, nodes)
    return DomainRuntime(domains=domains, catalog=catalog, nodes=nodes)


def configure_domain(runtime: DomainRuntime, domain_id: str, **kwargs: Any) -> None:
    """Pass runtime parameters to a domain plugin (e.g. tiny's source_dir).

    Domains opt in by accepting the kwargs they care about on their plugin
    instance. Unknown kwargs are ignored — the contract is "set what you recognize".
    """
    try:
        reg = runtime.domains.get(domain_id)
    except KeyError:
        return
    plugin = reg.plugin
    for k, v in kwargs.items():
        attr = f"_{k}" if not k.startswith("_") else k
        if hasattr(plugin, attr):
            setattr(plugin, attr, v)
        elif hasattr(plugin, k):
            setattr(plugin, k, v)


__all__ = ["DomainRuntime", "assemble_runtime", "configure_domain"]
