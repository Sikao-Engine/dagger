# Loom 实施计划（任务拆分）

> 配套：`design/universal_base_architecture.md`（底座总体）、`design/state_layer_architecture.md`（状态层）、
> `design/domain_plugin_cookbook.md`（插件手册）。
> 本文只回答：**先做什么、怎么验收、谁依赖谁。**

---

## 0. 已锁定的前提

| 项 | 决定 |
|----|------|
| 工作名 | `loom` |
| 技术栈 | Python 3.12 + Litestar + SQLAlchemy + SQLite（uv workspace）；React + Vite + TS + shadcn/ui（pnpm） |
| 兼容 | **不考虑 CubeClaw 数据兼容**。全新设计，旧记录需要时另写一次性脚本 |
| 首个端到端领域 | `domains/tiny` —— 纯本地文件批处理，零外部依赖 |
| Agent 后端 | **协议可配置**。`AgentBackend` Protocol + 多实现：`mock`（测试）/ `opencode-http`（opencode serve 兼容）。配置项决定用哪个，内核不认识 opencode |
| 状态层 | 按 `state_layer_architecture.md` 五层模型实现，**先于一切业务代码落地** |

---

## 1. 里程碑总览

核心参考：F:/repos/ai/cube-claw

```
M0 工程骨架
 └─> M1 StateStore 内核 ──┐
 └─> M2 DAG 编排内核 ─────┼─> M4 CLI 端到端 walking skeleton（tiny domain）
 └─> M3 Agent 层 + 合同 ──┘        │
                                   ├─> M5 服务端（DB + 调度 + REST/SSE）
                                   │        └─> M6 前端底座
                                   └─> M7 审查/产物/GC 完善
                                            └─> M8 第二个领域验证抽象
```

**M4 是第一个"能给人看"的节点**：一条命令跑完一个多分片 DAG，产出完整 state 树。
M1–M3 可三线并行（互不依赖，只依赖 M0 的接口约定）。

---

## 2. M0 — 工程骨架

| ID | 任务 | 交付物 | 验收 |
|----|------|--------|------|
| T0.1 | uv workspace 初始化 | `pyproject.toml`（root workspace）+ `packages/{loom_kernel,loom_agent,loom_cli}/pyproject.toml` + `server/` | `uv sync` 通过；`uv run python -c "import loom_kernel"` |
| T0.2 | 质量闸门 | ruff（lint+format）、mypy strict（仅 `loom_kernel`）、pytest + coverage、`pre-commit` | `uv run ruff check . && uv run mypy packages/loom_kernel && uv run pytest` 全绿 |
| T0.3 | **依赖方向强制** | `importlinter` 契约：`loom_kernel` 不得 import `loom_agent`/`server`/`domains`；`server` 不得 import `domains.*` 具体模块（只经 SPI 注册表） | `uv run lint-imports` 通过 |
| T0.4 | **禁拼路径规则** | 自定义 ruff 插件或 pytest 扫描：`packages/`、`server/`、`domains/` 中除 `loom_kernel/state/layout.py` 外，禁止出现裸 `Path(...) / ` 拼 state 路径 | 违规样例被测试捕获 |
| T0.5 | 配置模型 | `loom.yaml` schema + `loom_kernel.config`（pydantic）：`data_dir` / `workspaces_dir` / `agent.backend` / `agent.<backend>.*` / `domains` | 缺字段给出可读错误；`loom config show` 打印解析结果 |
| T0.6 | 前端骨架 | `web/`：Vite + TS + Tailwind + shadcn init + 路由壳 + `pnpm build` | `pnpm build` 通过，空壳页面可访问 |

**M0 完成判据**：一条 `make check`（或 `uv run nox -s check`）跑完全部闸门。

---

## 3. M1 — StateStore 内核（内核 F）

> 独立子系统，**不依赖 DAG、不依赖 Agent**。这是整个底座的地基，必须先钉死。

