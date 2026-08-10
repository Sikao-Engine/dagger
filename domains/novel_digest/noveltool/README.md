# noveltool (standalone tool package)

Deterministic CLI for the Dagger `novel_digest` domain: `status / next / fill / check`
(JSON output, semantic exit codes 0/1/2/3, idempotent).

This is a thin packaging shim so the CLI can live on your PATH, decoupled from
the repo checkout:

```bash
uv tool install -e .
noveltool status --root /path/to/book --out /path/to/run/shard-000
```

The implementation lives in the `dagger-domain-novel-digest` package
(`novel_digest.noveltool`); `[tool.uv.sources]` pins it (and the two dagger
packages it needs) to this repo checkout, so `uv tool install -e .` works
without publishing anything.
