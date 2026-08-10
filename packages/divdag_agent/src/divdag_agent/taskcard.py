"""TaskCard: structured input to an Agent, replacing the old "huge prompt with paths".

The orchestrator writes `contract/<nrid>/attempt-<n>/task_card.json` before
dispatching a node. The prompt shrinks to: "read `<task_card_path>`, do what it
says, write to `write_targets.result` when done."

This decouples layout changes from prompt text. A layout change is zero prompt
edits; the prompt only ever references the single task_card path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskCard:
    """The structured per-attempt input to an Agent node."""

    node: str
    shard: str = ""
    attempt: int = 1
    items: list[dict[str, Any]] = field(default_factory=list)
    workspace: dict[str, str] = field(default_factory=dict)
    references: list[dict[str, str]] = field(default_factory=list)
    write_targets: dict[str, str] = field(default_factory=dict)
    artifact_slots: list[dict[str, str]] = field(default_factory=list)
    success_criterion: str = ""
    forbidden: list[str] = field(default_factory=list)
    previous_attempt: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "node": self.node,
            "shard": self.shard,
            "attempt": self.attempt,
            "items": list(self.items),
            "workspace": dict(self.workspace),
            "references": list(self.references),
            "write_targets": dict(self.write_targets),
            "artifact_slots": list(self.artifact_slots),
            "success_criterion": self.success_criterion,
            "forbidden": list(self.forbidden),
        }
        if self.previous_attempt is not None:
            body["previous_attempt"] = dict(self.previous_attempt)
        if self.extra:
            body["extra"] = dict(self.extra)
        return body


def render_task_card_prompt(card_path: str) -> str:
    """The one-line prompt: just point the Agent at the task card.

    Layout changes need zero prompt edits because the only path the prompt
    mentions is the task card path.
    """
    return (
        f"读取 task card：`{card_path}`，按其中 `write_targets` 写入结果文件，"
        f"完成判据见 `success_criterion`。"
    )


__all__ = ["TaskCard", "render_task_card_prompt"]