| ID | 任务 | 交付物 | 验收 |
|----|------|--------|------|
| T1.1 | 坐标系 | `state/key.py`：`Layer` / `Scope` / `StateKey` / `K` 语义构造器 | `StateKey` frozen + hashable；非法组合（如 ARTIFACT+attempt）构造即报错 |
| T1.2 | **布局纯函数** | `state/layout.py`：`layout(key) -> PurePosixPath`，全仓唯一路径生成处 | 参数化单测钉死全部 20+ 种 key→路径映射；文件名安全化（item_id 含 `/`、超长、非 ASCII） |
| T1.3 | 信封与 schema 注册表 | `state/envelope.py` + `state/schema.py`：`register_schema` / JSON Schema 校验 / `normalize_envelope` | 写入非法 body 被 reject 并给出字段级错误；未知 kind 走宽松模式 |
| T1.4 | 原子写 | `state/io.py`：tmp+fsync+`os.replace`；jsonl O_APPEND 单行写 | 并发写同一 key 的压力测试无半截文件；Windows 下 `os.replace` 覆盖已存在文件通过 |
| T1.5 | StateStore 主体 | `state/store.py`：`path/read_json/write_json/write_bytes/open_scratch/latest_attempt/list` | 全 API 单测；只读模式（archive 加载）可用 |
| T1.6 | index + journal | `state/index.py`（entries + 分片 jsonl）、`state/journal.py` | `reindex` 从空 index 完全重建并与增量结果逐字节一致 |
| T1.7 | Attempt 隔离 | `RetryPolicy` FRESH/INHERIT/LINK + `begin_attempt()` / `LATEST` 指针 | 三种策略各自的 scratch 可见性单测；跨节点 scratch 不可见 |
| T1.8 | 相对寻址与 relocate | 内部记录全相对；`relocate(new_root)` | 把整个 `state/` 目录移动后所有 API 仍工作（含 index 校验） |
| T1.9 | GC / verify / archive | `state gc --layers` / `verify`（sha256 对账）/ `archive`→`.loomarc` / 只读加载 | GC 不触碰 contract/artifact；archive→解包→只读读取全部对象 |
| T1.10 | 契约文档 | `doc/contracts/state_objects.md` **由 schema 注册表自动生成** | CI 检查生成物与提交物一致 |

**M1 完成判据**：`pytest packages/loom_kernel/tests/state` 覆盖率 ≥ 90%，且能用 `loom state` CLI
对一个手工造出来的 state 树做 ls/cat/verify/gc/archive 全流程。

---

## 4. M2 — DAG 编排内核（内核 A）

> 概念沿用 CubeClaw 的 `dag/{template,instantiator,context,nodes/base}.py`，**重写而非拷贝**：
> 去掉 TaskType 枚举、去掉 platform 硬编码、Scope 增加动态分片。

| ID | 任务 | 交付物 | 验收 |
|----|------|--------|------|
| T2.1 | 模板模型 | `dag/template.py`：`NodeDef` / `EdgeDef` / `EdgeKind`(intra/run_entry/run_entry_all/serial_prev/last/all) / `DagTemplate` / 拓扑指纹 | 环检测、悬空边、重复节点名全部在 `validate()` 报错 |
| T2.2 | 节点契约 | `dag/node.py`：`NodeContract(reads/writes)` / `NodeHandler` / `NodeRegistry` | 未声明 read 缺失 → fail-fast；未声明 write → 拒绝 patch |
| T2.3 | 上下文 | `dag/context.py`：4 层优先级合并（run config → shard seed → 祖先 patch → node params）、`ContextConflictError` | 并行分支写同 key 冲突用例；`maps` 重映射用例 |
| T2.4 | 实例化 | `dag/instantiator.py`：模板 + 分片计划 → NodeRun 图；`selectors` 剪枝（取代 platform） | 3 分片 × 含 serial_prev/last/all 的模板生成图与期望快照一致 |
| T2.5 | 执行器注册表 | `executors/registry.py`：`ExecutorSpec(handler_kind, node_class, skill, variant_key, selectors)`，启动期注册 | 删掉硬编码枚举后仍能查询 scope/capability |
| T2.6 | 动态分片 | `Scope.SHARD_DYNAMIC` + `__shards__` 保留 patch key | 一个节点运行后动态展开 N 个下游分片的用例 |
| T2.7 | 内存执行引擎 | `engine.py`：拓扑推进、就绪计算、并发上限、失败传播、**每步把 node/context 写入 state control 层** | 用假 handler 跑完 20 节点图；中断后从 state 恢复继续 |

