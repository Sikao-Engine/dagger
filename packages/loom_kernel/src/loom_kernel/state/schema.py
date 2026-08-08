"""Schema registry: kind -> (version, JSON Schema, migration functions).

Every JSON written by the StateStore carries a `kind` and `schema_version`.
Reading auto-upgrades old bodies to the current version in-memory (never
writes back). Writing validates against the registered JSON Schema, rejecting
malformed bodies with field-level errors — those rejections feed the retry
prompt so the Agent learns what was wrong.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class SchemaError(ValueError):
    """Raised when a body fails schema validation or migration."""

    def __init__(self, message: str, *, kind: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.errors = errors or []


@dataclass
class SchemaEntry:
    kind: str
    version: int
    schema: dict[str, Any]
    migrations: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = field(default_factory=dict)


class _SchemaRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, SchemaEntry] = {}

    def register(
        self,
        kind: str,
        version: int,
        schema: dict[str, Any],
        migrations: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
    ) -> SchemaEntry:
        if kind in self._entries and self._entries[kind].version > version:
            # Re-registering a lower version is a programming error.
            raise SchemaError(
                f"cannot downgrade {kind} to v{version} (already v{self._entries[kind].version})",
                kind=kind,
            )
        entry = SchemaEntry(
            kind=kind,
            version=version,
            schema=schema,
            migrations=migrations or {},
        )
        self._entries[kind] = entry
        return entry

    def get(self, kind: str) -> SchemaEntry:
        if kind not in self._entries:
            raise SchemaError(f"unknown kind: {kind!r}", kind=kind)
        return self._entries[kind]

    def has(self, kind: str) -> bool:
        return kind in self._entries

    def all(self) -> list[SchemaEntry]:
        return list(self._entries.values())


SCHEMA_REGISTRY = _SchemaRegistry()


def get_schema(kind: str) -> SchemaEntry:
    return SCHEMA_REGISTRY.get(kind)


def validate(kind: str, body: dict[str, Any]) -> list[str]:
    """Validate body against the schema for `kind`. Returns a list of error strings.

    Empty list = valid. We use jsonschema if the registered schema is a real
    JSON Schema; otherwise we fall back to a permissive check.
    """
    if not SCHEMA_REGISTRY.has(kind):
        # Unknown kinds go through "lenient mode": object only.
        if not isinstance(body, dict):
            return [f"body for kind {kind!r} must be a JSON object"]
        return []
    entry = SCHEMA_REGISTRY.get(kind)
    try:
        import jsonschema

        validator = jsonschema.Draft7Validator(entry.schema)
        errs = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
        return [_format_jsonschema_error(e) for e in errs]
    except ImportError:  # pragma: no cover - jsonschema is a declared dep
        return []


def migrate(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """Migrate a body up to the current schema version for `kind` (in-memory only)."""
    if not SCHEMA_REGISTRY.has(kind):
        return body
    entry = SCHEMA_REGISTRY.get(kind)
    current = body.get("schema_version", 1)
    if not isinstance(current, int):
        return body
    while current < entry.version:
        nxt = current + 1
        fn = entry.migrations.get(nxt)
        if fn is None:
            break
        body = fn(body)
        body["schema_version"] = nxt
        current = nxt
    return body


def _format_jsonschema_error(err: Any) -> str:
    path = ".".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, sort_keys=True)


__all__ = ["SCHEMA_REGISTRY", "SchemaEntry", "SchemaError", "get_schema", "migrate", "validate"]
