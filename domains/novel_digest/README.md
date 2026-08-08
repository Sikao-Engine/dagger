# domains/novel_digest

Second domain — validates that Loom's abstractions generalize beyond `tiny`.

Pipeline: chapter digest → entity merge → timeline merge (serial across shards)
→ volume summary → consistency check → final report. Mirrors CubeClaw's
GlobalBatch topology structurally; only the node content is domain-specific.

Per §10 of the architecture doc, this is the abstraction-regression test: every
kernel change forced by this domain is logged as a leak and fed back as new SPI.

## 冒烟状态（2026-08-08）

**M-A 等价级完成**：SPI 五件套 + noveltool + Scanner + IntentDiff + 前端起点全部落地；
`loom run --domain novel_digest --backend mock` 真实 CLI 跑通；为补齐内核缺口做了
K1–K8 八处内核/宿主修复（全部带测试钉死，逐条见回归表）。

- 验收报告：`doc/plan/novel_digest_smoke_report.md`（判据映射 / 内核回归表 / 设计张力 / 复验命令）
- 内核回归登记：`doc/plan/novel_digest_acceptance.md` §4
- 未做：M-B 真实 LLM、M-C~M-E 真实数据长时跑、前端手点（等全流程验收）

## 如何跑

```bash
uv sync
uv run pytest domains/novel_digest -q          # 68 个领域测试
# 手动冒烟（mock 后端，真实 CLI + 真实文件产出）
uv run python -m novel_digest.testing /tmp/book --chapters 5
loom run --domain novel_digest --items /tmp/book --shards 2 --backend mock
noveltool status --root /tmp/book --out /tmp/book/<run_id>/shard-000
```

## 包结构

```
src/novel_digest/
├── plugin.py      # NovelPlugin（DomainPlugin SPI 全钩子）+ digest ResultValidator + WeightedChapterSharder
├── items.py       # ChapterSource：扫 chapters/*.txt，卷边界 → Milestone，frontier 读 .loom/cursor.json
├── templates.py   # build_template(workspace_root)：设计 §14.2 逐字照抄（8 节点 9 边）
├── executors.py   # 6 个 ExecutorSpec（ensure_workspace 由内核提供）
├── skills.py      # 4 个 SkillSpec + Jinja2 render_prompt（快照测试钉死）
├── schemas/       # novel_chapter / novel_volume_summary / novel_consistency_report（进 SCHEMA_REGISTRY）
├── nodes/         # entity_merge / timeline_merge 两个确定性 builtin NodeHandler
├── noveltool/     # 确定性 CLI：status / next / fill / check（JSON + 退出码 0/1/2/3 + 幂等）
├── scanners.py    # 5 个机械 Scanner（实现内核 review.Scanner 协议）
├── review.py      # NovelIntentDiff（左原文节选 / 右摘要）
└── testing.py     # 确定性 fixture 生成器（测试与手动冒烟共用）
```
