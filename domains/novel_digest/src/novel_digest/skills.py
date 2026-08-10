"""SkillSpecs for novel_digest (acceptance Step 3; design §14.1 lists three,
`novel-final-report` is a deliberate fourth addition — every agent node needs a
machine-verifiable success_key, and the doc's template has a final_report node).

Every prompt obeys the five prompt rules (cookbook §1 Step 3):
1. machine-verifiable success criterion (a key in session_result.outputs);
2. explicit inclusive boundaries (`shard.last_item.id` — itself included);
3. explicit forbidden actions;
4. references with their *purpose* stated;
5. artifact paths + schema pointer by kind name (never inlined schema text).

`render_prompt` is the Jinja2 renderer used by snapshot tests (and by hosts
that don't plug a custom PromptComposer).
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment
from divdag_kernel.spi import SkillSpec

NOVEL_DIGEST = SkillSpec(
    key="novel-digest",
    skill_name="novel-digest",
    prompt_template="""\
/novel-digest 处理本分片的 {{ shard.item_count }} 章原文：第 {{ shard.first_item.id }} 章 \
～ 第 {{ shard.last_item.id }} 章（**两端 inclusive，首末两章本身也要处理**）。

原文目录：`{{ ctx.workspace_root }}/chapters`（**只读**）；产出目录：`{{ ctx.shard_out_dir }}`。

流程：串行执行 `noveltool next` 推进指针；逐章生成产物后用
`noveltool fill <chapter_id> --file <产物.json>` 回填校验。每章产物写入
`{{ ctx.shard_out_dir }}/<chapter_id>.json`，schema 见 `novel_chapter`
（summary / entities / timeline_delta / digest_ok 四段齐全）。

参照系：`{{ refs.canon.path }}` 是人物设定权威，实体命名冲突时以它为准；
新出现的实体必须在 entities 中显式写出 first_seen_chapter。
时间线只写本片增量；跨片累积由内核 timeline_merge 节点负责，不要自己读其他分片的时间线。

禁止动作：不要修改 `chapters/` 目录下的任何文件；不要把产物写到 `{{ ctx.shard_out_dir }}` 以外；
不要写时间线以外的全局状态。

完成判据（机器可验证）：`noveltool status` 输出 `all_done=true` 后，写 session_result 终态：
digest_ok=true 且 outputs.chapters_done={{ shard.item_count }}（必须等于本分片章数，少一章即漏章）。
outputs 还需原样回传你实际使用的工作区坐标 shard_out_dir / run_out_dir / workspace_root
——上下文沿边流动，同片下游节点（entity_merge / timeline_merge）靠这份回传寻址，
回传值与下发值不一致即视为在错误现场作业。
""",
    success_key="digest_ok",
    timeout=7200,
    requires=("workspace_root", "shard_out_dir"),
    produces=("chapters_done", "shard_out_dir", "run_out_dir", "workspace_root"),
)

NOVEL_VOLUME_SUMMARY = SkillSpec(
    key="novel-volume-summary",
    skill_name="novel-volume-summary",
    prompt_template="""\
/novel-volume-summary 本片时间线已累积至 `{{ ctx.timeline_path }}`。请为本卷
（第 {{ shard.first_item.id }} ～ {{ shard.last_item.id }} 章，**inclusive**）写一段总述。

产物写入本片产出目录下的 `volume_summary.json`，schema 见 `novel_volume_summary`。

参照系：`{{ refs.canon.path }}` 用于核对人物称谓一致性，冲突以它为准。

禁止动作：不要改动任何逐章产物；不要读写其他分片的目录。

完成判据（机器可验证）：写 session_result 终态 volume_ok=true。
""",
    success_key="volume_ok",
    timeout=7200,
    requires=("timeline_path",),
    produces=("volume_ok",),
)

NOVEL_CONSISTENCY = SkillSpec(
    key="novel-consistency",
    skill_name="novel-consistency",
    prompt_template="""\
/novel-consistency 全部分片的实体归并（entities_ok）与分卷总述（volume_ok）均已完成。
请对照全局实体表与全局时间线做一致性校验，产出矛盾清单 `consistency_report.json`
（schema 见 `novel_consistency_report`），写入运行级产物目录。

参照系：`{{ refs.canon.path }}` 是人物设定权威，冲突以它为准。

禁止动作：不要修改任何逐章产物、实体表、时间线与分卷总述；只新增矛盾清单。

完成判据（机器可验证）：写 session_result 终态 consistency_ok=true。
""",
    success_key="consistency_ok",
    timeout=7200,
    requires=("entities_ok", "volume_ok"),
    produces=("consistency_ok",),
)

NOVEL_FINAL_REPORT = SkillSpec(
    key="novel-final-report",
    skill_name="novel-final-report",
    prompt_template="""\
/novel-final-report 一致性校验已完成（consistency_ok=true）。请汇总本次运行终稿：
全局实体表、全局时间线、矛盾清单、分卷总述索引，写入运行级产物目录的
`final_report.md`（人读）与 `final_report.json`（供后续 Run 召回）。

参照系：`{{ refs.canon.path }}` 是人物设定权威，终稿中的人名/地名以它为准。

禁止动作：不要改动任何上游产物。

完成判据（机器可验证）：写 session_result 终态 report_ok=true。
""",
    success_key="report_ok",
    timeout=7200,
    requires=("consistency_ok",),
    produces=("report_ok",),
)

SKILLS: list[SkillSpec] = [
    NOVEL_DIGEST,
    NOVEL_VOLUME_SUMMARY,
    NOVEL_CONSISTENCY,
    NOVEL_FINAL_REPORT,
]

# keep_trailing_newline: prompt files keep their final newline (faithful render).
_ENV = Environment(autoescape=False, keep_trailing_newline=True)


def render_prompt(spec: SkillSpec, views: dict[str, Any]) -> str:
    """Render a SkillSpec prompt template. `views` supplies run/shard/ctx/refs.

    Rendering is byte-stable for a given views dict (default Jinja2 semantics,
    no autoescape), which is what the snapshot tests pin.
    """
    return _ENV.from_string(spec.prompt_template).render(**views)


__all__ = [
    "NOVEL_CONSISTENCY",
    "NOVEL_DIGEST",
    "NOVEL_FINAL_REPORT",
    "NOVEL_VOLUME_SUMMARY",
    "SKILLS",
    "render_prompt",
]
