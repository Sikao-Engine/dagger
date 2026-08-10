# 领域插件开发手册（Domain Plugin Cookbook）

> 配套文档：[通用批量 Agent 编排底座架构设计](./universal_base_architecture.md)
>
> 本文回答一个问题：**手上有一批重复但需要语义判断的工作，如何在 30 分钟内把它变成一个
> 可监控、可续跑、可审查的 DivDag 领域插件。**

---

## 0. 先做可行性自检

在写任何代码之前，用这四个问题判断你的任务是否适合这个底座：

| 检查项 | 说明 | 不满足怎么办 |
|--------|------|------------|
| **能否枚举出有序工作项？** | 必须能列出 `WorkItem[]` 并给出 `seq` | 不能枚举 → 不是批量任务，用普通 Agent 对话即可 |
| **单项处理是否需要语义判断？** | 需要读上下文、做取舍 | 纯规则 → 直接写脚本，别引入 LLM |
| **是否有明确的"完成"判据？** | 能写进 `session_result.json` 的布尔或计数 | 判据模糊 → 先把判据定义清楚，否则无法无人值守 |
| **规模是否值得？** | 经验阈值：> 50 项，或单项 > 10 分钟 | 规模太小 → 手动跑 skill 更快 |

> 第三条最容易被忽略。CubeClaw 的每个节点都有可机器验证的完成判据
> （`range_complete=true`、`build_ok`、报告文件结构完整），这是它能自动推进的前提。

---

## 1. 五步建插件

```bash
divdag create-domain novel_digest
```

脚手架生成：

```
domains/novel_digest/
├── pyproject.toml          # entry_points: divdag.domains = novel_digest = ...:plugin
├── plugin.py               # DomainPlugin 实现（唯一入口）
├── items.py                # ItemSource
├── executors.py            # ExecutorSpec 列表
├── templates.py            # DagTemplate
├── skills.py               # SkillSpec（prompt 模板）
├── nodes/                  # builtin NodeHandler
├── validators.py           # ResultValidator / ResultRecoverer
├── scanners.py             # 机械化扫描 → Finding
├── cli/                    # 给 Agent 用的确定性 CLI（可选但强烈建议）
├── skills_md/              # Agent 侧 SKILL.md（SOP 文档）
└── web/                    # 前端领域模块
```

### Step 1：定义 WorkItem 与 ItemSource

```python
# items.py
class ChapterSource(ItemSource):
    async def refresh(self, ws: WorkspaceRef) -> ItemLedgerSnapshot:
        files = sorted(Path(ws.root, "chapters").glob("*.txt"))
        items = [
            WorkItem(
                id=f.stem,
                seq=int(f.stem.split("_")[1]),
                title=_first_line(f),
                payload={"path": str(f), "word_count": _wc(f), "volume": _vol(f)},
                labels=("prologue",) if _is_prologue(f) else (),
            )
            for f in files
        ]
        milestones = [
            Milestone(name=f"第{v}卷", boundary_item_id=last.id)
            for v, last in _volume_boundaries(items)
        ]
        return ItemLedgerSnapshot(items=items, milestones=milestones,
                                  frontier_item_id=_read_cursor(ws))
```

**要点**：
- `seq` 必须全局单调，它决定分片边界与续跑指针
- `labels` 用来做筛选与特殊处理（对应 CubeClaw 的 revert pair、locked file 标记）
- `payload` 放分片权重字段（`word_count` / `diff_size` ）

### Step 2：声明 Executor 与拓扑

先画图再写代码。用这四个问句定拓扑：

1. 哪些步骤**必须跨分片串行**？（后片依赖前片的累积状态）→ `SERIAL_PREV` 边
2. 哪些步骤**分片内顺序固定**？→ `INTRA` 边
3. 哪些步骤**可以并行**？→ 不连边
4. 哪些步骤**必须等全部分片完成**？→ `ALL` 边到 `Scope.RUN` 节点

> CubeClaw 的答案：pick 串行、build fix forward 串行、review 并行、final_review 汇聚。
> 大多数批量任务的答案与之同构。

```python
# executors.py
EXECUTORS = [
    ExecutorSpec("novel.digest", "逐章摘要", handler_kind="agent",
                 scope=Scope.SHARD, skill="novel-digest", default_timeout=7200),
    ExecutorSpec("novel.timeline_merge", "时间线合并", handler_kind="builtin",
                 scope=Scope.SHARD, node_class="nodes.timeline:TimelineMergeNode"),
    ...
]
```

### Step 3：写 SkillSpec（prompt 模板）

```python
# skills.py
NOVEL_DIGEST = SkillSpec(
    key="novel-digest",
    skill_name="novel-digest",
    prompt_template="""/novel-digest 请处理本分片的 {{ shard.item_count }} 章（{{ shard.first_item.id }} ~ {{ shard.last_item.id }}）。
原文目录：`{{ ctx.source_dir }}`；产出目录：`{{ ctx.shard_out_dir }}`。
请串行执行 `noveltool next` 推进，每章产出 summary/entities/timeline 三份 JSON。
人物与地点必须与设定卡 `{{ refs.canon.path }}` 对齐，新出现的实体要显式标注为 new。
时间线增量必须相对于 `{{ ctx.prev_timeline_path or '（本片为首片，无前置时间线）' }}`。
全部章节 done 后写 session_result 最终态（digest_ok=true, outputs.chapters_done=<数量>）。""",
    success_key="digest_ok",
    requires=("source_dir", "shard_out_dir"),
    produces=("timeline_path", "entities_path", "chapters_done"),
)
```