**M2 完成判据**：不依赖 DB、不依赖 HTTP，纯内存 + StateStore 即可跑完一个模板。

---

## 5. M3 — Agent 层与结果合同（内核 B）

| ID | 任务 | 交付物 | 验收 |
|----|------|--------|------|
| T3.1 | **AgentBackend Protocol** | `loom_agent/backend.py`：`ensure_ready/create_session/send_prompt/stream_events/reply_permission/abort/dispose` + 统一 `AgentEvent` | Protocol 上无任何 agentcli 字样；`agent.backend` 配置切换实现 |
| T3.2 | Mock 后端 | `backends/mock.py`：按脚本产出事件与结果文件，可注入失败/超时/背景任务 | 内核全部重试/校验/恢复逻辑均可用 mock 单测覆盖 |
| T3.3 | opencode-http 后端 | `backends/opencode_http.py`：`/session`、`/prompt_async`、`/event` SSE、`/permission/{id}/reply`、`/abort` + 进程守护 | 对本机 `agentcli serve` 冒烟通过；断流自动重连不丢事件 |
| T3.4 | SSE 归档 | 事件流 → `log/<node>/attempt-<n>/transcript.jsonl` | kill 进程后 transcript 仍是合法 jsonl |
| T3.5 | **TaskCard 生成** | `contract/taskcard.py`：输入/参照/写入目标/成功判据/上次失败 → `task_card.json` | prompt 中只出现一个路径；改布局零文案改动的回归测试 |
| T3.6 | 结果合同 | `contract/result.py`：schema、5 项内核校验、`ResultValidator` SPI 挂点 | 缺字段/判据未满足/写错位置 → 结构化拒绝原因 |
| T3.7 | 会话运行器 | `session_runner.py`：发 prompt → 等结果文件（**不信 idle**）→ 校验 → 重试（注入上次失败）→ 背景任务等待 | 幂等重跑跳过；超时/中止/背景任务三条路径各有用例 |
| T3.8 | Skill 规格 | `SkillSpec`：prompt 模板、`retry_policy`、超时、成功判据、artifact slots；固定 5 段 prompt 组装顺序 | 渲染快照测试 |

**M3 完成判据**：用 mock 后端跑通"发任务→Agent 写结果→校验失败→重试→通过"完整循环，
全过程产物落在 StateStore 正确的层。

---

## 6. M4 — CLI 端到端 walking skeleton ★

> **第一个可演示成果**：无 DB、无 HTTP，一条命令跑完 tiny domain。

| ID | 任务 | 交付物 | 验收 |
|----|------|--------|------|
| T4.1 | Domain SPI 注册 | `loom_kernel/spi.py` + entry_points 发现 + `loom domains` 列表 | 装/卸插件不改内核代码 |
| T4.2 | ItemSource / Sharder 内置 | `fixed_size` / `milestone_aligned` / `weighted` | 边界用例（不足一片、余数、空集） |
| T4.3 | WorkspaceProvider | Protocol + `copy-dir` / `shared-dir` / `none` 三个内置实现（`git-worktree` 留给 code_batch） | 现场准备/快照/释放 + `ReferenceSpec` 物化 |
| T4.4 | **domains/tiny** | 一批本地 txt → 每个文件产出摘要 slot；模板含"并行分片 + 串行累积 + 汇总"三种拓扑 | 插件代码 ≤ 200 行 |
| T4.5 | `loom run` CLI | `loom run --domain tiny --items ./data --shards 3`，含 `--resume` / `--dry-run` | 跑完产出完整 state 树；中途 Ctrl-C 后 `--resume` 接着跑 |
| T4.6 | 对账命令 | `loom state reconcile` 四条收敛规则 | 人为破坏（删 result / 改 index）后能被检出并正确收敛 |
| T4.7 | 端到端测试 | `tests/e2e/test_tiny_walkthrough.py`（mock 后端）+ 手动跑一次真实 agentcli | CI 中可重复；state 树结构快照断言 |

