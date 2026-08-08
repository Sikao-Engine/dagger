# 通用批量 Agent 编排底座（工作名：**Loom**）架构设计

> 本文从 CubeClaw（Minecraft Bedrock GlobalBatch 自动化系统）反向抽象出一个领域无关的
> 「批量 / 分片 / Skill-Node DAG」前后端底座，使得未来遇到同类任务（整理几千章网文剧情、
> 批量重构、批量翻译、批量数据清洗、批量论文精读……）时，只需实现一组插件契约，
> 而不必重写编排、会话、可观测、审查这四层基础设施。
>
> 技术栈延续 CubeClaw：后端 Python + Litestar + SQLAlchemy + SQLite，前端 React + Vite +
> TypeScript + shadcn/ui，Agent 侧沿用 opencode 协议（`agentcli serve` 兼容）。

---

## 目录

1. [CubeClaw 做对了什么：可复用的五个内核](#1-cubeclaw-做对了什么可复用的五个内核)
2. [领域耦合点盘查：哪些必须被拔掉](#2-领域耦合点盘查哪些必须被拔掉)
3. [Loom 领域模型：术语从业务名改为角色名](#3-loom-领域模型术语从业务名改为角色名)
4. [分层与包结构](#4-分层与包结构)
5. [内核 A：DAG 编排引擎](#5-内核-adag-编排引擎)
6. [内核 B：Agent 会话与结果合同](#6-内核-bagent-会话与结果合同)
7. [内核 C：Workspace / 资源供给](#7-内核-cworkspace--资源供给)
8. [内核 D：Item 台账、分片与规划](#8-内核-ditem-台账分片与规划)
9. [内核 E：证据、审查与报告](#9-内核-e证据审查与报告)
9b. [内核 F：运行时状态层（StateStore）](#9b-内核-f运行时状态层statestore) — 详见 [`state_layer_architecture.md`](./state_layer_architecture.md)
10. [插件契约总表（Domain SPI）](#10-插件契约总表domain-spi)
11. [前端底座](#11-前端底座)
12. [数据库 Schema](#12-数据库-schema)
13. [HTTP API 表面](#13-http-api-表面)
14. [端到端示例：网文剧情整理](#14-端到端示例网文剧情整理)
15. [从 CubeClaw 迁移的三阶段路线](#15-从-cubeclaw-迁移的三阶段路线)
16. [非目标与已知取舍](#16-非目标与已知取舍)

---

## 1. CubeClaw 做对了什么：可复用的五个内核

抛开 Minecraft / git / cherry-pick 这些业务词，CubeClaw 真正解决的是一类通用问题：

> **有 N 个同构工作项，处理每一项都需要「语义判断」，因此不能纯脚本；
> 但整体规则明确、可沉淀，因此不该长期由人做。**

它给出的答案由五个彼此正交的内核构成，这五个内核没有一个是 Minecraft 特有的：

| # | 内核 | CubeClaw 中的形态 | 通用价值 |
|---|------|------------------|---------|
| A | **DAG 编排引擎** | `service/dag/{template,instantiator,context}.py` + `scheduler.py` | 声明式拓扑 + 分片展开 + 串并行 + 断点续跑 |
| B | **Agent 会话 + 结果合同** | `cube/agentcli/*` + `service/agentcli/*` + `session_result.json` | 把不可靠的 LLM 循环变成可被程序调用、可被程序信任的节点 |
| C | **Workspace 供给** | `ensure_worktree` 五个 variant + `DiskManager` | 为并行节点提供隔离的、可回收的工作现场 |
| D | **Item 台账 + 分片规划** | `global_planner.py` + `SubBatch` + Milestone 切分建议 | 把几百上千个工作项变成可追踪、可续跑、可复盘的单元 |
| E | **证据 / 审查 / 报告** | evidence pack + `/batches/:id/.../review` + `batch-report` | 让 AI 的每个决策可回溯、可审计、可沉淀成下一轮的输入 |

**关键洞察：这五层之间的接口在 CubeClaw 里已经相当干净了。**

- 节点通过 `NodeContract(reads=..., writes=...)` 声明读写，注册表 fail-fast 校验（`dag/nodes/base.py`）
- 上下文沿边流动 + 边上 `maps` 重映射，节点不知道自己被接在哪条 pipeline 上（`dag/context.py`）
- executor 目录是唯一事实源，`capability` / `timeout` / `scope` / `handler_kind` 全部自描述（`executors/catalog.py`）
- 模板可持久化、可指纹比对、可从 DB 加载（`template_to_record` / `seed_default_templates`）

这意味着**抽象成本主要在"把领域词换成角色词" + "把三处硬编码换成 SPI"**，而不是重写。

---

## 2. 领域耦合点盘查：哪些必须被拔掉

逐处列出 CubeClaw 中与 Minecraft/git 强绑定的位置，以及在 Loom 中的替代物。

| 耦合点 | 现状（CubeClaw） | Loom 中的处理 |
|--------|-----------------|--------------|
| 数据模型命名 | `Batch` / `SubBatch` / `commits[]` / `end_commit` / `predecessor_branch` | 更名为 `Run` / `Shard` / `items[]` / `cursor` / `base_ref`，`ref` 类字段下沉到 domain payload |
| `BatchType` 枚举 | `global` / `netease` | 改为 `domain_id`（字符串，插件注册） |
| `TaskType` 枚举 | 17 个写死的 git 相关类型 | 删除枚举；`node_type` 为字符串，由 `ExecutorCatalog` 在启动时由插件注册决定 |
| `TaskTimeoutConfig` | 类属性写死每种 task 超时 | 移入 `ExecutorSpec.default_timeout`，插件注册时给出 |
| `SKILL_SPECS` | `service/agentcli/base.py` 里写死 prompt 模板与 `success_key` | `SkillSpec` 注册表，由插件提供；prompt 模板走 Jinja2 渲染 `NodeContext` |
| `task_handlers/*.py` | 六个 handler 拼 prompt，内含 git 分支语义 | 统一为 `PromptComposer` 接口，默认实现 = 模板渲染；复杂领域可自定义 |
| `RESULT_VALIDATORS` | `_validate_pick` 校验 `end_commit` off-by-one 等 | `ResultValidator` SPI，按 `node_type` 注册，内核只做通用字段校验 |
| `ensure_worktree` 五 variant | 全部是 `git worktree add` | `WorkspaceProvider` SPI；内置 `git-worktree` / `copy-dir` / `shared-dir` / `none` 四实现 |
| `DiskManager` | 假设 worktree、按 GB 估算 | `ResourceBudget` 可选模块；无资源约束的领域直接不启用 |
| `global_planner.py` | git log / tag / merge-base 扫描 | `ItemSource` SPI：产出有序 `WorkItem[]` + 可选 `Milestone[]` |
| `gb_init.py` | 建 4 个 git worktree + 写 `bd/*.txt` | `RunInitializer` = `WorkspaceProvider` + `StateSeeder` 两个 SPI 的组合 |
| `gbcli` | 领域确定性 CLI（pick/preview/rebase） | 保留为**领域插件自带的 CLI**；底座只约定「JSON 输出 + 语义化退出码 + 幂等」三条契约 |
| 生命周期 Instance/Candidate | 与 batch 分支强绑定 | 提取为可选模块 `run_lifecycle`，语义改为「同一目标的多次尝试 + 成品维护域」 |
| evidence pack 五快照 | `prev/incoming/local/on_conflict/resolved` | `ArtifactSpec`：领域声明自己要留哪几个 slot 及其展示方式 |
| POPO 通知 | `cube/popo/*` | `Notifier` SPI；内置 `noop` / `webhook` / `stdout` |
| 前端 `/planner` `/commits` `/batches/*/review` | 全是 git commit 语义 | 通用页面（Run/DAG/Task/Artifact）+ **领域页面槽位**（Domain Panel 注册） |

---

## 3. Loom 领域模型：术语从业务名改为角色名

```
Project                 ─ 一个长期存在的工作域（一个仓库 / 一部小说 / 一个数据集）
  └── Workspace         ─ 一份物理工作现场根目录 + 领域配置（locked rules、mirror map…）
        └── Run         ─ 一次批量作业（= CubeClaw Batch）
              ├── items[]           ─ 本次要处理的 WorkItem 有序列表
              ├── Shard[]           ─ 分片（= SubBatch），每片含 items 的一个连续区间
              │     └── NodeRun[]   ─ DAG 节点实例（= Task）
              │           └── Attempt[]   ─ 一次执行尝试（= TaskRun，含 session/transcript）
              └── Artifacts[]       ─ 产物与证据
```

术语对照表（迁移时的 rename map）：

| CubeClaw | Loom | 说明 |
|----------|------|------|
| `Batch` | `Run` | 一次批量作业；不再自带 git 分支语义 |
| `SubBatch` | `Shard` | 分片；`branch_name` → `shard_ref`（domain payload） |
| `commits[]` | `items[]` | `WorkItem { id, seq, title, payload, status }` |
| `Task` | `NodeRun` | DAG 节点实例 |
| `TaskRun` | `Attempt` | 一次尝试 |
| `end_commit` | `cursor_end` | 分片/批次的截止工作项 |
| `predecessor_branch` | `base_ref` | 基底引用，语义由 domain 解释 |
| `MainCommit` | `LedgerItem` | 全量工作项台账 |
| `Milestone` | `Milestone` | 保留，语义为「可停靠的边界」 |
| `agent_session.json` | `agent_session.json` | 保留 |
| `session_result.json` | `session_result.json` | 保留（结果合同是底座核心资产） |

**WorkItem 的最小契约**：

```python
@dataclass(frozen=True)
class WorkItem:
    id: str            # 领域内唯一（commit sha / 章节号 / 文件路径 / 行 ID）
    seq: int           # 全局有序序号；决定分片边界与"续跑指针"
    title: str         # 人类可读一行摘要
    payload: dict      # 领域自定义（author/date/word_count/tags…）
    labels: tuple[str, ...] = ()   # 用于筛选、风险标注、成对跳过等
```

> 有序性（`seq`）是底座的**唯一硬性要求**。它同时支撑：分片切分、断点续传指针、
> 前后依赖的串行边、进度百分比。若某领域天然无序（例如批量翻译独立文档），
> 令 `seq` = 输入顺序即可，串行边在模板里不连就是全并行。

---

## 4. 分层与包结构

```
loom/
├── packages/
│   ├── loom_kernel/            # 领域无关内核（无 HTTP、无 DB 依赖，可单测）
│   │   ├── dag/
│   │   │   ├── template.py     # NodeDef / EdgeDef / DagTemplate / EdgeKind
│   │   │   ├── instantiator.py # 模板 × Shard[] → NodeRun DAG
│   │   │   ├── context.py      # NodeContext / ContextPatch / 沿边合并 / 冲突检测
│   │   │   └── nodes/base.py   # NodeHandler / NodeContract / NodeRegistry / NodeRuntime
│   │   ├── executors/catalog.py# ExecutorSpec 注册表（运行时可由插件扩充）
│   │   ├── contract/
│   │   │   ├── session_result.py  # 结果合同 schema / prompt 前缀 / 通用校验
│   │   │   └── validators.py      # ResultValidator 注册表
│   │   ├── planning/
│   │   │   ├── item.py         # WorkItem / Milestone
│   │   │   └── sharder.py      # 分片策略（fixed / milestone-aware / weighted）
│   │   └── spi.py              # 所有 SPI Protocol 定义（单一入口）
│   │
│   ├── loom_agent/             # Agent 协议层（= cube/agentcli）
│   │   ├── client.py           # opencode HTTP + SSE 异步客户端
│   │   ├── process_manager.py  # 按 workdir 起独立进程 + 端口分配 + 健康探活 + 回收
│   │   ├── session_runner.py   # prompt 下发 → SSE 消费 → transcript 落盘 → 等待合同
│   │   ├── sse_parser.py
│   │   └── backends/           # AgentBackend 实现：opencode / claude-code / mock
│   │
│   └── loom_cli/               # 给 Agent 用的确定性 CLI 脚手架（gbcli 的通用化）
│       └── scaffold.py         # JSON 输出 + 语义化退出码 + 幂等 + 状态文件读写
│
├── server/                     # Litestar HTTP 服务 + 调度
│   ├── app.py
│   ├── scheduler.py            # 依赖驱动调度 + 解锁后继 + 完成判定
│   ├── runner.py               # 轮询 queued → 派发 handler → 状态机
│   ├── models.py               # SQLAlchemy ORM + Pydantic schema（领域无关）
│   ├── repositories.py
│   ├── controller/             # 通用 REST + SSE
│   ├── handlers/               # NodeRun 派发：agent / builtin / external / unsupported
│   └── domains/                # ★ 领域插件安装点
│       ├── registry.py         # DomainPlugin 发现（entry_points + 目录扫描）
│       └── <domain_id>/…
│
├── web/                        # 前端底座
│   ├── src/core/               # Run 列表 / DAG 画布 / Node 详情 / Attempt 流 / Artifact 浏览
│   ├── src/domains/<id>/       # 领域页面与面板（注册到槽位）
│   └── src/sdk/                # 类型化 API client + SSE hooks + Domain 注册表
│
└── domains/                    # 领域插件（可独立仓库，pip 安装）
    ├── code_batch/             # ← CubeClaw GlobalBatch 迁移到这里
    └── novel_digest/           # ← 网文剧情整理示例
```

**依赖方向严格单向**：`domains → server → loom_kernel`，`loom_kernel` 不 import 任何领域符号，
不 import Litestar / SQLAlchemy。这条规则由 CI 的 import-linter 守住。

---

## 5. 内核 A：DAG 编排引擎

这一层几乎可以**原样搬运** CubeClaw 的实现，只需三处泛化。

### 5.1 保留的设计（不改）

- **`NodeDef` / `EdgeDef` / `DagTemplate`** 的数据驱动拓扑描述
- **`Scope`**：`run_entry`（原 batch_entry）/ `shard`（原 subbatch）/ `run`（原 batch）
- **`EdgeKind`**：`intra` / `run_entry` / `run_entry_all` / `serial_prev` / `last` / `all`
- **边上 `maps`**：`{下游 key: 上游 key}` 重映射，让节点保持通用（这是 CubeClaw 最漂亮的一笔，
  它让 `ensure_worktree` 既能接 snapshot 分支又能接 rebase 产出）
- **`ContextPatch` 沿边合并**：近者覆盖远者、并行分支写同 key 且值不同 → `ContextConflictError`
- **`NodeContract(reads, writes)` fail-fast**：缺 key 立刻报错，产出未声明 key 立刻报错
- **拓扑指纹**：内置模板改动后自动覆盖 DB 副本（`_topology_fingerprint`）

### 5.2 三处泛化

**(1) ExecutorCatalog 从"编译期常量"变为"启动期注册表"**

```python
# loom_kernel/executors/catalog.py
@dataclass(frozen=True)
class ExecutorSpec:
    key: str                       # 全局唯一；建议 "<domain>.<name>" 命名空间
    label: str
    handler_kind: str              # agent | builtin | external | unsupported
    scope: str                     # run_entry | shard | run
    default_timeout: int = 3600
    required_capability: str | None = None
    node_class: str | None = None  # handler_kind=builtin 时的 NodeHandler 路径
    skill: str | None = None       # handler_kind=agent 时的 SkillSpec key
    variant_key: str = "variant"   # 支持 "<executor>:<variant>" 多实现
    selectors: dict = field(default_factory=dict)  # 替代 platform：任意标签选择器
    default_mock: bool = False

class ExecutorCatalog:
    def register(self, spec: ExecutorSpec) -> None: ...
    def get(self, key: str) -> ExecutorSpec | None: ...
    def all(self) -> list[ExecutorSpec]: ...
```

`platform: "win" | "ios"` 被泛化为 `selectors: {"platform": "win"}`。实例化时的裁剪逻辑
从「比较 platform 字段」变为「selectors 是否被当前可用执行器集合满足」，这样领域可以
用任意维度裁剪（GPU/无 GPU、有无某 API key、中文/英文 pipeline）。

**(2) `TaskType` 枚举删除**

`node_type` 全程用字符串。DB 层加 `CHECK` 约束改为「注册表存在性校验」，在
`schedule_run()` 时统一验证，失败即拒绝调度并给出可用 key 列表。

**(3) 分片展开支持"动态分片数"**

CubeClaw 的 `instantiate()` 假设分片列表在调度前已定。Loom 增加一种 `Scope.SHARD_DYNAMIC`：
入口节点执行完后返回 `shards: [...]`，调度器据此**二次展开** DAG。适用于「分片数依赖
Agent 的第一次扫描结果」的场景（例如先让 Agent 读目录才知道有多少卷）。

> 实现方式：入口节点 patch 中若含保留 key `__shards__`，`scheduler.on_node_completed`
> 检测到后调用 `instantiator.expand_dynamic(template, run, shards)` 追加 NodeRun 并入队。
> 已有节点 ID 保持不变，保证幂等重跑。

### 5.3 调度器职责边界

沿用 CubeClaw `TaskScheduler` 的四件事，但剥离 `DiskManager` 硬依赖：

```python
class Scheduler:
    def __init__(self, db, hooks: list[SchedulerHook] = ()): ...
```

`SchedulerHook` 是可选切面（`on_node_start` / `on_node_release` / `on_run_completed`），
`ResourceBudget`（原 DiskManager）与 `Notifier` 都以 Hook 形式接入，内核不感知它们存在。

---

## 6. 内核 B：Agent 会话与结果合同

这是 CubeClaw 最有价值、也最容易被低估的部分：**它让 LLM 的产出可被程序信任**。

### 6.1 AgentBackend 抽象

```python
class AgentBackend(Protocol):
    async def ensure_ready(self, workdir: str) -> AgentEndpoint: ...
    async def create_session(self, ep: AgentEndpoint, *, agent: str | None) -> str: ...
    async def send_prompt(self, ep, session_id: str, prompt: str) -> None: ...
    def stream_events(self, ep, session_id: str) -> AsyncIterator[AgentEvent]: ...
    async def reply_permission(self, ep, permission_id: str, approve: bool) -> None: ...
    async def abort(self, ep, session_id: str) -> None: ...
    async def dispose(self, ep) -> None: ...
```

内置实现：
- `opencode`（= 现 `agentcli serve`，直接复用 `cube/agentcli/client.py`）
- `claude_code` / 其他 CLI-agent（映射到同一事件流）
- `mock`（本地假执行，供前端联调与 CI）

`AgentEvent` 统一为 `{kind: text|tool|reasoning|step|idle|error, ...}`，
由各 backend 的 parser 归一化，上层 `session_runner` 完全不感知协议差异。

### 6.2 结果合同（原样保留，仅泛化字段）

节点下发前，编排器计算出结果文件路径与期望字段，写入 `*.meta.json`，
并把强约束前缀注入 prompt（沿用 `session_result_prompt_prefix` 的措辞，它已被实战打磨过）：

```jsonc
{
  "schema_version": 1,
  "node_run_id": "ab12cd34",
  "node_type": "digest",          // 原 task_type
  "skill": "novel-digest",
  "status": "running | success | failed | blocked | skipped",
  "success": false,
  "background_tasks": { "active": false, "pending_count": 0, "description": "" },
  "progress": { "done": 37, "total": 50 },   // ★ 新增：通用进度，前端直接画进度条
  "outputs": { /* 领域自定义，会被并入 ContextPatch（需在 contract.writes 声明） */ },
  "finished_at": "2026-08-07T09:00:00Z",
  "summary": "…"
}
```

内核校验（通用，所有领域生效）：
1. 文件存在、顶层是 object、`schema_version` 已知
2. `node_run_id` / `node_type` / `skill` 与 meta 一致
3. `status` 为终态才算完成；`running` + `background_tasks.active` → 继续等待并周期性 keepalive
4. `success=false` 必须带 `error` 或 `blocked_reason`
5. `outputs` 的 key 必须落在该节点 `NodeContract.writes` 内

领域校验（`ResultValidator` SPI，按 `node_type` 注册）：
例如 code_batch 的 `_validate_pick`（end-commit off-by-one 陷阱）原样迁入插件。

> **这套"只认文件不认 idle"的判定，是整个底座能无人值守的根本原因，必须原样保留。**

### 6.3 恢复与重试

沿用 CubeClaw 的三个机制，全部泛化为内核能力：

- **幂等跳过**：重跑前先读结果文件，若已是合法终态且 meta 一致 → 直接判成功，不烧 token
- **重试上下文注入**：`build_retry_prompt_prefix` 泛化，把前几次 Attempt 的
  `status/error/transcript_path/session_result` 摘要注入 prompt，要求 Agent 先做环境体检
- **产物兜底恢复**：`recover_*_session_result_if_possible` 泛化为 SPI
  `ResultRecoverer`：当 Agent 忘记翻转终态，但**声明产物已完整存在**时，由领域判断并合成终态

---

## 7. 内核 C：Workspace / 资源供给

### 7.1 WorkspaceProvider SPI

```python
class WorkspaceProvider(Protocol):
    kind: str  # "git-worktree" | "copy-dir" | "shared-dir" | "none" | 自定义

    async def prepare(self, req: WorkspaceRequest) -> WorkspaceHandle: ...
    async def snapshot(self, handle: WorkspaceHandle, label: str) -> WorkspaceHandle: ...
    async def release(self, handle: WorkspaceHandle, *, keep: bool) -> None: ...
    def estimate_size_gb(self, req: WorkspaceRequest) -> float: ...

@dataclass(frozen=True)
class WorkspaceRequest:
    run_id: str
    shard_index: int | None
    variant: str            # main / buildfix / readonly / reference:<name> …
    base_ref: str           # 领域语义：git ref / 目录快照 ID / 空
    readonly: bool = False
    labels: dict = field(default_factory=dict)
```

内置实现：

| kind | 用途 | 对应 CubeClaw |
|------|------|--------------|
| `git-worktree` | 共享 objects 的多工作区 | 现 `ensure_worktree` 全部 5 variant |
| `copy-dir` | 从模板目录复制（无 git 的领域） | — |
| `shared-dir` | 所有节点共用一个目录（只读参考资料） | 类似 `mcpe_netease_main` 的只读参照 |
| `none` | 节点不需要文件系统现场（纯 API 调用 / 纯 DB） | — |

`ensure_workspace` 成为**内核内置节点**，variant 由模板 params 指定，具体行为委派给
配置的 provider。CubeClaw 那 5 个 variant 类原样迁入 `domains/code_batch`，
作为 `git-worktree` provider 的 5 个 preset。

### 7.2 "多路参照系"泛化

CubeClaw 的四路 worktree（当前 / 上游当时 / 上一批次 / 权威实现）是**冲突解决的核心方法论**，
在其他领域同样成立：

- 网文剧情整理：当前章 / 前情提要 / 人物设定卡 / 已生成的时间线
- 批量翻译：原文 / 术语表 / 已翻译语料 / 风格指南
- 批量重构：改前 / 改后 / 参考实现 / 测试基线

因此底座把它提升为一等概念 **ReferenceSet**：

```python
@dataclass(frozen=True)
class ReferenceSpec:
    name: str          # "upstream_at_time" / "prev_batch" / "canon_setting"
    provider: str      # WorkspaceProvider.kind
    base_ref: str      # 表达式，可引用 context: "${run.cursor_end}^"
    readonly: bool = True
    description: str = ""   # ★ 会被注入 prompt，告诉 Agent 这份参照是干嘛的
```

`ReferenceSet` 在 Run 初始化时物化，路径与 description 一并注入每个 Agent 节点的 prompt。
Agent 因此天然获得"多路对比"能力，而不需要每个 skill 自己解释。

### 7.3 ResourceBudget（原 DiskManager，可选）

抽象为 `ResourceBudget` Hook：登记虚拟资源槽位、引用计数、超阈值时按策略淘汰
（FIFO / 二分保留 / LRU）。领域只需声明每种 workspace variant 的 `estimate_size_gb`
与保留策略。**无资源压力的领域直接不装这个 Hook**。

---

## 8. 内核 D：Item 台账、分片与规划

### 8.1 ItemSource SPI

```python
class ItemSource(Protocol):
    async def refresh(self, ws: WorkspaceRef) -> ItemLedgerSnapshot: ...
    async def resolve_frontier(self, ws: WorkspaceRef) -> str | None: ...

@dataclass
class ItemLedgerSnapshot:
    items: list[WorkItem]          # 按 seq 升序
    milestones: list[Milestone]    # 可选：可停靠边界
    frontier_item_id: str | None   # 已完成到哪
    meta: dict                     # 领域自定义（HEAD sha / 目录 mtime / 抓取时间）
```

实现举例：
- `code_batch`：`git log frontier..main` → WorkItem；`rXXuY` tag → Milestone
- `novel_digest`：扫描 `chapters/*.txt` → WorkItem（seq=章节号）；卷边界 → Milestone
- `paper_review`：读一个 CSV/JSONL 清单 → WorkItem

### 8.2 Sharder SPI

```python
class Sharder(Protocol):
    def suggest(self, items: list[WorkItem], ms: list[Milestone], cfg: dict) -> list[ShardPlan]: ...
    def validate(self, plan: list[ShardPlan]) -> list[str]: ...   # 返回警告
```

内核内置三种：
- `fixed_size`：每 N 项一片（= CubeClaw 默认）
- `milestone_aligned`：优先在 Milestone 边界切（= CubeClaw 的 split_suggestions）
- `weighted`：按 `WorkItem.payload` 中的权重字段（字数 / 改动行数 / 预估 token）均衡切分

前端规划页展示 `suggest()` 结果并允许手工调整每片数量——这套交互原样保留。

### 8.3 断点续传指针

CubeClaw 的 `bd/currentcommit.txt` 泛化为 `StateSeeder` 写入的
`<workspace>/.loom/cursor.json`：

```json
{ "run_id": "...", "shard_index": 1, "cursor_item_id": "ch_0413", "updated_at": "..." }
```

这是**文件系统层**的进度真相；数据库里的 NodeRun 状态是**编排层**的真相；
Agent 产出物是**业务层**的真相。三层各自独立可恢复，这是 CubeClaw 抗中断能力的来源，
底座原样继承并写进契约文档。

---

## 9. 内核 E：证据、审查与报告

### 9.1 ArtifactStore

```python
class ArtifactStore(Protocol):
    def path_for(self, run_id, shard_id, item_id, slot: str) -> str: ...
    async def put(self, ..., content: bytes | str) -> ArtifactRef: ...
    async def index(self, run_id: str) -> list[ArtifactRef]: ...
```

领域通过 `ArtifactSpec` 声明自己的 slot 与展示方式：

```python
EVIDENCE_SPEC = ArtifactSpec(
    slots=[
        Slot("prev",        label="冲突前本地",  view="code"),
        Slot("incoming",    label="上游意图",    view="code"),
        Slot("local",       label="本地实现",    view="code"),
        Slot("on_conflict", label="冲突原始态",  view="code"),
        Slot("resolved",    label="最终结果",    view="code"),
    ],
    default_view="diff-grid",     # 前端 EvidenceViewer 的布局模式
)
```

网文领域则可能是：

```python
DIGEST_SPEC = ArtifactSpec(
    slots=[
        Slot("raw",        label="原文",       view="prose"),
        Slot("summary",    label="剧情摘要",   view="markdown"),
        Slot("entities",   label="人物/地点",  view="json-table"),
        Slot("timeline",   label="时间线增量", view="json-table"),
        Slot("issues",     label="疑点/矛盾",  view="list"),
    ],
    default_view="tabs",
)
```

**前端 `EvidenceViewer` 只认 `ArtifactSpec`**，不认领域——这是让审查界面复用的关键。

### 9.2 Item-level Review

CubeClaw 的 Commit Review 界面本质是一个通用能力：
**「逐工作项展示：输入意图 → 实际产出 → AI 决策轨迹 → 机械化扫描发现 → 人工结论/批注」**。

底座提供的通用模型：

| 概念 | 说明 |
|------|------|
| `ReviewState` | 每个 item 一条：`unreviewed / pass / problem / defer` |
| `Finding` | 机械化扫描结果：`{code, severity, message, locator}`，由领域的 `Scanner` SPI 产出 |
| `Highlight` | 上浮到 Run 级的重点项（`auto / ai / expert` 三种来源） |
| `Annotation` | 人工批注，支持 item / run / ledger-item 三级 |
| `AiTrace` | 该 item 的 Agent 对话轨迹（含子 Agent），从 Attempt transcript 中按 item 索引切片 |

领域只需实现 `Scanner`（产出 Finding）与 `IntentDiffProvider`（左右对照的两侧内容），
就能白嫖整套审查界面。

### 9.3 Report 与记忆召回

`report` 节点通用化为：读取 Run 上下文 + 各节点 result + review 输出 → 产出
`report.json`（结构化，供后续 Run 召回）+ `report.md`（人读）。
底座提供 `MemoryIndex`：把历史 Run 的 report.json 按 `labels` / `item.payload` 建索引，
新 Run 的 prompt 中自动注入「相关历史决策」片段。

> 这一条在 CubeClaw 里是 `batch-report` skill 的隐含目标（"供后续批次召回"），
> 底座把它显式化为一个内核能力，因为几乎所有批量任务都需要「上一批怎么处理的」。

---

## 9b. 内核 F：运行时状态层（StateStore）

CubeClaw 的 `<batch>/temp/` 把**编排 meta、Agent 结果合同、skill 断点、业务产物、日志**
五类语义混在一个平坦目录里，路径靠字符串拼接散落在 6+ 处 handler 与 controller。
底座把这一层重新设计为 **StateStore**：

- **五层模型**：`control`（编排写） / `contract`（Agent 唯一被信任的写入口） /
  `scratch`（skill 草稿，可丢） / `artifact`（产物，append-only） / `log`（过程记录）；
  每层 owner、可变性、重跑语义、GC 策略各不相同。
- **坐标系 `StateKey`**：路径由 `(layer, scope, node_run_id, shard_id, item_id, attempt, slot)`
  纯函数生成，业务代码永不拼路径；人可读性由 `index.json` 承担。
- **Attempt 不可变**：每次尝试独立目录，`SkillSpec.retry_policy` 决定是否继承 scratch。
- **自描述 + 相对寻址**：每个对象带 `kind`/`schema_version`/`written_by`；内部路径全相对，
  整个 `state/` 打包即一份可离线审查的档案。
- **TaskCard**：编排把本次尝试的输入/参照/写入目标/成功判据写成结构化文件，
  prompt 收缩为一句"读 task_card 按其执行"。

> 完整设计（问题诊断、目录布局、原子写与并发规则、schema 迁移、GC/归档、
> 与 DB 的对账规则、`../temp` 逐项迁移映射）见
> **[`state_layer_architecture.md`](./state_layer_architecture.md)**。

---

## 10. 插件契约总表（Domain SPI）

一个领域插件 = 实现下面这个类，并在 `entry_points` 中注册。**除 `id` / `item_source` /
`executors` 三项外全部可选**，缺省走内核默认实现。

```python
class DomainPlugin(Protocol):
    id: str
    label: str
    version: str

    # ── 必需 ──
    def item_source(self) -> ItemSource: ...
    def executors(self) -> list[ExecutorSpec]: ...

    # ── 编排 ──
    def templates(self) -> list[DagTemplate]: ...          # 缺省: 线性 pipeline
    def node_handlers(self) -> list[NodeHandler]: ...      # builtin 节点实现
    def sharder(self) -> Sharder: ...                      # 缺省: fixed_size

    # ── Agent ──
    def skills(self) -> list[SkillSpec]: ...               # prompt 模板 + success_key + timeout
    def prompt_composer(self) -> PromptComposer | None: ...# 缺省: Jinja2 渲染 SkillSpec
    def result_validators(self) -> dict[str, ResultValidator]: ...
    def result_recoverers(self) -> dict[str, ResultRecoverer]: ...

    # ── 现场 ──
    def workspace_provider(self) -> WorkspaceProvider: ...  # 缺省: none
    def references(self) -> list[ReferenceSpec]: ...        # 多路参照系
    def state_seeder(self) -> StateSeeder | None: ...       # 写入 .loom/cursor.json 等

    # ── 审查 ──
    def artifact_spec(self) -> ArtifactSpec | None: ...
    def scanners(self) -> list[Scanner]: ...
    def intent_diff(self) -> IntentDiffProvider | None: ...

    # ── 前端 ──
    def web_manifest(self) -> WebManifest: ...   # 声明领域页面/面板的注册槽位与前端 bundle
```

### SkillSpec

```python
@dataclass(frozen=True)
class SkillSpec:
    key: str                # 与 ExecutorSpec.skill 对应
    skill_name: str         # Agent 侧 skill 名（prompt 里的 /xxx）
    prompt_template: str    # Jinja2；上下文 = NodeContext.values + run/shard/item 视图
    success_key: str        # session_result 中标志成功的字段名
    timeout: int = 14400
    requires: tuple[str, ...] = ()   # 需要的 context key，会并入 NodeContract.reads
    produces: tuple[str, ...] = ()   # 声明写入 outputs 的 key，并入 contract.writes
```

> Prompt 由三段拼成，顺序固定（沿用 CubeClaw 已验证的写法）：
> `[结果合同前缀] + [重试上下文(若有)] + [工作目录约束] + [SkillSpec 渲染结果] + [参照系说明]`

---

## 11. 前端底座

### 11.1 通用页面（领域无关，开箱即用）

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | Overview | 全部 Run 的状态卡片 + 近期事件流 |
| `/runs` | Run 列表 | 筛选 / 搜索 / 状态统计 |
| `/runs/:id` | **DAG Pipeline** | 画布 + 节点详情 + 运行配置 + 运行历史（= CubeClaw 主界面） |
| `/runs/:id/nodes/:nodeId` | Node 详情 | 依赖、context in/out、Attempt 列表 |
| `/attempts/:id` | **Attempt 实时流** | SSE：文本 / 工具调用 / 推理 / 进度（= `/tasks/:id`） |
| `/runs/:id/review` | **Item Review** | 列表 + 详情页签（Intent Diff / Evidence / AI Trace / Findings / Annotations） |
| `/ledger` | 工作项台账 | 全量 item + 状态 + 出现在哪些 Run + 专家意见 |
| `/planner` | 规划 | 台账进度 + Milestone 路线图 + 分片建议 + 手工调整 |
| `/templates` | DAG 模板管理 | 可视化编辑节点与边（已有 `DagTemplateManager`） |
| `/resources` | 资源 | ResourceBudget 视图（未启用则隐藏） |
| `/settings` | 配置 | Agent backend、并发、通知 |

CubeClaw 现有的 `DAGCanvas` / `NodeDetailPanel` / `RunHistoryPanel` / `useTaskStream` /
`CommitMapTable` / `EvidenceViewer` / `AnnotationPanel` 可以近乎原样搬运，
只需把 `commit` 相关字段换成 `item` 字段。

### 11.2 领域扩展机制：槽位注册

```ts
// web/src/sdk/domain.ts
export interface DomainModule {
  id: string
  label: string
  routes?: RouteObject[]                  // 追加的独立页面
  slots?: {
    runHeaderExtra?: React.FC<{ run: Run }>
    nodeDetailExtra?: React.FC<{ node: NodeRun }>
    itemRowExtra?: React.FC<{ item: WorkItem }>
    reviewDetailTabs?: ReviewTab[]        // 追加审查页签
    plannerPanel?: React.FC<{ ledger: Ledger }>
  }
  itemColumns?: ColumnDef<WorkItem>[]     // 台账表格的领域列
  artifactViews?: Record<string, React.FC<{ artifact: ArtifactRef }>>
}

registerDomain(codeBatchModule)
registerDomain(novelDigestModule)
```

后端 `GET /api/v1/domains` 返回已安装领域的 `web_manifest`，前端据此按需
`import()` 对应 bundle（Vite dynamic import + glob）。**未安装的领域零成本**。

### 11.3 SSE 与实时性

沿用 CubeClaw 的两级 SSE：
- 全局通道：Run/Node 状态变更、pipeline snapshot（带指纹去重，避免灌爆）
- Attempt 通道：Agent 事件流（文本增量、工具调用、进度）

前端 `useRunStream(runId)` / `useAttemptStream(attemptId)` 两个 hook 封装重连与背压。

---

## 12. 数据库 Schema

领域无关核心表（SQLite / 可切 Postgres）：

```
projects(id, name, description, config, …)
workspaces(id, project_id, name, domain_id, root_path, config, …)

runs(id, workspace_id, domain_id, template_id, status, lifecycle,
     items JSON, cursor_start, cursor_end, base_ref,
     config JSON, role, instance_id, candidate_id, timestamps…)

shards(id, run_id, index_num, generation, status,
       items JSON, base_ref, workspace_path, meta JSON)

node_runs(id, shard_id, run_id, node_key, node_type, generation, status,
          priority, dependencies JSON, payload JSON,
          result JSON,  -- 含 context_out
          error JSON, retry_count, max_retries, timeout_seconds, timestamps…)

attempts(id, node_run_id, attempt, status, runner, backend,
         session_id, prompt, context JSON, result JSON, error JSON,
         transcript_path, timestamps…)

-- 台账与规划
ledger_items(id, project_id, item_id, seq, title, payload JSON,
             status, first_seen_run, resolved_run, …)
milestones(id, project_id, name, boundary_item_id, status, …)
plans(id, project_id, snapshot JSON, suggestions JSON, refreshed_at)

-- 审查与产物
artifacts(id, run_id, shard_id, item_id, slot, path, meta JSON)
review_states(id, run_id, item_id, status, reviewer, updated_at)
findings(id, run_id, item_id, code, severity, message, locator JSON, source)
highlights(id, run_id, item_id, source, severity, status, message)
annotations(id, level, target_id, author, body, created_at)

-- 编排周边
dag_templates(id, domain_id, name, nodes JSON, edges JSON, version, is_default)
executors_cache(key, spec JSON)        -- 启动期注册表快照，供前端读取
agents(id, name, host, port, capabilities JSON, selectors JSON, status, …)
events(id, type, entity_type, entity_id, run_id, data JSON, created_at)
```

可选模块表（`run_lifecycle`）：`run_instances` / `run_candidates` / `tracked_refs` /
`rebase_requests`（在 code_batch 领域启用；网文领域不建表）。

**领域私有数据一律进 JSON 列或领域自建表（`<domain>_*` 前缀），核心表不加领域字段。**

---

## 13. HTTP API 表面

```
# Domains & Catalog
GET    /api/v1/domains                       # 已安装领域 + web manifest
GET    /api/v1/executors                     # 注册表快照（前端模板编辑器用）
GET    /api/v1/templates?domain=…            # DAG 模板 CRUD
POST   /api/v1/templates

# Ledger & Planning
GET    /api/v1/projects/:id/ledger           # 工作项台账（分页/筛选）
POST   /api/v1/projects/:id/ledger/refresh   # 触发 ItemSource.refresh
GET    /api/v1/projects/:id/plan             # 台账进度 + milestone + 分片建议
POST   /api/v1/runs                          # 从计划创建 Run（含分片覆盖）

# Run & DAG
GET    /api/v1/runs                          GET /api/v1/runs/:id
POST   /api/v1/runs/:id/schedule             # 展开 DAG 并入队
POST   /api/v1/runs/:id/cancel
POST   /api/v1/runs/:id/resume-from/:nodeId
GET    /api/v1/runs/:id/pipeline             # 前端画布数据
GET    /api/v1/runs/:id/events               # SSE

# Node & Attempt
GET    /api/v1/nodes/:id                     GET /api/v1/nodes/:id/context
POST   /api/v1/nodes/:id/retry|skip|block|force-success
GET    /api/v1/attempts/:id                  GET /api/v1/attempts/:id/transcript
GET    /api/v1/attempts/:id/stream           # SSE

# Review & Artifacts
GET    /api/v1/runs/:id/items                # 逐 item 的处理结果与状态
GET    /api/v1/runs/:id/items/:itemId/intent-diff
GET    /api/v1/runs/:id/items/:itemId/artifacts
GET    /api/v1/runs/:id/items/:itemId/trace
PUT    /api/v1/runs/:id/items/:itemId/review
GET/POST /api/v1/runs/:id/highlights | /annotations

# Ops
GET    /api/v1/agents                        POST /api/v1/agents/register|heartbeat
GET    /api/v1/resources                     # ResourceBudget（可选）
GET    /api/v1/config                        # 部署能力开关（can_run 等）
```

保持 CubeClaw 的两个好习惯：
1. **只读 GET 全部可在"审阅型部署"上工作**（`can_run: false` 时前端禁用所有执行入口）
2. **产物可打包下载**，把 `config + db + workspace` 整体交付给他人即可复现审查现场

---

## 14. 端到端示例：网文剧情整理

用来验证抽象是否真的通用。目标：**几千章原文 → 逐章剧情摘要 + 人物/地点实体 + 全局时间线 +
矛盾疑点清单 + 分卷总述**。

### 14.1 插件实现清单

| SPI | `novel_digest` 的实现 |
|-----|---------------------|
| `ItemSource` | 扫描 `chapters/*.txt`，`seq` = 章节号，`payload = {word_count, volume, title}`；Milestone = 卷边界 |
| `Sharder` | `weighted`，按 `word_count` 均衡切片（每片约 8 万字） |
| `WorkspaceProvider` | `shared-dir`（原文只读）+ `copy-dir`（每片一个产出目录） |
| `references()` | `canon`（人物设定卡目录）、`timeline_so_far`（上一片产出的时间线）、`style_guide` |
| `executors()` | `digest`（agent）、`entity_merge`（builtin）、`timeline_merge`（builtin）、`volume_summary`（agent）、`consistency_check`（agent）、`final_report`（agent） |
| `skills()` | `novel-digest` / `novel-volume-summary` / `novel-consistency` 三个 SkillSpec |
| `result_validators()` | 校验 `outputs.chapters_done == shard.item_count`，且每章 summary 非空 |
| `artifact_spec()` | 上文 `DIGEST_SPEC` 五 slot |
| `scanners()` | 机械扫描：摘要为空 / 出现未登记人物 / 时间线倒流 / 摘要长度异常 |
| `intent_diff()` | 左：原文节选；右：生成摘要 |
| `web_manifest()` | 追加 `/timeline` 页面 + 台账列（卷/字数/实体数） |

### 14.2 DAG 模板

```python
NOVEL_DIGEST_TEMPLATE = DagTemplate(
    id="novel_digest_default",
    domain_id="novel_digest",
    nodes=[
        NodeDef("init",            "ensure_workspace", Scope.RUN_ENTRY, params={"variant": "root"}),
        NodeDef("shard_ws",        "ensure_workspace", Scope.SHARD,     params={"variant": "shard"}),
        NodeDef("digest",          "digest",           Scope.SHARD,  priority=10),
        NodeDef("entity_merge",    "entity_merge",     Scope.SHARD,  priority=20),
        NodeDef("timeline_merge",  "timeline_merge",   Scope.SHARD,  priority=21),
        NodeDef("volume_summary",  "volume_summary",   Scope.SHARD,  priority=30),
        NodeDef("consistency",     "consistency_check",Scope.RUN,    priority=40),
        NodeDef("final_report",    "final_report",     Scope.RUN,    priority=50),
    ],
    edges=[
        EdgeDef("init", "shard_ws", EdgeKind.RUN_ENTRY_ALL),
        EdgeDef("shard_ws", "digest"),
        EdgeDef("digest", "entity_merge"),
        EdgeDef("digest", "timeline_merge"),
        # 时间线必须跨片串行（后片依赖前片的时间线状态）——与 pick 串行同构
        EdgeDef("timeline_merge", "timeline_merge", EdgeKind.SERIAL_PREV,
                maps={"prev_timeline_path": "timeline_path"}),
        # 实体表可并行合并，最后汇聚
        EdgeDef("entity_merge", "consistency", EdgeKind.ALL),
        EdgeDef("timeline_merge", "volume_summary"),
        EdgeDef("volume_summary", "consistency", EdgeKind.ALL),
        EdgeDef("consistency", "final_report"),
    ],
)
```

**注意这张图与 GlobalBatch 的拓扑同构**：
`digest ≈ pick`（分片内主循环）、`timeline_merge 的 SERIAL_PREV ≈ pick 串行 / build fix forward`、
`consistency ≈ final_review`、`final_report ≈ report`。
这正是抽象成立的证据——**拓扑模式是通用的，只有节点内容是领域的**。

### 14.3 复用到什么

零成本得到：DAG 画布与实时监控、断点续跑、失败重试与重试上下文注入、
结果合同判定、逐章审查界面（原文 vs 摘要对照 + AI trace + 机械扫描发现 + 批注）、
台账（哪章处理了、结论是什么）、跨 Run 记忆召回、通知。

需要写的只有：一个 `ItemSource`（约 60 行）、三个 SkillSpec（prompt 模板）、
两个 builtin NodeHandler（实体/时间线合并，纯确定性代码）、一个 Scanner、
一个前端时间线页面。

---

## 15. 从 CubeClaw 迁移的三阶段路线

**阶段 1：原地解耦（不动 CubeClaw 行为）**

1. 抽出 `loom_kernel`：把 `service/dag/*`、`executors/catalog.py`、
   `service/agentcli/base.py` 中的通用部分平移，删掉其中的 git/Minecraft 词汇
2. 引入 `spi.py`，把 `SKILL_SPECS` / `RESULT_VALIDATORS` / `ensure_worktree` variants /
   `global_planner` 改为通过注册表注入
3. `TaskType` 枚举 → 字符串 + 注册表校验；`platform` → `selectors`
4. 全程保持现有 API 路径与 DB 表名不变，只在内部改依赖方向。CI 加 import-linter 守边界

**阶段 2：CubeClaw 变成第一个领域插件**

5. 新建 `domains/code_batch`，把 GlobalBatch 的模板、skill、validator、worktree preset、
   planner、review scanner 全部搬进去
6. DB 迁移：表改名（`batches→runs` 等）走一次性 migration，历史数据保留
7. 前端拆分 `src/core` 与 `src/domains/code_batch`，引入 `registerDomain`
8. 验收标准：**跑一次完整 GlobalBatch，行为与迁移前逐节点一致**

**阶段 3：第二个领域验证抽象**

9. 实现 `domains/novel_digest`（或团队真实需要的第二个场景）
10. 凡是为了让第二个领域跑起来而不得不改内核的地方，都是抽象漏点，记录并回补 SPI
11. 产出《领域插件开发手册》与 `create-domain` 脚手架命令

> 阶段 3 是**抽象质量的唯一检验方式**。在第二个领域跑通之前，不要宣称底座已完成。

---

## 16. 非目标与已知取舍

**非目标**

- 不做通用工作流引擎（Airflow/Temporal 替代品）。Loom 的定位是
  「**面向 AI Agent 的批量分片编排**」，DAG 规模在几十到几百节点，单机 SQLite 足够
- 不做多租户与权限体系。默认单团队内网部署
- 不做 Agent 本身。Agent 能力由 backend（opencode / claude-code）提供

**已知取舍**

| 取舍 | 理由 |
|------|------|
| Items 存 Run 的 JSON 列而非独立表 | 一个 Run 的 item 数在千级，整体读写更简单；台账另有 `ledger_items` 表承担查询 |
| 结果合同用文件而非 HTTP 回调 | 文件天然幂等、可离线检查、Agent 侧实现门槛最低——这是 CubeClaw 实战验证过的选择 |
| 节点粒度 = 分片，而非单 item | 单 item 一个节点会让 DAG 爆炸到数千节点；分片内循环交给 Agent + 确定性 CLI 推进指针 |
| 上下文沿边合并而非全局黑板 | 并行冲突可被静态检测；黑板模型会让"谁写的这个值"不可追溯 |
| 前端领域扩展用槽位注册而非微前端 | 同仓构建、类型共享，复杂度低得多 |

---

## 附：核心设计原则（写给未来的自己）

1. **凡是能用代码写死的，绝不让 LLM 做。** Agent 只在需要语义理解的那一小块上决策
   （CubeClaw 的 gbcli 分工表是这条原则的最佳注脚）。
2. **只认结果文件，不认 idle。** Agent 说完话不等于干完活。
3. **现场三层可恢复**：业务层（产物）/ 文件层（cursor）/ 编排层（DB），任一层都能独立复原进度。
4. **节点必须通用，差异放在边上。** 用 `maps` 重映射，而不是在节点里 `if pipeline == …`。
5. **契约 fail-fast。** reads 缺 key、writes 未声明、并行写冲突，全部立刻报错，不做隐式兜底。
6. **可审查性是信任的前提。** 每个决策留证据、留轨迹、留人工结论，并沉淀回下一轮的输入。
