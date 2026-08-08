# 长篇小说分析任务验收指南

> 目标读者：第一次把 Loom 用于真实长篇任务（几千章原文 → 逐章摘要 + 实体 + 全局时间线 + 一致性报告）的工程师。
>
> 本文不手把手写完 `novel_digest` 插件；它给你一张地图 + 每一站的验收判据，让你在实际工作中按里程碑推进、按判据收口。设计基线在 `doc/design/universal_base_architecture.md` §14 和 `doc/design/domain_plugin_cookbook.md`，本文是它们在落地维度的展开。
>
> 配套代码起点：`domains/novel_digest/`（空壳包，已注册 entry point）。参考实现在 `domains/tiny/`（最小可跑通 SPI）。

---

## 0. 任务画像

| 维度 | 典型值 | 对底座的影响 |
|------|--------|--------------|
| 输入 | 几百到几千章原文 `chapters/*.txt`，每章 2k–8k 字 | item 数大 → **分片 + CLI 指针推进**，绝不一个 chapter 一个 DAG 节点 |
| 单 item 处理 | 读章 → 摘要 + 实体抽取 + 时间线增量，约 1–3 分钟 | 单片 30–90 分钟内可接受，超过则分片更细 |
| 跨片依赖 | 时间线必须串行累积（后片要读前片时间线） | **`SERIAL_PREV` 边**，与 CubeClaw pick 串行同构 |
| 汇聚依赖 | 一致性校验需全片实体表 + 时间线 | **`ALL` 边**到 `Scope.RUN` 节点 |
| 产物 | 每章 `<chapter_id>.json`（summary/entities/timeline 三段） + 全局实体表 + 全局时间线 + 矛盾清单 + 分卷总述 | item 维度产物入 `artifact/items/<id>/`，全局产物入 `artifact/run/` |
| 失败模式 | 单章 LLM 抽风 / 人物误判同一性 / 时间线倒流 / 漏章 | **先 Scanner 后人工**，80% 机械可抓 |

**拓扑选择**：cookbook 模式 C（主链串行 + 侧链并行）的精简变体——
`digest` 主链 + `timeline_merge` 串行累积 + `entity_merge`/`volume_summary` 并行 + `consistency`/`final_report` 汇聚。
与设计 §14.2 的 `NOVEL_DIGEST_TEMPLATE` 一致，与 CubeClaw GlobalBatch 拓扑同构（这是抽象成立的核心证据）。

---

## 1. 五步落地法（cookbook §1 在本任务的展开）

### Step 1 — 物化数据契约

**做什么**：把"一章的产物"写成 JSON Schema 文件，让 Agent 和 Scanner 都对着它对齐。

**落地**：在 `domains/novel_digest/src/novel_digest/schemas/` 下写：
- `chapter.json` — `{ summary, entities: [{name, type, aliases, first_seen_chapter}], timeline_delta: [{event, chapter, participants, anchors}], digest_ok }`
- `volume_summary.json` — 全卷级摘要
- `consistency_report.json` — 矛盾清单

**验收判据**：
- [ ] 任意一章手写一个完整 `chapter.json` 能通过 schema 校验（用内核 `SCHEMA_REGISTRY.register`）
- [ ] 任意一份缺字段的 `chapter.json` 被拒绝并给出字段级错误
- [ ] schema 文件进 `doc/contracts/` 自动生成流程（`loom_check contracts` 触发后产物与提交一致）

**反模式自查**：不要在 prompt 里内联 schema 文本——token 浪费 + 易截断；写 `*.meta.json`，prompt 只给路径。

### Step 2 — 画 DAG 拓扑

**做什么**：照设计 §14.2 的模板照抄，只改节点 `node_type` 命名。

**验收判据**：
- [ ] 模板 `validate()` 通过（无环、无悬空边、无重名节点）
- [ ] 每条边的 `EdgeKind` 都能说出"为什么这样"：
  - `init → shard_ws` = `RUN_ENTRY_ALL`（一个 init 出 N 个分片现场）
  - `shard_ws → digest` = `INTRA`（片内顺序）
  - `digest → timeline_merge` 然后 `timeline_merge → timeline_merge` = `SERIAL_PREV`（时间线跨片累积，后片读前片状态）
  - `digest → entity_merge` = `INTRA`（片内可并行，最后汇聚）
  - `entity_merge → consistency` = `ALL`（一致性校验需全片实体表）
  - `volume_summary → consistency` = `ALL`
  - `consistency → final_report` = `INTRA`
