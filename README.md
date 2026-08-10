# Dagger

Dagger — Weave thousands of judgment calls into one pipeline you can trust.

Dagger is a domain-agnostic orchestration foundation for batch AI-agent work: jobs too fuzzy for scripts and too big for humans. It shards your work items onto a declarative DAG, binds every agent session to a verifiable result contract, and makes every decision resumable, auditable, and reviewable — so a new domain only needs one plugin, not a whole new platform.

The Problem — 我们要解决什么

Some batch jobs are too fuzzy for scripts and too tedious for humans: cherry-picking hundreds of commits, digesting thousands of novel chapters, batch translating, refactoring, or reviewing papers. Every single item demands semantic judgment — yet the overall rules are clear and shouldn't keep burning human hours.

The Solution — 我们如何解决的

Dagger splits the work into shards on a declarative DAG, drives AI agents through strict result contracts — trust the result file, not the chatter — and provisions isolated workspaces with multi-way references for every node. Resume-from-failure, retry with context injection, evidence packs, per-item review, and cross-run memory come built in. Whatever can be hardcoded in code never touches the LLM; the agent only decides the one slice that truly needs understanding.

What is Dagger — Dagger 是什么

Dagger is a domain-agnostic batch agent orchestration foundation. Implement one small plugin contract — an ItemSource, a few skills, a validator — and you instantly get orchestration, agent sessions, observability, and review UI for free. No more rebuilding the same four layers of plumbing for every new batch domain.

## How to start

```bash
uv sync
```

### 打开一个工作区（以 novel_digest 为例）

```bash
# 1. 安装 Agent 侧 skill 到 ~/.agents/skills（--dest 可换 agent CLI 的目录）
uv run domains/novel_digest/install.py
# 2. 把确定性 CLI 装上 PATH（任何目录可用）
cd domains/novel_digest/noveltool && uv tool install -e . && cd -
# 3. 编译前端 → web/dist
cd web && pnpm install && pnpm build && cd -
# 4. 复制 config.example.toml，把 workspace 指向你的书目录，然后启动
cp config.example.toml my-dagger.toml
uv run server/main_server.py -c my-dagger.toml   # http://127.0.0.1:8000
```

详见 `doc/plan/novel_digest_acceptance.md` §0.5。

