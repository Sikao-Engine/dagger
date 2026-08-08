# 内核 F：运行时状态层（StateStore）
> 配套文档：`universal_base_architecture.md`（底座总体）、`domain_plugin_cookbook.md`（插件手册）。
> 本文只解决一件事：**所有"跑起来之后产生的东西"存哪、谁能写、怎么找、怎么恢复、怎么清、怎么审计。**

---

## 1. 设计目标与五条铁律

目标：**可维护**（改布局只动一处）、**可扩展**（新 skill 不新增路径规则）、
**易迁移**（目录整体搬走仍可用）、**易审计**（离线看得懂、追得到人）。

五条铁律：

| 铁律 | 内容 | 排除的问题 |
|------|------|-----------|
| **R1 单一路径权威** | 业务代码**永不拼路径**，只向 `StateStore` 要。`os.path.join` / `Path(...) /` 出现在 handler 里即视为违规（import-linter + 单测扫描） | P1 |
| **R2 所有权即分层** | 每个目录属且仅属于一个 owner（orchestrator / agent / cli / human），写权限由层决定，跨层写必须过 API | P2 |
| **R3 键即坐标** | 路径由结构化 `StateKey` 生成，**不由人取名**；人可读性靠 `index.json` 和 `_meta.json` 解决 | P3 |
| **R4 Attempt 不可变** | 每次尝试写入独立 `attempt-<n>/`，历史 attempt 只读；"最新"由指针文件表达 | P4、P7 |
| **R5 自描述 + 相对寻址** | 每个状态对象带 `kind` + `schema_version`；所有对外记录的路径都相对 state root | P5、P6 |

---

## 3. 五层状态模型

把原来一锅端的 `temp/` 切成 **5 个层**，每层的 owner / 可变性 / 生命周期 / 重跑语义都不同：

| 层 | 目录 | Owner（唯一写者） | 其他角色 | 可变性 | 重跑时 | 生命周期 |
|----|------|------------------|---------|--------|--------|---------|
| **control** 编排层 | `control/` | Orchestrator | Agent 只读、前端只读 | 节点开始前写一次 | 新 attempt 追加 | `durable` |
| **contract** 合同层 | `contract/` | Agent（经 CLI 或直写） | Orchestrator 只读并校验 | 每 attempt 一份，写完不改 | 新 attempt 新文件 | `durable` |
| **scratch** 草稿层 | `scratch/` | Agent / skill 自由读写 | 任何人可删 | 随时变 | 按 `retry_policy` 决定继承或清空 | `resumable` |
| **artifact** 产物层 | `artifact/` | Agent（append-only 写）+ CLI | 前端审查界面读 | 只增不改 | 同 item 重跑写新版本 | `archival` |
| **log** 日志层 | `log/` | Orchestrator（transcript）+ 命令执行器 | 前端读 | append-only | 每 attempt 独立 | `ephemeral`（可配 TTL） |

关键判据（写新 skill 时靠这张表决定文件放哪）：

```
这个文件被编排/前端当作"事实"消费吗？
  ├─ 是，且是"任务完成的声明"          → contract/
  ├─ 是，且是"给人看/给下一批召回的内容" → artifact/
  └─ 否
      ├─ 只有本节点自己在中途读写      → scratch/
      ├─ 是编排在节点开始前准备的输入   → control/
      └─ 是过程记录（对话/命令/stdout） → log/
```

> **P2 的根治**：`clean_and_reinit` 这类粗暴操作被替换为
> `state gc --layers scratch,log`，contract / artifact 永不被顺手清掉。

---

## 4. 目录布局