- [ ] `template.fingerprint` 计算稳定（同一模板同一指纹，用于幂等跳过判定）

**反模式自查**：
- 不要让 `digest` 直接 `ALL → consistency`——会丢掉时间线串行累积环节，导致后片时间线没前片基础。
- 不要把"分卷边界"硬编码进节点参数——Milestone 应该在 `ItemSource` 里声明，节点保持通用。

### Step 3 — 写 SkillSpec（prompt 模板）

**做什么**：照 cookbook §1 Step 3 的 `NOVEL_DIGEST` 模板写，注意 Prompt 编写规范五条。

**验收判据**：
- [ ] `success_key` 可机器验证（`digest_ok` / `consistency_ok` / `report_ok`，绝不是"请确保都处理好了"）
- [ ] 边界 inclusive/exclusive 显式写明："处理到第 {{ shard.last_item.id }} 章（**inclusive，该章本身也要处理**）"
- [ ] 禁止动作显式写明："不要修改 `chapters/` 目录；不要写时间线以外的产物到全局状态层"
- [ ] 参照系路径 + 用途都写明："`{{ refs.canon.path }}` 是人物设定权威，冲突时以它为准"
- [ ] 产物路径 + 格式显式写明："写入 `{{ ctx.shard_out_dir }}/<chapter_id>.json`，schema 见 `{{ ctx.chapter_schema_path }}`"
- [ ] `requires` 声明并入 `NodeContract.reads`，`produces` 声明并入 `writes`
- [ ] 渲染快照测试通过（同一 ctx 渲染出同一 prompt 文本，可 diff）

**反模式自查**：不要让 Agent 自己决定遍历顺序——指针由 CLI 推进，Agent 只处理"当前这一项"。

### Step 4 — 确定性 CLI（noveltool）

**做什么**：用 `loom_cli.scaffold` 脚手架生成 `noveltool`，照 cookbook §1 Step 4 实现四条命令。

**契约三条**：
1. 所有输出为 JSON（`--json` 默认开启）
2. 语义化退出码：0 成功 / 1 需人工 / 2 需审查 / 3 参数错
3. 幂等：重复执行同一命令不产生副作用

**命令集**：
- `noveltool status` — 当前进度、下一项、剩余数
- `noveltool next` — 推进一项：读入 → 调用固定处理 → 写产出 → 移动指针
- `noveltool fill <id> --file …` — 回填 Agent 生成的内容并校验 schema
- `noveltool check <id>` — 机械校验（字段齐全、实体已登记、时间线不倒流）

**分工原则**：

| Agent 负责 | noveltool 负责 |
|-----------|---------------|
| 读懂章节、生成摘要、判断人物同一性 | 遍历、指针推进、schema 校验、产物落盘 |
| 判断是否超出能力需上报 | 幂等、退出码、状态文件、证据快照 |

**验收判据**：
- [ ] `noveltool status` 在空 / 处理中 / 全完成 三态各跑一次，JSON 字段稳定
- [ ] `noveltool next` 幂等：连跑两次，第二次退出码 0 且无副作用
- [ ] `noveltool fill <id> --file <bad.json>` 拒绝并退出码 3，给出 schema 字段级错误
- [ ] `noveltool check <id>` 对"时间线倒流"用例返回退出码 2（需审查）

**反模式自查**：不要让 Agent 直接写 `session_result.json` 里的 `digest_ok`——`noveltool next` 全部 done 后由 CLI 或调度器收尾，Agent 只填单章产物。这样中途崩溃不会误报成功。

### Step 5 — 审查配置（Scanner + ArtifactSpec + IntentDiff）

**做什么**：照 cookbook §1 Step 5 写 Scanner，照设计 §14.1 写 `artifact_spec()` + `intent_diff()`。

