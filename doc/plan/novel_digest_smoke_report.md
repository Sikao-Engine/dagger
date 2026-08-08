# novel_digest 冒烟验收报告（M-A 等价 + 内核完备性验证）

> 日期：2026-08-08。执行范围：冒烟实现 `novel_digest` 第二领域，并以它为试金石验证/加固 loom kernel。
> 验收基线文档：`doc/plan/novel_digest_acceptance.md`；设计基线：`doc/design/universal_base_architecture.md` §14。

---

## 1. 范围声明

本次交付 = **M-A 等价级**（含 `loom run --domain novel_digest --backend mock` 真实 CLI 跑通）
+ **内核完备性验证**（每一处「内核实现不当/缺失」按判定三问确认后直接修了内核，逐条登记 §3）。

**未做**（等用户全流程验收）：M-B 真实 LLM、M-C/M-D 真实数据跑批与 kill 续跑、M-E 长时压测、
前端 `pnpm dev` 手点验收、`loom state archive` 的 `.loomarc` 只读加载验收。

测试口径：全仓 `uv run pytest -q` = **289 passed**（基线 182 → +107）；内核 `mypy --strict` 全绿；
`ruff check .` / `ruff format --check .` 全绿；import-linter 两合同 kept。

---

## 2. 判据映射表

### Step 1 — 物化数据契约

| 判据 | 状态 | 证据 |
|------|------|------|
| 完整 chapter.json 通过 schema 校验（SCHEMA_REGISTRY） | ✅ 自动化 | `domains/novel_digest/tests/test_schemas.py::TestChapterSchema::test_valid_chapter_passes` |
| 缺字段被拒绝并给出字段级错误 | ✅ 自动化 | `test_schemas.py::test_missing_field_rejected_with_field_level_error`（错误含字段名）|
| schema 进 `doc/contracts/` 自动生成流程 | ✅ 自动化+手动 | `scripts/loom_check.py contracts` 现加载领域 schema（K7）；产物含 `novel_chapter`/`novel_volume_summary`/`novel_consistency_report`；连续两次执行产物 sha256 一致 |

### Step 2 — 画 DAG 拓扑

| 判据 | 状态 | 证据 |
|------|------|------|
| 模板 `validate()` 通过 | ✅ | `test_template.py::TestTemplateShape::test_validate_passes` |
| 每条边能说出为什么 | ✅ | `templates.py` 模块 docstring 逐边注释；§14.2 逐字照抄（仅 init 节点 params 注入 workspace_root，见 §4 张力 1）|
| `template.fingerprint` 稳定 | ✅ | `test_template.py::test_fingerprint_stable` |
| 8 节点 9 边 / SERIAL_PREV+maps / 两条 ALL / run 级 INTRA | ✅ | `test_template.py` + `TestTemplateInstantiation`（K1 生效的直接证据）|

### Step 3 — SkillSpec

| 判据 | 状态 | 证据 |
|------|------|------|
| success_key 可机器验证 | ✅ | `test_skills.py::test_success_key_machine_verifiable`（每个 skill 的 `*_ok=true` 写入 prompt 文本）|
| inclusive 边界显式 | ✅ | `test_inclusive_boundary_explicit`（`shard.last_item.id` 引用 + 渲染文本含 inclusive 句）|
| 禁止动作显式 | ✅ | `test_forbidden_actions_explicit` |
| 参照系路径+用途 | ✅ | `test_reference_purpose_stated`（canon 是"权威"，非裸路径）|
| 产物路径+schema 指针 | ✅ | `test_artifact_path_and_schema_pointer`（按 kind 名指针，无内联 schema）|
| requires/produces 声明 | ✅ | `test_requires_produces_declared` |
| 渲染快照逐字节稳定 | ✅ | `TestRenderSnapshots`：四个 skill 的完整渲染文本作为常量钉在测试里，可 diff |

### Step 4 — noveltool

| 判据 | 状态 | 证据 |
|------|------|------|
| status 空/处理中/全完成三态，字段稳定 | ✅ | `test_noveltool.py::TestStatus`（字段集断言）|
| next 幂等 | ✅ | `TestNext::test_next_is_idempotent_per_chapter`（二次执行零副作用：产物与指针字节不变）|
| fill 坏文件退出码 3 + 字段级错误 | ✅ | `TestFill::test_fill_bad_file_exit_3_with_field_errors` |
| check 时间线倒流退出码 2 | ✅ | `TestCheck::test_check_timeline_regression_exit_2` |
| JSON 输出 + 退出码 0/1/2/3 + 幂等 | ✅ | 全部经 `loom_cli.scaffold` 契约；`next` 语义：当前章未 fill 前不推进指针（崩溃不会跳章）|

