"""Event bus: minimal in-process pub/sub + DB persistence.

The scheduler emits events (node_start/success/failure, run_started/completed).
They are (1) written to the `events` table for replay/audit and (2) pushed to
in-process subscribers. The SSE layer (T5.6) subscribes to this bus to stream
to clients — kept here as the single emission point so SSE is a thin add-on,
not a rewrite.

Each event carries a monotonic `seq` so an SSE client can resume after a
reconnect via `Last-Event-ID` (replay events with seq > last).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

from .models import Event


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DaggerEvent:
    """An in-process event. Mirrors the `events` table row."""

    seq: int
    type: str
    entity_type: str = ""
    entity_id: str | None = None
    run_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "run_id": self.run_id,
            "data": dict(self.data),
            "created_at": self.created_at.isoformat(),
        }


class EventBus:
    """In-process event bus. Thread-safe subscriber list.

    `persist` writes to the DB session; `publish` both persists and notifies
    subscribers. Subscribers are callables receiving a `DaggerEvent`.
    """

    def __init__(self) -> None:
        self._subs: list[Callable[[DaggerEvent], None]] = []
        self._lock = Lock()
        self._buffered: list[DaggerEvent] = []
        self._next_seq = 1

    def subscribe(self, cb: Callable[[DaggerEvent], None]) -> Callable[[], None]:
        """Register a subscriber. Returns an unsubscribe function."""
        with self._lock:
            self._subs.append(cb)

        def _unsub() -> None:
            with self._lock:
                if cb in self._subs:
                    self._subs.remove(cb)

        return _unsub

    def emit(
        self, ev_factory: Callable[[int], DaggerEvent], session: Session | None = None
    ) -> DaggerEvent:
        """Persist (if session given) + notify subscribers + buffer.

        Takes a factory so the bus can stamp the monotonic seq itself — callers
        use `make_*` helpers which now accept seq.
        """
        with self._lock:
            seq = self._next_seq
            self._next_seq += 1
        ev = ev_factory(seq)
        if session is not None:
            session.add(
                Event(
                    type=ev.type,
                    entity_type=ev.entity_type,
                    entity_id=ev.entity_id,
                    run_id=ev.run_id,
                    data=ev.data,
                )
            )
        with self._lock:
            self._buffered.append(ev)
            subs = list(self._subs)
        for cb in subs:
            try:
                cb(ev)
            except Exception:  # noqa: BLE001, S112 - subscriber must not break the bus
                continue
        return ev

    def buffered(self) -> list[DaggerEvent]:
        """Return a snapshot of emitted events (for tests / SSE catch-up)."""
        with self._lock:
            return list(self._buffered)

    def clear(self) -> None:
        with self._lock:
            self._buffered.clear()


def make_run_started(
    seq: int, run_id: str, domain_id: str, template_id: str
) -> DaggerEvent:
    return DaggerEvent(
        seq=seq,
        type="run.started",
        entity_type="run",
        entity_id=run_id,
        run_id=run_id,
        data={"domain_id": domain_id, "template_id": template_id},
    )


def make_node_started(seq: int, node_run_id: str, run_id: str) -> DaggerEvent:
    return DaggerEvent(
        seq=seq,
        type="node.started",
        entity_id=node_run_id,
        run_id=run_id,
        data={"node_run_id": node_run_id},
    )


def make_node_succeeded(
    seq: int, node_run_id: str, run_id: str, outputs: dict[str, Any]
) -> DaggerEvent:
    return DaggerEvent(
        seq=seq,
        type="node.succeeded",
        entity_type="node_run",
        entity_id=node_run_id,
        run_id=run_id,
        data={"node_run_id": node_run_id, "outputs": outputs},
    )


def make_node_failed(seq: int, node_run_id: str, run_id: str, reason: str) -> DaggerEvent:
    return DaggerEvent(
        seq=seq,
        type="node.failed",
        entity_type="node_run",
        entity_id=node_run_id,
        run_id=run_id,
        data={"node_run_id": node_run_id, "reason": reason},
    )


def make_run_completed(
    seq: int, run_id: str, completed: int, failed: int, skipped: int
) -> DaggerEvent:
    return DaggerEvent(
        seq=seq,
        type="run.completed",
        entity_type="run",
        entity_id=run_id,
        run_id=run_id,
        data={"completed": completed, "failed": failed, "skipped": skipped},
    )


__all__ = [
    "EventBus",
    "DaggerEvent",
    "make_node_failed",
    "make_node_started",
    "make_node_succeeded",
    "make_run_completed",
    "make_run_started",
]