**Scanner 清单**（先机械后人工）：
- `EmptySummaryScanner` — 摘要为空或过短（< 50 字）
- `SchemaIncompleteScanner` — `chapter.json` 缺字段
- `UndeclaredEntityScanner` — 摘要里出现不在实体表里的人物/地点
- `TimelineRegressionScanner` — 时间线倒流（事件章节号 < 前一事件）
- `AbnormalLengthScanner` — 摘要长度异常（> 原文 1/3 或 < 原文 1/50）

**ArtifactSpec**（设计 §9.1 `DIGEST_SPEC`）：
```python
def artifact_spec(self) -> ArtifactSpec:
    return ArtifactSpec(
        label="Novel chapter digest",
        slots=(
            Slot("raw",        label="原文",       view="prose"),
            Slot("summary",    label="剧情摘要",   view="markdown"),
            Slot("entities",   label="人物/地点",  view="json-table"),
            Slot("timeline",   label="时间线增量", view="json-table"),
            Slot("issues",     label="疑点/矛盾",  view="list"),
        ),
        default_view="tabs",
    )
```

**IntentDiff**：左 = 原文章节节选，右 = Agent 生成的摘要。

**验收判据**：
- [ ] Scanner 至少覆盖 cookbook §4 上线清单的三条：产出为空、schema 不完整、跨项一致性（时间线倒流即跨项）
- [ ] 每个 Scanner 对一个故意造坏的 item 返回一条 Finding（severity 正确）
- [ ] `artifact_spec` 五 slot 在前端 EvidenceViewer 全部可渲染（`pnpm dev` 起来手点一遍）
- [ ] `intent_diff` 左右两侧内容都能取到（不是空 None）

**反模式自查**：不要跳过 Scanner 直接上人工——CubeClaw 经验是 80% 低信号问题机械可抓，人只看剩下 20% 高信号项。

---

## 2. 增量里程碑（从单章到全本）

不要一上来就跑 5000 章。按这五个里程碑逐级收口，每级过了再下一级：

### M-A：单章 dry-run（不接 LLM）

**目标**：验证 SPI 五件套（ItemSource / Executor / Template / Skill / ArtifactSpec）的最小闭环。

**做法**：
1. 在 `domains/novel_digest/src/novel_digest/plugin.py` 写最小 `NovelPlugin`（参考 `domains/tiny/src/tiny/plugin.py` 形状）
2. 用 mock 后端（`backend: mock`）跑一章
3. scheduler mock `_seed_mock_artifacts` 会按声明的 spec 种子化产物 → EvidenceViewer 有东西可看

**验收判据**：
- [ ] `loom run --domain novel_digest --items ./test_data/one_chapter --shards 1 --backend mock` 跑完无错
- [ ] state 树结构符合 §14.3：`control/items/<id>.json` + `contract/<node_run_id>/attempt-1/result.json` + `artifact/items/<id>/summary.json`
- [ ] `loom state ls --layer artifact` 看到种子的 slot
- [ ] `/runs/:id/items/:id/evidence` 页面能展示 `summary` markdown slot
- [ ] `loom state archive` 出的 `.loomarc` 能被只读加载逐项查看

### M-B：单章真实 LLM

**目标**：验证 prompt + CLI + 后端协议三件对齐。

**做法**：
1. 起 `agentcli serve`（opencode-http 后端）
2. 用 1–3 章真实原文跑 `noveltool next` 推进
3. 看 Attempt 视图回放 transcript，确认 Agent 行为符合 prompt

**验收判据**：
- [ ] `loom run --domain novel_digest --backend opencode-http` 单章跑通
- [ ] 单节点手工跑通过一次（不经 DAG）：`noveltool next` 直接跑，确认 prompt 与 CLI 配合无误
- [ ] Attempt 流仅凭 SSE 可重建 transcript（不依赖后端日志）
- [ ] 中途 kill 进程后重跑，能从 `cursor.json` 正确续上
- [ ] 重跑已成功节点时幂等跳过（不重复烧 token）

### M-C：单片多章串行（验证 SERIAL_PREV）

**目标**：验证时间线累积串行链路。

**做法**：
1. 一个分片含 5–10 章
2. 验证 `timeline_merge` 的 `SERIAL_PREV` 边把前片的 `timeline_path` 映射到后片的 `prev_timeline_path`
3. 故意 kill 一次，验证 `--resume` 从 cursor 接着跑