**M4 完成判据**：`loom run --domain tiny` 用 mock 与真实后端各跑通一次，
`loom state archive` 出的 `.loomarc` 能被只读加载并逐项查看。

---

## 7. M5 — 服务端

| ID | 任务 | 交付物 | 验收 |
|----|------|--------|------|
| T5.1 | DB 模型 | `projects/workspaces/runs/shards/node_runs/attempts/ledger_items/milestones/plans/artifacts/review_*/dag_templates/agents/events` + alembic | 建库/迁移/回滚脚本可跑 |
| T5.2 | 仓储层 | Repository（DB 只存 `run_id` + 相对 key，**不存绝对路径**） | 单测断言：任何写入路径列的值都是相对的 |
| T5.3 | 调度器 | `scheduler.py`：就绪计算、并发额度、`SchedulerHook`（资源预算等可选钩子） | 与 M2 引擎共用同一套就绪逻辑（不重复实现） |
| T5.4 | 任务执行器 | `runner.py`：取任务 → 准备现场 → TaskCard → Agent → 校验 → 落库 | 崩溃重启后按 state 恢复 |
| T5.5 | REST | runs / shards / nodes / attempts / templates / executors / domains / plan / state(index,object,journal) / items artifacts | OpenAPI 生成，契约测试 |
| T5.6 | SSE | 全局事件流 + run 级流 + node 级流 | 断线重连、背压、多客户端 |
| T5.7 | 事件与进度 | 统一 `Event` 模型；节点 progress 落 `log/progress.jsonl` 并广播 | 前端可仅凭 SSE 重建视图 |

---

## 8. M6 — 前端底座

> **设计基线**：cube-claw `dashboard/` 是同形态前端的成熟参照，但其 `pick/branch/commit`
> 字样、`@lib/data/commit_map`、`NODE_TYPE_ICON` 硬编码表均属领域私有，**不直接搬运**。
> 可借鉴的是「编排侧通用骨架」：`DAGCanvas`（xyflow + 拓扑分层布局）+ `PipelineNode`
> （状态色 + 动态节点标记）+ `useTaskStream`（history-then-SSE 双段式）+ `EvidenceViewer`
> （slot 网格 + diff 模式）+ `NodeDetailPanel`（侧栏 + resume/block/success 三动作）。
> 这五块的结构 + 交互原样迁移到 `web/src/core`，仅把 `commit_map`/`batch`/`pick`
> 数据层换成 `item`/`run`/`shard`/`node_run`。

### 8.1 工程与依赖

| 项 | 选择 | 理由 |
|----|------|------|
| 构建 | Vite 7 + React 19 + TS 5.9 + Tailwind 4 | 与 cube-claw 同栈，迁移成本最低 |
| 组件库 | shadcn/ui（Radix + cva） | cube-claw 已有完整 ui/ 目录可原样复用（39 个文件） |
| 画布 | `@xyflow/react` | cube-claw `DAGCanvas` 已验证分层布局 + MiniMap + 暗色 |
| 状态 | zustand（cube-claw 同款） | SSE 流式更新天然适合，无需 React Query 的请求缓存 |
| 表格 | `@tanstack/react-table` + `react-virtuoso` | 台账千行虚拟滚动，cube-claw 同款 |
| SDK 类型 | `openapi-typescript` | 纯类型输出，零运行时，CI 跑 `litestar schema → .ts` 校验漂移 |
| HTTP client | 手写 fetch wrapper（cube-claw 同款） | 不引入 codegen 框架，SSE 走 `EventSource`-like 手写流 |

**目录布局**（对齐 §4 设计的 `web/src/{core,domains,sdk}`）：

