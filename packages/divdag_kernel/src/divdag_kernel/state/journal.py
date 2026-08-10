"""Journal: append-only audit log.

Every state write appends one record. Lets us answer "this conclusion was written
when, by whom, what was the previous attempt". Never mutated; the only allowed
post-action is `gc` which logs a single `gc` record (it does not delete lines).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .envelope import now_iso
from .io import append_jsonl, read_jsonl
from .key import StateKey


@dataclass(frozen=True)
class JournalEntry:
    ts: str
    op: str  # write | supersede | gc | reindex
    kind: str
    key: dict[str, Any]  # serialized StateKey
    actor: str = ""
    sha256: str = ""
    bytes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ts": self.ts,
            "op": self.op,
            "kind": self.kind,
            "key": dict(self.key),
        }
        if self.actor:
            d["actor"] = self.actor
        if self.sha256:
            d["sha256"] = self.sha256
        if self.bytes:
            d["bytes"] = self.bytes
        if self.extra:
            d.update(self.extra)
        return d


class Journal:
    """Append-only audit log at `<state_root>/journal.jsonl`."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, entry: JournalEntry) -> None:
        append_jsonl(self.path, entry.to_dict())

    def append_write(
        self,
        *,
        key: StateKey,
        kind: str,
        actor: str,
        sha256: str,
        nbytes: int,
        unwrapped: bool = False,
    ) -> None:
        extra: dict[str, Any] = {}
        if unwrapped:
            extra["unwrapped"] = True
        self.append(
            JournalEntry(
                ts=now_iso(),
                op="write",
                kind=kind,
                key=key.to_dict(),
                actor=actor,
                sha256=sha256,
                bytes=nbytes,
                extra=extra,
            )
        )

    def append_supersede(self, *, key: StateKey, reason: str) -> None:
        self.append(
            JournalEntry(
                ts=now_iso(),
                op="supersede",
                kind="",
                key=key.to_dict(),
                extra={"reason": reason},
            )
        )

    def append_gc(self, *, layers: list[str], freed_bytes: int) -> None:
        self.append(
            JournalEntry(
                ts=now_iso(),
                op="gc",
                kind="",
                key={},
                extra={"layers": layers, "freed_bytes": freed_bytes},
            )
        )

    def read_all(self) -> list[JournalEntry]:
        records = read_jsonl(self.path)
        out: list[JournalEntry] = []
        for r in records:
            out.append(
                JournalEntry(
                    ts=str(r.get("ts", "")),
                    op=str(r.get("op", "")),
                    kind=str(r.get("kind", "")),
                    key=dict(r.get("key") or {}) if isinstance(r.get("key"), dict) else {},
                    actor=str(r.get("actor", "")),
                    sha256=str(r.get("sha256", "")),
                    bytes=int(r.get("bytes", 0)) if isinstance(r.get("bytes"), (int, float)) else 0,
                    extra={
                        k: v
                        for k, v in r.items()
                        if k not in ("ts", "op", "kind", "key", "actor", "sha256", "bytes")
                    },
                )
            )
        return out

    def to_json(self) -> str:
        return json.dumps([e.to_dict() for e in self.read_all()], indent=2, default=str)


__all__ = ["Journal", "JournalEntry"]