**验收判据**：
- [ ] 第 N 片的时间线增量引用了第 N-1 片产出的时间线（手动 cat 两片 timeline.json 验证 anchors）
- [ ] 中途 kill + `--resume` 续跑，已完成节点幂等跳过
- [ ] 重试上下文注入生效（第二次 attempt 的 prompt 含前次失败摘要）
- [ ] DAG 画布上 `timeline_merge` 节点串行变色的顺序与片序一致

### M-D：多片并行 + 汇聚（验证 ALL + consistency）

**目标**：验证并行 + 全局一致性校验。

**做法**：
1. 3 片 × 5 章 = 15 章真实数据
2. 验证 `entity_merge` / `volume_summary` 并行，`consistency` 等全部 `ALL` 完成后跑
3. 跑 Scanner 全套

**验收判据**：
- [ ] 并行分支写同名 context key 不冲突（如有，用 `maps` 命名空间或命名空间 key）
- [ ] `consistency` 节点在所有 `entity_merge` + `volume_summary` 完成后才进入 ready
- [ ] Scanner 全套对故意造坏的 item 都报 Finding
- [ ] `final_report` 产出含全局实体表 + 全局时间线 + 矛盾清单
- [ ] 全程产物落在 StateStore 正确层（control/contract/scratch/artifact/log）

### M-E：全本 + 长时跑（验证生产化）

**目标**：真实规模、真实时长、真实恢复压力。

**做法**：
1. 几百到几千章真实原文
2. 跑数小时到数天，中间人为断电/kill 多次
3. 验证 `can_run: false` 审阅型部署能正常查看历史 Run

**验收判据**：
- [ ] 中途 kill 3+ 次，每次 `--resume` 都从 cursor 正确续上，无重复烧 token
- [ ] 磁盘预算不打爆（如启用 `ResourceBudget` Hook，预警触发）
- [ ] Blocked 时的通知渠道通了
- [ ] `can_run: false` 部署下，前端可正常查看历史 Run + EvidenceViewer 全程可用
- [ ] 全程 state 树通过 `loom state verify`（sha256 对账）无 corruption

---

## 3. 上线检查清单（cookbook §4 在本任务的具体化）

跑第一个真实 Run 之前逐条确认：

**编排**
- [ ] 模板拓扑图画过（M-A 手画一次，对照设计 §14.2），串行/并行/汇聚边都有明确理由
- [ ] 每个节点的 `NodeContract.reads/writes` 已声明，且能通过 dry-run 校验
- [ ] 分片建议在真实数据上试过（M-D 用真实章节数试），片数与单片耗时可接受（单片 30–90 分钟）

**Agent**
- [ ] 每个 SkillSpec 的完成判据可机器验证（M-B 单章跑通时验证）
- [ ] 边界项的 inclusive/exclusive 在 prompt 中显式写明
- [ ] `ResultValidator` 覆盖了本领域最容易出的 off-by-one（漏章）/ 漏项错误
- [ ] 单节点手工跑通过一次（不经 DAG），确认 prompt 与 noveltool 配合无误

**恢复**
- [ ] 中途 kill 进程后重跑，能从 `cursor.json` 正确续上（M-C 验证）
- [ ] 重跑已成功节点时会幂等跳过，不重复烧 token（M-C 验证）
- [ ] 重试上下文注入生效（第二次 attempt 的 prompt 含前次失败摘要）（M-C 验证）

**审查**
- [ ] Scanner 至少覆盖：产出为空、schema 不完整、跨项一致性（M-D 验证）
- [ ] Artifact slot 定义完整，前端 EvidenceViewer 能正确渲染（M-A 即可验证最小子集）
- [ ] Intent Diff 左右两侧内容都能取到（M-B 验证）

**运维**
- [ ] 资源预算（若启用）估算过，磁盘/内存不会打爆（M-E 验证）
- [ ] Blocked 时的通知渠道通了（M-E 验证）
- [ ] `can_run: false` 的审阅型部署能正常查看历史 Run（M-E 验证）

---

## 4. 抽象回归记录（T8.2）

本任务是 Loom 第二领域（M8），是抽象质量的度量。每当你**被迫修改内核**才能让 `novel_digest` 跑通，按这个表记录一次，作为 SPI 漏洞的反馈：

