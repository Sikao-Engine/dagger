# loom_agent

Backend-agnostic Agent protocol layer.

Defines `AgentBackend` Protocol and unified `AgentEvent`. Implementations:
- `backends/mock.py` — scripted events for tests and CI.
- `backends/opencode_http.py` — `opencode-cli serve`-compatible HTTP+SSE client.
- `backends/claude_code.py` — CLI-agent adapter (planned).

`session_runner` drives: send prompt → stream events → wait for contract file
(`session_result.json`) → validate → retry with previous-failure context → wait
background tasks. Never trusts SSE `idle` — only the result file.
