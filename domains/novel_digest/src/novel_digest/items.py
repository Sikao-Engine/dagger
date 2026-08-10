"""ChapterSource: ItemSource for novel_digest (acceptance §1 Step 1 / §14.1).

Scans `<root>/chapters/*.txt` into an ordered WorkItem list:
- `seq` = the trailing digit group of the file stem (`ch_0042.txt` → 42);
  files without digits fall back to their sort position.
- `payload` carries `word_count` (shard weight), `volume`, `title`, `path`.
- Volume boundaries (a `vNN` prefix in the stem, e.g. `v02_ch0007.txt`) become
  Milestones at each volume's last chapter.
- The frontier (resume pointer) is read from `<root>/.dagger/cursor.json` when
  present — the file-system layer of the three-layer recovery model (§7.3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dagger_kernel.planning import ItemLedgerSnapshot, Milestone, WorkItem

_SEQ_RE = re.compile(r"(\d+)(?!.*\d)")
_VOLUME_RE = re.compile(r"^v(\d+)", re.IGNORECASE)


def chapter_seq(stem: str, fallback: int) -> int:
    """Numeric seq from the stem's trailing digits (`ch_0042` → 42)."""
    m = _SEQ_RE.search(stem)
    return int(m.group(1)) if m else fallback


def chapter_volume(stem: str) -> int:
    """Volume number from a `vNN` stem prefix (default 1)."""
    m = _VOLUME_RE.match(stem)
    return int(m.group(1)) if m else 1


def _first_line(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                text = line.strip()
                if text:
                    return text
    except OSError:
        pass
    return path.stem


def _word_count(path: Path) -> int:
    """Character count — the right weight unit for CJK prose."""
    try:
        return len(path.read_text(encoding="utf-8"))
    except OSError:
        return 0


def read_frontier(root: Path) -> str | None:
    """Read `.dagger/cursor.json`'s cursor_item_id if the file exists."""
    cursor = Path(root, ".dagger", "cursor.json")
    if not cursor.exists():
        return None
    try:
        data = json.loads(cursor.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("cursor_item_id")
    return str(value) if value else None


def volume_milestones(items: list[WorkItem]) -> list[Milestone]:
    """One Milestone per volume, docked at the volume's last chapter."""
    last_of_volume: dict[int, WorkItem] = {}
    for item in items:
        vol = int(item.payload.get("volume", 1))
        last_of_volume[vol] = item  # items arrive in seq order → last wins
    return [
        Milestone(
            name=f"第{vol}卷",
            boundary_item_id=item.id,
            boundary_seq=item.seq,
        )
        for vol, item in sorted(last_of_volume.items())
    ]


class ChapterSource:
    """ItemSource: scans `chapters/*.txt` under the workspace root."""

    def __init__(self, source_dir: str | Path) -> None:
        self.source_dir = Path(source_dir)

    async def refresh(self, ws: Any) -> ItemLedgerSnapshot:
        root = Path(getattr(ws, "root", self.source_dir))
        chapters_dir = Path(root, "chapters")
        files = sorted(p for p in chapters_dir.glob("*.txt") if p.is_file())
        items: list[WorkItem] = []
        for pos, path in enumerate(files):
            stem = path.stem
            labels: tuple[str, ...] = ("prologue",) if stem.startswith("prologue") else ()
            items.append(
                WorkItem(
                    id=stem,
                    seq=chapter_seq(stem, pos),
                    title=_first_line(path),
                    payload={
                        "path": str(path),
                        "word_count": _word_count(path),
                        "volume": chapter_volume(stem),
                    },
                    labels=labels,
                )
            )
        items.sort(key=lambda it: it.seq)
        return ItemLedgerSnapshot(
            items=items,
            milestones=volume_milestones(items),
            frontier_item_id=read_frontier(root),
            meta={"source_dir": str(root)},
        )

    async def resolve_frontier(self, ws: Any) -> str | None:
        root = Path(getattr(ws, "root", self.source_dir))
        return read_frontier(root)


__all__ = ["ChapterSource", "chapter_seq", "chapter_volume", "read_frontier", "volume_milestones"]
