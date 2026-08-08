"""StateStore: the public API surface for all state I/O.

This is the **single** place business code may obtain a filesystem path.
`path(key)` is the only path-producing entry point; the path-concatenation
guard (T0.4) forbids raw `Path(...) /` usage outside `layout.py` and this module.

The store is synchronous: the kernel is I/O-bound but small. Concurrency lives
at the orchestration layer (each shard has an isolated subtree, so writes from
parallel shards never collide — see state_layer_architecture.md §7.2).

Attempt isolation is structural: `scratch/<node_run_id>/attempt-<n>/` directories
are independent by construction. `RetryPolicy` controls whether a new attempt
inherits the previous attempt's scratch contents.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .envelope import Envelope, make_envelope, normalize_envelope, now_iso
from .index import Index, IndexEntry
from .io import (
    append_jsonl,
    atomic_write_bytes,
    atomic_write_json,
    read_json,
)
from .journal import Journal
from .key import K, Layer, Scope, StateKey
from .layout import layout
from .retry import RetryPolicy
from .schema import SCHEMA_REGISTRY, migrate, validate


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to a written state object. Returned by every write call."""

    key: StateKey
    kind: str
    path: Path  # absolute
    rel: str  # relative to state root (POSIX)
    sha256: str
    size: int
    written_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key.to_dict(),
            "kind": self.kind,
            "path": self.rel,
            "sha256": self.sha256,
            "size": self.size,
            "written_at": self.written_at,
        }