### Step 5 — 审查配置

| 判据 | 状态 | 证据 |
|------|------|------|
| Scanner 覆盖三类（空产物/schema 不完整/跨项一致性） | ✅ | `test_scanners.py`（5 个 Scanner，含 timeline_regression 跨项）|
| 每个 Scanner 对造坏 item 报一条 Finding 且 severity 正确 | ✅ | `TestScannerFindings` 逐钉 |
| artifact_spec 五 slot 前端可渲染 | ⏳ 部分 | slot 名与 `K.artifact_item` 坐标一致（`test_plugin.py`）+ view 均为 KNOWN_VIEWS（内核构造即校验）；`pnpm dev` 手点属全流程 |
| intent_diff 两侧可取 | ✅ | `test_plugin.py::test_intent_diff_both_sides`（左=原文节选，右=摘要）|

### M-A（单章 dry-run 等价）

| 判据 | 状态 | 证据 |
|------|------|------|
| `loom run --domain novel_digest --items <dir> --shards N --backend mock` 跑完无错 | ✅ | `packages/loom_cli/tests/test_main.py::TestRunNovelDigest::test_mock_run_end_to_end`（退出码 0）+ 手动冒烟（§5 命令）|
| state 树符合 §14.3（control/items + contract/result + artifact slot） | ✅ | `test_walkthrough.py::test_full_run_two_shards` 逐项断言；CLI 测试断言 `control/items/<id>/item.json` |
| `loom state ls --layer artifact` 看到 slot | ✅ 替代 | walkthrough 断言 `store.query(layer="artifact", slot="summary")` 可取回（同一索引路径；`loom state` CLI 即该 query 的薄壳）|
| EvidenceViewer 展示 summary slot | ⏳ 待全流程 | 前端手点（M5 server 的种子化路径未动）|
| `.loomarc` 只读加载 | ⏳ 待全流程 | 用户验收 |

### §3 上线清单（机器可验证部分）

| 判据 | 状态 | 证据 |
|------|------|------|
| 每节点 reads/writes 声明 + dry-run 校验 | ✅ | builtin 契约 fail-fast（`test_nodes.py`）；`loom run --dry-run`（CLI 测试）|
| ResultValidator 覆盖 off-by-one（漏章） | ✅ | `test_walkthrough.py::test_validator_catches_missed_chapter`（K3 真跑真拦截）|
| 并行分支写同名 key 不冲突 | ✅ | 内核 `TestParallelWritesRule`（等值合并/异值抛错）+ walkthrough 全程无 ContextConflictError |
| 幂等跳过零派发 | ✅ | walkthrough 二次 `run_graph` 派发计数为 0 |

---

## 3. 内核回归表（核心章节）

> 同步登记于验收文档 §4。判定三问（被判据直接强制？通用能力？可配自动化测试？）逐条答案均为「是」。