```
<workspaces_dir>/<run_id>/
├── workspace/                       # 现场（worktree / copy-dir），归 WorkspaceProvider 管，不属于 state
│   ├── main/
│   ├── shard-01/
│   └── ref-upstream_at_time/
└── state/                           # ★ StateStore 根（原 ../temp 的替代）
    ├── run.json                     # 运行清单：run_id / domain / template / 配置快照（不可变）
    ├── index.json                   # 状态索引（唯一查询入口，可由 reindex 重建）
    ├── journal.jsonl                # 审计流水（append-only）
    ├── control/
    │   ├── plan.json                # 分片计划 + item 台账快照
    │   ├── cursor.json              # 断点指针（原 bd/currentcommit.txt 的泛化）
    │   ├── items/<item_id>.json     # 单个 WorkItem 的编排视图（可选，大批量时用 items.jsonl）
    │   └── nodes/<node_run_id>/
    │       ├── node.json            # NodeDef 实例化后的静态 payload
    │       └── context.json         # 沿边解析出的 NodeContext 快照（调试/复算用）
    ├── contract/
    │   └── <node_run_id>/
    │       ├── LATEST               # 单行文本："attempt-3"
    │       └── attempt-<n>/
    │           ├── task_card.json   # 编排写：本次尝试的全部输入与期望（见 §9）
    │           ├── result.json      # ★ Agent 写：唯一被信任的完成声明
    │           ├── claim.json       # 谁写的：agent_session_id / backend / model / 起止时间
    │           └── _meta.json
    ├── scratch/
    │   └── <node_run_id>/attempt-<n>/…   # skill 自由发挥（checkpoint、临时 diff、rounds/）
    ├── artifact/
    │   ├── run/<slot>.<ext>              # Run 级产物（report.json / report.md）
    │   ├── shards/<shard_id>/<slot>.<ext>
    │   └── items/<item_id>/
    │       ├── <slot>.<ext>              # 由 ArtifactSpec.slots 决定（evidence 5 槽 / digest 5 槽）
    │       └── _meta.json
    └── log/
        └── <node_run_id>/attempt-<n>/
            ├── transcript.jsonl          # Agent SSE 归档
            ├── commands.log              # 确定性 CLI 的 stdout/stderr
            └── progress.jsonl            # 节点进度事件
```

设计要点：

- **`state/` 与 `workspace/` 严格分离**。现场可以被删了重建（worktree 可重新物化），
  state 不行。
- **`state/` 自包含**：整个目录 tar 走就是一份完整可离线审计的运行档案，
  不依赖 DB、不依赖绝对路径（§11）。
- **item 维度独立于 shard 维度**。

---

## 5. 坐标系与 StateKey

所有路径由一个结构化键唯一决定：

```python
@dataclass(frozen=True)
class StateKey:
    layer: Layer                      # CONTROL | CONTRACT | SCRATCH | ARTIFACT | LOG
    scope: Scope                      # RUN | SHARD | NODE | ITEM
    node_run_id: str | None = None
    shard_id: str | None = None
    item_id: str | None = None
    attempt: int | None = None
    slot: str = ""                    # ArtifactSpec.slot / "result" / "cursor" …
```

```python
class StateStore:
    def path(self, key: StateKey) -> Path: ...              # 唯一路径生成入口
    def read_json(self, key: StateKey) -> dict | None: ...
    def write_json(self, key: StateKey, obj: dict, *, kind: str) -> ArtifactRef: ...
    def write_bytes(self, key: StateKey, data: bytes, *, kind: str) -> ArtifactRef: ...
    def open_scratch(self, node_run_id: str, attempt: int) -> Path: ...
    def latest_attempt(self, node_run_id: str) -> int: ...
    def list(self, *, layer=None, scope=None, item_id=None) -> list[ArtifactRef]: ...
    def relocate(self, new_root: Path) -> None: ...
```

规则：

1. **ID 全部不透明**。`node_run_id` / `shard_id` / `item_id` 是不带语义的稳定标识
   （`item_id` 由领域给，但底座只当字符串用，做文件名安全化）。
   → 彻底消除 P3 的 `<sfx>` 撞名。
2. **人可读性不靠路径**。想按名字找东西，查 `index.json`，或用
   `loom state ls --node review --shard b`。
3. **路径生成函数是纯函数且被单测钉死**：布局若要变更，只改 `StateStore._layout()` 一处，
   配合 `schema_version` 提升 + 迁移脚本。

---

## 6. 索引与自描述（index / _meta / journal）

### 6.1 每个 JSON 的信封

所有 StateStore 写出的 JSON 强制带信封：

```json
{
  "kind": "session_result",
  "schema_version": 2,
  "key": {"layer": "contract", "scope": "node", "node_run_id": "nr_0f3a", "attempt": 3, "slot": "result"},
  "written_by": {"role": "agent", "session_id": "ses_7c1", "backend": "agentcli", "model": "…"},
  "written_at": "2026-08-07T09:41:22Z",
  "body": { … }
}
```

