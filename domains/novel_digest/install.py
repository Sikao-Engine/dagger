"""Install the novel_digest agent skills (SKILL.md SOP docs) for your agent CLI.

Usage (from the repo root):

    uv run domains/novel_digest/install.py [--dest <skills-root>] [--dry-run]

What it does:
- Copies every skill under `skills_md/` next to this script into the agent
  skills root (default: `~/.agents/skills`, discovered by kimi-cli and most
  agent CLIs; use --dest for `~/.claude/skills`, `.kimi/skills`, ...).
- Idempotent: re-running refreshes files in place and reports
  installed / refreshed / unchanged per skill.
- Prints the remaining setup steps (noveltool, web build, server config).

Stdlib only — safe to run with any Python 3.12+, no repo venv required.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

SKILLS_SRC = Path(__file__).resolve().parent / "skills_md"
DEFAULT_DEST = Path.home() / ".agents" / "skills"

NEXT_STEPS = """
Next steps (workspace-decoupled setup):

  2. Install the deterministic CLI (puts `noveltool` on your PATH):
       cd domains/novel_digest/noveltool && uv tool install -e .

  3. Build the frontend bundle:
       cd web && pnpm install && pnpm build

  4. Copy `config.example.toml` to your own config, point `workspace` at the
     book directory you want to work in, then start Dagger:
       uv run server/main_server.py -c path/to/your.toml
"""


def install_skills(dest: Path, *, dry_run: bool = False) -> int:
    if not SKILLS_SRC.is_dir():
        print(f"error: skills source not found: {SKILLS_SRC}", file=sys.stderr)
        return 1
    skills = sorted(p for p in SKILLS_SRC.iterdir() if (p / "SKILL.md").is_file())
    if not skills:
        print(f"error: no skills (*/SKILL.md) under {SKILLS_SRC}", file=sys.stderr)
        return 1

    print(f"skills root: {dest}" + ("  [dry-run]" if dry_run else ""))
    for src in skills:
        target = dest / src.name
        if not target.exists():
            action = "install"
        elif _same_tree(src, target):
            action = "unchanged"
        else:
            action = "refresh"
        print(f"  {action:9s} {src.name} -> {target}")
        if dry_run or action == "unchanged":
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)

    print(f"\n{len(skills)} skill(s) processed.")
    print(NEXT_STEPS)
    return 0


def _same_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(_same_tree(Path(a, d), Path(b, d)) for d in cmp.common_dirs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"Agent skills root (default: {DEFAULT_DEST}).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing.")
    args = parser.parse_args(argv)
    return install_skills(args.dest.expanduser(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
