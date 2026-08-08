"""Review SPI: Finding / ScanContext / Scanner / IntentDiffProvider.

Kernel E (design §8.2) models per-item review as a domain-agnostic capability:
mechanical scanners produce `Finding`s; an `IntentDiffProvider` supplies the
two panes of the intent-vs-outcome comparison. Domains implement these
protocols; the kernel/server/front-end consume them without knowing the domain.

Everything here is pure data + Protocols — no I/O, no domain symbols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .planning.item import WorkItem

#: Closed severity set, ordered by signal value. `error` blocks auto-approval;
#: `warning` needs a human glance; `info` is noise worth keeping.
FINDING_SEVERITIES: frozenset[str] = frozenset({"info", "warning", "error"})


@dataclass(frozen=True)
class Finding:
    """One mechanical-scan finding about one item (design §8.2).

    `locator` points at the evidence: free-form coordinates such as
    ``{"path": "...", "line": 3}`` or ``{"event_index": 1}`` — the domain picks,
    the UI renders it opaquely.
    """

    code: str  # machine-readable finding kind, e.g. "empty_summary"
    severity: str  # one of FINDING_SEVERITIES
    message: str  # human-readable one-liner
    locator: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("Finding.code must be non-empty")
        if self.severity not in FINDING_SEVERITIES:
            raise ValueError(
                f"Finding.severity {self.severity!r} not known; known: {sorted(FINDING_SEVERITIES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "locator": dict(self.locator),
        }


@dataclass(frozen=True)
class ScanContext:
    """Pure-data context handed to scanners.

    `refs` carries domain-declared reference data a scanner may consult (e.g.
    the canon entity list for novel_digest). Keeping it a plain dict keeps the
    kernel agnostic of what references mean.
    """

    run_id: str = ""
    workspace_root: str = ""
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workspace_root": self.workspace_root,
            "refs": dict(self.refs),
        }


@runtime_checkable
class Scanner(Protocol):
    """SPI: one mechanical check over one item's digested product.

    `chapter` is the parsed per-item product document (novel_digest: the
    chapter digest JSON body); None means the product is missing entirely —
    scanners should report that rather than assume presence.
    """

    code: str  # finding code this scanner emits

    def scan(
        self, item: WorkItem, chapter: dict[str, Any] | None, ctx: ScanContext
    ) -> list[Finding]: ...


class IntentDiffProvider(Protocol):
    """SPI: supplies the two panes of the per-item intent diff (design §8.2).

    Left pane = the intent/input side (novel_digest: the original chapter
    excerpt); right pane = the outcome side (the generated summary). Returning
    None means "unavailable" — the UI shows an empty placeholder, and the
    acceptance check "both sides retrievable" fails loudly.
    """

    def intent(self, item: WorkItem) -> str | None: ...

    def outcome(self, item: WorkItem) -> str | None: ...


__all__ = [
    "FINDING_SEVERITIES",
    "Finding",
    "IntentDiffProvider",
    "ScanContext",
    "Scanner",
]
