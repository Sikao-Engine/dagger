---
name: novel-consistency
description: 全局一致性校验。Use when: 收到 /novel-consistency 指令，全部分片的实体归并与分卷总述已完成，需要产出矛盾清单（DivDag novel_digest 领域的汇聚 agent 节点）。
---

# novel-consistency — 全局一致性校验

对照全局实体表与全局时间线做一致性校验，产出矛盾清单。

## 输入

- 全局实体表、全局时间线、各片 `volume_summary.json`（运行级产物目录，路径见 prompt 下发）。
- 参照系：`refs.canon.path` 是人物设定权威，冲突以它为准。

## 流程

1. 通读全局实体表：找同一实体的多重身份、命名漂移、别名冲突。
2. 通读全局时间线：找倒流、锚点缺失、参与者与实体表对不上。
3. 写 `consistency_report.json` 到运行级产物目录，schema kind：`novel_consistency_report`。
   每条矛盾给出：涉及实体/事件、位置（章号）、矛盾描述、严重度。
4. 写 session_result 终态：`consistency_ok=true`（**有矛盾也写 true**——矛盾清单本身就是产物；
   `consistency_ok=false` 只用于你无法完成校验的情况）。

## 边界与禁忌

- 不要修改任何逐章产物、实体表、时间线与分卷总述；只新增矛盾清单。
