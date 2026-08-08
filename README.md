# Loom

Loom — Weave thousands of judgment calls into one pipeline you can trust.

Loom is a domain-agnostic orchestration foundation for batch AI-agent work: jobs too fuzzy for scripts and too big for humans. It shards your work items onto a declarative DAG, binds every agent session to a verifiable result contract, and makes every decision resumable, auditable, and reviewable — so a new domain only needs one plugin, not a whole new platform.

The Problem — 我们要解决什么

Some batch jobs are too fuzzy for scripts and too tedious for humans: cherry-picking hundreds of commits, digesting thousands of novel chapters, batch translating, refactoring, or reviewing papers. Every single item demands semantic judgment — yet the overall rules are clear and shouldn't keep burning human hours.

The Solution — 我们如何解决的

Loom splits the work into shards on a declarative DAG, drives AI agents through strict result contracts — trust the result file, not the chatter — and provisions isolated workspaces with multi-way references for every node. Resume-from-failure, retry with context injection, evidence packs, per-item review, and cross-run memory come built in. Whatever can be hardcoded in code never touches the LLM; the agent only decides the one slice that truly needs understanding.

What is Loom — Loom 是什么

Loom is a domain-agnostic batch agent orchestration foundation. Implement one small plugin contract — an ItemSource, a few skills, a validator — and you instantly get orchestration, agent sessions, observability, and review UI for free. No more rebuilding the same four layers of plumbing for every new batch domain.