class StateStore:
    """Synchronous store rooted at `<root>/state/`. Thread-safe within one process
    via the structural isolation of subtrees; cross-process safety is the caller's
    responsibility (the orchestrator serializes index updates).
    """

    def __init__(self, root: Path, *, run_id: str = "", readonly: bool = False) -> None:
        self.root = root.resolve()
        self.state_root = self.root / "state"
        self.run_id = run_id
        self.readonly = readonly
        self._index = Index()
        self._journal = Journal(self.state_root / "journal.jsonl")
        self._index_loaded = False
        self._init_dirs()

    # --- lifecycle ---
    def _init_dirs(self) -> None:
        for sub in ("control", "contract", "scratch", "artifact", "log"):
            (self.state_root / sub).mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_run(cls, run_root: Path, *, run_id: str = "", readonly: bool = False) -> StateStore:
        return cls(run_root, run_id=run_id, readonly=readonly)

    def relocate(self, new_root: Path) -> StateStore:
        """Return a new StateStore pointing at `new_root` with the same run_id.

        Does **not** move files on disk — the caller is expected to have copied or
        renamed the directory. Internal records are relative, so no rewriting is
        needed.
        """
        return StateStore(new_root, run_id=self.run_id, readonly=self.readonly)

    # --- path generation (the ONLY path entry point) ---
    def path(self, key: StateKey) -> Path:
        """Return the absolute OS path for `key`. Pure; no I/O, no side effects."""
        return self.state_root / Path(str(layout(key)))

    def rel(self, key: StateKey) -> str:
        return str(layout(key))

    # --- index / journal ---
    def _load_index(self) -> Index:
        if not self._index_loaded:
            _, _, entries = Index.load(self.state_root / "index.json")
            self._index = Index(entries)
            self._index_loaded = True
        return self._index

    @property
    def index(self) -> Index:
        return self._load_index()

    @property
    def journal(self) -> Journal:
        return self._journal

    def save_index(self) -> None:
        self.index.save(self.state_root / "index.json", run_id=self.run_id, state_root_rel=".")

    def _record_in_index(self, ref: ArtifactRef, *, written_at: str) -> None:
        entry = IndexEntry(
            kind=ref.kind,
            path=ref.rel,
            layer=ref.key.layer.value,
            scope=ref.key.scope.value,
            node_run_id=ref.key.node_run_id or "",
            shard_id=ref.key.shard_id or "",
            item_id=ref.key.item_id or "",
            attempt=ref.key.attempt or 0,
            slot=ref.key.slot or "",
            size=ref.size,
            sha256=ref.sha256,
            written_at=written_at,
        )
        self._load_index().add(entry)

    # --- JSON read / write ---
    def read_json(self, key: StateKey) -> dict[str, Any] | None:
        """Read a JSON object by key. Returns None if absent. Auto-migrates schema."""
        path = self.path(key)
        raw = read_json(path)
        if raw is None:
            return None
        # If it's an envelope, return the (migrated) body. If bare, return as-is.
        if isinstance(raw, dict) and "body" in raw and "kind" in raw:
            kind = str(raw.get("kind", ""))
            body = dict(raw.get("body", {}))
            if SCHEMA_REGISTRY.has(kind):
                body = migrate(kind, body)
            return body
        return raw

    def read_envelope(self, key: StateKey) -> Envelope | None:
        """Read the full envelope (with claim/written_by) for a key."""
        path = self.path(key)
        raw = read_json(path)
        if raw is None:
            return None
        env, _ = normalize_envelope(raw, expected_key=key)
        return env

    def write_json(
        self,
        key: StateKey,
        body: dict[str, Any],
        *,
        kind: str,
        written_by: dict[str, str] | None = None,
    ) -> ArtifactRef:
        """Write a JSON body wrapped in an envelope. Validates schema; rejects on failure."""
        if self.readonly:
            raise PermissionError(f"StateStore is readonly; cannot write {key}")
        # Validate first — reject before touching disk.
        body = dict(body)
        # Stamp the known schema_version onto the body before validation so callers
        # don't have to repeat it. The envelope also stores it for read-back.
        if SCHEMA_REGISTRY.has(kind):
            body["schema_version"] = SCHEMA_REGISTRY.get(kind).version
        errors = validate(kind, body)
        if errors:
            from .schema import SchemaError

            raise SchemaError(
                f"body fails schema for kind {kind!r}: {errors}",
                kind=kind,
                errors=errors,
            )
        envelope = make_envelope(
            kind=kind,
            key=key,
            body=body,
            written_by=written_by,
        )
        path = self.path(key)
        atomic_write_json(path, envelope.to_dict())
        ref = self._ref_for(key, kind, path, envelope.written_at)
        self._record_in_index(ref, written_at=envelope.written_at)
        self._journal.append_write(
            key=key,
            kind=kind,
            actor=written_by.get("role", "orchestrator") if written_by else "orchestrator",
            sha256=ref.sha256,
            nbytes=ref.size,
        )
        return ref

    def write_bytes(
        self, key: StateKey, data: bytes, *, kind: str, written_by: dict[str, str] | None = None
    ) -> ArtifactRef:
        """Write raw bytes (artifacts like diffs, prose, transcripts). No schema check."""
        if self.readonly:
            raise PermissionError(f"StateStore is readonly; cannot write {key}")
        path = self.path(key)
        atomic_write_bytes(path, data)
        written_at = now_iso()
        ref = self._ref_for_bytes(key, kind, path, data, written_at)
        self._record_in_index(ref, written_at=written_at)
        self._journal.append_write(
            key=key,
            kind=kind,
            actor=written_by.get("role", "orchestrator") if written_by else "orchestrator",
            sha256=ref.sha256,
            nbytes=ref.size,
        )
        return ref

    def append_jsonl(self, key: StateKey, obj: dict[str, Any]) -> None:
        """Append a a JSONL file (transcript / progress / journal)."""
        if self.readonly:
            raise PermissionError(f"StateStore is readonly; cannot append {key}")
        path = self.path(key)
        append_jsonl(path, obj)
        # Best-effort index entry: the file is append-only, so we update size lazily.
        existing = self._load_index().find_for_key(key)
        size = (existing.size + 1) if existing else 1
        entry = IndexEntry(
            kind="jsonl",
            path=self.rel(key),
            layer=key.layer.value,
            scope=key.scope.value,
            node_run_id=key.node_run_id or "",
            shard_id=key.shard_id or "",
            item_id=key.item_id or "",
            attempt=key.attempt or 0,
            slot=key.slot or "",
            size=size,
        )
        self._load_index().add(entry)

    def _ref_for(self, key: StateKey, kind: str, path: Path, written_at: str) -> ArtifactRef:
        data = path.read_bytes()
        return self._ref_for_bytes(key, kind, path, data, written_at)

    def _ref_for_bytes(
        self,
        key: StateKey,
        kind: str,
        path: Path,
        data: bytes,
        written_at: str,
    ) -> ArtifactRef:
        sha = hashlib.sha256(data).hexdigest()
        return ArtifactRef(
            key=key,
            kind=kind,
            path=path,
            rel=self.rel(key),
            sha256=sha,
            size=len(data),
            written_at=written_at,
        )

    # --- scratch / attempt ---
    def open_scratch(self, node_run_id: str, attempt: int) -> Path:
        """Return the scratch directory for this node/attempt, creating it if needed.

        The caller (the runner) is responsible for honoring `RetryPolicy`:
        - FRESH: just mkdir (default here).
        - INHERIT: copy the previous attempt's scratch into this one (call `inherit_scratch`).
        - LINK: set up a read-only overlay (caller's responsibility; platform-specific).
        """
        key = K.scratch_root(node_run_id, attempt)
        path = self.path(key)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def clear_scratch(self, node_run_id: str, attempt: int) -> None:
        """Remove all contents of a scratch dir (FRESH policy)."""
        path = self.path(K.scratch_root(node_run_id, attempt))
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    def inherit_scratch(self, node_run_id: str, attempt: int) -> Path:
        """Copy the previous attempt's scratch into the new attempt's directory."""
        if attempt <= 1:
            return self.open_scratch(node_run_id, attempt)
        prev = self.path(K.scratch_root(node_run_id, attempt - 1))
        cur = self.path(K.scratch_root(node_run_id, attempt))
        cur.mkdir(parents=True, exist_ok=True)
        if prev.exists():
            for entry in prev.iterdir():
                target = cur / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(entry, target)
        return cur

    def latest_attempt(self, node_run_id: str) -> int:
        """Return the highest attempt number that has a contract dir, or 0 if none."""
        contract_dir = self.state_root / "contract" / node_run_id
        if not contract_dir.exists():
            return 0
        best = 0
        for child in contract_dir.iterdir():
            if child.is_dir() and child.name.startswith("attempt-"):
                try:
                    n = int(child.name.removeprefix("attempt-"))
                    best = max(best, n)
                except ValueError:
                    continue
        return best

    def set_latest_attempt(self, node_run_id: str, attempt: int) -> None:
        """Write the `latest_attempt` pointer file under control/nodes/<nrid>/."""
        path = self.path(K.latest_attempt(node_run_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, f"attempt-{attempt}\n".encode())

    def read_latest_attempt_pointer(self, node_run_id: str) -> int | None:
        """Read the explicit pointer file. Returns None if not set."""
        path = self.path(K.latest_attempt(node_run_id))
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8").strip()
        if not text.startswith("attempt-"):
            return None
        try:
            return int(text.removeprefix("attempt-"))
        except ValueError:
            return None

    def begin_attempt(self, node_run_id: str, *, policy: RetryPolicy = RetryPolicy.FRESH) -> int:
        """Allocate a new attempt number and prepare its scratch dir per `policy`.

        Returns the new attempt number (1-based). Also creates the empty contract
        attempt directory so `latest_attempt()` reflects the new attempt immediately.
        """
        current = self.latest_attempt(node_run_id)
        next_attempt = current + 1
        if policy is RetryPolicy.FRESH:
            self.clear_scratch(node_run_id, next_attempt)
        elif policy is RetryPolicy.INHERIT:
            self.inherit_scratch(node_run_id, next_attempt)
        elif policy is RetryPolicy.LINK:
            # LINK is platform-specific; we just open the dir. Overlay setup is the
            # caller's responsibility (kernel provides the hook, domain implements it).
            self.open_scratch(node_run_id, next_attempt)
        else:  # pragma: no cover - exhaustive enum
            raise ValueError(f"unknown retry policy: {policy!r}")
        # Create the contract attempt directory so latest_attempt() sees the new attempt.
        contract_attempt = self.path(K.result(node_run_id, next_attempt)).parent
        contract_attempt.mkdir(parents=True, exist_ok=True)
        self.set_latest_attempt(node_run_id, next_attempt)
        return next_attempt

    # --- listing ---
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
    ) -> list[ArtifactRef]:
        """Query the index for matching ArtifactRefs."""
        out: list[ArtifactRef] = []
        for e in self._load_index().query(
            layer=layer,
            scope=scope,
            kind=kind,
            node_run_id=node_run_id,
            shard_id=shard_id,
            item_id=item_id,
            slot=slot,
        ):
            key = StateKey(
                Layer(e.layer),
                Scope(e.scope) if e.scope else Scope.NODE_RUN,
                node_run_id=e.node_run_id or None,
                shard_id=e.shard_id or None,
                item_id=e.item_id or None,
                attempt=e.attempt or None,
                slot=e.slot,
            )
            out.append(
                ArtifactRef(
                    key=key,
                    kind=e.kind,
                    path=self.state_root / Path(e.path),
                    rel=e.path,
                    sha256=e.sha256,
                    size=e.size,
                    written_at=e.written_at,
                )
            )
        return out

    # Note: the design doc refers to StateStore.list; we use `query` to avoid
    # shadowing the builtin `list` in type annotations. Callers wanting the
    # design-doc name can use `store.query(...)`.

    # --- GC / verify / archive ---
    def gc(self, *, layers: list[Layer | str]) -> int:
        """Delete the contents of the named layers (default scratch/log). Freed bytes returned.

        `control` / `contract` / `artifact` are never touched by GC — they are durable.
        """
        if self.readonly:
            raise PermissionError("StateStore is readonly; cannot gc")
        freed = 0
        layer_names = [l.value if isinstance(l, Layer) else l for l in layers]
        for name in layer_names:
            if name in ("control", "contract", "artifact"):
                continue
            d = self.state_root / name
            if not d.exists():
                continue
            for child in d.iterdir():
                freed += _tree_size(child)
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        self._journal.append_gc(layers=layer_names, freed_bytes=freed)
        return freed

    def verify(self) -> list[str]:
        """Verify every index entry's sha256 matches the file on disk. Returns problems."""
        problems: list[str] = []
        for e in self._load_index():
            p = self.state_root / Path(e.path)
            if not p.exists():
                problems.append(f"missing: {e.path}")
                continue
            if not p.is_file():
                continue
            data = p.read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if e.sha256 and actual != e.sha256:
                problems.append(f"sha256 mismatch: {e.path}")
        return problems

    def reindex(self) -> Index:
        """Rebuild the index by walking the tree. Existing index is discarded."""
        entries: list[IndexEntry] = []
        # Walk every layer's directory. For each file, derive a StateKey from the path
        # shape and (if present) the `_meta.json`/envelope metadata.
        for layer_name in ("control", "contract", "scratch", "artifact", "log"):
            base = self.state_root / layer_name
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.is_dir():
                    continue
                rel = str(path.relative_to(self.state_root)).replace("\\", "/")
                entry = _derive_index_entry(path, rel, layer_name)
                if entry is not None:
                    entries.append(entry)
        self._index = Index(entries)
        self._index_loaded = True
        self.save_index()
        return self._index