`body` 之外的字段由 `StateStore` 自动补全——**Agent 只需要写 `body` 的内容**，
信封由 CLI 包装（Agent 直写场景则由读取端 `normalize_envelope()` 补齐并在 journal 标记 `unwrapped`）。

### 6.2 `index.json`

```json
{
  "schema_version": 1,
  "run_id": "run_2026_0807_a",
  "state_root_rel": ".",
  "entries": [
    {"kind": "session_result", "path": "contract/nr_0f3a/attempt-3/result.json",
     "layer": "contract", "node_run_id": "nr_0f3a", "attempt": 3,
     "size": 2841, "sha256": "…", "written_at": "…"},
    {"kind": "evidence", "path": "artifact/items/9c1e2f/resolved.diff",
     "layer": "artifact", "item_id": "9c1e2f", "slot": "resolved", …}
  ]
}
```

- **前端与 controller 只通过 index 定位文件**，不再出现
  `Path(temp)/f"branch_dance_{suffix}"` 这种反向拼接（P1/P5 根治）。
- index 是**缓存**，不是真相：`loom state reindex` 扫描目录树 + 读 `_meta.json` 完全重建。
- 大 run（万级 item）时 index 拆为 `index/entries-*.jsonl` 分片，接口不变。

### 6.3 `journal.jsonl`

每次写入 append 一行，**只增不改**：

```json
{"ts":"…","op":"write","kind":"session_result","key":{…},"actor":"agent:ses_7c1","sha256":"…","bytes":2841}
{"ts":"…","op":"supersede","kind":"session_result","key":{…,"attempt":2},"reason":"retry"}
{"ts":"…","op":"gc","layers":["scratch"],"freed_bytes":1843922}
```

审计问题"这个结论是第几次尝试、谁写的、之前那次写了什么"直接可答（P7 根治）。

---

## 7. 写入语义：原子性、并发、Attempt 隔离

### 7.1 原子写

```
write(key, data):
    tmp = path.with_suffix(path.suffix + f".tmp.{pid}.{ts}")
    tmp.write_bytes(data); flush; fsync
    os.replace(tmp, path)          # 同盘原子替换
    append journal
    update index (best-effort，失败可 reindex 补)
```

读者**永远不会看到半截文件**。

### 7.2 并发规则

| 场景 | 规则 |
|------|------|
| 多 shard 并行 | 各自子树互不相交（`contract/<node_run_id>/`、`scratch/<node_run_id>/`），无锁 |
| 多 shard 写同一 run 级产物 | **禁止直写**。各自写 `artifact/shards/<shard_id>/<slot>`，由汇总节点合并到 `artifact/run/` |
| 追加型 run 级流水 | 仅允许 `*.jsonl` 的 O_APPEND 单行写（单行 < 4KB 保证原子） |
| index 更新 | 单进程 orchestrator 串行；外部写入者只 append journal，index 由 orchestrator 或 reindex 收敛 |

### 7.3 Attempt 隔离（P4 根治）

```python
class RetryPolicy(StrEnum):
    FRESH    = "fresh"       # 新 attempt 从空 scratch 开始
    INHERIT  = "inherit"     # 复制上一 attempt 的 scratch（断点续传）
    LINK     = "link"        # 只读挂载上一 attempt scratch，新写入落新目录
```

由 `SkillSpec.retry_policy` 声明，**默认 `FRESH`**。
"review_b 误 resume review_a" 这类 bug 在新结构下**不可能发生**：不同节点的 scratch
根本不共享目录，同节点不同 attempt 默认不继承。需要续传的（如 pick 的逐 commit 推进）
显式声明 `INHERIT`，语义清晰且可在前端展示"本次继承自 attempt-2"。

---

## 8. Schema 版本与迁移

```python
@register_schema("session_result", version=2)
class SessionResultV2(TypedDict): ...

@migration("session_result", 1, 2)
def _v1_to_v2(body: dict) -> dict:
    body.setdefault("progress", {"done": 0, "total": 0})
    body["outputs"] = body.pop("artifacts", [])
    return body
```

- 读取时按 `kind` + `schema_version` 自动升级到当前版本（**升级只在内存，不回写**，
  除非显式 `loom state migrate --write`）。
- `kind` 注册表同时给出 **JSON Schema**，用于：
  1. 写入时校验（Agent 写错立刻 reject 并给出可读错误，进入重试 prompt）；
  2. 前端自动生成只读表格视图（未知 kind 也能渲染）；
  3. 文档自动生成。
