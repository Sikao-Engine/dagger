"""Test/demo scaffolding for novel_digest.

Deterministic fixture builders shared by the test suite and usable by hand:

    python -m novel_digest.testing <target_dir> [--chapters N]

writes a demo book (`chapters/ch_0001.txt` ... ) suitable for
`divdag run --domain novel_digest --items <target_dir> --backend mock`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def chapter_ids(n: int) -> list[str]:
    return [f"ch_{i:04d}" for i in range(1, n + 1)]


def make_book(root: str | Path, chapters: int = 5) -> Path:
    """A deterministic demo book: <root>/chapters/ch_XXXX.txt."""
    root = Path(root)
    chapters_dir = Path(root, "chapters")
    chapters_dir.mkdir(parents=True, exist_ok=True)
    for i, cid in enumerate(chapter_ids(chapters), start=1):
        (chapters_dir / f"{cid}.txt").write_text(
            f"第{i}章 风起\n" + "「韩立」赶路。" * 150, encoding="utf-8"
        )
    return root


def make_chapter_product(
    chapter_id: str,
    *,
    summary: str | None = None,
    event_chapter: int | None = None,
    digest_ok: bool = True,
) -> dict:
    """A schema-valid novel_chapter product (deterministic)."""
    seq = int(chapter_id.removeprefix("ch_"))
    return {
        "chapter_id": chapter_id,
        "summary": summary
        if summary is not None
        else f"第 {chapter_id} 章摘要：「韩立」继续前行。" * 3,
        "entities": [
            {
                "name": "韩立",
                "type": "person",
                "aliases": [],
                "first_seen_chapter": chapter_id,
            }
        ],
        "timeline_delta": [
            {
                "event": f"{chapter_id} 事件",
                "chapter": event_chapter if event_chapter is not None else seq,
                "participants": ["韩立"],
                "anchors": [chapter_id],
            }
        ],
        "digest_ok": digest_ok,
    }


def write_product(out: str | Path, chapter_id: str, body: dict) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = Path(out, f"{chapter_id}.json")
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m novel_digest.testing")
    parser.add_argument("target", help="Directory to write the demo book into.")
    parser.add_argument("--chapters", type=int, default=5)
    args = parser.parse_args(argv)
    book = make_book(args.target, chapters=args.chapters)
    print(json.dumps({"book": str(book), "chapters": args.chapters}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
