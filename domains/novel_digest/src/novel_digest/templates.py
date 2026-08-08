"""DagTemplate for novel_digest — design §14.2, transcribed verbatim.

The only additions to the doc listing are the `workspace_root` param on the
`init` node (the kernel's `ensure_workspace` builtin needs to know where to
create the run directory; the variant params come straight from §14.2) and the
trailing run-level INTRA edge `consistency → final_report`, which the kernel
instantiator supports (K1).

Edge rationale (acceptance Step 2):
- `init → shard_ws` = RUN_ENTRY_ALL: one init fans out N shard workspaces.
- `shard_ws → digest` = INTRA: within-shard ordering.
- `digest → timeline_merge` + `timeline_merge → timeline_merge` = SERIAL_PREV:
  the timeline accumulates across shards; shard N reads shard N-1's timeline.
- `digest → entity_merge` = INTRA: shard-local, parallel-safe; fan-in later.
- `entity_merge → consistency` = ALL: consistency needs every shard's table.
- `volume_summary → consistency` = ALL.
- `consistency → final_report` = INTRA: run-level sequential (K1).
"""

from __future__ import annotations

from pathlib import Path

from loom_kernel.dag import DagTemplate, EdgeDef, EdgeKind, NodeDef, Scope

TEMPLATE_ID = "novel_digest_default"
DOMAIN_ID = "novel_digest"


def build_template(workspace_root: str | Path = ".") -> DagTemplate:
    """Build the default template. `workspace_root` lands in the init node's params."""
    return DagTemplate(
        id=TEMPLATE_ID,
        domain_id=DOMAIN_ID,
        is_default=True,
        nodes=(
            NodeDef(
                "init",
                "ensure_workspace",
                Scope.RUN_ENTRY,
                params={"variant": "root", "workspace_root": str(workspace_root)},
            ),
            NodeDef(
                "shard_ws",
                "ensure_workspace",
                Scope.SHARD,
                params={"variant": "shard"},
            ),
            NodeDef("digest", "digest", Scope.SHARD, priority=10),
            NodeDef("entity_merge", "entity_merge", Scope.SHARD, priority=20),
            NodeDef("timeline_merge", "timeline_merge", Scope.SHARD, priority=21),
            NodeDef("volume_summary", "volume_summary", Scope.SHARD, priority=30),
            NodeDef("consistency", "consistency_check", Scope.RUN, priority=40),
            NodeDef("final_report", "final_report", Scope.RUN, priority=50),
        ),
        edges=(
            EdgeDef("init", "shard_ws", EdgeKind.RUN_ENTRY_ALL),
            EdgeDef("shard_ws", "digest"),
            EdgeDef("digest", "entity_merge"),
            EdgeDef("digest", "timeline_merge"),
            # 时间线必须跨片串行（后片依赖前片的时间线状态）
            EdgeDef(
                "timeline_merge",
                "timeline_merge",
                EdgeKind.SERIAL_PREV,
                maps={"prev_timeline_path": "timeline_path"},
            ),
            # 实体表可并行合并，最后汇聚
            EdgeDef("entity_merge", "consistency", EdgeKind.ALL),
            EdgeDef("timeline_merge", "volume_summary"),
            EdgeDef("volume_summary", "consistency", EdgeKind.ALL),
            EdgeDef("consistency", "final_report"),
        ),
    )


__all__ = ["DOMAIN_ID", "TEMPLATE_ID", "build_template"]