- 布局本身也有版本：`run.json.layout_version`。`StateStore` 打开旧 layout 时挂
  `LegacyLayoutAdapter`（§14），保证老 run 仍可读。

---

## 9. Agent 侧契约：TaskCard 与唯一写入口

### 9.1 TaskCard 取代"超长 prompt 里塞一堆路径"

编排在节点启动前写

```
contract/<node_run_id>/attempt-<n>/task_card.json
```

```json
{
  "kind": "task_card", "schema_version": 1,
  "body": {
    "node": "digest", "shard": "shard-02", "attempt": 3,
    "items": [{"id": "ch_0413", "seq": 413, "title": "…"}],
    "workspace": {"main": "…/workspace/shard-02"},
    "references": [
      {"name": "canon_setting", "path": "…/workspace/ref-canon", "purpose": "人物设定权威，只读"}
    ],
    "write_targets": {
      "result":   "…/contract/nr_0f3a/attempt-3/result.json",
      "scratch":  "…/scratch/nr_0f3a/attempt-3/",
      "artifact": "…/artifact/items/{item_id}/{slot}"
    },
    "artifact_slots": [{"slot": "summary", "ext": "md"}, {"slot": "timeline", "ext": "json"}],
    "success_criterion": "每个 item 的 summary 与 timeline 槽均已写入且非空",
    "forbidden": ["写 control/ 或其他 node_run_id 的目录", "修改历史 attempt"],
    "previous_attempt": {"attempt": 2, "failure": "…", "scratch": null}
  }
}
```

prompt 收缩为一句：
> 读取 `<task_card_path>`，按其中 `write_targets` 写入结果；完成判据见 `success_criterion`。

**收益**：布局变更零 prompt 改动；路径注入可被单测覆盖；Agent 拿到的是结构化数据而非散文。

### 9.2 唯一写入口

Agent 被允许的写入只有三处，且**推荐一律经过确定性 CLI**：

```bash
loom state result  --write  <json|-@file>     # → contract/.../result.json（自动包信封、校验 schema）
loom state artifact --item ch_0413 --slot summary --file out.md
loom state scratch  --path checkpoint.json    # 只是返回一个安全路径，供 skill 自由写
```

CLI 语义化退出码:0 成功 / 1 拒绝 / 2 需人工 / 3 参数错，
写失败即刻给出结构化错误，进入重试上下文。

> 允许 Agent 直写文件（有些 skill 用编辑器工具更自然），但**只在 `scratch/` 与
> `artifact/` 白名单路径内**；`result.json` 直写会在读取时被 `normalize_envelope()`
> 补信封并在 journal 标记 `unwrapped`，前端显示"未经 CLI 写入"提示。

---

## 11. 生命周期、GC 与归档

| 层 | 默认策略 | 触发 |
|----|---------|------|
| `log` | 保留最近 N=3 个 attempt；超过 30 天压缩为 `.zst` | 定时 + run 结束 |
| `scratch` | run 达终态后清空（除非 run 标记 `keep_scratch`） | run 结束 |
| `control` | 永久（体积小） | — |
| `contract` | 永久 | — |
| `artifact` | 永久；可 `--archive` 转冷存（打包 + 只留 index 条目 + 校验和） | 手动 / 定时 |

```bash
loom state gc  --run <id> --layers scratch,log --dry-run
loom state archive --run <id> --out run_2026_0807_a.loomarc   # tar.zst + manifest + 校验
loom state verify --run <id>                                   # 校验 sha256 与 index 一致
```

`.loomarc` 归档包 = `state/` 全量 + `run.json` + `index.json` + 校验清单，
**离线解开即可用只读模式在前端加载审查**（

---

## 10. 可移植性：相对路径 + 重定位

规则：

1. **state 内部记录的路径一律相对 `state/`**（`index.json` / `_meta.json` / `result.json` 内的引用）。
2. **DB 中存 `run_id` + 相对 key**，不存绝对路径。
3. **绝对路径只在两个瞬间存在**：① `StateStore.path()` 返回值；② 渲染 TaskCard 时。
4. 跨机器搬迁：`loom state relocate --run <id> --root <new_path>` 只改 `run.json.root`
   与外部现场引用（workspace 路径），state 内部无需改写。

---

