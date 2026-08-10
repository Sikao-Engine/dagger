"""Step 5: the five mechanical scanners.

Each scanner must fire exactly the expected Finding (severity pinned) on a
deliberately broken item, and stay silent on a good one. Covers the three
required classes from the go-live checklist: empty product, incomplete schema,
cross-item consistency (timeline regression).
"""

from __future__ import annotations

from divdag_kernel.planning import WorkItem
from divdag_kernel.review import ScanContext
from novel_digest.scanners import (
    SCANNERS,
    AbnormalLengthScanner,
    EmptySummaryScanner,
    SchemaIncompleteScanner,
    TimelineRegressionScanner,
    UndeclaredEntityScanner,
)
from novel_digest.testing import make_chapter_product

CTX = ScanContext(run_id="run_x", workspace_root="/book")


def _item(word_count: int = 3000) -> WorkItem:
    return WorkItem(
        id="ch_0001",
        seq=1,
        title="第1章",
        payload={"word_count": word_count, "volume": 1},
    )


class TestScannerFindings:
    def test_empty_summary(self) -> None:
        chapter = make_chapter_product("ch_0001", summary="太短")
        findings = EmptySummaryScanner().scan(_item(), chapter, CTX)
        assert len(findings) == 1
        assert findings[0].code == "empty_summary"
        assert findings[0].severity == "warning"

    def test_schema_incomplete(self) -> None:
        chapter = make_chapter_product("ch_0001")
        del chapter["entities"]
        findings = SchemaIncompleteScanner().scan(_item(), chapter, CTX)
        assert len(findings) == 1
        assert findings[0].code == "schema_incomplete"
        assert findings[0].severity == "error"
        assert "entities" in findings[0].message

    def test_schema_incomplete_reports_missing_product(self) -> None:
        findings = SchemaIncompleteScanner().scan(_item(), None, CTX)
        assert len(findings) == 1
        assert findings[0].severity == "error"

    def test_undeclared_entity(self) -> None:
        chapter = make_chapter_product(
            "ch_0001", summary="「韩立」与「墨居仁」对峙，「神秘人」暗中观察。" + "补充" * 30
        )
        findings = UndeclaredEntityScanner().scan(_item(), chapter, CTX)
        assert len(findings) == 2  # 墨居仁 + 神秘人 undeclared; 韩立 is declared
        assert {f.severity for f in findings} == {"warning"}
        assert {f.locator["entity"] for f in findings} == {"墨居仁", "神秘人"}

    def test_undeclared_entity_respects_canon(self) -> None:
        chapter = make_chapter_product("ch_0001", summary="「韩立」拜入「七玄门」。" + "补充" * 30)
        ctx = ScanContext(refs={"canon_entities": ["七玄门"]})
        assert UndeclaredEntityScanner().scan(_item(), chapter, ctx) == []

    def test_timeline_regression(self) -> None:
        chapter = make_chapter_product("ch_0001")
        chapter["timeline_delta"] = [
            {"event": "e1", "chapter": 5, "participants": [], "anchors": []},
            {"event": "e2", "chapter": 3, "participants": [], "anchors": []},
        ]
        findings = TimelineRegressionScanner().scan(_item(), chapter, CTX)
        assert len(findings) == 1
        assert findings[0].code == "timeline_regression"
        assert findings[0].severity == "error"
        assert findings[0].locator["event_index"] == 1

    def test_timeline_regression_uses_floor_from_refs(self) -> None:
        chapter = make_chapter_product("ch_0002", event_chapter=2)
        ctx = ScanContext(refs={"timeline_floor": 5})
        findings = TimelineRegressionScanner().scan(_item(), chapter, ctx)
        assert len(findings) == 1

    def test_abnormal_length(self) -> None:
        chapter = make_chapter_product("ch_0001")  # ~60-char summary
        findings = AbnormalLengthScanner().scan(_item(word_count=10000), chapter, CTX)
        assert len(findings) == 1
        assert findings[0].code == "abnormal_length"
        assert findings[0].severity == "warning"

    def test_all_scanners_silent_on_good_chapter(self) -> None:
        chapter = make_chapter_product("ch_0001")
        for scanner in SCANNERS:
            assert scanner.scan(_item(), chapter, CTX) == [], scanner.code

    def test_scanner_suite_covers_required_classes(self) -> None:
        codes = {s.code for s in SCANNERS}
        assert codes == {
            "empty_summary",
            "schema_incomplete",
            "undeclared_entity",
            "timeline_regression",
            "abnormal_length",
        }