| 日期 | 修改的内核文件 | 修改原因 | 是否回写为新 SPI | 反馈去向 |
|------|---------------|---------|-----------------|---------|
| _示例_ | `loom_kernel/dag/instantiator.py` | novel_digest 需要"动态分片"（先扫一遍才能决定片数） | 是 → `Scope.SHARD_DYNAMIC` + `__shards__` 已实现 | 设计 §11.3 已记 |

**回归判据**：
- 若内核零改动即可跑通 M-D → 抽象成功，可继续。
- 若每跑通一个里程碑就要改内核 → 抽象失败，停下做 SPI 重构，而不是继续打补丁。
- 任何"被迫"修改必须先问：是内核能力缺失（回写 SPI）还是领域私有需求（不该进内核）。

**已知内核已覆盖的能力**（设计 §11 已固化，novel_digest 应零成本复用）：
- DAG 画布 + 实时监控 + 断点续跑 + 失败重试 + 重试上下文注入
- 结果合同判定 + StateStore 五层布局 + GC/verify/archive/relocate
- EvidenceViewer（ArtifactSpec 驱动）+ State 浏览器 + 台账 + 规划页
- SSE 双段式 + 进程管理 + OpenAPI → TS 类型生成（CI 漂移校验）
- 领域槽位注册（`web_manifest` 动态 import，未装零成本）

**novel_digest 应自己写的**（不应进内核）：
- `ItemSource`（扫描 `chapters/*.txt`，约 60 行）
- 三个 `SkillSpec`（prompt 模板）
- 两个 builtin `NodeHandler`（`entity_merge` / `timeline_merge`，纯确定性代码）
- 一个 `Scanner` 套件
- 一个前端时间线页面（`web/src/domains/novel_digest/index.ts`，走 `web_manifest` 注册）

---

## 5. 文件起点

`domains/novel_digest/` 已有空壳：

```
domains/novel_digest/
├── pyproject.toml          # entry_points: loom.domains = novel_digest = ...:plugin
├── README.md               # 任务画像 + 拓扑说明
└── src/novel_digest/        # 你要写的：
    ├── __init__.py
    ├── plugin.py            # NovelPlugin（DomainPlugin SPI 实现）
    ├── schemas/             # chapter.json / volume_summary.json / consistency_report.json
    ├── skills.py            # NOVEL_DIGEST / NOVEL_VOLUME_SUMMARY / NOVEL_CONSISTENCY 三个 SkillSpec
    ├── scanners.py          # 五个 Scanner
    ├── nodes/               # entity_merge / timeline_merge 两个 builtin NodeHandler
    └── noveltool/           # 确定性 CLI（noveltool status/next/fill/check）
```

前端起点：
```
web/src/domains/novel_digest/
└── index.ts                 # default export DomainModule（itemColumns / artifactViews / routes）
```

`web_manifest()` 声明：
```python
def web_manifest(self) -> dict[str, Any]:
    return {
        "id": "novel_digest",
        "label": "Novel Digest",
        "bundle": "domains/novel_digest/index.ts",
        "slots": ["itemRowExtra", "reviewDetailTabs"],  # 台账加卷/字数列 + 审查加时间线 tab
        "routes": ["/timeline"],  # 全局时间线页面
    }
```

---

## 6. 与现有底座的接驳点

主循环已全绿（M0–M7 T7.1 + T6.9 EvidenceViewer）。novel_digest 落地时直接消费：

| 接驳点 | 已就绪 | novel_digest 怎么用 |
|--------|--------|---------------------|
| `DomainPlugin` SPI | ✅ M0 T0.4 + M4 T4.1 | 实现 `NovelPlugin`，entry point 注册 |
| `StateStore` 五层 | ✅ M1 | 章节产物入 `artifact/items/<id>/`，全局产物入 `artifact/run/<slot>` |
| DAG 引擎 + SERIAL_PREV/ALL | ✅ M2 | 时间线串行 + 一致性汇聚直接用 |
| `AgentBackend` Protocol | ✅ M3 | mock 跑 M-A，opencode-http 跑 M-B+ |
| CLI walking skeleton | ✅ M4 | `loom run --domain novel_digest` 即可 |
| server (REST + SSE + 调度) | ✅ M5 | 前端画布 / Attempt / State / Ledger / Planner 全套可用 |
| 前端底座 | ✅ M6 | DAGCanvas / RunDetail / Attempt / StateBrowser / Ledger / Planner 全套 |
| `ArtifactSpec` + REST + EvidenceViewer | ✅ M7 T7.1 + T6.9 | `artifact_spec()` 声明五 slot，EvidenceViewer 零前端改动展示 |

