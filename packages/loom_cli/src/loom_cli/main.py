"""loom CLI: run, state, config, domains.

`loom run --domain tiny --items ./data --shards 3` runs the tiny domain
end-to-end with the mock backend (or a configured real backend).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

import click

from loom_cli.scaffold import die

LAYOUT_VERSION = 1


def _load_config_or_default() -> dict[str, Any]:
    """Load loom.yaml if present; else return a default config."""
    from loom_kernel.config import load_config_from_dict

    path = Path.cwd() / "loom.yaml"
    if path.exists():
        try:
            import ruyaml  # type: ignore[import-not-found]

            data = dict(ruyaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except ImportError:
            click.echo(
                "warning: ruyaml not installed; install the [yaml] extra for loom.yaml parsing",
                err=True,
            )
            data = {}
        return load_config_from_dict(data).model_dump()
    return load_config_from_dict({}).model_dump()


def _build_registry(catalog, nodes, domains_dir: Path | None = None) -> Any:
    """Discover domains via entry_points + (optionally) a local domains dir."""
    from loom_kernel.spi import DomainRegistry, discover_entry_points

    registry = DomainRegistry()
    for plugin in discover_entry_points():
        registry.register(plugin)
    # If a local domains dir is provided (dev mode), also register tiny manually
    # so it works without an installed entry point.
    if domains_dir is not None and (domains_dir / "tiny").exists():
        try:
            sys.path.insert(0, str(domains_dir / "tiny" / "src"))
            from tiny.plugin import TinyPlugin  # type: ignore[import-not-found]

            # Override the source_dir from CLI args later; for discovery use a placeholder.
            registry.register(TinyPlugin(source_dir="."))
        except Exception as exc:  # pragma: no cover
            click.echo(f"warning: failed to load local tiny domain: {exc}", err=True)
    registry.contribute_to(catalog, nodes)
    return registry


def _build_mock_dispatcher(*, store, registry, backend, declared_writes_for) -> Any:
    """Build an AgentDispatcher that simulates the Agent writing a success result.

    For the M4 walking-skeleton this shortcuts the real SessionRunner; a real
    deployment wires the SessionRunner here with the configured backend.
    """

    def _dispatch(
        *,
        node_run,
        ctx,
        executor,
        store,
        attempt,
    ) -> dict[str, Any]:
        from loom_kernel.state import K

        node_key = node_run.node_key
        outputs: dict[str, Any]
        if node_key == "work":
            outputs = {"work_ok": True}
        elif node_key == "report":
            outputs = {"report_ok": True}
        else:
            outputs = {}
        store.write_json(
            K.result(node_run.node_run_id, attempt),
            {
                "status": "success",
                "success": True,
                "node_run_id": node_run.node_run_id,
                "node_type": node_run.node_type,
                "skill": executor.skill or "",
                "outputs": outputs,
            },
            kind="session_result",
            written_by={"role": "agent", "backend": "mock"},
        )
        return outputs

    return _dispatch


@click.group()
def cli() -> None:
    """Loom: batch Agent orchestration CLI."""


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
    from loom_agent.backends.mock import MockBackend
    from loom_kernel.dag import NodeRegistry
    from loom_kernel.dag.instantiator import ShardPlan, instantiate
    from loom_kernel.engine import run_graph
    from loom_kernel.executors import ExecutorCatalog
    from loom_kernel.planning import fixed_size
    from loom_kernel.planning.item import ItemLedgerSnapshot
    from loom_kernel.state import StateStore

    # Discover domains + assemble catalogs.
    catalog = ExecutorCatalog()
    nodes = NodeRegistry()
    registry = _build_registry(
        catalog, nodes, domains_dir=Path(__file__).resolve().parents[2] / "domains"
    )
    # Register a noop builtin handler for the tiny.init node (no workspace setup needed).
    from loom_kernel.dag import ContextPatch, NodeContract

    class _NoopInit:
        contract = NodeContract(writes=("initialized",))

        def run(self, ctx: object) -> ContextPatch:  # type: ignore[override]
            return ContextPatch(values={"initialized": True})

    nodes.register("tiny.init", _NoopInit())
    try:
        reg = registry.get(domain)
    except KeyError as exc:
        die(str(exc), exit_code=3)
        return

    # Override tiny's source_dir from --items.
    if domain == "tiny":
        reg.plugin._source_dir = items_dir  # type: ignore[attr-defined]
    # Build the item ledger synchronously (tiny uses sync file scan).
    src = reg.plugin.item_source()
    import asyncio as _aio

    async def _refresh():
        return await src.refresh(type("Ws", (), {"root": items_dir})())

    snap: ItemLedgerSnapshot = _aio.run(_refresh())
    items = snap.items
    if not items:
        die(f"no items found in {items_dir}", exit_code=3)
        return
    # Shard plan.
    plans = fixed_size(items, snap.milestones, {"size": max(1, len(items) // shards or 1)})
    if not plans:
        plans = [ShardPlan(shard_id="shard-000", index=0, items=tuple(i.id for i in items))]
    click.echo(f"domain={domain} items={len(items)} shards={len(plans)}")
    if dry_run:
        click.echo("dry-run: would run template " + reg.templates()[0].id)
        return
    # Set up StateStore.
    config = _load_config_or_default()
    run_id = f"run_{uuid.uuid4().hex[:8]}" if not resume else "run_resume"
    data_dir = Path(config["data_dir"])
    store_root = data_dir / run_id
    store = StateStore(store_root, run_id=run_id)
    # Mock backend: register a script per node_type that writes success.
    mock = MockBackend(store=store)
    for spec in reg.executors:
        if spec.handler_kind == "agent":
            outputs = {"work_ok": True} if spec.skill == "tiny-work" else {"report_ok": True}
            mock.register(
                spec.key,
                __import__("loom_agent").backends.mock.MockScript(
                    result_body={
                        "status": "success",
                        "success": True,
                        "node_run_id": "",
                        "node_type": spec.key,
                        "skill": spec.skill or "",
                        "outputs": outputs,
                    },
                ),
            )
    dispatcher = _build_mock_dispatcher(
        store=store, registry=registry, backend=mock, declared_writes_for=lambda nt: None
    )
    # Instantiate + run.
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
    from loom_kernel.dag import NodeRegistry
    from loom_kernel.executors import ExecutorCatalog

    catalog = ExecutorCatalog()
    nodes = NodeRegistry()
    registry = _build_registry(catalog, nodes)
    out = [
        {"id": r.plugin.id, "label": r.plugin.label, "version": r.plugin.version}
        for r in registry.all()
    ]
    click.echo(json.dumps(out, indent=2, ensure_ascii=False))


@cli.command()
def config() -> None:
    """Show parsed Loom config."""
    cfg = _load_config_or_default()
    click.echo(json.dumps(cfg, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    cli()
