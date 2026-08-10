"""K6: CLI acceptance — `dagger run --domain novel_digest --backend mock` really runs.

Also pins: `dagger domains` lists both domains, the tiny domain still runs
(regression), and the generic local-domain loader (directory name = package
name) registers plugins without entry points.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from dagger_cli.main import _build_registry, _default_domains_dir, cli
from dagger_kernel.dag import NodeRegistry
from dagger_kernel.executors import ExecutorCatalog
from dagger_kernel.state import StateStore


def _make_book(root: Path, chapters: int = 5) -> Path:
    book = root / "book"
    ch = book / "chapters"
    ch.mkdir(parents=True)
    for i in range(1, chapters + 1):
        (ch / f"ch_{i:04d}.txt").write_text(f"第{i}章\n" + "正文。" * 200, encoding="utf-8")
    return book


class TestRunNovelDigest:
    def test_mock_run_end_to_end(self, tmp_path: Path, monkeypatch) -> None:
        book = _make_book(tmp_path)
        monkeypatch.chdir(tmp_path)  # state lands under tmp_path/.dagger
        result = CliRunner().invoke(
            cli,
            [
                "run",
                "--domain",
                "novel_digest",
                "--items",
                str(book),
                "--shards",
                "2",
                "--backend",
                "mock",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "failed=0" in result.output
        assert "skipped=0" in result.output
        # State tree exists with contract results + seeded item ledger.
        runs = list((tmp_path / ".dagger").glob("run_*"))
        assert len(runs) == 1
        state = runs[0] / "state"
        results = list((state / "contract").rglob("result.json"))
        assert len(results) >= 13  # ≥ 2 shards × 5 + init + 2 run nodes
        assert (state / "control" / "items" / "ch_0001" / "item.json").exists()
        # The workspace got provisioned through the kernel's ensure_workspace.
        shard_dirs = list(book.glob(f"{runs[0].name}/shard-*/"))
        assert len(shard_dirs) >= 2
        assert (shard_dirs[0] / "ch_0001.json").exists()
        # sha256 + index integrity.
        store = StateStore(runs[0], run_id=runs[0].name, readonly=True)
        assert store.verify() == []

    def test_dry_run(self, tmp_path: Path) -> None:
        book = _make_book(tmp_path)
        result = CliRunner().invoke(
            cli,
            ["run", "--domain", "novel_digest", "--items", str(book), "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "novel_digest_default" in result.output

    def test_unknown_domain_exit_3(self, tmp_path: Path) -> None:
        book = _make_book(tmp_path)
        result = CliRunner().invoke(cli, ["run", "--domain", "nope", "--items", str(book)])
        assert result.exit_code == 3


class TestDomainsCommand:
    def test_lists_both_domains(self) -> None:
        result = CliRunner().invoke(cli, ["domains"])
        assert result.exit_code == 0
        ids = {d["id"] for d in json.loads(result.output)}
        assert {"tiny", "novel_digest"} <= ids


class TestTinyRegression:
    def test_tiny_still_runs(self, tmp_path: Path, monkeypatch) -> None:
        src = tmp_path / "items"
        src.mkdir()
        for name in ("a.txt", "b.txt"):
            (src / name).write_text(f"content of {name}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            cli, ["run", "--domain", "tiny", "--items", str(src), "--shards", "1"]
        )
        assert result.exit_code == 0, result.output
        assert "failed=0" in result.output


class TestLocalDomainLoader:
    def test_local_domains_dir_generic_loading(self) -> None:
        """The dev fallback loads <pkg>.plugin for every domains/*/src package."""
        catalog = ExecutorCatalog()
        nodes = NodeRegistry()
        registry = _build_registry(catalog, nodes, domains_dir=_default_domains_dir())
        ids = {r.plugin.id for r in registry.all()}
        assert {"tiny", "novel_digest"} <= ids
        # Kernel builtins poured via contribute_to.
        assert catalog.require("ensure_workspace").handler_kind == "builtin"

    def test_default_domains_dir_points_at_repo(self) -> None:
        assert (_default_domains_dir() / "tiny").is_dir()
        assert (_default_domains_dir() / "novel_digest").is_dir()
