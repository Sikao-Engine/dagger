"""ExecutorSpec list for novel_digest (design §14.1).

Six domain executors; `ensure_workspace` comes from the kernel (K2) and is not
re-registered here. Node-type keys follow §14.2's bare names (`digest`,
`entity_merge`, ...) so the template can be transcribed verbatim.
"""

from __future__ import annotations

from dagger_kernel.executors import ExecutorSpec

EXECUTORS: list[ExecutorSpec] = [
    ExecutorSpec(
        key="digest",
        label="逐章摘要",
        handler_kind="agent",
        scope="shard",
        skill="novel-digest",
        default_timeout=7200,
    ),
    ExecutorSpec(
        key="entity_merge",
        label="实体归并",
        handler_kind="builtin",
        scope="shard",
        node_class="novel_digest.nodes.entity_merge:EntityMergeNode",
    ),
    ExecutorSpec(
        key="timeline_merge",
        label="时间线累积",
        handler_kind="builtin",
        scope="shard",
        node_class="novel_digest.nodes.timeline_merge:TimelineMergeNode",
    ),
    ExecutorSpec(
        key="volume_summary",
        label="分卷总述",
        handler_kind="agent",
        scope="shard",
        skill="novel-volume-summary",
        default_timeout=7200,
    ),
    ExecutorSpec(
        key="consistency_check",
        label="一致性校验",
        handler_kind="agent",
        scope="run",
        skill="novel-consistency",
        default_timeout=7200,
    ),
    ExecutorSpec(
        key="final_report",
        label="终稿报告",
        handler_kind="agent",
        scope="run",
        skill="novel-final-report",
        default_timeout=7200,
    ),
]

__all__ = ["EXECUTORS"]
