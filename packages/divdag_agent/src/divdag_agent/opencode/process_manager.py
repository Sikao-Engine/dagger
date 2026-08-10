"""divdag_agent.opencode.process_manager — agentcli serve process lifecycle.

Vendored from CubeClaw's `cube.agentcli.process_manager` (long-validated).
Each workdir (or unique key) maps to one agentcli serve process on an
offset port. State persists to disk so a restart can recover the table.

Design (unchanged from CubeClaw):
  1. Uniqueness: one workdir → one process → one port.
  2. Persisted: state in `<data_dir>/opencode/sessions.json`.
  3. Thread-safe: process-level port-allocation lock.
  4. Observable: per-process stdout/stderr logs.

Workdir → process → port::
    /path/A  →  PID 12345  →  port 4096
    /path/B  →  PID 12346  →  port 4097
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .client import Session, check_health_sync

logger = logging.getLogger(__name__)

_DEFAULT_STATE_FILE = Path("opencode/sessions.json")
_DEFAULT_LOG_DIR = Path("opencode/logs")
_STARTUP_TIMEOUT_SEC = 20
_HEALTH_POLL_INTERVAL = 1

# Process-level lock so concurrent starts across instances don't grab one port.
_PORT_ALLOC_LOCK = threading.Lock()


class ProcessStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class ManagedProcess:
    """One agentcli serve process instance."""

    path: str
    port: int
    pid: int | None = None
    status: ProcessStatus = ProcessStatus.STOPPED
    session_id: str | None = None
    started_at: str | None = None
    last_error: str | None = None
    key: str | None = None  # unique-key discriminator (ensure_running_unique)

    _process: subprocess.Popen | None = field(default=None, repr=False)
    _stdout_log: Any | None = field(default=None, repr=False)
    _stderr_log: Any | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "port": self.port,
            "pid": self.pid,
            "status": self.status.value,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "last_error": self.last_error,
            "key": self.key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManagedProcess:
        proc = cls(
            path=data.get("path", ""),
            port=data.get("port", 0),
            pid=data.get("pid"),
            session_id=data.get("session_id"),
            started_at=data.get("started_at"),
            last_error=data.get("last_error"),
            key=data.get("key"),
        )
        try:
            proc.status = ProcessStatus(data.get("status", "stopped"))
        except ValueError:
            proc.status = ProcessStatus.STOPPED
        return proc

    @property
    def is_alive(self) -> bool:
        """Check liveness by probing the port (no HTTP)."""
        if not self.port:
            return False
        return _port_open(self.port)


class AgentServerProcessManager:
    """agentcli serve process lifecycle manager.

    Sync::
        mgr = AgentServerProcessManager(data_dir=Path("./.divdag"), base_port=4096)
        ok, proc, msg = mgr.ensure_running("/path/to/workspace")

    Async::
        ok, proc, msg = await mgr.ensure_running_async("/path/to/workspace")
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        base_port: int = 4096,
        state_file: Path | None = None,
        log_dir: Path | None = None,
        startup_timeout: int = _STARTUP_TIMEOUT_SEC,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.base_port = base_port
        self._state_file = self.data_dir / (state_file or _DEFAULT_STATE_FILE)
        self._log_dir = self.data_dir / (log_dir or _DEFAULT_LOG_DIR)
        self._startup_timeout = startup_timeout
        self._processes: dict[str, ManagedProcess] = {}
        self._load_state()

    # ── Public sync API ───────────────────────────────────────────

    def ensure_running(
        self,
        path: str,
        chat_id: str | None = None,
    ) -> tuple[bool, ManagedProcess, str]:
        """Ensure a process runs for `path`. Returns (ok, proc, msg)."""
        resolved = self._resolve_path(path)
        if resolved is None:
            dummy = ManagedProcess(path=path, port=0)
            dummy.status = ProcessStatus.ERROR
            dummy.last_error = f"path does not exist or is invalid: {path}"
            return False, dummy, dummy.last_error

        path = resolved
        proc_key = path
        with _PORT_ALLOC_LOCK:
            proc = self._processes.get(proc_key)
            if proc and proc.is_alive:
                proc.status = ProcessStatus.RUNNING
                return True, proc, f"already running on port {proc.port}"

            port = self._pick_free_port()
            if proc is None:
                proc = ManagedProcess(path=path, port=port, key=proc_key)
                self._processes[proc_key] = proc
            else:
                proc.port = port
                proc.session_id = None

            return self._start_process(proc)

    def ensure_running_unique(
        self,
        path: str,
        key: str,
        chat_id: str | None = None,
    ) -> tuple[bool, ManagedProcess, str]:
        """Start an independent process keyed by `key` (cwd still `path`).

        Unlike ensure_running(path), this does NOT reuse by workdir; the caller
        can pass a node_run_id/session_id as key to isolate ports per task.
        """
        resolved = self._resolve_path(path)
        if resolved is None:
            dummy = ManagedProcess(path=path, port=0)
            dummy.status = ProcessStatus.ERROR
            dummy.last_error = f"path does not exist or is invalid: {path}"
            return False, dummy, dummy.last_error

        proc_key = key or resolved
        with _PORT_ALLOC_LOCK:
            proc = self._processes.get(proc_key)
            if proc and proc.is_alive:
                proc.status = ProcessStatus.RUNNING
                return True, proc, f"already running on port {proc.port}"

            port = self._pick_free_port()
            if proc is None:
                proc = ManagedProcess(path=resolved, port=port, key=proc_key)
                self._processes[proc_key] = proc
            else:
                proc.path = resolved
                proc.port = port
                proc.session_id = None

            return self._start_process(proc)

    def stop(self, key: str) -> tuple[bool, str]:
        """Stop the process for `key` (workdir path or unique key)."""
        resolved = self._resolve_path(key, must_exist=False)
        proc_key = key
        proc = self._processes.get(proc_key)
        if proc is None and resolved:
            proc_key = resolved
            proc = self._processes.get(proc_key)
        if not proc:
            return False, f"no process found for {key}"

        self._kill_process(proc)
        proc.status = ProcessStatus.STOPPED
        proc.pid = None
        proc.session_id = None
        self._save_state()
        logger.info("[ProcessManager] stopped: %s", proc_key)
        return True, "stopped"

    def stop_all(self) -> int:
        count = 0
        for key in list(self._processes.keys()):
            ok, _ = self.stop(key)
            if ok:
                count += 1
        return count

    def get_or_create_api_session(self, key: str) -> str | None:
        """Get/create a agentcli API session for the process at `key`."""
        resolved = self._resolve_path(key, must_exist=False)
        proc_key = key
        proc = self._processes.get(proc_key)
        if proc is None and resolved:
            proc = self._processes.get(resolved)
        if not proc or proc.status != ProcessStatus.RUNNING:
            return None
        if proc.session_id:
            return proc.session_id

        try:
            import httpx

            title = f"DivDag - {Path(proc.path).name}"
            with httpx.Client(timeout=10.0, trust_env=False) as c:
                resp = c.post(
                    f"http://127.0.0.1:{proc.port}/session",
                    json={"title": title},
                )
                resp.raise_for_status()
                sess = Session.from_dict(resp.json())
                proc.session_id = sess.id
                self._save_state()
                return sess.id
        except Exception as exc:
            logger.error("[ProcessManager] create API session failed: %s", exc)
            return None

    def list_processes(self) -> list[ManagedProcess]:
        return list(self._processes.values())

    def get_status_text(self) -> str:
        if not self._processes:
            return "no agentcli processes."
        lines = ["=== agentcli processes ==="]
        for proc in self._processes.values():
            alive = proc.is_alive
            icon = (
                "🟢"
                if alive
                else {"stopped": "⚪", "starting": "🟡", "error": "🔴"}.get(proc.status.value, "⚪")
            )
            lines.append(f"{icon} {Path(proc.path).name}  port={proc.port}  pid={proc.pid or '-'}")
            if proc.last_error:
                lines.append(f"   ⚠ {proc.last_error}")
        return "\n".join(lines)

    # ── Public async API ──────────────────────────────────────────

    async def ensure_running_async(
        self, path: str, chat_id: str | None = None
    ) -> tuple[bool, ManagedProcess, str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.ensure_running, path, chat_id)

    async def ensure_running_unique_async(
        self, path: str, key: str, chat_id: str | None = None
    ) -> tuple[bool, ManagedProcess, str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.ensure_running_unique, path, key, chat_id)

    async def stop_async(self, key: str) -> tuple[bool, str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.stop, key)

    # ── Internals: start / kill ───────────────────────────────────

    def _start_process(self, proc: ManagedProcess) -> tuple[bool, ManagedProcess, str]:
        path = Path(proc.path)
        if not path.exists():
            proc.status = ProcessStatus.ERROR
            proc.last_error = f"path does not exist: {proc.path}"
            return False, proc, proc.last_error

        self._log_dir.mkdir(parents=True, exist_ok=True)
        out_log = self._log_dir / f"agentcli_{proc.port}.out.log"
        err_log = self._log_dir / f"agentcli_{proc.port}.err.log"

        cmd = [
            "agentcli",
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(proc.port),
        ]
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            kwargs["shell"] = True

        logger.info("[ProcessManager] starting: %s (cwd=%s)", " ".join(cmd), proc.path)

        try:
            stdout_fh = open(out_log, "w", encoding="utf-8")
            stderr_fh = open(err_log, "w", encoding="utf-8")
            process = subprocess.Popen(
                cmd,
                cwd=proc.path,
                stdout=stdout_fh,
                stderr=stderr_fh,
                **kwargs,
            )
            proc.pid = process.pid
            proc._process = process
            proc._stdout_log = stdout_fh
            proc._stderr_log = stderr_fh
            proc.status = ProcessStatus.STARTING
            proc.started_at = datetime.now().isoformat()
        except FileNotFoundError:
            proc.status = ProcessStatus.ERROR
            proc.last_error = "agentcli command not found on PATH."
            return False, proc, proc.last_error
        except Exception as exc:
            proc.status = ProcessStatus.ERROR
            proc.last_error = str(exc)
            return False, proc, proc.last_error

        logger.info(
            "[ProcessManager] waiting for ready: port=%d pid=%s timeout=%ds",
            proc.port,
            proc.pid,
            self._startup_timeout,
        )
        t_start = time.time()
        t_last_log = t_start
        for _ in range(self._startup_timeout):
            time.sleep(_HEALTH_POLL_INTERVAL)
            elapsed = time.time() - t_start
            if check_health_sync(proc.port):
                proc.status = ProcessStatus.RUNNING
                self._save_state()
                msg = f"running port={proc.port} PID={proc.pid}"
                logger.info("[ProcessManager] %s (%.1fs)", msg, elapsed)
                return True, proc, msg
            now = time.time()
            if now - t_last_log >= 5.0:
                logger.info(
                    "[ProcessManager] still waiting: port=%d elapsed=%.0fs/%ds",
                    proc.port,
                    elapsed,
                    self._startup_timeout,
                )
                t_last_log = now

        self._kill_process(proc)
        proc.status = ProcessStatus.ERROR
        proc.last_error = (
            f"agentcli serve not ready within {self._startup_timeout}s "
            f"(port={proc.port}). check log: {err_log}"
        )
        return False, proc, proc.last_error

    def _kill_process(self, proc: ManagedProcess) -> None:
        if proc._process:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc._process.pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                    )
                else:
                    proc._process.terminate()
                try:
                    proc._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc._process.kill()
                    proc._process.wait(timeout=2)
            except Exception as exc:
                logger.warning("[ProcessManager] terminate error: %s", exc)
            proc._process = None
        elif proc.pid:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                    )
                else:
                    os.kill(proc.pid, signal.SIGTERM)
                logger.info("[ProcessManager] killed by pid: %d", proc.pid)
            except (ProcessLookupError, PermissionError, OSError) as exc:
                logger.warning("[ProcessManager] kill by pid failed (%d): %s", proc.pid, exc)
            proc.pid = None

        for fh in (proc._stdout_log, proc._stderr_log):
            if fh:
                with contextlib.suppress(Exception):
                    fh.close()
        proc._stdout_log = proc._stderr_log = None

    # ── Internals: port allocation ────────────────────────────────

    def _pick_free_port(self) -> int:
        """Find a free port (caller must hold _PORT_ALLOC_LOCK)."""
        used = {p.port for p in self._processes.values() if p.port}
        port = self.base_port
        while True:
            if port in used or _port_open(port):
                port += 1
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                    probe.bind(("127.0.0.1", port))
                break
            except OSError:
                port += 1
                continue
        return port

    # ── Internals: path / state ───────────────────────────────────

    def _resolve_path(self, path: str, must_exist: bool = True) -> str | None:
        if not path:
            return None
        try:
            resolved = str(Path(path).expanduser().resolve())
            if must_exist and not Path(resolved).exists():
                return None
            return resolved
        except Exception:
            return None

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = [p.to_dict() for p in self._processes.values()]
            self._state_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("[ProcessManager] save state failed: %s", exc)

    def _load_state(self) -> None:
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            for item in data:
                proc = ManagedProcess.from_dict(item)
                key = proc.key or proc.path
                # A persisted process may have died while we were down; mark
                # it stopped if the port is no longer open.
                if proc.status == ProcessStatus.RUNNING and not proc.is_alive:
                    proc.status = ProcessStatus.STOPPED
                    proc.pid = None
                self._processes[key] = proc
        except Exception as exc:
            logger.warning("[ProcessManager] load state failed: %s", exc)


def _port_open(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


__all__ = [
    "AgentServerProcessManager",
    "ManagedProcess",
    "ProcessStatus",
]
