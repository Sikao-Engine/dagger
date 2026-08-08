"""T7.1: ArtifactSpec / Slot / ArtifactStore unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from loom_kernel.state import (
    ArtifactSpec,
    K,
    Slot,
    StateStore,
    StateStoreArtifactStore,
    group_refs_by_slot,
)


def test_slot_rejects_unknown_view() -> None:
    with pytest.raises(ValueError, match="not known"):
        Slot(name="x", view="hologram")


def test_slot_rejects_unsafe_name() -> None:
    for bad in ("a/b", "..", ".", ""):
        with pytest.raises(ValueError):
            Slot(name=bad)


def test_spec_rejects_duplicate_slots() -> None:
    with pytest.raises(ValueError, match="unique"):
        ArtifactSpec(slots=(Slot("a"), Slot("a")))


def test_spec_slot_for_roundtrip() -> None:
    spec = ArtifactSpec(slots=(Slot("summary", label="Summary", view="markdown"),))
    s = spec.slot_for("summary")
    assert s is not None and s.view == "markdown"
    assert spec.slot_for("missing") is None


def test_spec_to_dict_shape() -> None:
    spec = ArtifactSpec(
        label="Tiny",
        slots=(Slot("summary", view="markdown"), Slot("raw", view="prose")),
        default_view="tabs",
    )
    d = spec.to_dict()
    assert d["label"] == "Tiny"
    assert d["default_view"] == "tabs"
    assert [s["name"] for s in d["slots"]] == ["summary", "raw"]


def test_state_store_artifact_store_protocol_satisfied(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run", run_id="run_1")
    adapter = StateStoreArtifactStore(store)
    # StateStore satisfies ArtifactStore through the adapter.
    assert hasattr(adapter, "item_artifacts")
    assert hasattr(adapter, "artifact_bytes")
    assert hasattr(adapter, "artifact_key")


def test_group_refs_by_slot_declared_empty_placeholder(
    tmp_path: Path,
) -> None:
    """Declared-but-unwritten slots appear with ref=None so the UI can show
    'missing' instead of silently dropping the slot."""
    store = StateStore(tmp_path / "run", run_id="run_1")
    spec = ArtifactSpec(
        slots=(
            Slot("summary", view="markdown"),
            Slot("entities", view="json-table", optional=True),
        )
    )
    # Write only the `summary` slot.
    store.write_bytes(
        K.artifact_item("item_a", "summary"),
        b"# summary",
        kind="artifact",
        written_by={"role": "agent"},
    )
    refs = store.query(layer="artifact", item_id="item_a")
    grouped = group_refs_by_slot(refs, spec)
    names = [g["slot"]["name"] for g in grouped]
    assert names == ["summary", "entities"]
    summary = next(g for g in grouped if g["slot"]["name"] == "summary")
    entities = next(g for g in grouped if g["slot"]["name"] == "entities")
    assert summary["ref"] is not None
    assert summary["undeclared"] is False
    assert entities["ref"] is None
    assert entities["undeclared"] is False


def test_group_refs_by_slot_undeclared_appended(tmp_path: Path) -> None:
    """Artifacts written to a slot the spec doesn't declare are flagged
    `undeclared=True` so reviewers see spec drift immediately."""
    store = StateStore(tmp_path / "run", run_id="run_1")
    spec = ArtifactSpec(slots=(Slot("summary", view="markdown"),))
    store.write_bytes(
        K.artifact_item("item_a", "summary"),
        b"# summary",
        kind="artifact",
    )
    store.write_bytes(
        K.artifact_item("item_a", "rogue"),
        b"rogue",
        kind="artifact",
    )
    refs = store.query(layer="artifact", item_id="item_a")
    grouped = group_refs_by_slot(refs, spec)
    rogue = next(g for g in grouped if g["slot"]["name"] == "rogue")
    assert rogue["undeclared"] is True
    assert rogue["ref"] is not None
    assert rogue["slot"]["view"] == "code"  # default for undeclared


def test_group_refs_by_slot_no_spec_keeps_all_refs(tmp_path: Path) -> None:
    """A domain without an ArtifactSpec still returns every artifact, all
    flagged `undeclared=True` — the UI shows them as raw slots."""
    store = StateStore(tmp_path / "run", run_id="run_1")
    store.write_bytes(K.artifact_item("a", "x"), b"x", kind="artifact")
    refs = store.query(layer="artifact", item_id="a")
    grouped = group_refs_by_slot(refs, None)
    assert len(grouped) == 1
    assert grouped[0]["undeclared"] is True
