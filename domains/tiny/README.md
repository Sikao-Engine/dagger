# domains/tiny

First end-to-end domain. Pure local batch processing — no external dependencies.
Input: a directory of `.txt` files. Output: per-file summary slot.

The template exercises three topologies:
1. Parallel shards (`init → shard_ws[i] → digest[i]`)
2. Serial accumulation (`digest[i] ─SERIAL_PREV─→ digest[i+1]`)
3. Aggregation (`digest[*] ─ALL─→ report`)
