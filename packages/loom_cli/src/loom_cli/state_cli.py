"""loom-state CLI: the single write path Agents are allowed to use.

Subcommands: ls, cat, result --write, artifact, verify, gc, reindex, archive.
Currently a thin shell around StateStore; full command coverage lands in M5+.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from loom_kernel.state import Layer, StateStore


@click.group()
def cli() -> None:
    """Loom state inspection CLI."""


@cli.command("ls")
@click.option(
    "--run", "run_root", required=True, type=click.Path(exists=True), help="Run root dir."
)
@click.option("--layer", type=str, default=None, help="Filter by layer.")
def ls_cmd(run_root: str, layer: str) -> None:
    """List state objects for a run."""
    store = StateStore(Path(run_root), readonly=True)
    entries = store.query(layer=Layer(layer) if layer else None)
    out = [
        {
            "kind": e.kind,
            "path": e.rel,
            "layer": e.key.layer.value,
            "size": e.size,
        }
        for e in entries
    ]
    click.echo(json.dumps(out, indent=2, ensure_ascii=False, default=str))


@cli.command("verify")
@click.option("--run", "run_root", required=True, type=click.Path(exists=True))
def verify_cmd(run_root: str) -> None:
    """Verify a run's state (sha256 + index consistency)."""
    store = StateStore(Path(run_root), readonly=True)
    problems = store.verify()
    if problems:
        click.echo(json.dumps({"ok": False, "problems": problems}, indent=2))
        sys.exit(1)
    click.echo(json.dumps({"ok": True}))


@cli.command("reindex")
@click.option("--run", "run_root", required=True, type=click.Path(exists=True))
def reindex_cmd(run_root: str) -> None:
    """Rebuild a run's index from the tree."""
    store = StateStore(Path(run_root))
    store.reindex()
    click.echo(json.dumps({"ok": True, "entries": len(list(store.index))}))


if __name__ == "__main__":
    cli()