```
web/
├── package.json              # pnpm workspace（独立，pyproject.toml 已 exclude）
├── openapi.json              # CI 生成：litestar --print-openapi-schema
├── src/
│   ├── sdk/                  # 与后端零漂移
│   │   ├── types.gen.ts      # openapi-typescript 产物（commit 进仓，CI 校验）
│   │   ├── client.ts         # fetch wrapper：GET/POST + 错误归一化
│   │   ├── sse.ts            # 两级 SSE：useRunStream + useAttemptStream
│   │   └── domain.ts         # DomainModule 注册表 + 动态 import
│   ├── core/                 # 通用页面（领域无关）
│   │   ├── pages/            # overview / runs / runs/:id / attempts/:id / ledger / planner / templates / settings
│   │   ├── components/
│   │   │   ├── dag/          # DAGCanvas / PipelineNode / NodeDetailPanel / dag_utils
│   │   │   ├── run/          # RunHeader / RunConfig / RunHistory / ShardList
│   │   │   ├── attempt/      # AttemptTimeline / TranscriptView / ToolCallCard
│   │   │   ├── state/        # StateBrowser（layer/kind/item filter + object viewer）
│   │   │   ├── review/       # EvidenceViewer（ArtifactSpec 驱动）/ FindingList / AnnotationPanel
│   │   │   └── agents/       # ProcessManager（M5 phase 3 的 /agents/processes 消费）
│   │   └── store/            # zustand：server / runs / pipeline / planner
│   ├── domains/              # 领域面板（按 web_manifest 动态 import）
│   │   └── <id>/             # 各领域自定义 routes + slots + itemColumns + artifactViews
│   ├── lib/                  # utils / constants（cn 等，从 cube-claw 搬）
│   ├── ui/                   # shadcn 组件（从 cube-claw dashboard/src/components/ui 搬）
│   ├── App.tsx               # 路由壳 + domain registry 初始化
│   └── main.tsx
└── tests/                    # vitest + @testing-library（DOM 行为级）
```

### 8.2 任务拆分（一次性铺完，按依赖序）

