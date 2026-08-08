"""Envelope: the uniform wrapper around every JSON object the StateStore writes.

    {
      "kind": "session_result",
      "schema_version": 2,
      "key": { ...StateKey dict... },
      "written_by": {"role": "agent", "session_id": "...", "backend": "...", "model": "..."},
      "written_at": "2026-08-07T09:41:22Z",
      "body": { ... user content ... }
    }

`written_by` / `written_at` / `key` are added by the store; the caller supplies
`kind` and `body`. When an Agent writes `result.json` directly (without going
through the CLI), the reader calls `normalize_envelope()` to wrap the bare body
and marks the journal entry `unwrapped`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .key import StateKey
from .schema import SCHEMA_REGISTRY, migrate, validate


@dataclass(frozen=True)
class Envelope:
    kind: str
    schema_version: int
    key: StateKey
    written_by: dict[str, str] = field(default_factory=dict)
    written_at: str = ""
    body: dict[str, Any] = field(default_factory=dict)
    unwrapped: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "schema_version": self.schema_version,
            "key": self.key.to_dict(),
            "written_by": dict(self.written_by),
            "written_at": self.written_at,
            "body": dict(self.body),
        }
        if self.unwrapped:
            d["unwrapped"] = True
        return d


def now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_envelope(
    *,
    kind: str,
    key: StateKey,
    body: dict[str, Any],
    written_by: dict[str, str] | None = None,
    written_at: str | None = None,
) -> Envelope:
    """Build an envelope, stamping `written_at` and the known schema_version for `kind`."""
    version = SCHEMA_REGISTRY.get(kind).version if SCHEMA_REGISTRY.has(kind) else 1
    return Envelope(
        kind=kind,
        schema_version=version,
        key=key,
        written_by=dict(written_by) if written_by else {},
        written_at=written_at or now_iso(),
        body=dict(body),
    )


def normalize_envelope(
    raw: dict[str, Any], *, expected_key: StateKey | None = None
) -> tuple[Envelope, list[str]]:
    """Coerce a raw dict into an Envelope. Returns (envelope, validation_errors).

    Three input shapes are accepted:
      1. Full envelope (has `kind` + `body`): migrated in-memory and validated.
      2. Bare body (no `kind`): treated as `session_result` if `expected_key.slot`
         is "result", otherwise the kind is inferred from slot. Marked unwrapped.
      3. Body with `schema_version` but missing `body` wrapper: promoted.

    `validation_errors` is non-empty only when the body fails its schema.
    """
    errors: list[str] = []
    if isinstance(raw, dict) and "kind" in raw and "body" in raw:
        kind = str(raw["kind"])
        body = dict(raw["body"])
        body["schema_version"] = raw.get("schema_version", 1)
        body = migrate(kind, body)
        errors = validate(kind, body)
        # Build envelope. If the caller didn't pass a key, try to read it from the raw.
        key = expected_key
        if key is None:
            kd = raw.get("key")
            if isinstance(kd, dict):
                try:
                    key = StateKey.from_dict(kd)
                except Exception:
                    key = None
        if key is None:
            raise ValueError("envelope missing key and no expected_key supplied")
        env = Envelope(
            kind=kind,
            schema_version=body.get("schema_version", 1)
            if isinstance(body.get("schema_version"), int)
            else 1,
            key=key,
            written_by=dict(raw.get("written_by") or {})
            if isinstance(raw.get("written_by"), dict)
            else {},
            written_at=str(raw.get("written_at") or ""),
            body=body,
            unwrapped=bool(raw.get("unwrapped")),
        )
        return env, errors

    # Bare body path: infer kind from slot.
    slot = expected_key.slot if expected_key else ""
    kind = "session_result" if slot == "result" else slot or "unknown"
    body = dict(raw)
    body["schema_version"] = (
        body.get("schema_version", 1) if isinstance(body.get("schema_version"), int) else 1
    )
    body = migrate(kind, body)
    errors = validate(kind, body)
    if expected_key is None:
        raise ValueError("bare body requires expected_key to stamp the envelope")
    env = Envelope(
        kind=kind,
        schema_version=body.get("schema_version", 1)
        if isinstance(body.get("schema_version"), int)
        else 1,
        key=expected_key,
        written_by={},
        written_at="",
        body=body,
        unwrapped=True,
    )
    return env, errors


def register_schema(
    kind: str,
    version: int,
    schema: dict[str, Any],
    migrations: dict[int, Any] | None = None,
) -> None:
    """Convenience proxy for SCHEMA_REGISTRY.register (re-exported here for ergonomics)."""
    SCHEMA_REGISTRY.register(
        kind,
        version,
        schema,
        migrations,
    )


__all__ = [
    "Envelope",
    "make_envelope",
    "normalize_envelope",
    "now_iso",
    "register_schema",
]
