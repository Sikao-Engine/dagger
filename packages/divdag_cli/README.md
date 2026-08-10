# divdag_cli

Deterministic CLI for DivDag. Two entry points:

- `divdag` — orchestration CLI (`run`, `state`, `config`, `domains`).
- `divdag-state` — the **single write path** Agents are allowed to use for state:
  writes go through this so envelopes, schema validation, and journaling are automatic.

Provides `divdag_cli.scaffold` so domains can ship their own deterministic CLIs
 reusing JSON output, semantic exit codes (0 ok / 1 needs-human /
2 needs-review / 3 param-error), and idempotency helpers.