| ID | 任务 | 交付物 | 验收 |
|----|------|--------|------|
| T6.1 | **工程骨架** | `web/` pnpm 工程 + Vite + TS + Tailwind + shadcn init + 路由壳 + `pnpm build` 通过 | `pnpm dev` 空壳可访问；`pnpm build` 产物可被 server 静态托管（可选） |
| T6.2 | **SDK 类型 + client** | `scripts/gen-openapi.ts`（拉 `/api/v1/schema` → `openapi.json`）+ `openapi-typescript` → `types.gen.ts` + `client.ts`（typed fetch） | `pnpm gen:sdk` 重生成后 `git diff` 为空（CI 校验）；缺字段编译报错 |
| T6.3 | **两级 SSE hook** | `useRunStream(runId)` + `useAttemptStream(attemptId)`：双段式（REST history → SSE tail）+ `Last-Event-ID` 重连 + drop-oldest 背压感知 | 断线 3s 内自动重连不丢 seq；attempt 流可仅凭 SSE 重建 transcript |
| T6.4 | **DAG 画布** | `DAGCanvas`（xyflow）+ `PipelineNode`（状态色/动态标记/优先级）+ `dag_utils`（拓扑分层布局 `layoutNodes`）+ `NodeDetailPanel`（侧栏 + resume/block/success 动作） | 从 `GET /runs/:id/pipeline` + `useRunStream` 实时更新节点状态；点击节点联动侧栏 |
| T6.5 | **Run 视图** | `/runs/:id`：DAG 画布 + RunHeader（状态/进度/计数）+ ShardList + RunHistory + RunConfig | SSE 推 `node.started/succeeded/failed` 时画布节点变色 + 计数刷新 |
| T6.6 | **Attempt 视图** | `/attempts/:id`：AttemptTimeline（text/reasoning/tool/step 分区）+ ToolCallCard + transcript 滚动跟随 + 进度条（`progress.done/total`） | 仅用 mock 后端跑通的 attempt 可完整回放；SSE 实时增量追加 |
| T6.7 | **State 浏览器** | `/runs/:id/state`：layer（control/contract/scratch/artifact/log）/ kind / item 三级 filter + index 表格 + 对象 JSON 预览 + journal 时间线 | 调 `GET /runs/:id/state` + `GET /runs/:id/state/object`；前端**零路径拼接**（路径全来自 index） |
| T6.8 | **台账 + 规划页** | `/ledger`（项目选择 + 分页 + status 筛选 + 领域列）+ `/planner`（进度统计 + Milestone 路线图 + 分片建议表 + 手工调片 + 创建 Run） | `GET /projects/:id/ledger` + `GET /projects/:id/plan` + `POST /projects/:id/ledger/refresh` + `POST /runs` 闭环 |
| T6.9 | **审查界面** | ✅ `EvidenceViewer`（`ArtifactSpec` 驱动：slot 网格 + tabs/diff-grid/stack 三布局 + diff 双槽 LCS 对比）+ `artifact-views.tsx` 七 renderer（prose/markdown/code/json/json-table/list/diff）+ `item-evidence.tsx` 页（item 选栏 + viewer）+ run-detail Evidence 入口 + 13 单测（dispatch + markdown 安全 + LCS diff） | tiny domain 声明 `summary`/markdown slot 即可展示（M7 T7.1 已后端就绪）；mock Run 跑完端到端看到种子化产物；spec drift（undeclared slot）琥珀边框可见 |
| T6.10 | **进程管理页** | `/agents`：`ProcessManager`（list + status + stop one/stop-all）+ 端口/pid/started_at 展示 | 消费 M5 phase 3 的 `GET /agents/processes` + `POST /agents/processes/{key}/stop` |
| T6.11 | **领域槽位注册** | `domain.ts`：`registerDomain(module)` + `GET /domains` 启动期拉 manifest → 按 `web_manifest` 动态 `import()` 对应 bundle；slot 槽位（runHeaderExtra/nodeDetailExtra/itemRowExtra/reviewDetailTabs/plannerPanel）+ itemColumns + artifactViews + 独立 routes | tiny domain 注册一个 `itemRowExtra`（显示 word_count 列）验证；未安装领域零成本（不 import） |
| T6.12 | **配置页 + 路由壳** | `/settings`（agent backend 切换 / 并发 / 通知）+ `/templates`（DagTemplateManager 可视化编辑节点边）+ App.tsx 路由聚合 + 侧边导航 | 全部路由可达；`can_run:false` 时禁用所有执行入口（对齐 §13 设计） |
| T6.13 | **测试 + CI 闸门** | vitest（DOM 行为级：SSE hook 重连 / 画布节点联动 / State 过滤 / 槽位渲染）+ `pnpm gen:sdk` 漂移校验脚本 + eslint + tsc --noEmit | `pnpm check` 全绿；SDK 重生成 `git diff` 为空 |

### 8.3 关键设计点

**SSE 双段式**（借鉴 cube-claw `useTaskStream`，泛化字段）：
```
useRunStream(runId):
  1. GET /runs/:id/pipeline            ← REST 快照（节点状态/计数）
  2. GET /runs/:id/events/stream       ← SSE 增量（node.started/succeeded/failed）
  3. Last-Event-ID 重连 ← 服务器有界 queue catch-up

useAttemptStream(attemptId):
  1. GET /attempts/:id/transcript      ← REST 历史（jsonl 数组）
  2. GET /attempts/:id/stream          ← SSE tail（运行中时）
```

**State 浏览器零路径拼接**（对齐 §4/T6.3）：
- `GET /runs/:id/state` 返回 `StateIndexEntry[]`（含 `path` 字段，来自后端 `layout()`）
- 前端只展示/过滤，**不构造路径**
- 看对象内容走 `GET /runs/:id/state/object?layer=...&node_run_id=...`（后端拼）

**领域槽位机制**（对齐 §11.2）：
```ts
// web/src/sdk/domain.ts
interface DomainModule {
  id: string; label: string
  routes?: RouteObject[]
  slots?: {
    runHeaderExtra?: FC<{run: Run}>
    nodeDetailExtra?: FC<{node: NodeRun}>
    itemRowExtra?: FC<{item: WorkItem}>
    reviewDetailTabs?: ReviewTab[]
    plannerPanel?: FC<{ledger: Ledger}>
  }
  itemColumns?: ColumnDef<WorkItem>[]
  artifactViews?: Record<string, FC<{artifact: ArtifactRef}>>
}
// 启动期：GET /domains → manifest → 按 id 动态 import
```

