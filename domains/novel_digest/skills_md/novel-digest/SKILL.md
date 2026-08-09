---
name: novel-digest
description: 逐章摘要 + 实体抽取 + 时间线增量。Use when: 收到 /novel-digest 指令，需要处理一个分片内的连续章节（Loom novel_digest 领域的主链 agent 节点）。
---

# novel-digest — 分片逐章消化

处理本分片的全部章节（区间两端 **inclusive**，首末两章本身也要处理）。
指针由 `noveltool` 推进，你只处理"当前这一项"，不要自己决定遍历顺序。

## 输入

- 原文目录：`<workspace_root>/chapters/*.txt`（**只读**，禁止修改）。
- 产出目录：`shard_out_dir`（prompt 下发，逐章产物与指针都落在这里）。
- 参照系：`refs.canon.path` 是人物设定权威，实体命名冲突时以它为准。

## 流程

1. `noveltool status --root <workspace_root> --out <shard_out_dir>` 查看当前指针与剩余章数。
2. `noveltool next --root <workspace_root> --out <shard_out_dir>` 推进一章，读出本章原文路径。
3. 阅读本章，生成产物 JSON（summary / entities / timeline_delta / digest_ok 四段齐全，
   schema kind：`novel_chapter`）。新出现的实体必须显式写出 `first_seen_chapter`。
4. `noveltool fill <chapter_id> --file <产物.json> --root <workspace_root> --out <shard_out_dir>` 回填并校验。
   退出码非 0 时按 JSON 里的字段级错误修正后重填。
5. 重复 1–4 直到 `noveltool status` 输出 `all_done=true`。
6. 写 session_result 终态：`digest_ok=true`，`outputs.chapters_done` 必须等于本分片章数（少一章即漏章），
   并原样回传 `shard_out_dir` / `run_out_dir` / `workspace_root`（下游节点靠这份回传寻址）。

## 边界与禁忌

- 时间线只写本片增量；跨片累积由 timeline_merge 节点负责，不要读其他分片的时间线。
- 不要把产物写到 `shard_out_dir` 以外；不要写时间线以外的全局状态。
- 单章 LLM 判断不稳时（人物同一性存疑、时间线锚点缺失），在产物的 `issues` 字段标注，不要静默跳过。
