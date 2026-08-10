"""noveltool CLI: status / next / fill / check (acceptance Step 4).

All commands emit JSON on stdout and exit with semantic codes:
0 ok / 1 needs-human / 2 needs-review / 3 param-error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from dagger_cli.scaffold import EXIT_OK, CommandResult

from . import core


def _emit(code: int, payload: dict[str, Any]) -> int:
    """Print the CommandResult JSON envelope but return the semantic exit code."""
    result = CommandResult(
        ok=code == EXIT_OK,
        data=payload,
        error=str(payload.get("error", "")),
    )
    sys.stdout.write(result.to_json() + "\n")
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noveltool", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def _add(name: str, **kwargs: Any) -> argparse.ArgumentParser:
        p = sub.add_parser(name, **kwargs)
        p.add_argument("--root", default=".", help="Workspace root containing chapters/.")
        p.add_argument("--out", default=".", help="Product dir (chapter JSONs + pointer.json).")
        return p

    _add("status", help="Progress, next item, remaining count.")
    _add("next", help="Advance the pointer one chapter (idempotent).")
    p_fill = _add("fill", help="Persist an Agent product after schema validation.")
    p_fill.add_argument("chapter_id")
    p_fill.add_argument("--file", required=True, help="Path to the Agent-produced JSON.")
    p_check = _add("check", help="Mechanical review of one chapter product.")
    p_check.add_argument("chapter_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "status":
        return _emit(EXIT_OK, core.status(root, out))
    if args.command == "next":
        code, payload = core.advance(root, out)
        return _emit(code, payload)
    if args.command == "fill":
        code, payload = core.fill(root, out, args.chapter_id, Path(args.file))
        return _emit(code, payload)
    if args.command == "check":
        code, payload = core.check(root, out, args.chapter_id)
        return _emit(code, payload)
    return 3  # pragma: no cover - argparse enforces the subcommand set


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
