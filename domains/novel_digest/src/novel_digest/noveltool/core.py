"""noveltool core: pure, testable functions behind the CLI commands.

Layout:
- `<root>/chapters/*.txt` — read-only source chapters.
- `<out>/<chapter_id>.json` — per-chapter product (schema `novel_chapter`).
- `<out>/pointer.json` — the self-held progress pointer (smoke plan D10):
  `{"cursor_item_id": ..., "updated_at": ...}`.

Pointer semantics (this is what makes `next` idempotent):
- `next` dispatches the chapter *after* the cursor only when the cursor
  chapter's product is filled (`digest_ok=true`). If the current chapter is
  unfilled, `next` is a no-op — the pointer never skips unfinished work, so a
  crash mid-chapter can never silently drop it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dagger_cli.scaffold import (
    EXIT_NEEDS_HUMAN,
    EXIT_NEEDS_REVIEW,
    EXIT_OK,
    EXIT_PARAM_ERROR,
)
from dagger_kernel.state.schema import validate as validate_schema

from ..items import chapter_seq
from ..schemas import NOVEL_CHAPTER

POINTER_NAME = "pointer.json"


@dataclass(frozen=True)
class ChapterRef:
    id: str
    seq: int
    path: Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


def list_chapters(root: Path) -> list[ChapterRef]:
    """All chapters under `<root>/chapters`, ordered by seq."""
    chapters_dir = Path(root, "chapters")
    refs = [
        ChapterRef(id=p.stem, seq=chapter_seq(p.stem, pos), path=p)
        for pos, p in enumerate(sorted(chapters_dir.glob("*.txt")))
        if p.is_file()
    ]
    return sorted(refs, key=lambda r: r.seq)


def load_pointer(out: Path) -> dict[str, Any]:
    path = Path(out, POINTER_NAME)
    if not path.exists():
        return {"cursor_item_id": None, "updated_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cursor_item_id": None, "updated_at": ""}
    return {"cursor_item_id": data.get("cursor_item_id"), "updated_at": data.get("updated_at", "")}


def save_pointer(out: Path, cursor_item_id: str | None) -> None:
    path = Path(out, POINTER_NAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"cursor_item_id": cursor_item_id, "updated_at": _now()}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def product_path(out: Path, chapter_id: str) -> Path:
    return Path(out, f"{chapter_id}.json")


def load_product(out: Path, chapter_id: str) -> dict[str, Any] | None:
    path = product_path(out, chapter_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_filled(product: dict[str, Any] | None) -> bool:
    return bool(product) and product.get("digest_ok") is True


def make_stub(chapter_id: str) -> dict[str, Any]:
    """A schema-valid placeholder the Agent later replaces via `fill`."""
    return {
        "chapter_id": chapter_id,
        "summary": "",
        "entities": [],
        "timeline_delta": [],
        "digest_ok": False,
    }


def status(root: Path, out: Path) -> dict[str, Any]:
    """Progress snapshot: stable field set across empty/mid/complete states."""
    chapters = list_chapters(root)
    pointer = load_pointer(out)
    cursor = pointer["cursor_item_id"]
    filled = [c.id for c in chapters if is_filled(load_product(out, c.id))]
    after_cursor = cursor is None
    next_id: str | None = None
    for c in chapters:
        if after_cursor:
            next_id = c.id
            break
        if c.id == cursor:
            after_cursor = True
    return {
        "total": len(chapters),
        "filled": len(filled),
        "filled_ids": filled,
        "remaining": len(chapters) - len(filled),
        "cursor_item_id": cursor,
        "next_id": next_id,
        "all_done": len(chapters) > 0 and len(filled) == len(chapters),
    }


def advance(root: Path, out: Path) -> tuple[int, dict[str, Any]]:
    """`next`: move the pointer one chapter forward (idempotent, see module docstring)."""
    chapters = list_chapters(root)
    if not chapters:
        return EXIT_NEEDS_HUMAN, {"error": f"no chapters under {Path(root, 'chapters')}"}
    cursor = load_pointer(out)["cursor_item_id"]
    by_id = {c.id: c for c in chapters}
    if cursor is None:
        target = chapters[0]
    elif cursor not in by_id:
        return EXIT_PARAM_ERROR, {"error": f"cursor points at unknown chapter {cursor!r}"}
    elif not is_filled(load_product(out, cursor)):
        # Current chapter unfinished → no-op (idempotent; nothing skipped).
        return EXIT_OK, {
            "advanced": False,
            "chapter_id": cursor,
            "reason": "current chapter not filled",
        }
    else:
        pos = next(i for i, c in enumerate(chapters) if c.id == cursor)
        if pos + 1 >= len(chapters):
            return EXIT_OK, {"advanced": False, "all_done": True}
        target = chapters[pos + 1]
    stub_created = False
    if load_product(out, target.id) is None:
        _write_product(out, target.id, make_stub(target.id))
        stub_created = True
    save_pointer(out, target.id)
    return EXIT_OK, {"advanced": True, "chapter_id": target.id, "stub_created": stub_created}


def _write_product(out: Path, chapter_id: str, body: dict[str, Any]) -> None:
    path = product_path(out, chapter_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys → byte-identical rewrites for identical content (idempotent fill).
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def fill(root: Path, out: Path, chapter_id: str, file: Path) -> tuple[int, dict[str, Any]]:
    """`fill`: validate an Agent-produced document against novel_chapter, then persist."""
    known = {c.id for c in list_chapters(root)}
    if chapter_id not in known:
        return EXIT_PARAM_ERROR, {"error": f"unknown chapter {chapter_id!r}"}
    try:
        body = json.loads(Path(file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return EXIT_PARAM_ERROR, {"error": f"cannot read product file: {exc}"}
    if not isinstance(body, dict):
        return EXIT_PARAM_ERROR, {"error": "product file must be a JSON object"}
    if body.get("chapter_id") not in (None, chapter_id):
        return EXIT_PARAM_ERROR, {
            "error": f"chapter_id mismatch: file says {body.get('chapter_id')!r}"
        }
    errors = validate_schema(NOVEL_CHAPTER, body)
    if errors:
        return EXIT_PARAM_ERROR, {"error": "schema validation failed", "schema_errors": errors}
    _write_product(out, chapter_id, body)
    return EXIT_OK, {"filled": chapter_id}


def timeline_regressions(root: Path, out: Path, chapter_id: str) -> list[dict[str, Any]]:
    """Event chapters must be non-decreasing across the accumulated timeline.

    The floor starts at the max event chapter of all *filled earlier* products,
    then walks this chapter's delta in order.
    """
    chapters = list_chapters(root)
    by_id = {c.id: c for c in chapters}
    target = by_id[chapter_id]
    floor = 0
    for c in chapters:
        if c.seq >= target.seq:
            break
        product = load_product(out, c.id)
        if not is_filled(product):
            continue
        for event in product.get("timeline_delta", []):
            floor = max(floor, int(event.get("chapter", 0)))
    findings: list[dict[str, Any]] = []
    product = load_product(out, chapter_id) or {}
    for i, event in enumerate(product.get("timeline_delta", [])):
        chapter_no = int(event.get("chapter", 0))
        if chapter_no < floor:
            findings.append(
                {
                    "code": "timeline_regression",
                    "event_index": i,
                    "event_chapter": chapter_no,
                    "floor": floor,
                }
            )
        floor = max(floor, chapter_no)
    return findings


def check(root: Path, out: Path, chapter_id: str) -> tuple[int, dict[str, Any]]:
    """`check`: mechanical review of one chapter product."""
    known = {c.id for c in list_chapters(root)}
    if chapter_id not in known:
        return EXIT_PARAM_ERROR, {"error": f"unknown chapter {chapter_id!r}"}
    product = load_product(out, chapter_id)
    if product is None:
        return EXIT_NEEDS_HUMAN, {"error": f"no product for {chapter_id!r}; run fill first"}
    findings: list[dict[str, Any]] = []
    schema_errors = validate_schema(NOVEL_CHAPTER, product)
    findings.extend({"code": "schema_incomplete", "detail": e} for e in schema_errors)
    if product.get("digest_ok") is not True:
        findings.append({"code": "digest_not_ok", "detail": "digest_ok is not true"})
    findings.extend(timeline_regressions(root, out, chapter_id))
    if findings:
        return EXIT_NEEDS_REVIEW, {"ok": False, "chapter_id": chapter_id, "findings": findings}
    return EXIT_OK, {"ok": True, "chapter_id": chapter_id}


__all__ = [
    "POINTER_NAME",
    "ChapterRef",
    "advance",
    "check",
    "fill",
    "is_filled",
    "list_chapters",
    "load_pointer",
    "load_product",
    "make_stub",
    "save_pointer",
    "status",
    "timeline_regressions",
]
