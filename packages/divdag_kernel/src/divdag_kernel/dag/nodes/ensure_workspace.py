"""ensure_workspace: the kernel's built-in workspace-provisioning node.

Design doc §6 names ``ensure_workspace`` a **kernel builtin node** whose variant
is selected by template params. This module implements the minimal local-dir
semantics every domain gets for free:

- ``variant=root`` (typically ``Scope.RUN_ENTRY``): create
  ``<workspace_root>/<run_id>`` and emit ``run_out_dir`` plus a
  ``workspace_root`` pass-through, so downstream shard nodes can reference the
  immutable source root without the template threading it through params.
- ``variant=shard`` (typically ``Scope.SHARD``): read ``run_out_dir`` from the
  upstream patch (the ``RUN_ENTRY_ALL`` fan-out), create
  ``<run_out_dir>/<shard_id>`` and emit ``shard_out_dir`` (plus pass-throughs).

One ``node_type`` serves both variants, so the declared contract is the **union**
of both variants' writes and ``reads`` stays empty (the shard variant's
``run_out_dir`` dependency is enforced at run time, fail-fast). This is a known
design tension: a future ``ExecutorSpec.variant_key`` ``<executor>:<variant>``
multi-implementation can split the contract per variant.

The full WorkspaceProvider SPI (git-worktree / copy-dir / snapshot / release /
ResourceBudget, design §6.1) is intentionally **not** implemented here; this
handler is the local-dir floor. Domains with richer workspace needs register
their own node types via the SPI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context import ContextPatch, NodeContext
from . import ContractError, NodeContract

ENSURE_WORKSPACE_NODE_TYPE = "ensure_workspace"

#: Union contract across the two variants (see module docstring for the tension).
ENSURE_WORKSPACE_CONTRACT = NodeContract(
    reads=(),
    writes=("workspace_root", "run_out_dir", "shard_out_dir"),
)


class EnsureWorkspaceNode:
    """Builtin handler for the kernel's ``ensure_workspace`` node type."""

    contract = ENSURE_WORKSPACE_CONTRACT

    def run(self, ctx: NodeContext) -> ContextPatch:
        variant = str(ctx.get("variant", "root"))
        if variant == "root":
            return self._run_root(ctx)
        if variant == "shard":
            return self._run_shard(ctx)
        raise ContractError(
            f"ensure_workspace: unknown variant {variant!r} (expected 'root' or 'shard')"
        )

    @staticmethod
    def _run_root(ctx: NodeContext) -> ContextPatch:
        root_raw = ctx.get("workspace_root")
        if not root_raw:
            raise ContractError(
                "ensure_workspace variant=root requires a 'workspace_root' node param"
            )
        root = Path(str(root_raw))
        run_id = str(ctx.get("run_id", "") or "run")
        out = Path(root, run_id)
        out.mkdir(parents=True, exist_ok=True)
        return ContextPatch(
            values={"workspace_root": str(root), "run_out_dir": str(out)},
        )

    @staticmethod
    def _run_shard(ctx: NodeContext) -> ContextPatch:
        run_out_raw = ctx.get("run_out_dir")
        if not run_out_raw:
            raise ContractError(
                "ensure_workspace variant=shard requires 'run_out_dir' from an upstream "
                "node (wire init -> shard_ws with EdgeKind.RUN_ENTRY_ALL)"
            )
        shard_id = str(ctx.get("shard_id", "") or "shard")
        out = Path(str(run_out_raw), shard_id)
        out.mkdir(parents=True, exist_ok=True)
        values: dict[str, Any] = {"shard_out_dir": str(out)}
        # Pass through the coordinates this node consumed so same-shard downstream
        # nodes (digest, merge, ...) can reference them via plain INTRA edges.
        values["run_out_dir"] = str(run_out_raw)
        workspace_root = ctx.get("workspace_root")
        if workspace_root:
            values["workspace_root"] = str(workspace_root)
        return ContextPatch(values=values)


__all__ = [
    "ENSURE_WORKSPACE_CONTRACT",
    "ENSURE_WORKSPACE_NODE_TYPE",
    "EnsureWorkspaceNode",
]