## 11. 与数据库的关系：谁是真相

| 事实 | 权威载体 | 备份 |
|------|---------|------|
| 业务产物（摘要 / 证据 / 报告） | `state/artifact/` | — |
| 任务完成声明 | `state/contract/.../result.json` | DB `attempts.result_ref` 只存引用与摘要 |
| 编排调度状态（谁 ready、谁 running） | DB `node_runs` / `attempts` | `state/control/` 可用于重建 |
| 断点位置 | `state/control/cursor.json` | DB 缓存 |
| 对话轨迹 | `state/log/*/transcript.jsonl` | DB 只存索引 |

原则：**文件系统是业务真相，DB 是编排真相与索引。**
两者不一致时的收敛方向由 `loom state reconcile` 明确规定：

```
DB 说 success 但 contract 缺 result.json      → 降级为 needs_review，报告不一致
contract 有 result.json 但 DB 说 running     → 采信文件，标记 success（幂等重跑的正常情形）
artifact 存在但 index 无条目                  → reindex 补
index 有条目但文件缺失                        → 标记 missing，verify 失败
```

---

## 12. 访问面：Python API / CLI / HTTP

### Python

```python
store = StateStore.for_run(run_id)
card  = store.read_json(K.task_card(node_run_id, attempt))
ref   = store.write_json(K.result(node_run_id, attempt), body, kind="session_result")
for a in store.list(layer=Layer.ARTIFACT, item_id="ch_0413"): ...
```

`K` 是 StateKey 的语义化构造器（`K.result` / `K.cursor` / `K.evidence(item, slot)`），
**这是业务代码唯一被允许接触"路径"的地方**。

### CLI（Agent + 人共用）

```
loom state ls        [--layer] [--node] [--item] [--kind]
loom state cat       <key-expr>
loom state result    --write / --check
loom state artifact  --item <id> --slot <s> --file <f>
loom state reindex | verify | gc | archive | relocate | reconcile | migrate
```

### HTTP（前端）

```
GET  /api/v1/runs/{run_id}/state/index                 # 索引（支持 layer/kind/item 过滤）
GET  /api/v1/runs/{run_id}/state/object?key=…          # 单对象（JSON 直出 / 二进制流）
GET  /api/v1/runs/{run_id}/items/{item_id}/artifacts   # 审查界面主入口（按 ArtifactSpec 分槽）
GET  /api/v1/runs/{run_id}/nodes/{node_run_id}/attempts # attempt 列表 + 各自 result 摘要
GET  /api/v1/runs/{run_id}/state/journal               # 审计流水（分页）
POST /api/v1/runs/{run_id}/state/gc                    # 需确认参数
```

前端 `EvidenceViewer` / `NodeDetailPanel` / `CommitReviewDetail` 全部改为
**只消费上面这 4 个只读接口 + `ArtifactSpec`**，不再有任何路径知识。

---

## 13. 失效模式对照表

| 失效场景 | `../temp` 现状 | Loom StateStore |
|---------|---------------|----------------|
| 编排读到写一半的结果 | 轮询 + 解析失败重试兜底 | `os.replace` 原子写，结构上不可能 |
| 两个节点串味 checkpoint | 靠往目录名塞 task_id 打补丁 | 目录按 `node_run_id`/`attempt` 天然隔离 |
| 换机器 / 换盘符 | `sanitize_*` 一族清洗，仍偶发绝对路径泄漏 | 内部全相对，`relocate` 一条命令 |
| "这个结论谁写的、第几次" | 无从查证 | `claim.json` + `journal.jsonl` |
| 重跑后想看上次结果 | 已被覆盖 | 历史 attempt 只读保留 |
| 磁盘吃紧 | 只能整体清 temp（连证据一起没） | 按层 GC，contract/artifact 受保护 |
| 新增一个 skill 要存中间态 | 自己拼一个 `temp/xxx_state/` | 声明 slot + 用 `store.open_scratch()` |
| 前端要展示新产物 | 后端加 controller 拼路径 + 前端加 fetch | 写进 `ArtifactSpec` 即自动出现在审查界面 |
| 离线拿到归档包 | 一堆无上下文文件 | `.loomarc` 自解释，可只读加载 |
| 布局需要调整 | 改 6+ 处拼接 + 前端 + 迁移脚本 | 改 `StateStore._layout()` + bump `layout_version` |