def _tree_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for child in p.iterdir():
        total += _tree_size(child)
    return total


def _derive_index_entry(path: Path, rel: str, layer_name: str) -> IndexEntry | None:
    """Best-effort IndexEntry from a file path. Used by reindex() only."""
    import hashlib as _h
    import json as _json

    data = path.read_bytes()
    sha = _h.sha256(data).hexdigest()
    size = len(data)
    kind = "unknown"
    written_at = ""

    # Try to read envelope metadata.
    try:
        obj = _json.loads(data.decode("utf-8"))
        if isinstance(obj, dict):
            if "kind" in obj:
                kind = str(obj["kind"])
            if "written_at" in obj:
                written_at = str(obj["written_at"])
    except (ValueError, UnicodeDecodeError):
        kind = "binary"

    # Parse coordinates from the relative path.
    scope = _scope_for_rel(layer_name, rel)
    coords = _coords_for_rel(layer_name, rel)

    return IndexEntry(
        kind=kind,
        path=rel,
        layer=layer_name,
        scope=scope,
        node_run_id=coords.get("node_run_id", ""),
        shard_id=coords.get("shard_id", ""),
        item_id=coords.get("item_id", ""),
        attempt=coords.get("attempt", 0),
        slot=coords.get("slot", ""),
        size=size,
        sha256=sha,
        written_at=written_at,
    )


