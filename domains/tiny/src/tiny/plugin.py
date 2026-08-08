"""tiny plugin: minimal-but-real domain.

Implements DomainPlugin SPI:
- ItemSource: scans a directory of .txt files (seq = sort order).
- ExecutorSpec: tiny.work (agent), tiny.report (agent).
- DagTemplate: init → shard work (parallel) → report (ALL aggregation).
- SkillSpec: tiny-work + tiny-report prompt templates.

Plug-and-play: registering this entry point makes the tiny domain available to
`loom run --domain tiny` with zero kernel code changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom_kernel.dag import (
    ContextPatch,
    DagTemplate,
    EdgeDef,
    EdgeKind,
    NodeDef,
    NodeRegistry,
    Scope,
)
from loom_kernel.dag.nodes import NodeContract
from loom_kernel.executors import ExecutorSpec
from loom_kernel.planning import ItemLedgerSnapshot, WorkItem
from loom_kernel.spi import SkillSpec
from loom_kernel.state import ArtifactSpec, Slot

TEMPLATE = DagTemplate(
    id="tiny_default",
    domain_id="tiny",
    nodes=(
        NodeDef("init", "tiny.init", Scope.RUN_ENTRY, priority=0),
        NodeDef("work", "tiny.work", Scope.SHARD, priority=10),
        NodeDef("report", "tiny.report", Scope.RUN, priority=50),
    ),
    edges=(
        EdgeDef("init", "work", EdgeKind.RUN_ENTRY_ALL),
        EdgeDef("work", "report", EdgeKind.ALL),
    ),
)

SKILLS = [
    SkillSpec(
        key="tiny-work",
        skill_name="tiny-work",
        prompt_template=(
            "/tiny-work 处理本分片的 {{ shard.item_count }} 个文件。"
            "每项产出写入 `{{ ctx.shard_out_dir }}/<item_id>.md`。"
            "全部完成后写 session_result（work_ok=true）。"
        ),
        success_key="work_ok",
        produces=("work_ok",),
    ),
    SkillSpec(
        key="tiny-report",
        skill_name="tiny-report",
        prompt_template=(
            "/tiny-report 汇总 `{{ ctx.run_out_dir }}` 下所有产出，"
            "写入 `{{ ctx.run_out_dir }}/report.md`。"
            "完成后写 session_result（report_ok=true）。"
        ),
        success_key="report_ok",
        produces=("report_ok",),
    ),
]


class TinySource:
    """Scans a directory of .txt files into an ordered WorkItem list."""

    def __init__(self, source_dir: str | Path) -> None:
        self.source_dir = Path(source_dir)

    async def refresh(self, ws: Any) -> ItemLedgerSnapshot:
        root = Path(getattr(ws, "root", self.source_dir))
        files = sorted(p for p in root.glob("*.txt") if p.is_file())
        items = [
            WorkItem(
                id=p.stem,
                seq=i,
                title=p.stem,
                payload={"path": str(p), "size": p.stat().st_size},
            )
            for i, p in enumerate(files)
        ]
        return ItemLedgerSnapshot(items=items, milestones=[], frontier_item_id=None)


class _NoopInit:
    """Builtin handler for the `tiny.init` run-entry node.

    Initializes the run context (no workspace setup needed for the local-file
    tiny domain). Registered via `node_handlers` so the kernel assembles it
    through the SPI — no host code needs to know about `tiny.init`.
    """

    contract = NodeContract(writes=("initialized",))

    def run(self, ctx: object) -> ContextPatch:  # type: ignore[override]
        return ContextPatch(values={"initialized": True})


class TinyPlugin:
    """The DomainPlugin implementation for the tiny domain."""

    id = "tiny"
    label = "Tiny Demo"
    version = "0.1.0"

    def __init__(self, source_dir: str | Path | None = None) -> None:
        self._source_dir = source_dir

    def item_source(self) -> TinySource:
        if self._source_dir is None:
            raise ValueError("TinyPlugin requires a source_dir; set via config")
        return TinySource(self._source_dir)

    def executors(self) -> list[ExecutorSpec]:
        return [
            ExecutorSpec(
                key="tiny.init",
                label="init",
                handler_kind="builtin",
                scope="run_entry",
            ),
            ExecutorSpec(
                key="tiny.work",
                label="Work",
                handler_kind="agent",
                scope="shard",
                skill="tiny-work",
            ),
            ExecutorSpec(
                key="tiny.report",
                label="Report",
                handler_kind="agent",
                scope="run",
                skill="tiny-report",
            ),
        ]

    def node_handlers(self, registry: NodeRegistry) -> None:
        registry.register("tiny.init", _NoopInit())

    def templates(self) -> list[DagTemplate]:
        return [TEMPLATE]

    def skills(self) -> list[SkillSpec]:
        return SKILLS

    def artifact_spec(self) -> ArtifactSpec:
        # tiny.work writes `<item_id>.md` per file under the run's output dir.
        # The Agent should mirror those into the per-item artifact layer at
        # slot `summary` so the review UI can show them via this spec.
        return ArtifactSpec(
            label="Tiny file summary",
            slots=(
                Slot(
                    name="summary",
                    label="Summary",
                    view="markdown",
                    description="One-paragraph summary the Agent wrote for this file.",
                ),
            ),
            default_view="tabs",
        )

    def web_manifest(self) -> dict[str, Any]:
        """Slots for the Loom review UI + a domain page.

        `itemRowExtra` lets the tiny domain add a column to the ledger table
        without writing any generic front-end code — the column is rendered
        by the manifest-declared bundle at `web/src/domains/tiny/index.ts`.
        """
        return {
            "id": "tiny",
            "label": "Tiny Demo",
            "bundle": "domains/tiny/index.ts",
            "slots": ["itemRowExtra"],
        }


plugin = TinyPlugin()
