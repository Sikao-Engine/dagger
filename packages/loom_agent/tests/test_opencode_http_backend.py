"""opencode_http backend: ensure_ready/dispose + stream translation wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from loom_agent.backend import AgentEvent
from loom_agent.backends.opencode_http import OpencodeEndpoint, OpencodeHttpBackend
from loom_agent.opencode import SSEEvent
from loom_agent.opencode.process_manager import ManagedProcess, ProcessStatus


class _FakeMgr:
    """Records calls; returns a running process."""

    def __init__(self) -> None:
        self.stopped: list[str] = []
        self.next_port = 5000

    async def ensure_running_unique_async(self, path: str, key: str, chat_id=None):
        proc = ManagedProcess(path=path, port=self.next_port, key=key)
        proc.status = ProcessStatus.RUNNING
        proc.pid = 123
        self.next_port += 1
        return True, proc, "fake-running"

    async def stop_async(self, key: str):
        self.stopped.append(key)
        return True, "stopped"


class _FakeClient:
    """Yields scripted raw SSEEvents; records prompt/abort/permission."""

    def __init__(self, *, host: str, port: int) -> None:
        self.host = host
        self.port = port
        _FakeClient.last = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        await self.close()
        return False

    async def create_session(self, title=None):
        from loom_agent.opencode import Session

        return Session(id="sess-fake", title=title)

    async def send_prompt_async(self, sid, text, agent=None, model=None):
        _FakeClient.prompts.append((sid, text))
        return True

    async def abort_session(self, sid):
        return True

    async def respond_permission(self, sid, pid, response, remember=True):
        _FakeClient.perms.append((pid, response))
        return True

    async def close(self):
        pass

    async def stream_events_robust(self, sid, **kw):
        # Yield a text part, a tool part, then idle.
        yield SSEEvent(
            event="message.part.updated",
            data='{"type":"message.part.updated","properties":{"part":{"type":"text","text":"hi"}}}',
        )
        yield SSEEvent(
            event="message.part.updated",
            data='{"type":"message.part.updated","properties":{"part":{"type":"tool","tool":"edit","state":{"status":"completed"}}}}',
        )
        yield SSEEvent(event="session.idle", data='{"type":"session.idle"}')


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeClient.prompts = []
    _FakeClient.perms = []
    yield


class TestEnsureReady:
    async def test_ensure_ready_returns_endpoint_with_unique_key(self, tmp_path: Path) -> None:
        with patch("loom_agent.backends.opencode_http.AgentCLIAsyncClient", _FakeClient):
            backend = OpencodeHttpBackend(process_manager=_FakeMgr())
            ep = await backend.ensure_ready(str(tmp_path))
        assert isinstance(ep, OpencodeEndpoint)
        assert ep.port == 5000
        assert ep.workdir == str(tmp_path)
        assert ep.process_key.startswith("loom-")

    async def test_ensure_ready_raises_on_failure(self, tmp_path: Path) -> None:
        class _FailMgr(_FakeMgr):
            async def ensure_running_unique_async(self, path, key, chat_id=None):
                proc = ManagedProcess(path=path, port=0, key=key)
                proc.status = ProcessStatus.ERROR
                proc.last_error = "boom"
                return False, proc, "boom"

        backend = OpencodeHttpBackend(process_manager=_FailMgr())
        with pytest.raises(RuntimeError, match="boom"):
            await backend.ensure_ready(str(tmp_path))


class TestSessionLifecycle:
    async def test_create_session_and_prompt(self, tmp_path: Path) -> None:
        with patch("loom_agent.backends.opencode_http.AgentCLIAsyncClient", _FakeClient):
            backend = OpencodeHttpBackend(process_manager=_FakeMgr())
            ep = await backend.ensure_ready(str(tmp_path))
            sid = await backend.create_session(ep)
            await backend.send_prompt(ep, sid, "go")
        assert sid == "sess-fake"
        assert _FakeClient.prompts == [("sess-fake", "go")]

    async def test_abort_and_permission(self, tmp_path: Path) -> None:
        with patch("loom_agent.backends.opencode_http.AgentCLIAsyncClient", _FakeClient):
            backend = OpencodeHttpBackend(process_manager=_FakeMgr())
            ep = await backend.ensure_ready(str(tmp_path))
            await backend.reply_permission(ep, "perm-1", approve=True)
            await backend.abort(ep, "sess-fake")
        assert _FakeClient.perms == [("perm-1", "always")]

    async def test_dispose_stops_process(self, tmp_path: Path) -> None:
        with patch("loom_agent.backends.opencode_http.AgentCLIAsyncClient", _FakeClient):
            mgr = _FakeMgr()
            backend = OpencodeHttpBackend(process_manager=mgr)
            ep = await backend.ensure_ready(str(tmp_path))
            await backend.dispose(ep)
        assert mgr.stopped == [ep.process_key]


class TestStreamTranslation:
    async def test_stream_yields_normalized_events(self, tmp_path: Path) -> None:
        with patch("loom_agent.backends.opencode_http.AgentCLIAsyncClient", _FakeClient):
            backend = OpencodeHttpBackend(process_manager=_FakeMgr())
            ep = await backend.ensure_ready(str(tmp_path))
            events: list[AgentEvent] = []
            async for ev in backend.stream_events(ep, "sess-fake"):
                events.append(ev)
        kinds = [e.kind for e in events]
        assert "text" in kinds
        assert "tool" in kinds
        assert "idle" in kinds
        # idle is forwarded but the session_runner does NOT treat it as success.
        idle_ev = next(e for e in events if e.kind == "idle")
        assert idle_ev.kind == "idle"
