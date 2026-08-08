"""K2: the kernel's built-in `ensure_workspace` node (minimal local-dir semantics).

Pinned behavior:
- variant=root creates <workspace_root>/<run_id> and emits run_out_dir (+ a
  workspace_root pass-through).
- variant=shard reads run_out_dir from upstream and creates
  <run_out_dir>/<shard_id>, emitting shard_out_dir (+ pass-throughs).
- The union contract covers both variants; missing inputs fail fast.
- DomainRegistry.contribute_to pours the kernel executor + handler before any
  domain contribution, so hosts get the node with zero wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loom_kernel.dag import NodeContext, NodeRegistry
from loom_kernel.dag.nodes import ContractError
from loom_kernel.dag.nodes.ensure_workspace import (
    ENSURE_WORKSPACE_CONTRACT,
    EnsureWorkspaceNode,
)
from loom_kernel.executors import ExecutorCatalog, ExecutorSpec
from loom_kernel.spi import KERNEL_EXECUTORS, DomainRegistry


def _ctx(values: dict) -> NodeContext:
    return NodeContext(node_params=dict(values))


class TestRootVariant:
    def test_creates_run_dir_and_emits_keys(self, tmp_path: Path) -> None:
        node = EnsureWorkspaceNode()
        patch = node.run(_ctx({"variant": "root", "workspace_root": str(tmp_path), "run_id": "r1"}))
        out = tmp_path / "r1"
        assert out.is_dir()
        assert patch.values["run_out_dir"] == str(out)
        assert patch.values["workspace_root"] == str(tmp_path)

    def test_missing_workspace_root_fails_fast(self, tmp_path: Path) -> None:
        node = EnsureWorkspaceNode()
        with pytest.raises(ContractError, match="workspace_root"):
            node.run(_ctx({"variant": "root", "run_id": "r1"}))


class TestShardVariant:
    def test_creates_shard_dir_and_passes_through(self, tmp_path: Path) -> None:
        run_out = tmp_path / "r1"
        run_out.mkdir()
        node = EnsureWorkspaceNode()
        ctx = NodeContext(
            ancestor_patches={"run_out_dir": str(run_out), "workspace_root": str(tmp_path)},
            shard_seed={"shard_id": "shard-003"},
            node_params={"variant": "shard"},
        )
        patch = node.run(ctx)
        out = run_out / "shard-003"
        assert out.is_dir()
        assert patch.values["shard_out_dir"] == str(out)
        assert patch.values["run_out_dir"] == str(run_out)
        assert patch.values["workspace_root"] == str(tmp_path)

    def test_missing_run_out_dir_fails_fast(self, tmp_path: Path) -> None:
        node = EnsureWorkspaceNode()
        with pytest.raises(ContractError, match="run_out_dir"):
            node.run(_ctx({"variant": "shard", "shard_id": "s0"}))

    def test_unknown_variant_fails_fast(self) -> None:
        node = EnsureWorkspaceNode()
        with pytest.raises(ContractError, match="unknown variant"):
            node.run(_ctx({"variant": "weird"}))


class TestContract:
    def test_union_contract_covers_both_variants(self) -> None:
        assert set(ENSURE_WORKSPACE_CONTRACT.writes) == {
            "workspace_root",
            "run_out_dir",
            "shard_out_dir",
        }
        assert ENSURE_WORKSPACE_CONTRACT.reads == ()

    def test_handler_satisfies_its_own_contract(self, tmp_path: Path) -> None:
        node = EnsureWorkspaceNode()
        for variant in ("root", "shard"):
            ctx = NodeContext(
                ancestor_patches={"run_out_dir": str(tmp_path)},
                shard_seed={"shard_id": "s0"},
                node_params={
                    "variant": variant,
                    "workspace_root": str(tmp_path),
                    "run_id": "r1",
                },
            )
            patch = node.run(ctx)
            node.contract.assert_writes_allowed(dict(patch.values))


class TestKernelRegistration:
    def test_contribute_to_pours_kernel_builtins_first(self) -> None:
        catalog = ExecutorCatalog()
        nodes = NodeRegistry()
        DomainRegistry().contribute_to(catalog, nodes)
        spec = catalog.require("ensure_workspace")
        assert spec.handler_kind == "builtin"
        handler = nodes.handler_for("ensure_workspace")
        assert isinstance(handler, EnsureWorkspaceNode)
        assert nodes.contract_for("ensure_workspace") is ENSURE_WORKSPACE_CONTRACT

    def test_domain_may_override_kernel_key(self) -> None:
        """Documented extension point: domains registering the same key win."""

        class _Plugin:
            id = "overrider"
            label = "Overrider"
            version = "0.0.1"

            def executors(self) -> list[ExecutorSpec]:
                return [
                    ExecutorSpec(
                        key="ensure_workspace",
                        label="custom",
                        handler_kind="builtin",
                        scope="shard",
                    )
                ]

        registry = DomainRegistry()
        registry.register(_Plugin())
        catalog = ExecutorCatalog()
        nodes = NodeRegistry()
        registry.contribute_to(catalog, nodes)
        assert catalog.require("ensure_workspace").label == "custom"


class TestKernelExecutorsShape:
    def test_kernel_executors_declared(self) -> None:
        keys = [s.key for s in KERNEL_EXECUTORS]
        assert keys == ["ensure_workspace"]