def _scope_for_rel(layer: str, rel: str) -> str:
    parts = [p for p in rel.split("/") if p]
    if layer == "control":
        if parts and parts[0] == "nodes":
            return "node"
        if len(parts) >= 2 and parts[0] == "items":
            return "item"
        if len(parts) >= 2 and parts[0] == "shards":
            return "shard"
        return "run"
    if layer == "contract":
        return "node_run"
    if layer == "scratch":
        return "node_run"
    if layer == "log":
        return "node_run"
    if layer == "artifact":
        if len(parts) >= 2 and parts[0] == "run":
            return "run"
        if len(parts) >= 2 and parts[0] == "shards":
            return "shard"
        if len(parts) >= 2 and parts[0] == "items":
            return "item"
    return ""


def _coords_for_rel(layer: str, rel: str) -> dict[str, Any]:
    parts = [p for p in rel.split("/") if p]
    coords: dict[str, Any] = {}
    if layer in ("contract", "scratch", "log"):
        # <layer>/<node_run_id>/attempt-<n>/<file>
        if len(parts) >= 2:
            coords["node_run_id"] = parts[1]
        if len(parts) >= 3 and parts[2].startswith("attempt-"):
            try:
                coords["attempt"] = int(parts[2].removeprefix("attempt-"))
            except ValueError:
                pass
        if parts:
            coords["slot"] = Path(parts[-1]).stem
    elif layer == "control":
        if len(parts) >= 2 and parts[0] == "nodes":
            coords["node_run_id"] = parts[1]
            if len(parts) >= 3:
                coords["slot"] = Path(parts[-1]).stem
        elif len(parts) >= 2 and parts[0] == "items":
            coords["item_id"] = parts[1]
            if len(parts) >= 3:
                coords["slot"] = Path(parts[-1]).stem
            else:
                coords["slot"] = "item"
        elif len(parts) >= 2 and parts[0] == "shards":
            coords["shard_id"] = parts[1]
            coords["slot"] = Path(parts[-1]).stem
        else:
            coords["slot"] = Path(parts[-1]).stem
    elif layer == "artifact":
        if len(parts) >= 2 and parts[0] == "run":
            coords["slot"] = Path(parts[-1]).stem
        elif len(parts) >= 3 and parts[0] == "shards":
            coords["shard_id"] = parts[1]
            coords["slot"] = Path(parts[-1]).stem
        elif len(parts) >= 3 and parts[0] == "items":
            coords["item_id"] = parts[1]
            coords["slot"] = Path(parts[-1]).stem
    return coords


__all__ = ["ArtifactRef", "StateStore"]
