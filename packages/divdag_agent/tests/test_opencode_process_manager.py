"""process_manager: port allocation + state persistence (no real agentcli spawn)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from divdag_agent.opencode.process_manager import (
    AgentServerProcessManager,
    ManagedProcess,
    ProcessStatus,
)


@pytest.fixture
def mgr(tmp_path: Path) -> AgentServerProcessManager:
    return AgentServerProcessManager(data_dir=tmp_path, base_port=4096)


def _fake_start_ok(
    self: AgentServerProcessManager, proc: ManagedProcess
) -> tuple[bool, ManagedProcess, str]:
    """Replace _start_process: mark running without spawning agentcli."""
    proc.status = ProcessStatus.RUNNING
    proc.pid = 99900
    proc.started_at = "2026-01-01T00:00:00"
    self._save_state()
    return True, proc, "fake-running"


class TestPortAllocation:
    def test_first_port_is_base(self, mgr: AgentServerProcessManager) -> None:
        with patch.object(AgentServerProcessManager, "_start_process", _fake_start_ok):
            ok, proc, _ = mgr.ensure_running(".")
        assert ok is True
        assert proc.port == 4096

    def test_second_call_reuses_if_alive(self, mgr: AgentServerProcessManager) -> None:
        # The fake process doesn't bind a port, so is_alive (port probe) is False.
        # Patch is_alive so the reuse branch is taken.
        with (
            patch.object(AgentServerProcessManager, "_start_process", _fake_start_ok),
            patch.object(ManagedProcess, "is_alive", new=True),
        ):
            mgr.ensure_running(".")
            ok, proc2, msg = mgr.ensure_running(".")
        assert ok is True
        assert proc2.port == 4096
        assert "already running" in msg

    def test_unique_key_gets_offset_port(self, mgr: AgentServerProcessManager) -> None:
        # Occupy base port so the next allocation must skip it.
        import socket

        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 4096))
        holder.listen(1)
        try:
            with patch.object(AgentServerProcessManager, "_start_process", _fake_start_ok):
                ok, proc, _ = mgr.ensure_running_unique(".", "task-A")
                ok2, proc2, _ = mgr.ensure_running_unique(".", "task-B")
        finally:
            holder.close()
        assert ok and ok2
        assert proc.port != 4096
        assert proc2.port != 4096
        assert proc.port != proc2.port


class TestStatePersistence:
    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        mgr1 = AgentServerProcessManager(data_dir=tmp_path, base_port=4096)
        with patch.object(AgentServerProcessManager, "_start_process", _fake_start_ok):
            mgr1.ensure_running_unique(".", "k1")
        state_file = mgr1._state_file
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert any(p["key"] == "k1" for p in data)

        mgr2 = AgentServerProcessManager(data_dir=tmp_path, base_port=4096)
        procs = {p.key: p for p in mgr2.list_processes() if p.key}
        assert "k1" in procs
        # The fake process isn't really alive → load marks it stopped.
        assert procs["k1"].status == ProcessStatus.STOPPED

    def test_stop_clears_pid(self, mgr: AgentServerProcessManager) -> None:
        with patch.object(AgentServerProcessManager, "_start_process", _fake_start_ok):
            mgr.ensure_running_unique(".", "k1")
        ok, _ = mgr.stop("k1")
        assert ok is True
        proc = next(p for p in mgr.list_processes() if p.key == "k1")
        assert proc.status == ProcessStatus.STOPPED
        assert proc.pid is None


class TestResolvePath:
    def test_missing_path_returns_none(self, mgr: AgentServerProcessManager) -> None:
        assert mgr._resolve_path("/no/such/path/xyz", must_exist=True) is None

    def test_existing_path_resolved(self, tmp_path: Path, mgr: AgentServerProcessManager) -> None:
        assert mgr._resolve_path(str(tmp_path), must_exist=True) == str(tmp_path.resolve())
