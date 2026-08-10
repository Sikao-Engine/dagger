---
name: novel-volume-summary
description: 分卷总述。Use when: 收到 /novel-volume-summary 指令，本片时间线已累积完成，需要为一卷（连续章节区间）写总述（Dagger novel_digest 领域的侧链 agent 节点）。
---

# novel-volume-summary — 分卷总述

为本卷（章节区间两端 **inclusive**）写一段总述。

## 输入

- 本片累积时间线：`timeline_path`（prompt 下发，已含前片串行累积结果）。
- 本片逐章产物：`shard_out_dir` 下的 `<chapter_id>.json`。
- 参照系：`refs.canon.path` 用于核对人物称谓一致性，冲突以它为准。

## 流程

1. 读 `timeline_path` 与本片逐章产物的 summary 段。
2. 写 `volume_summary.json` 到本片产出目录，schema kind：`novel_volume_summary`。
3. 写 session_result 终态：`volume_ok=true`。

## 边界与禁忌

- 不要改动任何逐章产物；不要读写其他分片的目录。
- 总述覆盖区间必须与下发区间一致，不多不少。