| # | 内核文件 | 修改原因（强制判据） | 回写形态 | 后续去向 |
|---|---------|---------------------|---------|---------|
| K1 | `dag/instantiator.py` | Step 2 照抄 §14.2：`consistency→final_report` 为 run 级 INTRA，原实现只认 SHARD 两端 | INTRA 支持两端同属 {RUN, RUN_ENTRY}；混用仍抛 `InstantiateError` | 语义已通用化，无后续 |
| K2 | `dag/nodes/ensure_workspace.py`（新）+ `spi.py` | Step 2 / 设计 §6：`ensure_workspace` 是内核内置节点但全仓无实现 | 内建节点（root/shard 两 variant，local-dir 最小语义）；`KERNEL_EXECUTORS` + `contribute_to` 先内建后领域（领域可覆盖同名 key，已文档化） | WorkspaceProvider 全 SPI（git-worktree/copy-dir/snapshot/release/ResourceBudget）留后续项 |
| K3 | `engine.py` + `spi.py` | §3 清单 + 设计 §5.2-5：outputs ⊆ produces 与 ResultValidator 无任何一层执行 | `run_graph(skills=, validators=)` 入参；违规走既有重试/失败路径；`ResultValidator` 协议补可选 `context`（含 shard 视图，供漏章校验） | server 调度路径接线留后续项 |
| K4 | `engine.py::_resolve_context` | Step 3 / cookbook：`{{ shard.item_count }}`/`{{ shard.last_item.id }}` 无值 | shard 视图充实（item_count/items/first_item/last_item），shard_seed 补 item_count | 语义已通用化 |
| K5 | `review.py`（新）+ `spi.py` | Step 5：`scanners: list[Any]` 无类型占位、无 intent_diff 钩子 | `Finding`/`ScanContext`/`Scanner`/`IntentDiffProvider` 最小 SPI；`DomainPlugin.intent_diff()`/`mock_outputs()`；`scanners: list[Scanner]` | T7.2/T7.3（ReviewState/Highlight/Annotation）落地点 |
| K8 | `engine.py::_propagate` | walkthrough 直接强制：原实现把分片节点的输出**广播到全部片**的目标实例，与 INTRA（本片）/SERIAL_PREV（下一片）语义矛盾；digest 的 `chapters_done` 分片异值必然误报 `ContextConflictError` | 缺陷修复：按 edge kind 定向投递（INTRA 同片 / SERIAL_PREV 下一片 / LAST 仅末片 / ALL 汇聚单实例 / RUN_ENTRY(_ALL) 扇出） | 语义校正，无后续 |
| K6 | `loom_cli/main.py`（宿主） | M-A 判据 1：CLI mock 路径 tiny 专用且带 bug | 修 `parents[4]` 路径 bug（计划原文 parents[3] 有误，实际指向 `packages/`）、本地域泛化加载（目录名=包名）、mock 通用化、传 skills/validators、修 `reg.templates()` 误调用与 `die()` 不退出两个潜在 bug | server 侧 mock 种子化已另有 `_seed_mock_artifacts` |
| K7 | `scripts/loom_check.py`（宿主） | Step 1：领域 kind 不进合同文档 | best-effort 导入 `<pkg>.schemas` 后生成 | 无 |

**「内核零改动跑通了吗？」——没有。** 共 6 处内核改动（K1–K5、K8）+ 2 处宿主修复（K6、K7）。
逐条论证「通用能力」：K1/K2/K8 是拓扑与上下文创播语义（任何含 run 级收口链/串行链的领域都会踩中，
CubeClaw 的 GlobalBatch 拓扑同构）；K3/K4 是结果合同与 prompt 上下文合同（设计 §5.2 与 cookbook
早已承诺但实现缺位）；K5 是审查 SPI（设计 §8.2 承诺的 Finding/Scanner/IntentDiff）。无一处为
novel_digest 私有需求进内核——领域私有的（章节扫描、prompt、合并逻辑、noveltool、scanner 规则）
全部留在 `domains/novel_digest/`。

按验收文档 §4 的回归判据：这不是「每跑一个里程碑就改一次内核」的无限补丁，而是**一次性把设计已承诺
但实现缺位的内核能力补齐**；六处改动各自带测试钉死，后续领域（code_batch）应能零内核改动复用——
这将是抽象收敛性的下一次度量点。

---

## 4. 设计张力记录

1. **ensure_workspace 双 variant 共用一个 node_type**：contract 只能取并集
   （`writes=("workspace_root","run_out_dir","shard_out_dir")`、`reads=()`），shard variant 对
   `run_out_dir` 的依赖在运行期 fail-fast（ContractError）而非静态声明。后续可用
   `ExecutorSpec.variant_key` 的 `<executor>:<variant>` 多实现拆分 contract。
   另：`ExecutorSpec.scope` 无法表达「RUN_ENTRY 与 SHARD 皆可用」，内核 spec 暂记 `scope="any"`
   （该字段当前仅展示用途，无校验消费方）。
2. **digest 回传工作区坐标**：上下文沿边流动 + §14.2 照抄（不加边）的前提下，同片下游节点
   （entity_merge/timeline_merge）只能通过 digest 的 outputs 回传拿到 `shard_out_dir` 等坐标。
   这被写成 prompt 里的显式纪律（回传值与下发值不一致 = 在错误现场作业），属于可机器校验的
   工作区纪律，但确实让 agent 的 produces 带上三个「管线味」key。替代方案（TaskCard 携带
   workspace 坐标，server 侧已有其 schema）属 M5+ 全流程范畴。
3. **volume_summary 拿不到 shard_out_dir**：§14.2 的入边只有 `timeline_merge → volume_summary`，
   其 prompt 只引用 `ctx.timeline_path`（可满足）。mock 不需要文件；真实 Agent 若需读片产物，
   需要 TaskCard 或额外 maps——记为模板设计张力，不在冒烟期改模板（照抄优先）。
