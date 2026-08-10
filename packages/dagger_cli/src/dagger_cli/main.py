"""dagger CLI: run, state, config, domains.

`dagger run --domain <id> --items ./data --shards 3` runs a domain's default
template end-to-end with the mock backend (or a configured real backend).

Domain discovery: entry points (`dagger.domains` group) first; as a dev fallback,
each `<repo>/domains/*/src/<pkg>/plugin.py` is imported best-effort (directory
name = package name convention). The mock dispatcher is domain-agnostic: a
plugin's optional `mock_outputs` hook supplies domain-shaped outputs, otherwise
outputs are synthesized from the SkillSpec (produces + success_key).
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import click

from dagger_cli.scaffold import die

LAYOUT_VERSION = 1


def _default_domains_dir() -> Path:
    """The repo's local domains dir (dev fallback for uninstalled domains)."""
    # main.py lives at <repo>/packages/dagger_cli/src/dagger_cli/main.py → parents[4]
    # is the repo root.
    return Path(__file__).resolve().parents[4] / "domains"


def _load_config_or_default() -> dict[str, Any]:
    """Load dagger.yaml if present; else return a default config."""
    from dagger_kernel.config import load_config_from_dict

    path = Path.cwd() / "dagger.yaml"
    if path.exists():
        try:
            import ruyaml  # type: ignore[import-not-found]

            data = dict(ruyaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except ImportError:
            click.echo(
                "warning: ruyaml not installed; install the [yaml] extra for dagger.yaml parsing",
                err=True,
            )
            data = {}
        return load_config_from_dict(data).model_dump()
    return load_config_from_dict({}).model_dump()


def _load_local_domains(registry: Any, domains_dir: Path) -> None:
    """Dev fallback: import `<pkg>.plugin` from each `domains/*/src` directory.

    Convention: directory name under `src/` = importable package name; the
    plugin module exposes a `plugin` instance (the entry-point target). Entry
    points win over local loading (a known id is never double-registered).
    """
    seen = {r.plugin.id for r in registry.all()}
    for domain_dir in sorted(domains_dir.iterdir()):
        src = domain_dir / "src"
        if not src.is_dir():
            continue
        packages = sorted(p for p in src.iterdir() if (p / "__init__.py").exists())
        for pkg in packages:
            try:
                if str(src) not in sys.path:
                    sys.path.insert(0, str(src))
                mod = importlib.import_module(f"{pkg.name}.plugin")
                obj = getattr(mod, "plugin", None)
                plugin_id = getattr(obj, "id", None)
                if obj is None or plugin_id is None or plugin_id in seen:
                    continue
                registry.register(obj)
                seen.add(plugin_id)
            except Exception as exc:  # a broken local domain must not kill the CLI
                click.echo(f"warning: failed to load local domain {pkg.name!r}: {exc}", err=True)


def _build_registry(catalog: Any, nodes: Any, domains_dir: Path | None = None) -> Any:
    """Discover domains via entry_points + (optionally) a local domains dir."""
    from dagger_kernel.spi import DomainRegistry, discover_entry_points

    registry = DomainRegistry()
    for plugin in discover_entry_points():
        registry.register(plugin)
    if domains_dir is not None and domains_dir.exists():
        _load_local_domains(registry, domains_dir)
    registry.contribute_to(catalog, nodes)
    return registry


def _build_mock_dispatcher(*, reg: Any) -> Any:
    """Build an AgentDispatcher that simulates a successful Agent.

    Domain-shaped outputs come from the plugin's optional `mock_outputs` hook
    (mock data is domain knowledge); otherwise we synthesize `{key: True}` over
    the SkillSpec's produces + success_key. The engine validates the outputs
    against the result contract (skills/validators) and writes the canonical
    result file itself — the dispatcher only supplies the outputs dict.
    """

    def _dispatch(
        *,
        node_run: Any,
        ctx: Any,
        executor: Any,
        store: Any,
        attempt: int,
    ) -> dict[str, Any]:
        if reg.mock_outputs is not None:
            outputs = reg.mock_outputs(node_run.node_type, ctx)
            if outputs is not None:
                return dict(outputs)
        skill = reg.skills.get(executor.skill or "")
        if skill is None:
            return {}
        keys = set(skill.produces) | {skill.success_key}
        return {k: True for k in sorted(keys)}

    return _dispatch


def _configure_plugin_source(reg: Any, items_dir: str) -> None:
    """Pass the --items dir to plugins that keep a `_source_dir` attribute.

    Mirrors the server's `configure_domain` convention. Templates are re-pulled
    afterwards because a domain may embed the configured value in node params
    (e.g. novel_digest's ensure_workspace workspace_root).
    """
    plugin = reg.plugin
    if hasattr(plugin, "_source_dir"):
        plugin._source_dir = items_dir  # documented config convention (see server)
        reg.templates = list(plugin.templates())


@click.group()
def cli() -> None:
    """Dagger: batch Agent orchestration CLI."""


@cli.command()
@click.option("--domain", required=True, help="Domain id (e.g. tiny).")
@click.option(
    "--items", "items_dir", required=True, type=click.Path(exists=True), help="Source items dir."
)
@click.option("--shards", default=3, show_default=True, type=int, help="Shard count hint.")
@click.option("--backend", default="mock", type=click.Choice(["mock"]), help="Agent backend.")
@click.option("--resume", is_flag=True, help="Resume an existing run (idempotent skip).")
@click.option("--dry-run", is_flag=True, help="Plan + validate without running.")
def run(
    domain: str,
    items_dir: str,
    shards: int,
    backend: str,
    resume: bool,
    dry_run: bool,
) -> None:
    """Run a domain's default template end-to-end."""
    from dagger_kernel.dag import NodeRegistry
    from dagger_kernel.dag.instantiator import ShardPlan, instantiate
    from dagger_kernel.engine import run_graph
    from dagger_kernel.executors import ExecutorCatalog
    from dagger_kernel.planning.item import ItemLedgerSnapshot
    from dagger_kernel.state import K, StateStore

    # Discover domains + assemble catalogs (kernel builtins included).
    catalog = ExecutorCatalog()
    nodes = NodeRegistry()
    registry = _build_registry(catalog, nodes, domains_dir=_default_domains_dir())
    try:
        reg = registry.get(domain)
    except KeyError as exc:
        sys.exit(die(str(exc), exit_code=3))

    _configure_plugin_source(reg, items_dir)
    # Build the item ledger synchronously (domain sources do a local file scan).
    src = reg.plugin.item_source()
    import asyncio as _aio

    async def _refresh() -> ItemLedgerSnapshot:
        return await src.refresh(type("Ws", (), {"root": items_dir})())

    snap: ItemLedgerSnapshot = _aio.run(_refresh())
    items = snap.items
    if not items:
        sys.exit(die(f"no items found in {items_dir}", exit_code=3))
    # Shard plan via the domain's sharder (default: fixed_size). `--shards` is a
    # hint: fixed_size reads `size`; weighted-style sharders read `shards`.
    cfg = {"size": max(1, len(items) // shards or 1), "shards": shards}
    plans = reg.sharder.suggest(items, snap.milestones, cfg) if reg.sharder else []
    if not plans:
        plans = [ShardPlan(shard_id="shard-000", index=0, items=tuple(i.id for i in items))]
    click.echo(f"domain={domain} items={len(items)} shards={len(plans)}")
    if not reg.templates:
        sys.exit(die(f"domain {domain!r} declares no templates", exit_code=3))
    if dry_run:
        click.echo("dry-run: would run template " + reg.templates[0].id)
        return
    # Set up StateStore.
    config = _load_config_or_default()
    run_id = f"run_{uuid.uuid4().hex[:8]}" if not resume else "run_resume"
    data_dir = Path(config["data_dir"])
    store_root = data_dir / run_id
    store = StateStore(store_root, run_id=run_id)
    # Seed the per-item ledger entries into the control layer (§14.3 tree shape).
    for it in items:
        store.write_json(
            K.item(it.id), it.to_dict(), kind="work_item", written_by={"role": "orchestrator"}
        )
    dispatcher = _build_mock_dispatcher(reg=reg)
    # Instantiate + run. skills/validators wire the result contract (K3).
    tpl = reg.templates[0]
    tpl.validate()
    graph = instantiate(template=tpl, run_id=run_id, shards=plans, node_registry=nodes)
    result = run_graph(
        graph=graph,
        template=tpl,
        store=store,
        catalog=catalog,
        node_registry=nodes,
        agent_dispatcher=dispatcher,
        skills=reg.skills,
        validators=reg.validators,
    )
    store.save_index()
    click.echo(
        f"completed={len(result.completed)} failed={len(result.failed)} skipped={len(result.skipped)}"
    )
    click.echo(f"state_root={store.state_root}")
    sys.exit(0 if not result.failed else 1)


@cli.command()
def domains() -> None:
    """List installed domains."""
    from dagger_kernel.dag import NodeRegistry
    from dagger_kernel.executors import ExecutorCatalog

    catalog = ExecutorCatalog()
    nodes = NodeRegistry()
    registry = _build_registry(catalog, nodes, domains_dir=_default_domains_dir())
    out = [
        {"id": r.plugin.id, "label": r.plugin.label, "version": r.plugin.version}
        for r in registry.all()
    ]
    click.echo(json.dumps(out, indent=2, ensure_ascii=False))


@cli.command()
def config() -> None:
    """Show parsed Dagger config."""
    cfg = _load_config_or_default()
    click.echo(json.dumps(cfg, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    cli()
