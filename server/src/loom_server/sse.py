"""SSE broker: bridges the sync EventBus to async SSE streams.

Two stream kinds:
  - run/global stream: subscribes to EventBus, replays buffered events
    (seq > last_seq catch-up via Last-Event-ID), then streams live.
  - attempt stream: replays transcript.jsonl (Agent events), tails if the
    attempt is still running.

Backpressure: a bounded queue; on full, the oldest event is dropped (a live
SSE client that can't keep up loses oldest, not newest — preferable for a
status feed).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from loom_kernel.state import K, StateStore

from .events import EventBus, LoomEvent

_QUEUE_MAX = 256
_TAIL_POLL_SECONDS = 0.5
_TAIL_IDLE_TIMEOUT_SECONDS = 3600


def _encode(ev: LoomEvent) -> dict[str, Any]:
    """Encode a LoomEvent as a ServerSentEventMessage dict (data + id + event)."""
    return {
        "data": json.dumps(ev.to_dict(), default=str),
        "id": str(ev.seq),
        "event": ev.type,
    }


def _safe_put(queue: asyncio.Queue[LoomEvent | None], ev: LoomEvent) -> None:
    """Put with drop-oldest backpressure (called via call_soon_threadsafe)."""
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(ev)
    except asyncio.QueueFull:
        pass


class SSEBroker:
    """Streams EventBus events as SSE messages."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def stream(
        self,
        *,
        run_id: str | None = None,
        last_seq: int = 0,
        catch_up_only: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE message dicts. Replays buffered (seq > last_seq) then live.

        ``catch_up_only=True`` exits after replaying buffered events — useful for
        audit/recovery and for tests (the live loop never blocks).
        """
        # ── catch-up ───────────────────────────────────────────────
        for ev in self._bus.buffered():
            if ev.seq <= last_seq:
                continue
            if run_id is not None and ev.run_id != run_id:
                continue
            yield _encode(ev)

        if catch_up_only:
            return

        # ── live ───────────────────────────────────────────────────
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[LoomEvent | None] = asyncio.Queue(maxsize=_QUEUE_MAX)

        def _cb(ev: LoomEvent) -> None:
            try:
                loop.call_soon_threadsafe(_safe_put, queue, ev)
            except RuntimeError:
                pass  # loop closed mid-flight; subscriber will be removed in finally

        unsub = self._bus.subscribe(_cb)
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    return
                if run_id is not None and ev.run_id != run_id:
                    continue
                yield _encode(ev)
        finally:
            unsub()

    async def stream_attempt(
        self,
        *,
        store: StateStore,
        node_run_id: str,
        attempt: int,
        is_running: bool,
    ) -> AsyncIterator[dict[str, Any]]:
        """tail if the attempt is still running.

        Each line is one AgentEvent dict. Yields `data:` only (no id —
        transcript lines have no monotonic seq).
        """
        path = store.path(K.transcript(node_run_id, attempt))
        if not path.exists():
            return
        # Replay existing content.
        seen = 0
        for line in _read_lines(path):
            seen += 1
            yield {"data": line}

        if not is_running:
            return

        # Tail: poll for new lines until idle timeout.
        import time

        deadline = time.monotonic() + _TAIL_IDLE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(_TAIL_POLL_SECONDS)
            new_lines = _read_lines(path)[seen:]
            if not new_lines:
                continue
            for line in new_lines:
                seen += 1
                yield {"data": line}


def _read_lines(path: Path) -> list[str]:
    """Read transcript.jsonl as a list of stripped line strings (skips blanks)."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln.strip()]


__all__ = ["SSEBroker"]
