"""Mock AgentBackend: scripted events + result-file writes for tests and CI.

Lets the entire kernel + session_runner be exercised without a real Agent.
Configurable: inject a per-node script that decides what events to emit and
whether to write a success/failure result.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from divdag_kernel.state import K, StateStore

from ..backend import AgentEvent


@dataclass
class MockScript:
    """Per-node script: what events to emit, what result to write."""

    events: list[AgentEvent] = field(default_factory=list)
    result_body: dict[str, Any] | None = None  # if set, written to result.json
    fail_with: str = ""  # if set, write a failure result
    delay_seconds: float = 0.0


class MockBackend:
    """An in-process AgentBackend that runs scripts.

    Scripts are registered by node_type. When a session is created, the backend
    looks up the script (if any) and replays its events + writes its result.
    """

    backend = "mock"

    def __init__(self, *, store: StateStore | None = None) -> None:
        self._scripts: dict[str, MockScript] = {}
        self._store = store
        self._sessions: dict[str, dict[str, Any]] = {}
        self._next_session_id = 1

    def register(self, node_type: str, script: MockScript) -> None:
        self._scripts[node_type] = script

    def bind_session_node_type(self, session_id: str, node_type: str) -> None:
        """Associate a session with a node_type so stream_events knows which script."""
        if session_id not in self._sessions:
            raise KeyError(session_id)
        self._sessions[session_id]["node_type"] = node_type

    async def ensure_ready(self, workdir: str) -> dict[str, Any]:
        # The mock doesn't spawn processes; just return a fake endpoint.
        return {"workdir": workdir, "ready": True}

    async def create_session(self, endpoint: Any, *, agent: str | None = None) -> str:
        sid = f"mock-{self._next_session_id}"
        self._next_session_id += 1
        self._sessions[sid] = {
            "endpoint": endpoint,
            "prompt": "",
            "aborted": False,
            "node_type": "",
        }
        return sid

    async def send_prompt(self, endpoint: Any, session_id: str, prompt: str) -> None:
        if session_id not in self._sessions:
            raise KeyError(f"unknown session: {session_id}")
        self._sessions[session_id]["prompt"] = prompt

    async def stream_events(self, endpoint: Any, session_id: str) -> AsyncIterator[AgentEvent]:
        # Look up the node_type bound to this session to find its script.
        session = self._sessions.get(session_id, {})
        node_type = session.get("node_type", "")
        script = self._scripts.get(node_type) or MockScript()
        if script.delay_seconds:
            await asyncio.sleep(script.delay_seconds)
        for ev in script.events:
            yield ev
        # After the events, write the result file (if a store + script result are set).
        if self._store and script.result_body is not None:
            self._write_result(node_type=node_type, body=script.result_body)

    async def reply_permission(self, endpoint: Any, permission_id: str, approve: bool) -> None:
        pass

    async def abort(self, endpoint: Any, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["aborted"] = True

    async def dispose(self, endpoint: Any) -> None:
        pass

    def _write_result(self, *, node_type: str, body: dict[str, Any]) -> None:
        """The mock directly writes the result contract file (simulating an Agent)."""
        assert self._store is not None
        # Find the node_run_id for this node_type from the latest task_card under
        # the contract layer. The mock is a test helper, so we cheat: look at the
        # most recently written task_card.
        contract_dir = self._store.state_root / "contract"
        if not contract_dir.exists():
            return
        # Pick the most recently created node_run_id directory.
        nrid_dirs = sorted(
            (p for p in contract_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
        )
        if not nrid_dirs:
            return
        nrid = nrid_dirs[-1].name
        attempt = self._store.latest_attempt(nrid)
        if attempt == 0:
            attempt = 1
        # The Agent is allowed to write directly to scratch/artifact, but result.json
        # is a contract file. We simulate "Agent wrote it directly" — the store's
        # normalize_envelope path will wrap it on read.
        path = self._store.path(K.result(nrid, attempt))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
        # Touch the index so verify() is consistent.
        self._store.reindex()


__all__ = ["MockBackend", "MockScript"]