**Prompt 编写规范**（从 CubeClaw 实战中提炼，务必遵守）：

| 规范 | 反例 | 正例 |
|------|------|------|
| 完成判据必须可机器验证 | "处理完所有章节" | "`noveltool status` 输出 `all_done=true`" |
| 边界必须写清 inclusive/exclusive | "处理到第 50 章" | "处理到第 50 章（**inclusive，第 50 章本身也要处理**）" |
| 明确禁止的动作 | — | "不要修改原文目录；不要 checkout 到其他分支" |
| 给出参照系及其用途 | 只给路径 | "`{{ refs.canon.path }}` 是人物设定权威，冲突时以它为准" |
| 声明产物路径与格式 | "输出结果" | "写入 `{{ ctx.shard_out_dir }}/<chapter_id>.json`，schema 见 meta 文件" |

### Step 4：确定性 CLI（强烈建议）

**这是 CubeClaw 最重要的经验之一**：把能写死的逻辑从 LLM 手里拿走。

`divdag_cli.scaffold` 提供脚手架，你的 CLI 只需满足三条契约：

```
1. 所有输出为 JSON（`--json` 默认开启）
2. 语义化退出码：0 成功 / 1 需人工 / 2 需审查 / 3 参数错
3. 幂等：重复执行同一命令不产生副作用
```

典型命令集（照搬 gbcli 的形状）：

```
noveltool status              # 当前进度、下一项、剩余数
noveltool next                # 推进一项：读入 → 调用固定处理 → 写产出 → 移动指针
noveltool fill <id> --file …  # 回填 Agent 生成的内容并校验 schema
noveltool check <id>          # 机械校验（字段齐全、实体已登记、时间线不倒流）
```

**分工原则**：

| Agent 负责 | CLI 负责 |
|-----------|---------|
| 读懂章节、生成摘要、判断人物同一性 | 遍历、指针推进、schema 校验、产物落盘 |
| 判断是否超出能力需上报 | 幂等、退出码、状态文件、证据快照 |

### Step 5：审查配置

```python
# scanners.py
class EmptySummaryScanner(Scanner):
    code = "empty_summary"
    async def scan(self, run, item, artifacts) -> list[Finding]:
        s = artifacts.get("summary")
        if not s or len(s.text) < 50:
            return [Finding(code=self.code, severity="warning",
                            message=f"{item.id} 摘要过短或为空")]
        return []
```

Scanner 是**机械化的、零成本的第一道防线**。CubeClaw 的经验是：
80% 的问题（漏同步、宏被冲掉、残留冲突标记、超大 commit）都能被机械扫描抓到，
真正需要人看的只有剩下 20%。**先写 Scanner，再谈人工审查。**

---

## 2. 常见拓扑模式速查

### 模式 A：纯并行（无跨项依赖）

```
init → shard_ws[i] → process[i] ──ALL──→ aggregate → report
```
适用：批量翻译独立文档、批量图片标注、批量单测生成。

### 模式 B：累积串行（后项依赖前项状态）

```
init → shard_ws[i] → process[i] ─SERIAL_PREV─→ process[i+1]
                          └──ALL──→ aggregate
```
适用：cherry-pick、时间线构建、增量索引、连载剧情梳理。

### 模式 C：主链串行 + 侧链并行（CubeClaw 模式）

```
init → pick[i] ─SERIAL_PREV─→ pick[i+1]
         ├→ snapshot[i] → review[i] ──ALL──→ final_review ─→ report
         └→ buildfix[i] → build[i] ─SERIAL_PREV─→ build[i+1] ─LAST─→ fixup
```
适用：主流程必须串行，但验证/审查可以在快照上并行。**这是最有价值的模式**——
它让"慢验证"不阻塞"快推进"。

### 模式 D：先探后做（Preview → Execute）

```
（Run 1）scan[i] ──ALL──→ risk_summary      # 只读，评估难度与风险
（Run 2）根据 risk_summary 调整分片粒度后再跑模式 B/C
```
适用：不确定难度、需要提前决定拆多细、需要提前拉人的场景。
CubeClaw 的 `netease-impact-preview` 就是这个模式。

---

## 3. 反模式清单

