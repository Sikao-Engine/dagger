"""Built-in state schemas, registered at kernel import time.

These are the kernels' own contract kinds: `session_result`, `task_card`,
`claim`, `cursor`, `plan`. Domain plugins register their own kinds via
`register_schema()` in their SPI module.
"""

from __future__ import annotations

from typing import Any

from .schema import SCHEMA_REGISTRY


def _session_result_v1_to_v2(body: dict[str, Any]) -> dict[str, Any]:
    """Promote a v1 session_result body to v2: add progress + rename artifacts -> outputs."""
    body.setdefault("progress", {"done": 0, "total": 0})
    if "artifacts" in body and "outputs" not in body:
        body["outputs"] = body.pop("artifacts")
    elif "outputs" not in body:
        body["outputs"] = {}
    return body


# --- session_result (the Agent-facing result contract) ----------------------
# Mirrors §6.2 of universal_base_architecture.md.
SCHEMA_REGISTRY.register(
    "session_result",
    version=2,
    schema={
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["status", "success", "schema_version"],
        "properties": {
            "schema_version": {"type": "integer", "const": 2},
            "node_run_id": {"type": "string"},
            "node_type": {"type": "string"},
            "skill": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["running", "success", "failed", "blocked", "skipped"],
            },
            "success": {"type": "boolean"},
            "error": {"type": "string"},
            "blocked_reason": {"type": "string"},
            "background_tasks": {
                "type": "object",
                "properties": {
                    "active": {"type": "boolean"},
                    "pending_count": {"type": "integer", "minimum": 0},
                    "description": {"type": "string"},
                },
            },
            "progress": {
                "type": "object",
                "properties": {
                    "done": {"type": "integer", "minimum": 0},
                    "total": {"type": "integer", "minimum": 0},
                },
            },
            "outputs": {"type": "object"},
            "finished_at": {"type": "string"},
            "summary": {"type": "string"},
        },
    },
    migrations={
        2: _session_result_v1_to_v2,
    },
)

# --- task_card (orchestrator's structured input to the Agent) ---------------
SCHEMA_REGISTRY.register(
    "task_card",
    version=1,
    schema={
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["node", "attempt", "write_targets"],
        "properties": {
            "node": {"type": "string"},
            "shard": {"type": "string"},
            "attempt": {"type": "integer", "minimum": 1},
            "items": {"type": "array"},
            "workspace": {"type": "object"},
            "references": {"type": "array"},
            "write_targets": {"type": "object"},
            "artifact_slots": {"type": "array"},
            "success_criterion": {"type": "string"},
            "forbidden": {"type": "array", "items": {"type": "string"}},
            "previous_attempt": {"type": "object"},
        },
    },
    migrations=None,
)

# --- claim (who wrote what, when) --------------------------------------------
SCHEMA_REGISTRY.register(
    "claim",
    version=1,
    schema={
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["role", "backend"],
        "properties": {
            "role": {"type": "string"},
            "session_id": {"type": "string"},
            "backend": {"type": "string"},
            "model": {"type": "string"},
            "started_at": {"type": "string"},
            "finished_at": {"type": "string"},
        },
    },
)

# --- cursor (run/shard progress pointer) ------------------------------------
SCHEMA_REGISTRY.register(
    "cursor",
    version=1,
    schema={
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["updated_at"],
        "properties": {
            "run_id": {"type": "string"},
            "shard_id": {"type": "string"},
            "cursor_item_id": {"type": "string"},
            "cursor_seq": {"type": "integer", "minimum": 0},
            "updated_at": {"type": "string"},
        },
    },
)

# --- plan (control layer) ----------------------------------------------------
SCHEMA_REGISTRY.register(
    "plan",
    version=1,
    schema={
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "shards": {"type": "array"},
            "items": {"type": "array"},
            "created_at": {"type": "string"},
        },
    },
)

__all__ = ["SCHEMA_REGISTRY"]
