"""Step 4: noveltool — the deterministic CLI.

Pins: status three-state JSON shape, next idempotence, fill's schema rejection
with field-level errors (exit 3), check's timeline-regression review (exit 2).
Exit codes: 0 ok / 1 needs-human / 2 needs-review / 3 param-error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from novel_digest.noveltool import core
from novel_digest.noveltool.cli import main
from novel_digest.testing import make_book, make_chapter_product, write_product


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return make_book(tmp_path)


def _cli(*args: str) -> tuple[int, dict]:
    """Run the CLI in-process; capture stdout JSON + exit code."""
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(list(args))
    return code, json.loads(buf.getvalue())


class TestStatus:
    def test_empty_state(self, book: Path, tmp_path: Path) -> None:
        code, payload = _cli("status", "--root", str(book), "--out", str(tmp_path / "out"))
        assert code == 0
        data = payload["data"]
        assert data["total"] == 5
        assert data["filled"] == 0
        assert data["remaining"] == 5
        assert data["all_done"] is False
        assert data["next_id"] == "ch_0001"
        assert data["cursor_item_id"] is None
        # Field set is stable across states.
        assert set(data) == {
            "total",
            "filled",
            "filled_ids",
            "remaining",
            "cursor_item_id",
            "next_id",
            "all_done",
        }

    def test_mid_and_complete_states(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        for cid in ("ch_0001", "ch_0002"):
            write_product(out, cid, make_chapter_product(cid))
        core.save_pointer(out, "ch_0002")
        mid = core.status(book, out)
        assert mid["filled"] == 2 and mid["remaining"] == 3 and mid["all_done"] is False
        assert mid["next_id"] == "ch_0003"
        for cid in ("ch_0003", "ch_0004", "ch_0005"):
            write_product(out, cid, make_chapter_product(cid))
        done = core.status(book, out)
        assert done["all_done"] is True and done["remaining"] == 0
        assert done["next_id"] == "ch_0003"  # next after cursor, regardless of fill state


class TestNext:
    def test_next_is_idempotent_per_chapter(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        code, payload = core.advance(book, out)
        assert code == 0 and payload["advanced"] is True and payload["chapter_id"] == "ch_0001"
        assert payload["stub_created"] is True
        stub_bytes = (out / "ch_0001.json").read_bytes()
        pointer_bytes = (out / core.POINTER_NAME).read_bytes()
        # Second next: current chapter unfilled → no-op, zero side effects.
        code, payload = core.advance(book, out)
        assert code == 0 and payload["advanced"] is False
        assert (out / "ch_0001.json").read_bytes() == stub_bytes
        assert (out / core.POINTER_NAME).read_bytes() == pointer_bytes
        # After filling, next advances to ch_0002.
        write_product(out, "ch_0001", make_chapter_product("ch_0001"))
        code, payload = core.advance(book, out)
        assert code == 0 and payload["advanced"] is True and payload["chapter_id"] == "ch_0002"

    def test_next_at_end_reports_all_done(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        for cid in ("ch_0001", "ch_0002", "ch_0003", "ch_0004", "ch_0005"):
            write_product(out, cid, make_chapter_product(cid))
        core.save_pointer(out, "ch_0005")
        code, payload = core.advance(book, out)
        assert code == 0 and payload["advanced"] is False and payload["all_done"] is True

    def test_next_on_empty_book_needs_human(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        (empty / "chapters").mkdir(parents=True)
        code, payload = core.advance(empty, tmp_path / "out")
        assert code == 1
        assert "no chapters" in payload["error"]


class TestFill:
    def test_fill_valid_product(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        src = write_product(tmp_path / "inbox", "ch_0001", make_chapter_product("ch_0001"))
        code, payload = _cli(
            "fill", "ch_0001", "--file", str(src), "--root", str(book), "--out", str(out)
        )
        assert code == 0
        assert payload["data"]["filled"] == "ch_0001"
        # Idempotent: filling the same content again is a byte-identical no-op.
        before = (out / "ch_0001.json").read_bytes()
        code, _ = _cli(
            "fill", "ch_0001", "--file", str(src), "--root", str(book), "--out", str(out)
        )
        assert code == 0
        assert (out / "ch_0001.json").read_bytes() == before

    def test_fill_bad_file_exit_3_with_field_errors(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        bad = make_chapter_product("ch_0001")
        del bad["summary"]
        del bad["digest_ok"]
        src = write_product(tmp_path / "inbox", "ch_0001", bad)
        code, payload = _cli(
            "fill", "ch_0001", "--file", str(src), "--root", str(book), "--out", str(out)
        )
        assert code == 3
        errors = payload["data"]["schema_errors"]
        assert any("summary" in e for e in errors)
        assert any("digest_ok" in e for e in errors)
        assert not (out / "ch_0001.json").exists()  # rejected → nothing persisted

    def test_fill_unknown_chapter_exit_3(self, book: Path, tmp_path: Path) -> None:
        src = write_product(tmp_path / "inbox", "ch_9999", make_chapter_product("ch_0001"))
        code, _ = _cli(
            "fill",
            "ch_9999",
            "--file",
            str(src),
            "--root",
            str(book),
            "--out",
            str(tmp_path / "out"),
        )
        assert code == 3


class TestCheck:
    def test_check_ok(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        write_product(out, "ch_0001", make_chapter_product("ch_0001"))
        code, payload = _cli("check", "ch_0001", "--root", str(book), "--out", str(out))
        assert code == 0 and payload["data"]["ok"] is True

    def test_check_missing_product_needs_human(self, book: Path, tmp_path: Path) -> None:
        code, _ = _cli("check", "ch_0001", "--root", str(book), "--out", str(tmp_path / "out"))
        assert code == 1

    def test_check_timeline_regression_exit_2(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        write_product(out, "ch_0001", make_chapter_product("ch_0001", event_chapter=7))
        # ch_0002's event jumps back before ch_0001's → cross-item regression.
        write_product(out, "ch_0002", make_chapter_product("ch_0002", event_chapter=3))
        code, payload = _cli("check", "ch_0002", "--root", str(book), "--out", str(out))
        assert code == 2
        findings = payload["data"]["findings"]
        assert any(f["code"] == "timeline_regression" for f in findings)

    def test_check_unfilled_stub_needs_review(self, book: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        write_product(out, "ch_0001", core.make_stub("ch_0001"))
        code, payload = _cli("check", "ch_0001", "--root", str(book), "--out", str(out))
        assert code == 2
        assert any(f["code"] == "digest_not_ok" for f in payload["data"]["findings"])
