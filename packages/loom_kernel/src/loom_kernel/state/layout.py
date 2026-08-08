"""Pure layout function: StateKey -> relative POSIX path.

**This is the only path-construction logic in the kernel.** All other modules
obtain paths via `StateStore.path(key)`, which calls `layout()` here. The CI
path-concatenation guard (T0.4) forbids raw `Path(...) /` usage outside this
file and the store.

Path shape (all relative to the state root):

    run.json
    index.json
    journal.jsonl
    control/
        plan.json
        cursor.json                       # run-level cursor
        cursor-<shard_id>.json            # shard-level cursor
        items.jsonl                       # bulk item ledger (optional)
        items/<item_id>.json              # single item orchestrator view
        nodes/<node_run_id>/
            node.json                     # NodeDef instance static payload
            context.json                  # resolved NodeContext snapshot
            latest_attempt                # text: "attempt-3"
    contract/
        <node_run_id>/
            attempt-<n>/
                task_card.json
                result.json
                claim.json
                _meta.json
    scratch/
        <node_run_id>/attempt-<n>/        # directory; arbitrary contents
    artifact/
        run/<slot>.<ext>                  # ext folded into slot for now
        shards/<shard_id>/<slot>.<ext>
        items/<item_id>/
            <slot>.<ext>
            _meta.json
    log/
        <node_run_id>/attempt-<n>/
            transcript.jsonl
            commands.log
            progress.jsonl

`<ext>` is the extension encoded in `slot` (e.g. slot="summary" → ext implicit
".json" by convention; the store uses `slot` as the filename and lets the caller
control bytes). For artifacts, callers may pass `slot="summary.md"` to pin ext.

ID sanitization: `item_id` / `node_run_id` / `shard_id` are validated to be safe
path segments in `StateKey`. Layout does not re-sanitize — the invariant is that
the key is already valid. Long IDs and non-ASCII are passed through; filesystems
support them and we do not want to destroy information.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .key import StateKey


class PurePosixPath(str):
    """A relative POSIX path string. Use PurePath-style joins via `/`.

    We deliberately use a thin str subclass rather than `pathlib.PurePosixPath`
    because the latter mangles trailing separators and complicates equality in
    snapshot tests. Layout output is a normalized string; `StateStore.path()`
    converts to an OS path at the boundary.
    """


def _join(*parts: str) -> PurePosixPath:
    """Join posix parts, collapsing repeated slashes and dropping empties."""
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        for seg in p.split("/"):
            if seg:
                out.append(seg)
    return PurePosixPath("/".join(out))


_KNOWN_EXTS: dict[str, str] = {
    "transcript": "transcript.jsonl",
    "progress": "progress.jsonl",
    "commands": "commands.log",
    "items": "items.jsonl",
}


def _ext_for_slot(slot: str) -> str:
    """Return the file name for a slot. Preserves explicit extensions; maps known slots."""
    if "." in slot:
        return slot
    if slot in _KNOWN_EXTS:
        return _KNOWN_EXTS[slot]
    return f"{slot}.json"


def layout(key: StateKey) -> PurePosixPath:
    """Pure function: map a StateKey to a relative POSIX path under the state root.

    Pure: no I/O, no filesystem. Snapshot tests pin every combination.
    """
    layer = key.layer
    scope = key.scope
    slot = key.slot
    nrid = key.node_run_id or ""
    shid = key.shard_id or ""
    iid = key.item_id or ""
    att = key.attempt

    if layer.value == "control":
        if scope.value == "run":
            # Run-scoped control files. slot names a known file.
            if slot == "run":
                return PurePosixPath("run.json")
            if slot == "plan":
                return PurePosixPath("control/plan.json")
            if slot == "cursor":
                return PurePosixPath("control/cursor.json")
            if slot == "items":
                return PurePosixPath("control/items.jsonl")
            if slot == "index_root":
                return PurePosixPath("index.json")
            if slot == "journal":
                return PurePosixPath("journal.jsonl")
            # Unknown run-slot: place under control/ with the slot name.
            return _join("control", _ext_for_slot(slot))
        if scope.value == "shard":
            if slot == "cursor":
                return _join("control", f"cursor-{shid}.json")
            return _join("control", "shards", shid, _ext_for_slot(slot))
        if scope.value == "node":
            if slot == "latest_attempt":
                return _join("control", "nodes", nrid, "latest_attempt")
            if slot == "node":
                return _join("control", "nodes", nrid, "node.json")
            if slot == "context":
                return _join("control", "nodes", nrid, "context.json")
            return _join("control", "nodes", nrid, _ext_for_slot(slot))
        if scope.value == "item":
            return _join("control", "items", iid, _ext_for_slot(slot or "item"))
        raise ValueError(f"control layer does not support scope={scope.value}")

    if layer.value == "contract":
        # contract always: contract/<node_run_id>/attempt-<n>/<slot>.json
        fname = _ext_for_slot(slot if slot else "result")
        return _join("contract", nrid, f"attempt-{att}", fname)

    if layer.value == "scratch":
        # scratch root is a directory; we return the directory path.
        # The store exposes open_scratch() that materializes it.
        return _join("scratch", nrid, f"attempt-{att}")

    if layer.value == "log":
        fname = _ext_for_slot(slot)
        return _join("log", nrid, f"attempt-{att}", fname)

    if layer.value == "artifact":
        if scope.value == "run":
            return _join("artifact", "run", _ext_for_slot(slot))
        if scope.value == "shard":
            return _join("artifact", "shards", shid, _ext_for_slot(slot))
        if scope.value == "item":
            fname = _ext_for_slot(slot)
            return _join("artifact", "items", iid, fname)
        raise ValueError(f"artifact layer does not support scope={scope.value}")

    raise ValueError(f"unknown layer: {layer!r}")


__all__ = ["PurePosixPath", "layout"]
