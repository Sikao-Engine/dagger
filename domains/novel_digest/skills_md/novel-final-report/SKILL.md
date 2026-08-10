---
name: novel-final-report
description: 汇总运行终稿。Use when: 收到 /novel-final-report 指令，一致性校验已完成，需要汇总全局实体表/时间线/矛盾清单/分卷总述为人读终稿（DivDag novel_digest 领域的收尾 agent 节点）。
---

# novel-final-report — 运行终稿

一致性校验已完成（consistency_ok=true），汇总本次运行终稿。

## 输入

- 运行级产物目录下的：全局实体表、全局时间线、`consistency_report.json`、各片 `volume_summary.json`。
- 参照系：`refs.canon.path` 是人物设定权威，终稿中的人名/地名以它为准。

## 流程

1. 汇总写入运行级产物目录：
   - `final_report.md` — 人读终稿（分卷总述索引 + 全局时间线纲要 + 矛盾清单摘要）。
   - `final_report.json` — 机器可读索引（供后续 Run 召回）。
2. 写 session_result 终态：`report_ok=true`。

## 边界与禁忌

- 不要改动任何上游产物；终稿只新增不重写。
