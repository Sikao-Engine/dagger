"""T0.4: forbid raw path concatenation outside layout.py and store.py.

A pytest test that scans the kernel source tree for `Path(...) /` and
`os.path.join(...)` style concatenation, except in the two sanctioned modules.
This is the structural enforcement of state_layer_architecture.md §R1
("business code never concatenates paths").
"""

from __future__ import annotations

import re
from pathlib import Path

KERNEL_SRC = Path(__file__).resolve().parents[2] / "src" / "dagger_kernel"

# Modules allowed to construct state paths. Everything else must call StateStore.path()
# or StateStore.rel() or K.* and never touch Path() arithmetic on state coordinates.
PATH_BUILDING_ALLOWLIST = {
    "dagger_kernel/state/layout.py",
    "dagger_kernel/state/store.py",
    "dagger_kernel/state/io.py",  # tmp-file naming + os.replace
}


def _iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _rel_to_kernel(p: Path) -> str:
    parts = p.parts
    idx = parts.index("dagger_kernel")
    return "/".join(parts[idx:])


# Patterns that signal "hand-rolled path concatenation on state coordinates".
# We allow `Path(...)` *imports* and `pathlib.Path` references; we flag
# `Path(...) /` (operator concat) and `os.path.join(...)` calls.
_PATH_OP_CONCAT = re.compile(r"Path\([^)]*\)\s*[/+]")


class TestNoRawPathConcat:
    def test_no_path_operator_concat_outside_allowlist(self) -> None:
        offenders: list[str] = []
        for src in _iter_py_files(KERNEL_SRC):
            rel = _rel_to_kernel(src)
            if rel in PATH_BUILDING_ALLOWLIST:
                continue
            text = src.read_text(encoding="utf-8")
            # Find `Path(...) /` or `Path(...) +` arithmetic.
            for m in _PATH_OP_CONCAT.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line_no}: {m.group().strip()!r}")
        assert not offenders, (
            "Raw Path concatenation outside layout.py/store.py/io.py is forbidden "
            "(state_layer_architecture.md §R1). Use StateStore.path(K.*):\n  "
            + "\n  ".join(offenders)
        )

    def test_no_os_path_join_outside_allowlist(self) -> None:
        offenders: list[str] = []
        for src in _iter_py_files(KERNEL_SRC):
            rel = _rel_to_kernel(src)
            if rel in PATH_BUILDING_ALLOWLIST:
                continue
            text = src.read_text(encoding="utf-8")
            # Crude regex: os.path.join(...) anywhere.
            for m in re.finditer(r"os\.path\.join\s*\(", text):
                line_no = text[: m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line_no}")
        assert not offenders, "os.path.join forbidden; use StateStore helpers."

    def test_state_path_construction_lives_only_in_layout(self) -> None:
        # The `layout` function and `StateStore.path` are the only sanctioned builders.
        # If anyone added a new builder it would be a layout split — surface it here.
        for src in _iter_py_files(KERNEL_SRC):
            rel = _rel_to_kernel(src)
            if rel == "dagger_kernel/state/layout.py":
                continue
            text = src.read_text(encoding="utf-8")
            # No other module should define a function called `layout` that returns a path.
            assert not re.search(r"def\s+layout\s*\(", text), (
                f"{rel}: defining `layout()` is reserved for state/layout.py"
            )