**从 cube-claw 搬运清单**（结构搬，数据层重写）：
| cube-claw 文件 | 去向 | 改动 |
|----------------|------|------|
| `dashboard/src/components/ui/*` (39 个) | `web/src/ui/` | 原样 |
| `dashboard/src/lib/utils.ts` | `web/src/lib/utils.ts` | 原样 |
| `dashboard/src/components/dag/DAGCanvas.tsx` | `web/src/core/components/dag/DAGCanvas.tsx` | `PipelineRun`→`PipelineOut`，`node_runs`→`nodes` |
| `dashboard/src/components/dag/PipelineNode.tsx` | 同上 | `NODE_TYPE_ICON` 表删，用 `node_type` 文本 |
| `dashboard/src/components/dag/dag_utils.ts` | 同上 | `layoutNodes` 原样，`STATUS_COLOR` 保留 |
| `dashboard/src/components/dag/NodeDetailPanel.tsx` | 同上 | 删 `branch_name`/`subbatch_*`，改调 `/nodes/:id/retry\|skip\|block\|force-success` |
| `dashboard/src/lib/sse/useTaskStream.ts` | `web/src/sdk/sse.ts` | `taskId`→`attemptId`，`/tasks/:id/messages`→`/attempts/:id/transcript` |
| `dashboard/src/lib/sse/parser.ts` | 同上 | 原样（opencode 协议归一化） |
| `dashboard/src/components/commit_map/EvidenceViewer.tsx` | `web/src/core/components/review/EvidenceViewer.tsx` | `EvidenceSource` 改为 `ArtifactSpec.slots` 驱动，5 路硬编码→动态 |
| `dashboard/src/components/commit_map/AnnotationPanel.tsx` | 同上 | `commit`→`item` |

### 8.4 DoD

1. `pnpm check`（tsc --noEmit + eslint + vitest + `gen:sdk` 漂移校验）全绿；
2. `pnpm build` 产物可被 `loom_server` 静态托管（或独立 dev server proxy 到 `:8000`）；
3. 用 mock 后端跑通：创建 Run → DAG 画布实时更新 → Attempt 流回放 → State 浏览器查看产物 → 审查界面展示 tiny 的 `ArtifactSpec`；
4. tiny domain 通过 `web_manifest` 注册一个自定义面板，**不写一行通用前端代码**即可在 `/runs/:id` 出现领域专属列；
5. 未安装领域（如 `novel_digest` 未装时）前端零报错、零额外 bundle。

---

## 9. M7 — 审查、产物与运维完善

| ID | 任务 | 交付 | 验收 |
|----|------|------|------|
| T7.1 | `ArtifactSpec` / `Slot` / `ArtifactStore` 正式化，item 维度产物一等化 | ✅ `loom_kernel/state/artifact_spec.py`（`Slot` + `ArtifactSpec` + `ArtifactStore` Protocol + `StateStoreArtifactStore` 适配器 + `group_refs_by_slot`）+ `spi.py` 类型化（`artifact_spec() -> ArtifactSpec \| None`）+ REST `GET /runs/{run_id}/items/{item_id}/artifacts` & `.../{slot}` 原始字节 + `DomainOut.artifact_spec` 内联 + tiny 声明 `summary` markdown slot + scheduler mock 按声明 spec 种子化产物 | kernel 9 单测 + server 6 集成测试全绿；`gen:sdk --check` 通过；前端 `EvidenceViewer` 仅消费 spec 不识领域（T6.9 实现） |
| T7.2 | `Scanner` SPI（产出 Finding）+ `IntentDiffProvider`（左右对照） | — | — |
| T7.3 | ReviewState / Highlight / Annotation 的 API 与前端闭环 | — | — |
| T7.4 | Report 节点 + `MemoryIndex`（历史 Run 决策召回注入 prompt） | — | — |
| T7.5 | `ResourceBudget` Hook（磁盘/并发额度），可选装 | — | — |
| T7.6 | 运维命令齐活：`gc / verify / archive / relocate / migrate` 全部接 server | — | — |

