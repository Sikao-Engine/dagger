"""NovelPlugin: the DomainPlugin SPI implementation for novel_digest.

Assembly of the five SPI pieces (design §14.1): ItemSource / executors /
template / skills / artifact spec, plus sharder, result validators, scanners,
intent diff, the mock-outputs hook, and the web manifest.

`source_dir` follows the same configuration convention as tiny: the host (CLI
`--items`, or the server's `configure_domain`) sets `_source_dir` before
`item_source()` is consumed; templates are re-pulled afterwards because the
init node embeds the workspace root.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from divdag_kernel.dag import DagTemplate, NodeContext, NodeRegistry
from divdag_kernel.executors import ExecutorSpec
from divdag_kernel.planning import Milestone, WorkItem
from divdag_kernel.planning.sharder import ShardPlan, weighted
from divdag_kernel.review import IntentDiffProvider, Scanner
from divdag_kernel.spi import ReferenceSpec, SkillSpec
from divdag_kernel.state.artifact_spec import ArtifactSpec, Slot

from .executors import EXECUTORS
from .items import ChapterSource, chapter_seq
from .nodes import register_handlers
from .review import NovelIntentDiff
from .scanners import SCANNERS
from .schemas import NOVEL_CHAPTER  # noqa: F401 — import registers the kinds
from .skills import SKILLS
from .templates import DOMAIN_ID, build_template

CANON_REF = ReferenceSpec(
    name="canon",
    provider="shared-dir",
    base_ref="canon/",
    readonly=True,
    description="人物设定权威目录：实体命名冲突时以它为准",
)


class WeightedChapterSharder:
    """Sharder: balance shards by chapter word_count (~80k chars per shard).

    A `shards` hint in cfg is honored by deriving target_weight from the total;
    an explicit `target_weight` always wins.
    """

    def suggest(
        self, items: list[WorkItem], milestones: list[Milestone], cfg: dict[str, Any]
    ) -> list[ShardPlan]:
        cfg = dict(cfg)
        if "target_weight" not in cfg and cfg.get("shards"):
            total = sum(max(1.0, float(i.payload.get("word_count", 1))) for i in items)
            cfg["target_weight"] = max(1.0, total / max(1, int(cfg["shards"])))
        cfg.setdefault("weight_key", "word_count")
        cfg.setdefault("target_weight", 80000)
        return weighted(items, milestones, cfg)

    def validate(self, plan: list[ShardPlan]) -> list[str]:
        return []


def validate_digest_result(
    body: dict[str, Any],
    *,
    node_run_id: str,
    context: dict[str, Any] | None = None,
) -> list[str]:
    """ResultValidator for `digest`: the off-by-one / missed-chapter guard.

    `outputs.chapters_done` must equal the shard's item count (from the engine's
    enriched shard view), and digest_ok must be true.
    """
    errors: list[str] = []
    outputs = body.get("outputs", {})
    if not isinstance(outputs, dict):
        return ["outputs is not an object"]
    done = outputs.get("chapters_done")
    if not isinstance(done, int) or isinstance(done, bool) or done < 0:
        errors.append(f"outputs.chapters_done must be a non-negative int, got {done!r}")
    expected = (context or {}).get("shard", {}).get("item_count")
    if isinstance(expected, int) and isinstance(done, int) and done != expected:
        errors.append(f"chapters_done={done} != shard item_count={expected}（漏章 off-by-one）")
    if outputs.get("digest_ok") is not True:
        errors.append("outputs.digest_ok is not true")
    return errors


def _mock_chapter(item_id: str) -> dict[str, Any]:
    """Deterministic mock chapter product (schema-valid novel_chapter)."""
    seq = chapter_seq(item_id, 0)
    summary = (
        f"第 {item_id} 章的 mock 摘要：「韩立」在本章继续修行，剧情平稳推进。"
        f"本段文字由 mock_outputs 确定性生成，仅用于打通编排与状态链路。"
    )
    return {
        "chapter_id": item_id,
        "summary": summary,
        "entities": [
            {
                "name": "韩立",
                "type": "person",
                "aliases": ["韩老魔"] if seq % 2 else [],
                "first_seen_chapter": item_id,
            }
        ],
        "timeline_delta": [
            {
                "event": f"{item_id} 的 mock 事件",
                "chapter": seq,
                "participants": ["韩立"],
                "anchors": [item_id],
            }
        ],
        "digest_ok": True,
    }


class NovelPlugin:
    """DomainPlugin SPI for novel_digest."""

    id = DOMAIN_ID
    label = "Novel Digest"
    version = "0.1.0"

    def __init__(self, source_dir: str | None = None) -> None:
        self._source_dir = source_dir

    # ── required ──────────────────────────────────────────────────────────
    def item_source(self) -> ChapterSource:
        if self._source_dir is None:
            raise ValueError("NovelPlugin requires source_dir (configure before item_source)")
        return ChapterSource(self._source_dir)

    def executors(self) -> list[ExecutorSpec]:
        return list(EXECUTORS)

    # ── orchestration ─────────────────────────────────────────────────────
    def templates(self) -> list[DagTemplate]:
        return [build_template(self._source_dir or ".")]

    def node_handlers(self, registry: NodeRegistry) -> None:
        register_handlers(registry)

    def sharder(self) -> WeightedChapterSharder:
        return WeightedChapterSharder()

    # ── agent ─────────────────────────────────────────────────────────────
    def skills(self) -> list[SkillSpec]:
        return list(SKILLS)

    def result_validators(self) -> dict[str, Any]:
        return {"digest": validate_digest_result}

    # ── workspace / references ────────────────────────────────────────────
    def references(self) -> list[ReferenceSpec]:
        return [CANON_REF]

    # ── review ────────────────────────────────────────────────────────────
    def artifact_spec(self) -> ArtifactSpec:
        return ArtifactSpec(
            label="Novel chapter digest",
            slots=(
                Slot("raw", label="原文", view="prose"),
                Slot("summary", label="剧情摘要", view="markdown"),
                Slot("entities", label="人物/地点", view="json-table"),
                Slot("timeline", label="时间线增量", view="json-table"),
                Slot("issues", label="疑点/矛盾", view="list"),
            ),
            default_view="tabs",
        )

    def scanners(self) -> list[Scanner]:
        return list(SCANNERS)

    def intent_diff(self) -> IntentDiffProvider:
        return NovelIntentDiff(self._source_dir or ".")

    # ── mock ──────────────────────────────────────────────────────────────
    def mock_outputs(self, node_type: str, ctx: NodeContext) -> dict[str, Any] | None:
        """Domain-shaped outputs for the mock dispatcher (kernel K5 hook).

        For `digest` the mock also writes the per-chapter product files into
        the shard_out_dir, so the downstream builtin merge nodes run their real
        deterministic code over them during a mock run.
        """
        if node_type == "digest":
            items = [str(i) for i in (ctx.shard.get("items") or [])]
            values = ctx.values()
            shard_out_raw = values.get("shard_out_dir")
            if shard_out_raw:
                shard_out = Path(str(shard_out_raw))
                shard_out.mkdir(parents=True, exist_ok=True)
                for item_id in items:
                    path = Path(shard_out, f"{item_id}.json")
                    path.write_text(
                        json.dumps(_mock_chapter(item_id), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            outputs: dict[str, Any] = {"digest_ok": True, "chapters_done": len(items)}
            # Echo the workspace coordinates: context flows along edges, so the
            # same-shard merge nodes locate the products through this pass-through.
            for key in ("shard_out_dir", "run_out_dir", "workspace_root"):
                if values.get(key):
                    outputs[key] = str(values[key])
            return outputs
        if node_type == "volume_summary":
            return {"volume_ok": True}
        if node_type == "consistency_check":
            return {"consistency_ok": True}
        if node_type == "final_report":
            return {"report_ok": True}
        return None

    # ── web ───────────────────────────────────────────────────────────────
    def web_manifest(self) -> dict[str, Any]:
        return {
            "id": DOMAIN_ID,
            "label": "Novel Digest",
            "bundle": "domains/novel_digest/index.ts",
            "slots": ["itemRowExtra", "reviewDetailTabs"],  # 台账加卷/字数列 + 审查加时间线 tab
            "routes": ["/timeline"],  # 全局时间线页面
        }


plugin = NovelPlugin()

__all__ = [
    "CANON_REF",
    "NovelPlugin",
    "WeightedChapterSharder",
    "plugin",
    "validate_digest_result",
]
