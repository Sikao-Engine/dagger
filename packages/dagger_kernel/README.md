# dagger_kernel

Domain-agnostic core of the Dagger batch-Agent orchestration base.

Contains:
- `state/` — StateStore: the single source of truth for runtime artifacts
  (control / contract / scratch / artifact / log layers).
- `dag/` — DAG orchestration engine: template, instantiator, context, node contracts.
- `contract/` — session_result schema, validators, SkillSpec, TaskCard.
- `executors/` — runtime-registered ExecutorSpec catalog.
- `planning/` — WorkItem, Sharder strategies, ItemLedgerSnapshot.
- `workspace/` — WorkspaceProvider SPI + builtin implementations.
- `spi.py` — DomainPlugin / DomainRegistry (single entry point).
- `config.py` — pydantic config model (`dagger.yaml` schema).

This package imports **no domain code, no HTTP, no DB**. CI's import-linter enforces this.
