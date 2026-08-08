

"""ArtifactSpec / Slot / ArtifactStore: the domain-declared shape of per-item
artifacts and how the review UI should render them.

A domain declares its artifact shape once (in its SPI module) and the review
interface (`EvidenceViewer` on the web) consumes that spec to render the slots
without knowing the domain. This is the formalization of the loose
`artifact_spec() -> Any | None` stub on `DomainPlugin` (T7.1).

`ArtifactStore` is a thin Protocol over `StateStore`: every artifact lives
under `artifact/items/<item_id>/<slot>` and is reached via `StateStore.query`
or `StateStore.path`. The protocol exists so domain code can name the
capability; the kernel's `StateStore` is the only implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .key import K, StateKey
from .store import ArtifactRef, StateStore

# View modes the front-end understands. Kept as a closed set so a domain
# can't invent a view the UI can't render; new views are added here with a
# matching renderer in `web/src/core/components/review/`.
KNOWN_VIEWS: frozenset[str] = frozenset(
    {
        "prose",  # plain text / long form
        "markdown",  # rendered markdown
        "code",  # monospace + diff-friendly
        "json",  # pretty JSON object
        "json-table",  # array of objects as a table
        "list",  # bullet list of strings
        "diff",  # two-slot diff (left/right)
        "tabs",  # layout hint: render children as tabs
        "diff-grid",  # layout hint: side-by-side grid of slots
    }
)


@dataclass(frozen=True)
class Slot:
    """One artifact slot for one item, with a view hint for the UI.

    `name` matches the `StateKey.slot` the Agent writes. `view` must be one of
    `KNOWN_VIEWS` (validated at construction so a bad spec fails fast at
    domain-registration time, not at render time).
    """

    name: str
    label: str = ""
    view: str = "prose"
    description: str = ""
    optional: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Slot.name must be non-empty")
        if "/" in self.name or "\\" in self.name or self.name in (".", ".."):
            raise ValueError(f"Slot.name must be a safe path segment: {self.name!r}")
        if self.view not in KNOWN_VIEWS:
            raise ValueError(f"Slot.view {self.view!r} not known; known: {sorted(KNOWN_VIEWS)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label or self.name,
            "view": self.view,
            "description": self.description,
            "optional": self.optional,
        }


@dataclass(frozen=True)
class ArtifactSpec:
    """The domain-declared artifact shape: the slot list + a layout hint.

    `default_view` is a layout hint (`tabs` / `diff-grid` / `code`...) the
    front-end `EvidenceViewer` uses to pick the initial layout. Slots are
    rendered per their own `view`.
    """

    slots: tuple[Slot, ...] = ()
    default_view: str = "tabs"
    label: str = ""

    def __post_init__(self) -> None:
        if self.default_view not in KNOWN_VIEWS:
            raise ValueError(
                f"ArtifactSpec.default_view {self.default_view!r} not known; "
                f"known: {sorted(KNOWN_VIEWS)}"
            )
        names = [s.name for s in self.slots]
        if len(names) != len(set(names)):
            dups = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"slot names must be unique; dups: {dups}")

    def slot_for(self, name: str) -> Slot | None:
        for s in self.slots:
            if s.name == name:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": [s.to_dict() for s in self.slots],
            "default_view": self.default_view,
            "label": self.label,
        }


@runtime_checkable
class ArtifactStore(Protocol):
    """Capability protocol: read item-scoped artifacts.

    The kernel's `StateStore` satisfies this protocol. Domains that want a
    custom backing store (e.g. a remote blob store) implement this and supply
    it via their SPI; the kernel's REST surface only ever calls these methods.
    """

    def item_artifacts(self, run_id: str, item_id: str) -> list[ArtifactRef]: ...
    def artifact_bytes(self, ref: ArtifactRef) -> bytes: ...
    def artifact_key(self, item_id: str, slot: str) -> StateKey: ...


class StateStoreArtifactStore:
    """Adapter: exposes the `ArtifactStore` protocol over a `StateStore`.

    Path knowledge stays here (delegating to `K.artifact_item`), so callers
    of `ArtifactStore` never construct a `StateKey` themselves.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def item_artifacts(self, run_id: str, item_id: str) -> list[ArtifactRef]:
        # run_id is informational; the store is already rooted at the run.
        _ = run_id
        return self._store.query(layer="artifact", item_id=item_id)

    def artifact_bytes(self, ref: ArtifactRef) -> bytes:
        return ref.path.read_bytes()

    def artifact_key(self, item_id: str, slot: str) -> StateKey:
        return K.artifact_item(item_id, slot)


def group_refs_by_slot(
    refs: Iterable[ArtifactRef], spec: ArtifactSpec | None
) -> list[dict[str, Any]]:
    """Group `ArtifactRef`s by `slot`, intersecting with the declared spec.

    - Slots declared in the spec appear even if no artifact exists yet (the UI
      shows an empty placeholder so reviewers see what's missing).
    - Declared slots are ordered by the spec; unknown slots (the Agent wrote
      to a slot the spec doesn't list) are appended at the end, flagged
      `undeclared: True` so the UI can highlight the spec drift.
    """
    by_slot: dict[str, ArtifactRef] = {}
    for r in refs:
        by_slot[r.key.slot] = r

    out: list[dict[str, Any]] = []
    if spec:
        for s in spec.slots:
            ref = by_slot.pop(s.name, None)
            out.append(
                {
                    "slot": s.to_dict(),
                    "ref": ref.to_dict() if ref else None,
                    "undeclared": False,
                }
            )
    for slot_name, ref in by_slot.items():
        out.append(
            {
                "slot": {
                    "name": slot_name,
                    "label": slot_name,
                    "view": "code",
                    "description": "",
                    "optional": True,
                },
                "ref": ref.to_dict(),
                "undeclared": True,
            }
        )
    return out


__all__ = [
    "KNOWN_VIEWS",
    "ArtifactSpec",
    "ArtifactStore",
    "Slot",
    "StateStoreArtifactStore",
    "group_refs_by_slot",
]
