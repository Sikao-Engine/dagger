"""Atomic write primitives. tmp + fsync + os.replace.

Readers **never** see a half-written file. This eliminates the read-during-write
race that CubeClaw worked around with 15s polling + JSON-parse-retry.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically: tmp file -> fsync -> os.replace.

    On Windows, `os.replace` atomically overwrites an existing file (unlike
    `os.rename` which raises). We rely on that.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = f".tmp.{os.getpid()}.{int(__import__('time').time() * 1000)}"
    tmp = path.with_name(path.name + suffix)
    try:
        # O_WRONLY | O_CREAT | O_TRUNC, binary mode.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_BINARY, 0o644)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            os.close(fd)
            raise
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def atomic_write_json(path: Path, obj: Any, *, indent: int = 2) -> None:
    """Write `obj` as pretty-printed JSON atomically. Stable key order for reproducibility."""
    text = json.dumps(obj, indent=indent, sort_keys=True, default=str, ensure_ascii=False)
    atomic_write_bytes(path, text.encode("utf-8"))


def append_jsonl(path: Path, obj: Any) -> None:
    """Append a single JSONL record. Uses O_APPEND for atomic single-line writes.

    Each record is < 4KB to stay within the POSIX atomicity guarantee for
    append-mode writes on most filesystems.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, default=str, ensure_ascii=False, separators=(",", ":"))
    data = (line + "\n").encode("utf-8")
    # Open in binary append; O_APPEND on POSIX is atomic for writes < PIPE_BUF.
    with open(path, "ab") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object, returning None if missing. Raises on malformed JSON."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object at {path}, got {type(obj).__name__}")
    return obj


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read all JSONL records. Skips blank lines. Raises on malformed lines."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{lineno}: expected JSON object per line")
        out.append(obj)
    return out


def safe_rel_path_str(p: str) -> str:
    """Normalize a relative POSIX path string to forward slashes for storage."""
    if sys.platform.startswith("win"):
        return p.replace("\\", "/")
    return p


__all__ = [
    "append_jsonl",
    "atomic_write_bytes",
    "atomic_write_json",
    "read_json",
    "read_jsonl",
    "safe_rel_path_str",
]
