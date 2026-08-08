"""Step 3: SkillSpec prompts.

Pins: byte-stable rendering snapshots (same views → same text, diffable), the
five prompt rules (machine-verifiable success key, inclusive boundary,
forbidden actions, reference purpose, artifact path + schema pointer), and the
K4 shard-view references (`shard.item_count` / `shard.last_item.id`).
"""

from __future__ import annotations

from novel_digest.skills import (
    NOVEL_CONSISTENCY,
    NOVEL_DIGEST,
    NOVEL_FINAL_REPORT,
    NOVEL_VOLUME_SUMMARY,
    SKILLS,
    render_prompt,
)

VIEWS = {
    "ctx": {
        "workspace_root": "/book",
        "shard_out_dir": "/book/run_x/shard-000",
        "run_out_dir": "/book/run_x",
        "timeline_path": "/book/run_x/shard-000/timeline.json",
        "entities_ok": True,
        "volume_ok": True,
        "consistency_ok": True,
    },
    "shard": {
        "shard_id": "shard-000",
        "index": 0,
        "item_count": 3,
        "items": ["ch_0001", "ch_0002", "ch_0003"],
        "first_item": {"id": "ch_0001"},
        "last_item": {"id": "ch_0003"},
    },
    "run": {"run_id": "run_x", "template_id": "novel_digest_default"},
    "refs": {"canon": {"path": "/book/canon"}},
}

EXPECTED_DIGEST = """\
/novel-digest 处理本分片的 3 章原文：第 ch_0001 章 ～ 第 ch_0003 章（**两端 inclusive，首末两章本身也要处理**）。

原文目录：`/book/chapters`（**只读**）；产出目录：`/book/run_x/shard-000`。

流程：串行执行 `noveltool next` 推进指针；逐章生成产物后用
`noveltool fill <chapter_id> --file <产物.json>` 回填校验。每章产物写入
`/book/run_x/shard-000/<chapter_id>.json`，schema 见 `novel_chapter`
（summary / entities / timeline_delta / digest_ok 四段齐全）。

参照系：`/book/canon` 是人物设定权威，实体命名冲突时以它为准；
新出现的实体必须在 entities 中显式写出 first_seen_chapter。
时间线只写本片增量；跨片累积由内核 timeline_merge 节点负责，不要自己读其他分片的时间线。

禁止动作：不要修改 `chapters/` 目录下的任何文件；不要把产物写到 `/book/run_x/shard-000` 以外；
不要写时间线以外的全局状态。

完成判据（机器可验证）：`noveltool status` 输出 `all_done=true` 后，写 session_result 终态：
digest_ok=true 且 outputs.chapters_done=3（必须等于本分片章数，少一章即漏章）。
outputs 还需原样回传你实际使用的工作区坐标 shard_out_dir / run_out_dir / workspace_root
——上下文沿边流动，同片下游节点（entity_merge / timeline_merge）靠这份回传寻址，
回传值与下发值不一致即视为在错误现场作业。
"""

EXPECTED_VOLUME = """\
/novel-volume-summary 本片时间线已累积至 `/book/run_x/shard-000/timeline.json`。请为本卷
（第 ch_0001 ～ ch_0003 章，**inclusive**）写一段总述。

产物写入本片产出目录下的 `volume_summary.json`，schema 见 `novel_volume_summary`。

参照系：`/book/canon` 用于核对人物称谓一致性，冲突以它为准。

禁止动作：不要改动任何逐章产物；不要读写其他分片的目录。

完成判据（机器可验证）：写 session_result 终态 volume_ok=true。
"""

EXPECTED_CONSISTENCY = """\
/novel-consistency 全部分片的实体归并（entities_ok）与分卷总述（volume_ok）均已完成。
请对照全局实体表与全局时间线做一致性校验，产出矛盾清单 `consistency_report.json`
（schema 见 `novel_consistency_report`），写入运行级产物目录。

参照系：`/book/canon` 是人物设定权威，冲突以它为准。

禁止动作：不要修改任何逐章产物、实体表、时间线与分卷总述；只新增矛盾清单。

完成判据（机器可验证）：写 session_result 终态 consistency_ok=true。
"""

EXPECTED_FINAL_REPORT = """\
/novel-final-report 一致性校验已完成（consistency_ok=true）。请汇总本次运行终稿：
全局实体表、全局时间线、矛盾清单、分卷总述索引，写入运行级产物目录的
`final_report.md`（人读）与 `final_report.json`（供后续 Run 召回）。

参照系：`/book/canon` 是人物设定权威，终稿中的人名/地名以它为准。

禁止动作：不要改动任何上游产物。

完成判据（机器可验证）：写 session_result 终态 report_ok=true。
"""


class TestRenderSnapshots:
    """Byte-stable snapshots: if a prompt changes, the diff shows up here."""

    def test_digest_snapshot(self) -> None:
        assert render_prompt(NOVEL_DIGEST, VIEWS) == EXPECTED_DIGEST

    def test_volume_summary_snapshot(self) -> None:
        assert render_prompt(NOVEL_VOLUME_SUMMARY, VIEWS) == EXPECTED_VOLUME

    def test_consistency_snapshot(self) -> None:
        assert render_prompt(NOVEL_CONSISTENCY, VIEWS) == EXPECTED_CONSISTENCY

    def test_final_report_snapshot(self) -> None:
        assert render_prompt(NOVEL_FINAL_REPORT, VIEWS) == EXPECTED_FINAL_REPORT

    def test_rendering_is_deterministic(self) -> None:
        for spec in SKILLS:
            assert render_prompt(spec, VIEWS) == render_prompt(spec, VIEWS)


class TestPromptRules:
    """The five prompt rules, checked mechanically per skill."""

    def test_success_key_machine_verifiable(self) -> None:
        for spec in SKILLS:
            assert spec.success_key, spec.key
            assert f"{spec.success_key}=true" in spec.prompt_template

    def test_inclusive_boundary_explicit(self) -> None:
        assert "inclusive" in NOVEL_DIGEST.prompt_template
        assert "shard.last_item.id" in NOVEL_DIGEST.prompt_template
        rendered = render_prompt(NOVEL_DIGEST, VIEWS)
        assert "第 ch_0003 章（**两端 inclusive" in rendered

    def test_forbidden_actions_explicit(self) -> None:
        for spec in SKILLS:
            assert "禁止动作" in spec.prompt_template, spec.key

    def test_reference_purpose_stated(self) -> None:
        for spec in SKILLS:
            assert "refs.canon.path" in spec.prompt_template, spec.key
            assert "为准" in spec.prompt_template, spec.key  # the purpose, not just the path

    def test_artifact_path_and_schema_pointer(self) -> None:
        assert "shard_out_dir" in NOVEL_DIGEST.prompt_template
        assert "novel_chapter" in NOVEL_DIGEST.prompt_template  # schema by kind name
        # The schema text itself is never inlined into the prompt.
        assert '"properties"' not in NOVEL_DIGEST.prompt_template

    def test_shard_item_count_referenced(self) -> None:
        assert "shard.item_count" in NOVEL_DIGEST.prompt_template
        assert "3" in render_prompt(NOVEL_DIGEST, VIEWS)

    def test_requires_produces_declared(self) -> None:
        assert set(NOVEL_DIGEST.requires) == {"workspace_root", "shard_out_dir"}
        assert "chapters_done" in NOVEL_DIGEST.produces
        for spec in SKILLS:
            assert spec.produces or spec.success_key  # every skill declares its surface
