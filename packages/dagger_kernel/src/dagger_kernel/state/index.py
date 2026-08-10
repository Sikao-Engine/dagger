"""Index: a queryable cache of every state object.

`index.json` is the **only** query surface for the frontend / HTTP controllers.
It is a cache, not the source of truth: `reindex()` rebuilds it by walking the
tree and reading `_meta.json` files. For very large runs, it is sharded into
`index/entries-*.jsonl` files; the in-memory model is the same.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import atomic_write_json, read_jsonl
from .key import Layer, Scope, StateKey


@dataclass(frozen=True)
class IndexEntry:
    kind: str
    path: str  # relative POSIX path under state root
    layer: str
    scope: str = ""
    node_run_id: str = ""
    shard_id: str = ""
    item_id: str = ""
    attempt: int = 0
    slot: str = ""
    size: int = 0
    sha256: str = ""
    written_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "path": self.path,
            "layer": self.layer,
        }
        if self.scope:
            d["scope"] = self.scope
        if self.node_run_id:
            d["node_run_id"] = self.node_run_id
        if self.shard_id:
            d["shard_id"] = self.shard_id
        if self.item_id:
            d["item_id"] = self.item_id
        if self.attempt:
            d["attempt"] = self.attempt
        if self.slot:
            d["slot"] = self.slot
        if self.size:
            d["size"] = self.size
        if self.sha256:
            d["sha256"] = self.sha256
        if self.written_at:
            d["written_at"] = self.written_at
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IndexEntry:
        return cls(
            kind=str(d.get("kind", "")),
            path=str(d.get("path", "")),
            layer=str(d.get("layer", "")),
            scope=str(d.get("scope", "")),
            node_run_id=str(d.get("node_run_id", "")),
            shard_id=str(d.get("shard_id", "")),
            item_id=str(d.get("item_id", "")),
            attempt=int(d.get("attempt", 0)) if isinstance(d.get("attempt"), (int, float)) else 0,
            slot=str(d.get("slot", "")),
            size=int(d.get("size", 0)) if isinstance(d.get("size"), (int, float)) else 0,
            sha256=str(d.get("sha256", "")),
            written_at=str(d.get("written_at", "")),
        )

    def key_matches(self, k: StateKey) -> bool:
        """Does this entry correspond to the given StateKey? Compares by coordinates."""
        if self.layer != k.layer.value:
            return False
        if k.node_run_id and self.node_run_id != k.node_run_id:
            return False
        if k.shard_id and self.shard_id != k.shard_id:
            return False
        if k.item_id and self.item_id != k.item_id:
            return False
        if k.attempt and self.attempt != k.attempt:
            return False
        if k.slot and self.slot != k.slot:
            return False
        return True


class Index:
    """In-memory index. Persisted to `index.json` (or sharded jsonl for large runs)."""

    def __init__(self, entries: list[IndexEntry] | None = None) -> None:
        self._entries: list[IndexEntry] = list(entries or [])

    def __iter__(self) -> Iterator[IndexEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, entry: IndexEntry) -> None:
        # Replace any existing entry with the same path; entries are point-in-time.
        self._entries = [e for e in self._entries if e.path != entry.path]
        self._entries.append(entry)

    def remove_by_path(self, path: str) -> None:
        self._entries = [e for e in self._entries if e.path != path]

    def query(
        self,
        *,
        layer: Layer | str | None = None,
        scope: Scope | str | None = None,
        kind: str | None = None,
        node_run_id: str | None = None,
        shard_id: str | None = None,
        item_id: str | None = None,
        slot: str | None = None,
    ) -> list[IndexEntry]:
        layer_v = layer.value if isinstance(layer, Layer) else layer
        scope_v = scope.value if isinstance(scope, Scope) else scope
        out: list[IndexEntry] = []
        for e in self._entries:
            if layer_v is not None and e.layer != layer_v:
                continue
            if scope_v is not None and e.scope != scope_v:
                continue
            if kind is not None and e.kind != kind:
                continue
            if node_run_id is not None and e.node_run_id != node_run_id:
                continue
            if shard_id is not None and e.shard_id != shard_id:
                continue
            if item_id is not None and e.item_id != item_id:
                continue
            if slot is not None and e.slot != slot:
                continue
            out.append(e)
        return out

    def find_for_key(self, key: StateKey) -> IndexEntry | None:
        for e in self._entries:
            if e.key_matches(key):
                return e
        return None

    def save(self, path: Path, *, run_id: str, state_root_rel: str = ".") -> None:
        data = {
            "schema_version": 1,
            "run_id": run_id,
            "state_root_rel": state_root_rel,
            "entries": [e.to_dict() for e in self._entries],
        }
        atomic_write_json(path, data)

    @classmethod
    def load(cls, path: Path) -> tuple[str, str, list[IndexEntry]]:
        """Load `index.json`. Returns (run_id, state_root_rel, entries)."""
        if not path.exists():
            return ("", ".", [])
        import json as _json

        raw = _json.loads(path.read_text(encoding="utf-8"))
        entries = [IndexEntry.from_dict(d) for d in raw.get("entries", [])]
        return (str(raw.get("run_id", "")), str(raw.get("state_root_rel", ".")), entries)

    @classmethod
    def load_sharded(cls, root: Path) -> tuple[str, str, list[IndexEntry]]:
        """Load sharded `index/entries-*.jsonl` if present, else fall back to index.json."""
        shard_dir = root / "index"
        if shard_dir.exists():
            all_entries: list[IndexEntry] = []
            run_id = ""
            state_root_rel = "."
            for shard in sorted(shard_dir.glob("entries-*.jsonl")):
                for rec in read_jsonl(shard):
                    if rec.get("run_id") and not run_id:
                        run_id = str(rec.get("run_id"))
                    if rec.get("state_root_rel") and state_root_rel == ".":
                        state_root_rel = str(rec.get("state_root_rel", "."))
                    if "entries" in rec and isinstance(rec["entries"], list):
                        for e in rec["entries"]:
                            if isinstance(e, dict):
                                all_entries.append(IndexEntry.from_dict(e))
                    elif "kind" in rec:
                        all_entries.append(IndexEntry.from_dict(rec))
            return (run_id, state_root_rel, all_entries)
        return cls.load(root / "index.json")

    def to_json(self) -> str:
        return json.dumps([e.to_dict() for e in self._entries], indent=2, default=str)


__all__ = ["Index", "IndexEntry"]
