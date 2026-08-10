"""Step 1: materialized data contracts.

- A complete chapter product passes schema validation.
- A field-missing product is rejected with field-level errors.
- All three kinds are registered in the kernel SCHEMA_REGISTRY.
"""

from __future__ import annotations

import copy

import novel_digest.schemas
from dagger_kernel.state.schema import SCHEMA_REGISTRY, validate
from novel_digest.schemas import (
    NOVEL_CHAPTER,
    NOVEL_CONSISTENCY_REPORT,
    NOVEL_VOLUME_SUMMARY,
)
from novel_digest.testing import make_chapter_product


class TestChapterSchema:
    def test_valid_chapter_passes(self) -> None:
        assert validate(NOVEL_CHAPTER, make_chapter_product("ch_0001")) == []

    def test_missing_field_rejected_with_field_level_error(self) -> None:
        bad = make_chapter_product("ch_0001")
        del bad["summary"]
        errors = validate(NOVEL_CHAPTER, bad)
        assert errors, "expected schema errors"
        assert any("summary" in e for e in errors), f"field-level error expected: {errors}"

    def test_nested_entity_field_error_is_precise(self) -> None:
        bad = make_chapter_product("ch_0001")
        del bad["entities"][0]["first_seen_chapter"]
        errors = validate(NOVEL_CHAPTER, bad)
        assert any("first_seen_chapter" in e for e in errors)

    def test_wrong_type_rejected(self) -> None:
        bad = make_chapter_product("ch_0001")
        bad["timeline_delta"] = copy.deepcopy(bad["timeline_delta"])
        bad["timeline_delta"][0]["chapter"] = "三"  # must be int
        errors = validate(NOVEL_CHAPTER, bad)
        assert any("chapter" in e for e in errors)


class TestKindRegistration:
    def test_three_kinds_registered(self) -> None:
        for kind in (NOVEL_CHAPTER, NOVEL_VOLUME_SUMMARY, NOVEL_CONSISTENCY_REPORT):
            assert SCHEMA_REGISTRY.has(kind), f"{kind} not registered"

    def test_registration_is_idempotent(self) -> None:
        novel_digest.schemas.register_schemas()  # second registration must not raise
        assert SCHEMA_REGISTRY.has(NOVEL_CHAPTER)

    def test_volume_and_consistency_schemas_validate(self) -> None:
        assert (
            validate(
                NOVEL_VOLUME_SUMMARY,
                {
                    "volume": 1,
                    "summary": "本卷总述。",
                    "chapter_range": {"first": "ch_0001", "last": "ch_0005"},
                    "volume_ok": True,
                },
            )
            == []
        )
        assert (
            validate(
                NOVEL_CONSISTENCY_REPORT,
                {
                    "contradictions": [],
                    "checked_entities": 3,
                    "checked_events": 5,
                    "consistency_ok": True,
                },
            )
            == []
        )