**T7.1 关键决策**：
- `KNOWN_VIEWS` 视图集合封闭（prose/markdown/code/json/json-table/list/diff/tabs/diff-grid），新视图必须同步前端 renderer，防领域发明 UI 无法渲染的 view。
- `ArtifactStore` 是 Protocol；`StateStoreArtifactStore` 是内核唯一实现。路径知识只留适配器内部（调 `K.artifact_item`），REST 与领域代码零路径拼接。
- `group_refs_by_slot` 把声明但未写入的 slot 暴露为 `ref: None`（UI 显示"缺失"），未声明的写入暴露为 `undeclared: true`（spec drift 立即可见）。
- 修复 `.gitignore` 历史问题：`state/` 全局规则误屏蔽 `packages/loom_kernel/src/loom_kernel/state/` 整个 M1–M6 内核模块（从未进仓）。改为 `/state/` 锁仓库根，并把 state 源码一次性补入 T7.1 提交。

---

## 10. M8 — 第二领域验证抽象

| ID | 任务 | 验收 |
|----|------|------|
| T8.1 | `domains/novel_digest`（章节摘要 + 时间线累积 + 一致性校验 + 总报告） | **内核零改动**即可跑通；若需改内核，改动点必须回写为新 SPI |
| T8.2 | 抽象回归报告 | 记录为了第二领域被迫修改内核的每一处，作为抽象质量的度量 |

> `domains/code_batch`（CubeClaw 迁移）排在 M8 之后，不进本轮计划。

---

## 11. 依赖与并行

| 阶段 | 可并行的线 |
|------|-----------|
| M0 后 | ① M1 StateStore ② M2 DAG 内核 ③ M3 Agent 层（用假 StateStore 接口打桩） |
| M4 | 必须 M1+M2+M3 全部就绪（收敛点） |
| M4 后 | ① M5 服务端 ② M7 产物/审查内核部分 |
| M5 后 | M6 前端 |

**关键路径**：M0 → M1 → M4 → M5 → M6。M2/M3 若滞后会阻塞 M4，需优先保 M1（其余两线都要写 state）。

---

## 12. 每个任务的完成定义（DoD）

一个任务算完成，必须同时满足：

1. 代码 + 类型标注齐全，`ruff` / `mypy` / `lint-imports` 全绿；
2. 单测覆盖核心分支，**失败路径也有用例**（不只测 happy path）；
3. 对外契约（Protocol / schema / CLI / HTTP）在 `doc/contracts/` 有对应条目，能自动生成的必须自动生成；
4. 不引入新的路径拼接、不引入新的硬编码枚举；
5. 若修改了 StateStore 布局或 schema，同步 bump 版本并补迁移。

---

## 13. 主要风险

| 风险 | 表现 | 应对 |
|------|------|------|
| 布局过早固化 | M1 钉死路径后 M4 发现不够用 | 布局纯函数 + 全量参数化单测，改动成本被压到"改一处 + 跑测试" |
| DAG 内核泛化过度 | 抽象层多到没人看得懂 | 以 tiny domain 的三种拓扑为准绳，写不出用例的泛化一律不做 |
| Agent 协议差异 | 换后端时语义对不齐（权限、背景任务、中止） | Protocol 层定义统一 `AgentEvent` 语义 + 一套后端一致性测试套件，新后端必须过 |
| 前端与后端契约漂移 | 改字段忘了同步 | OpenAPI → TS 类型生成进 CI |
| 双份就绪逻辑 | M2 内存引擎与 M5 调度器各写一套 | T5.3 明确共用 M2 的就绪计算，服务端只加持久化与并发额度 |

---

## 14. 建议的开工顺序

1. **T0.1–T0.5**（半天到一天）：先把闸门立起来，尤其是 T0.3/T0.4 两条强制规则——它们是这次重构不重蹈覆辙的保险丝。
2. **T1.1–T1.5**：StateStore 主干。这一段做扎实，后面所有模块都在它上面写。
3. 之后按 M1 剩余 / M2 / M3 三线推进。