**未就绪**（M7 后续 + M8）：
- `Scanner` SPI（T7.2）— novel_digest 写 Scanner 时可能要先把 SPI 落地；若需改内核，记入 §4 回归表
- `IntentDiffProvider`（T7.2）— 原文 vs 摘要对照
- `ReviewState` / `Highlight` / `Annotation`（T7.3）— 审查批注闭环
- `MemoryIndex`（T7.4）— 跨 Run 记忆召回
- `ResourceBudget`（T7.5）— 磁盘/并发额度（M-E 验证用）

这些未就绪项不影响 M-A 到 M-D 的推进；Scanner/IntentDiff 可以先在领域内用本地实现跑通，等 SPI 落地再上提。

---

## 7. 推进节奏建议

1. **先写 §1 Step 1 物化数据契约**——schema 文件是后续一切对齐的基准，先钉死。
2. **M-A 单章 dry-run 用 mock 后端跑通**——验证 SPI 五件套闭环 + EvidenceViewer 可用，最低成本拿到反馈。
3. **M-B 单章真实 LLM**——验证 prompt + noveltool + 后端协议对齐，这一关过了后面都是规模化问题。
4. **M-C 单片多章串行**——时间线累积是本任务最容易出错的环节，单独验证。
5. **M-D 多片并行 + 汇聚**——验证拓扑完整性 + Scanner 全套。
6. **M-E 全本长时跑**——生产化压力测试，验证恢复 + 预算 + 通知。

每个里程碑过了再下一级。如果 M-A 就跑不通，先停下来修 SPI/底座，不要硬推。

---

## 8. 失败时的排查路径

| 症状 | 先查 | 再查 |
|------|------|------|
| `loom run` 报 SPI 错 | `plugin.py` 的 entry point 是否注册成功（`loom domains` 列表） | `DomainPlugin` 必需方法是否齐全 |
| Agent 跑完但 `digest_ok` 不 true | SkillSpec 的 `success_key` 与 `session_result.outputs` 字段名是否一致 | `noveltool status` 的退出码 |
| 时间线倒流 | `timeline_merge` 节点的 `maps` 是否把 `prev_timeline_path` 映射进来 | `SERIAL_PREV` 边是否连对（画布上看串行顺序） |
| EvidenceViewer 显示 undeclared slot | Agent 写的 slot 名与 `artifact_spec.slots` 的 `name` 是否一致 | `K.artifact_item(item_id, slot)` 的 slot 拼写 |
| 重跑烧 token | 节点是否幂等跳过（看 DAG 画布节点状态） | `cursor.json` 的 `cursor_item_id` 是否更新 |
| `consistency` 节点不 ready | `entity_merge` / `volume_summary` 是否全部 success | `ALL` 边是否连对 |
| state 树 corruption | `loom state verify`（sha256 对账） | 是否绕过 `StateStore.path` 直接拼路径（T0.4 守卫会抓） |

---

## 9. 验收门槛（最终）

novel_digest 视为"生产可用"需同时满足：

1. **M-E 全本跑通**：几千章真实原文，数小时到数天，中途 3+ 次人为中断均正确续上
2. **零内核改动**（或所有改动已回写为新 SPI，记入 §4 表）
3. **§3 上线清单全勾**
4. **EvidenceViewer 端到端可用**：任意一章可看到原文 vs 摘要 + 实体表 + 时间线 + 疑点，Scanner 发现项可见
5. **`loom state archive` 出的 `.loomarc` 能在 `can_run: false` 部署下只读加载逐项查看**
6. **前端 `/timeline` 页面可用**（领域自定义 route，走 `web_manifest` 注册）

满足这六条，本任务可作为 Loom 第二领域验收通过，抽象质量得到验证。同时为后续 `domains/code_batch`（CubeClaw 迁移）证明底座可承载真实生产负载。
