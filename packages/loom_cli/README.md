# loom_cli

Deterministic CLI for Loom. Two entry points:

- `loom` — orchestration CLI (`run`, `state`, `config`, `domains`).
- `loom-state` — the **single write path** Agents are allowed to use for state:
  writes go through this so envelopes, schema validation, and journaling are automatic.

Provides `loom_cli.scaffold` so domains can ship their own deterministic CLIs
(gbcli-style) reusing JSON output, semantic exit codes (0 ok / 1 needs-human /
2 needs-review / 3 param-error), and idempotency helpers.