| 反模式 | 后果 | 正确做法 |
|--------|------|---------|
| 一个 item 一个 DAG 节点 | 数千节点，画布不可用，DB 压力大 | 分片 + 片内由 CLI 推进指针 |
| 用 SSE `idle` 判定完成 | Agent 中途放弃也被判成功 | 只认 `session_result.json` 终态 |
| 节点里写 `if pipeline == "x"` | 节点不可复用，模板失去意义 | 边上 `maps` 重映射 + 节点保持通用 |
| 完成判据写"请确保都处理好了" | 无法自动推进，必须人看 | 给出可机器验证的判据表达式 |
| 让 Agent 自己决定遍历顺序 | 不可续跑、不可审计 | 指针由 CLI 推进，Agent 只处理"当前这一项" |
| 并行分支写同名 context key | `ContextConflictError` | 用命名空间 key（`win_ok` / `ios_ok`）或边上 maps |
| 把领域字段加进核心表 | 底座被污染，下个领域要再改一次 | 进 JSON 列或 `<domain>_*` 表 |
| 没有 Scanner 就上人工审查 | 人被淹没在低价值检查里 | 先机械扫描，人只看高信号项 |
| prompt 里内联大段元信息 | token 浪费、易截断 | 写 `*.meta.json`，prompt 只给路径 |

---

## 4. 上线检查清单

跑第一个真实 Run 之前逐条确认：

**编排**
- [ ] 模板拓扑图画过，串行/并行/汇聚边都有明确理由
- [ ] 每个节点的 `NodeContract.reads/writes` 已声明，且能通过 dry-run 校验
- [ ] 分片建议在真实数据上试过，片数与单片耗时可接受（建议单片 30–90 分钟）

**Agent**
- [ ] 每个 SkillSpec 的完成判据可机器验证
- [ ] 边界项的 inclusive/exclusive 在 prompt 中显式写明
- [ ] `ResultValidator` 覆盖了本领域最容易出的 off-by-one / 漏项错误
- [ ] 单节点手工跑通过一次（不经 DAG），确认 prompt 与 CLI 配合无误

**恢复**
- [ ] 中途 kill 进程后重跑，能从 cursor 正确续上
- [ ] 重跑已成功节点时会幂等跳过，不重复烧 token
- [ ] 重试上下文注入生效（第二次 attempt 的 prompt 含前次失败摘要）

**审查**
- [ ] Scanner 至少覆盖：产出为空、schema 不完整、跨项一致性
- [ ] Artifact slot 定义完整，前端能正确渲染
- [ ] Intent Diff 左右两侧内容都能取到

**运维**
- [ ] 资源预算（若启用）估算过，磁盘/内存不会打爆
- [ ] Blocked 时的通知渠道通了
- [ ] `can_run: false` 的审阅型部署能正常查看历史 Run

## 5. 最小可行插件（60 行）

作为起步参考，一个"什么都用默认"的插件长这样：

```python
# domains/tiny/plugin.py
from divdag_kernel.spi import DomainPlugin
from divdag_kernel.executors import ExecutorSpec, Scope
from divdag_kernel.dag import DagTemplate, NodeDef, EdgeDef, EdgeKind
from divdag_kernel.contract import SkillSpec
from divdag_kernel.planning import WorkItem, ItemLedgerSnapshot

class TinySource:
    async def refresh(self, ws):
        lines = (ws.root / "todo.txt").read_text(encoding="utf-8").splitlines()
        return ItemLedgerSnapshot(
            items=[WorkItem(id=f"i{n}", seq=n, title=t, payload={})
                   for n, t in enumerate(lines) if t.strip()],
            milestones=[], frontier_item_id=None,
        )

TEMPLATE = DagTemplate(
    id="tiny_default", domain_id="tiny",
    nodes=[
        NodeDef("work", "tiny.work", Scope.SHARD, priority=10),
        NodeDef("report", "tiny.report", Scope.RUN, priority=50),
    ],
    edges=[EdgeDef("work", "report", EdgeKind.ALL)],
)

SKILLS = [
    SkillSpec(key="tiny-work", skill_name="tiny-work",
              prompt_template="/tiny-work 处理这 {{ shard.item_count }} 项："
                              "{{ shard.items | map(attribute='title') | join('、') }}。"
                              "每项产出写入 `{{ ctx.shard_out_dir }}/<item_id>.md`。"
                              "全部完成后写 session_result（work_ok=true）。",
              success_key="work_ok"),
    SkillSpec(key="tiny-report", skill_name="tiny-report",
              prompt_template="/tiny-report 汇总 `{{ ctx.run_out_dir }}` 下所有产出，"
                              "写入 `{{ ctx.run_out_dir }}/report.md`。",
              success_key="report_ok"),
]

class TinyPlugin(DomainPlugin):
    id, label, version = "tiny", "Tiny Demo", "0.1.0"
    def item_source(self): return TinySource()
    def executors(self): return [
        ExecutorSpec("tiny.work", "Work", handler_kind="agent",
                     scope=Scope.SHARD, skill="tiny-work"),
        ExecutorSpec("tiny.report", "Report", handler_kind="agent",
                     scope=Scope.RUN, skill="tiny-report"),
    ]
    def templates(self): return [TEMPLATE]
    def skills(self): return SKILLS

plugin = TinyPlugin()
```

装上之后立刻拥有：规划页、DAG 画布、实时 Agent 流、断点续跑、重试、审查列表、报告。
**这就是底座的价值。**
