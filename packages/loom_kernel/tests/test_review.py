"""K5: review SPI (Finding / ScanContext / Scanner / IntentDiffProvider) + SPI assembly.

Pinned behavior:
- Finding validates its severity and serializes round-trip.
- DomainRegistry assembles intent_diff / scanners / mock_outputs from the plugin.
- contribute_to pours kernel builtins before domain contributions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loom_kernel.dag import NodeContext, NodeRegistry
from loom_kernel.executors import ExecutorCatalog, ExecutorSpec
from loom_kernel.planning import WorkItem
from loom_kernel.review import Finding, IntentDiffProvider, ScanContext, Scanner
from loom_kernel.spi import DomainRegistry


class TestFinding:
    def test_round_trip(self) -> None:
        f = Finding(
            code="empty_summary",
            severity="warning",
            message="ch_0001 摘要为空",
            locator={"path": "out/ch_0001.json", "field": "summary"},
        )
        d = f.to_dict()
        assert d == {
            "code": "empty_summary",
            "severity": "warning",
            "message": "ch_0001 摘要为空",
            "locator": {"path": "out/ch_0001.json", "field": "summary"},
        }

    def test_unknown_severity_rejected(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            Finding(code="x", severity="fatal", message="boom")

    def test_empty_code_rejected(self) -> None:
        with pytest.raises(ValueError, match="code"):
            Finding(code="", severity="info", message="boom")


class _ToyScanner:
    code = "toy"

    def scan(
        self, item: WorkItem, chapter: dict[str, Any] | None, ctx: ScanContext
    ) -> list[Finding]:
        if chapter is None:
            return [Finding(code=self.code, severity="error", message="missing product")]
        return []


class _ToyIntentDiff:
    def intent(self, item: WorkItem) -> str | None:
        return f"original:{item.id}"

    def outcome(self, item: WorkItem) -> str | None:
        return f"summary:{item.id}"


class _ToyPlugin:
    id = "toy"
    label = "Toy"
    version = "0.1.0"

    def executors(self) -> list[ExecutorSpec]:
        return [ExecutorSpec(key="toy.work", label="work", handler_kind="agent", scope="shard")]

    def scanners(self) -> list[Scanner]:
        return [_ToyScanner()]

    def intent_diff(self) -> IntentDiffProvider:
        return _ToyIntentDiff()

    def mock_outputs(self, node_type: str, ctx: NodeContext) -> dict[str, Any] | None:
        if node_type == "toy.work":
            return {"work_ok": True, "done": ctx.shard.get("item_count", 0)}
        return None


class TestSpiAssembly:
    def test_registration_assembles_review_hooks(self) -> None:
        reg = DomainRegistry().register(_ToyPlugin())
        assert len(reg.scanners) == 1
        item = WorkItem(id="i1", seq=0, title="t")
        findings = reg.scanners[0].scan(item, None, ScanContext())
        assert findings[0].code == "toy"
        assert findings[0].severity == "error"
        assert reg.intent_diff is not None
        assert reg.intent_diff.intent(item) == "original:i1"
        assert reg.intent_diff.outcome(item) == "summary:i1"
        assert reg.mock_outputs is not None
        ctx = NodeContext(shard={"item_count": 7})
        assert reg.mock_outputs("toy.work", ctx) == {"work_ok": True, "done": 7}
        assert reg.mock_outputs("toy.other", ctx) is None

    def test_registration_defaults_when_hooks_absent(self) -> None:
        class _Bare:
            id = "bare"
            label = "Bare"
            version = "0.0.1"

            def executors(self) -> list[ExecutorSpec]:
                return []

        reg = DomainRegistry().register(_Bare())
        assert reg.scanners == []
        assert reg.intent_diff is None
        assert reg.mock_outputs is None

    def test_contribute_to_pours_kernel_and_domain(self, tmp_path: Path) -> None:
        registry = DomainRegistry()
        registry.register(_ToyPlugin())
        catalog = ExecutorCatalog()
        nodes = NodeRegistry()
        registry.contribute_to(catalog, nodes)
        # Kernel builtin arrived without any host wiring.
        assert catalog.require("ensure_workspace").handler_kind == "builtin"
        assert nodes.handler_for("ensure_workspace") is not None
        # Domain executor arrived too.
        assert catalog.require("toy.work").handler_kind == "agent"
