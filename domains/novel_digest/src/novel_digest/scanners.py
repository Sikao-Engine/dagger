"""Mechanical scanners for novel_digest (acceptance Step 5; kernel K5 protocol).

Five scanners implement the kernel's `Scanner` protocol, each emitting kernel
`Finding`s. Conventions that make the checks fully mechanical:
- Entity mentions in summaries are 「corner-bracket」 quoted (「韩立」); the
  UndeclaredEntityScanner flags quoted names absent from the chapter's entity
  table and the optional `ctx.refs["canon_entities"]` list.
- `ctx.refs["timeline_floor"]` (int, optional) supplies the cross-item event
  floor for the TimelineRegressionScanner; within-chapter order is always
  checked.

`chapter=None` means the product file is missing: only SchemaIncompleteScanner
reports that (as an error); the others stay silent (nothing to scan).
"""

from __future__ import annotations

import re
from typing import Any

from loom_kernel.planning import WorkItem
from loom_kernel.review import Finding, ScanContext
from loom_kernel.state.schema import validate as validate_schema

from .schemas import NOVEL_CHAPTER

MIN_SUMMARY_CHARS = 50
_MENTION_RE = re.compile(r"「([^」]+)」")


class EmptySummaryScanner:
    """摘要为空或过短（< 50 字）。"""

    code = "empty_summary"

    def scan(
        self, item: WorkItem, chapter: dict[str, Any] | None, ctx: ScanContext
    ) -> list[Finding]:
        if chapter is None:
            return []
        summary = str(chapter.get("summary") or "")
        if len(summary) < MIN_SUMMARY_CHARS:
            return [
                Finding(
                    code=self.code,
                    severity="warning",
                    message=f"{item.id} 摘要为空或过短（{len(summary)} 字 < {MIN_SUMMARY_CHARS}）",
                    locator={"item_id": item.id, "field": "summary"},
                )
            ]
        return []


class SchemaIncompleteScanner:
    """chapter.json 缺字段（对 novel_chapter schema 校验）。"""

    code = "schema_incomplete"

    def scan(
        self, item: WorkItem, chapter: dict[str, Any] | None, ctx: ScanContext
    ) -> list[Finding]:
        if chapter is None:
            return [
                Finding(
                    code=self.code,
                    severity="error",
                    message=f"{item.id} 产物文件缺失",
                    locator={"item_id": item.id},
                )
            ]
        errors = validate_schema(NOVEL_CHAPTER, chapter)
        return [
            Finding(
                code=self.code,
                severity="error",
                message=f"{item.id} schema 校验失败：{err}",
                locator={"item_id": item.id, "detail": err},
            )
            for err in errors
        ]


class UndeclaredEntityScanner:
    """摘要里出现不在实体表里的「人物/地点」。"""

    code = "undeclared_entity"

    def scan(
        self, item: WorkItem, chapter: dict[str, Any] | None, ctx: ScanContext
    ) -> list[Finding]:
        if chapter is None:
            return []
        summary = str(chapter.get("summary") or "")
        declared = {str(e.get("name", "")) for e in chapter.get("entities", [])}
        declared |= {str(a) for e in chapter.get("entities", []) for a in e.get("aliases", [])}
        canon = {str(n) for n in ctx.refs.get("canon_entities", [])}
        findings: list[Finding] = []
        for name in sorted(set(_MENTION_RE.findall(summary))):
            if name and name not in declared and name not in canon:
                findings.append(
                    Finding(
                        code=self.code,
                        severity="warning",
                        message=f"{item.id} 摘要提及「{name}」但未在实体表登记",
                        locator={"item_id": item.id, "entity": name},
                    )
                )
        return findings


class TimelineRegressionScanner:
    """时间线倒流：事件章节号小于前一事件（或小于 ctx.refs['timeline_floor']）。"""

    code = "timeline_regression"

    def scan(
        self, item: WorkItem, chapter: dict[str, Any] | None, ctx: ScanContext
    ) -> list[Finding]:
        if chapter is None:
            return []
        floor = int(ctx.refs.get("timeline_floor", 0))
        findings: list[Finding] = []
        for i, event in enumerate(chapter.get("timeline_delta", [])):
            chapter_no = int(event.get("chapter", 0))
            if chapter_no < floor:
                findings.append(
                    Finding(
                        code=self.code,
                        severity="error",
                        message=(
                            f"{item.id} 时间线倒流：事件 {i} 章节号 {chapter_no} < 前序 {floor}"
                        ),
                        locator={"item_id": item.id, "event_index": i},
                    )
                )
            floor = max(floor, chapter_no)
        return findings


class AbnormalLengthScanner:
    """摘要长度异常（> 原文 1/3 或 < 原文 1/50；原文长度取 item.payload.word_count）。"""

    code = "abnormal_length"

    def scan(
        self, item: WorkItem, chapter: dict[str, Any] | None, ctx: ScanContext
    ) -> list[Finding]:
        if chapter is None:
            return []
        word_count = int(item.payload.get("word_count", 0))
        if word_count <= 0:
            return []
        summary_len = len(str(chapter.get("summary") or ""))
        if summary_len > word_count / 3 or summary_len < word_count / 50:
            return [
                Finding(
                    code=self.code,
                    severity="warning",
                    message=(f"{item.id} 摘要长度异常：{summary_len} 字 vs 原文 {word_count} 字"),
                    locator={"item_id": item.id, "field": "summary"},
                )
            ]
        return []


SCANNERS: list[Any] = [
    EmptySummaryScanner(),
    SchemaIncompleteScanner(),
    UndeclaredEntityScanner(),
    TimelineRegressionScanner(),
    AbnormalLengthScanner(),
]

__all__ = [
    "MIN_SUMMARY_CHARS",
    "SCANNERS",
    "AbnormalLengthScanner",
    "EmptySummaryScanner",
    "SchemaIncompleteScanner",
    "TimelineRegressionScanner",
    "UndeclaredEntityScanner",
]