4. **`mock_outputs` 的定位**：测试亲和 SPI——mock 数据的形状是领域知识，宿主（CLI/测试）
   只认钩子不认领域。CLI mock 与域 walkthrough 共用同一钩子（R4），两条验证路径一致。
   缺省 None 时宿主按 `produces ∪ {success_key}` 合成 `{k: True}`（对 tiny 完全等价）。
5. **CLI 分片提示是近似的**：`--shards N` 经 `WeightedChapterSharder` 折算 target_weight≈total/N，
   加权切分为近似算法，5 章小样例 `--shards 2` 实际切 3 片。判据只要求「跑完无错」，符合；
   真实数据的片数调参属 M-C/M-D。
6. **StateSeeder / prompt_composer / result_recoverers 未接线**：spi.py 的占位钩子保持原样；
   noveltool 的 `<out>/pointer.json` 与设计 §7.3 的 `.loom/cursor.json` 对齐留后续项（D10）。
7. **executor key 未命名空间化**：为照抄 §14.2，`digest`/`entity_merge` 等用裸 key（非
   `novel.digest`）。ExecutorCatalog 全局唯一，多域同装时有撞名风险——后续可考虑模板侧
   node_type 前缀化或 catalog 按域分区。

---

## 5. 如何复验

```bash
uv sync
# 全量测试（289 passed：内核 131 + loom_agent 37 + CLI 7 + tiny 2 + novel_digest 68 + server 44）
uv run pytest -q
# 质量门槛
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/loom_kernel/src
.venv/Scripts/lint-imports.exe
# 合同文档（二次执行 git diff 应为空）
uv run python scripts/loom_check.py contracts
# 前端类型检查
web\node_modules\.bin\tsc.CMD --noEmit -p web\tsconfig.app.json   # 仓库根执行时用 -p web/tsconfig.app.json
# 手动冒烟（在任意临时目录执行）
uv run python -m novel_digest.testing <tmp>\book --chapters 5
.venv\Scripts\loom.exe domains                                     # 列出 tiny + novel_digest
cd <tmp> && <repo>\.venv\Scripts\loom.exe run --domain novel_digest --items <tmp>\book --shards 2 --backend mock
# 期望：completed=18 failed=0 skipped=0，退出码 0；state 树在 <tmp>\.loom\<run_id>\state
<repo>\.venv\Scripts\noveltool.exe status --root <tmp>\book --out <tmp>\book\<run_id>\shard-000
```

## 6. 已知限制与后续项

- server 调度路径未传 skills/validators（`scheduler.py` 的 mock/real 派发未接 K3）——接线留后续项，
  冒烟验证载体是内核 engine + CLI。
- WorkspaceProvider 全 SPI（git-worktree/copy-dir/snapshot/release/ResourceBudget）未做。
- EvidenceViewer 种子化属 server `_seed_mock_artifacts`（M5+ 全流程验证）；冒烟只验证 spec 注册 +
  slot 坐标一致 + mock 写 summary slot 可 query 取回。
- StateSeeder/prompt_composer/result_recoverers 钩子未接线；`.loom/cursor.json` 与 noveltool
  `pointer.json` 的对齐留后续项。
- 前端 `pnpm dev` 手点（时间线页 / 台账列 / 审查 tab）待全流程；tiny 的前端 bundle 缺失未补
  （不动 tiny，仅记录）。本机 pnpm 不在 PATH，前端验证改用 `web\node_modules\.bin\tsc.CMD
  --noEmit` 直接跑（全绿）。
- weighted 分片在真实章节数据上的片数调参（M-C/M-D）。

## 7. 给用户的全流程验收清单

按验收文档 §2 的 M-A→M-E 路径推进：

1. **M-A 复验**：跑 §5 的手动冒烟命令；检查 `<tmp>\.loom\<run_id>\state` 的五层树；
   `loom-state ls --run <run_root> --layer artifact`（artifact 层需先经 server mock 种子化或
   walkthrough 写入）；前端起 `pnpm -C web dev` 打开 EvidenceViewer。
2. **M-B**：起 opencode 兼容后端，`loom run --domain novel_digest --backend opencode-http`
   单章跑通；单节点 `noveltool next/fill/check` 手验；kill 续跑看 cursor。
3. **M-C**：单片 5–10 章，验证 `prev_timeline_path` 串接与 `--resume` 幂等跳过。
4. **M-D**：3 片 × 5 章真实数据，看 ALL 汇聚时点 + Scanner 全套 + final_report 产物。
5. **M-E**：全本长时跑 + 3 次以上中断续跑 + `loom state verify` 全绿 + `can_run: false` 审阅部署。
