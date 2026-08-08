"""StateStore: the single source of truth for runtime artifacts.

Five-layer model: `control` / `contract` / `scratch` / `artifact` / `log`.
Each layer has one owner, distinct mutability, distinct GC policy.

This module's public API is the **only** path-handling surface business code may
touch. Path concatenation outside `layout.py` is a violation enforced by CI.
"""

from __future__ import annotations

from . import schemas as _schemas  # noqa: F401 — imports register built-in kinds
from .artifact_spec import (
    KNOWN_VIEWS,
    ArtifactSpec,
    ArtifactStore,
    Slot,
    StateStoreArtifactStore,
    group_refs_by_slot,
)
from .envelope import Envelope, normalize_envelope, register_schema
from .index import Index, IndexEntry
from .io import atomic_write_bytes, atomic_write_json, read_json, read_jsonl
from .journal import Journal, JournalEntry
from .key import K, Layer, Scope, StateKey, StateKeyError
from .layout import PurePosixPath, layout
from .retry import RetryPolicy
from .schema import SCHEMA_REGISTRY, SchemaError, get_schema
from .store import StateStore

__all__ = [
    "KNOWN_VIEWS",
    "SCHEMA_REGISTRY",
    "ArtifactSpec",
    "ArtifactStore",
    "Envelope",
    "Index",
    "IndexEntry",
    "Journal",
    "JournalEntry",
    "K",
    "Layer",
    "PurePosixPath",
    "RetryPolicy",
    "SchemaError",
    "Scope",
    "Slot",
    "StateKey",
    "StateKeyError",
    "StateStore",
    "StateStoreArtifactStore",
    "atomic_write_bytes",
    "atomic_write_json",
    "get_schema",
    "group_refs_by_slot",
    "layout",
    "normalize_envelope",
    "read_json",
    "read_jsonl",
    "register_schema",
]
