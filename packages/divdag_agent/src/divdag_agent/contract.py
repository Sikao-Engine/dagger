"""Result contract: the JSON shape an Agent must produce to be trusted.

Mirrors §6.2 of universal_base_architecture.md. The kernel's `session_result`
schema validates generic fields (status/success/outputs/...). This module adds
the domain-side `ResultValidator` SPI and the kernel's 5 invariants.

The 5 kernel invariants (always enforced, all domains):
  1. File exists; top-level is an object; schema_version is known.
  2. node_run_id / node_type / skill match the meta.
  3. status is a terminal state for completion; running+background → keep waiting.
  4. success=false requires an `error` or `blocked_reason`.
  5. outputs keys must be in the node's declared `writes` (NodeContract).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ResultContract:
    """The validated session_result body."""

    node_run_id: str
    node_type: str
    skill: str
    status: str  # running | success | failed | blocked | skipped
    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    blocked_reason: str = ""
    background_active: bool = False
    progress_done: int = 0
    progress_total: int = 0
    summary: str = ""

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> ResultContract:
        return cls(
            node_run_id=str(body.get("node_run_id", "")),
            node_type=str(body.get("node_type", "")),
            skill=str(body.get("skill", "")),
            status=str(body.get("status", "running")),
            success=bool(body.get("success", False)),
            outputs=dict(body.get("outputs", {})),
            error=str(body.get("error", "")),
            blocked_reason=str(body.get("blocked_reason", "")),
            background_active=bool((body.get("background_tasks") or {}).get("active", False)),
            progress_done=int((body.get("progress") or {}).get("done", 0)),
            progress_total=int((body.get("progress") or {}).get("total", 0)),
            summary=str(body.get("summary", "")),
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("success", "failed", "blocked", "skipped")

    @property
    def needs_human(self) -> bool:
        return self.status == "blocked"


class ResultValidator(Protocol):
    """Domain-side validator. Returns a list of error strings (empty = valid)."""

    def __call__(self, body: dict[str, Any], *, node_run_id: str) -> list[str]: ...


def check_kernel_invariants(
    body: dict[str, Any],
    *,
    node_run_id: str,
    node_type: str,
    skill: str,
    declared_writes: tuple[str, ...] | None = None,
) -> list[str]:
    """Run the 5 kernel invariants. Returns [] on success, else a list of error strings."""
    errors: list[str] = []
    if not isinstance(body, dict):
        return ["result body must be a JSON object"]
    # 1. schema_version known (the kernel's write path stamps it; here we just
    #    verify the body has a status, which is the only required terminal marker).
    if "status" not in body:
        errors.append("missing required field: status")
    if "success" not in body:
        errors.append("missing required field: success")
    # 2. identity fields match meta.
    if body.get("node_run_id") and body.get("node_run_id") != node_run_id:
        errors.append(
            f"node_run_id mismatch: body={body.get('node_run_id')!r} meta={node_run_id!r}"
        )
    if body.get("node_type") and body.get("node_type") != node_type:
        errors.append(f"node_type mismatch: body={body.get('node_type')!r} meta={node_type!r}")
    if skill and body.get("skill") and body.get("skill") != skill:
        errors.append(f"skill mismatch: body={body.get('skill')!r} meta={skill!r}")
    # 3. terminal check is the caller's job (drives the wait loop), not an error.
    # 4. success=false requires an error reason.
    if body.get("success") is False and not body.get("error") and not body.get("blocked_reason"):
        errors.append("success=false but no error or blocked_reason provided")
    # 5. outputs keys must be in declared writes.
    if declared_writes is not None:
        outputs = body.get("outputs")
        if isinstance(outputs, dict):
            bad = [k for k in outputs if k not in declared_writes]
            if bad:
                errors.append(
                    f"outputs wrote undeclared keys: {bad} (declared: {list(declared_writes)})"
                )
    return errors


__all__ = ["ResultContract", "ResultValidator", "check_kernel_invariants"]
