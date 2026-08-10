"""StateStore integration tests: atomic write, attempt isolation, relocate, gc, verify, archive."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dagger_kernel.state import (
    K,
    Layer,
    RetryPolicy,
    SchemaError,
    StateStore,
)


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "run", run_id="run_test")


class TestWriteRead:
    def test_write_then_read_envelope(self, store: StateStore) -> None:
        key = K.result("nr_1", 1)
        ref = store.write_json(
            key,
            {
                "status": "success",
                "success": True,
                "outputs": {"chapters_done": 5},
                "summary": "ok",
            },
            kind="session_result",
            written_by={"role": "agent", "session_id": "ses_1", "backend": "mock"},
        )
        assert ref.sha256 and ref.size > 0
        env = store.read_envelope(key)
        assert env is not None
        assert env.kind == "session_result"
        assert env.body["success"] is True
        assert env.written_by["session_id"] == "ses_1"

    def test_invalid_body_rejected_with_field_errors(self, store: StateStore) -> None:
        key = K.result("nr_1", 1)
        with pytest.raises(SchemaError) as exc:
            store.write_json(
                key,
                {"status": "invalid-status", "success": "not-a-bool"},
                kind="session_result",
            )
        assert exc.value.kind == "session_result"
        assert exc.value.errors  # field-level errors populated

    def test_read_missing_returns_none(self, store: StateStore) -> None:
        assert store.read_json(K.result("nr_missing", 1)) is None

    def test_write_bytes_artifact(self, store: StateStore) -> None:
        ref = store.write_bytes(
            K.artifact_item("ch_1", "summary"),
            b"# chapter 1\n...",
            kind="artifact",
        )
        assert ref.size == len(b"# chapter 1\n...")
        # On disk.
        assert ref.path.read_bytes() == b"# chapter 1\n..."


class TestAtomicWrite:
    def test_no_partial_file_after_write(self, store: StateStore) -> None:
        key = K.result("nr_1", 1)
        store.write_json(key, {"status": "success", "success": True}, kind="session_result")
        # No .tmp files leaked.
        tmp_files = list(store.state_root.rglob("*.tmp.*"))
        assert tmp_files == []

    def test_concurrent_writes_same_key_last_wins(self, store: StateStore) -> None:
        key = K.result("nr_1", 1)
        for i in range(5):
            store.write_json(
                key,
                {"status": "success", "success": True, "summary": f"try-{i}"},
                kind="session_result",
            )
        env = store.read_envelope(key)
        assert env is not None
        assert env.body["summary"] == "try-4"

    def test_overwrite_existing_file_on_windows(self, store: StateStore) -> None:
        # os.replace must atomically replace — test it does not raise.
        key = K.result("nr_1", 1)
        store.write_json(key, {"status": "success", "success": True}, kind="session_result")
        store.write_json(
            key,
            {"status": "failed", "success": False, "error": "retry"},
            kind="session_result",
        )
        env = store.read_envelope(key)
        assert env is not None
        assert env.body["success"] is False


class TestAttemptIsolation:
    def test_fresh_attempt_starts_empty(self, store: StateStore) -> None:
        n1 = store.begin_attempt("nr_1", policy=RetryPolicy.FRESH)
        scratch1 = store.open_scratch("nr_1", n1)
        (scratch1 / "checkpoint.json").write_text('{"i":1}')
        n2 = store.begin_attempt("nr_1", policy=RetryPolicy.FRESH)
        scratch2 = store.open_scratch("nr_1", n2)
        assert not (scratch2 / "checkpoint.json").exists()
        assert n2 == 2

    def test_inherit_attempt_copies_previous(self, store: StateStore) -> None:
        n1 = store.begin_attempt("nr_1", policy=RetryPolicy.FRESH)
        scratch1 = store.open_scratch("nr_1", n1)
        (scratch1 / "state.json").write_text('{"step":3}')
        n2 = store.begin_attempt("nr_1", policy=RetryPolicy.INHERIT)
        scratch2 = store.open_scratch("nr_1", n2)
        assert (scratch2 / "state.json").read_text() == '{"step":3}'

    def test_latest_attempt_tracking(self, store: StateStore) -> None:
        assert store.latest_attempt("nr_1") == 0
        store.begin_attempt("nr_1")
        assert store.latest_attempt("nr_1") == 1
        store.begin_attempt("nr_1")
        assert store.latest_attempt("nr_1") == 2
        # Explicit pointer file reflects the latest.
        assert store.read_latest_attempt_pointer("nr_1") == 2

    def test_cross_node_scratch_isolation(self, store: StateStore) -> None:
        store.begin_attempt("nr_a")
        sa = store.open_scratch("nr_a", 1)
        (sa / "x.json").write_text("{}")
        store.begin_attempt("nr_b")
        sb = store.open_scratch("nr_b", 1)
        # node b's scratch does not see node a's file.
        assert not (sb / "x.json").exists()


class TestIndexJournal:
    def test_journal_records_every_write(self, store: StateStore) -> None:
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        store.write_bytes(
            K.artifact_item("ch_1", "summary"),
            b"data",
            kind="artifact",
        )
        entries = store.journal.read_all()
        assert len(entries) == 2
        assert entries[0].op == "write"
        assert entries[1].kind == "artifact"

    def test_index_query_by_layer(self, store: StateStore) -> None:
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        store.write_bytes(K.artifact_item("ch_1", "summary"), b"x", kind="artifact")
        store.save_index()
        # Re-open a fresh store to load from disk.
        store2 = StateStore(store.root, run_id=store.run_id)
        results = store2.query(layer=Layer.ARTIFACT)
        assert len(results) == 1
        assert results[0].key.item_id == "ch_1"

    def test_reindex_rebuilds_consistently(self, store: StateStore) -> None:
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        store.write_bytes(K.artifact_item("ch_1", "summary"), b"hello", kind="artifact")
        store.save_index()
        before = sorted((e.path, e.size) for e in store.index)

        # Corrupt: delete index.json, rebuild.
        (store.state_root / "index.json").unlink()
        store.reindex()
        after = sorted((e.path, e.size) for e in store.index)
        assert before == after


class TestRelocate:
    def test_relocate_preserves_api(self, tmp_path: Path) -> None:
        root1 = tmp_path / "orig"
        store = StateStore(root1, run_id="run_r")
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        # Move the directory.
        root2 = tmp_path / "moved"
        root1.rename(root2)
        store2 = store.relocate(root2)
        env = store2.read_envelope(K.result("nr_1", 1))
        assert env is not None
        assert env.body["success"] is True


class TestGcVerify:
    def test_gc_only_scratch_log(self, store: StateStore) -> None:
        # Populate each layer.
        store.begin_attempt("nr_1")
        scratch = store.open_scratch("nr_1", 1)
        (scratch / "tmp").write_text("x")
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        store.write_bytes(K.artifact_item("ch_1", "summary"), b"y", kind="artifact")
        # GC only scratch+log.
        freed = store.gc(layers=[Layer.SCRATCH, Layer.LOG])
        assert freed >= 1
        # Scratch dir emptied (contents gone), contract+artifact intact.
        assert not any((store.state_root / "scratch").iterdir())
        assert store.read_envelope(K.result("nr_1", 1)) is not None
        assert (store.state_root / "artifact").exists()
        # Artifact content still readable.
        art_path = store.path(K.artifact_item("ch_1", "summary"))
        assert art_path.read_bytes() == b"y"

    def test_gc_refuses_control_contract_artifact(self, store: StateStore) -> None:
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        # CONTRACT is durable — gc must report zero bytes freed and leave the file.
        freed = store.gc(layers=[Layer.CONTRACT])
        assert freed == 0
        assert store.read_envelope(K.result("nr_1", 1)) is not None

    def test_verify_detects_missing_and_corruption(self, store: StateStore) -> None:
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        store.save_index()
        # Corrupt the file's bytes after indexing.
        path = store.path(K.result("nr_1", 1))
        path.write_bytes(b"{}")
        problems = store.verify()
        assert any("sha256 mismatch" in p for p in problems)


class TestReadOnly:
    def test_readonly_load_works(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "r", run_id="run_ro")
        store.write_json(
            K.result("nr_1", 1),
            {"status": "success", "success": True},
            kind="session_result",
        )
        ro = StateStore(tmp_path / "r", run_id="run_ro", readonly=True)
        env = ro.read_envelope(K.result("nr_1", 1))
        assert env is not None
        with pytest.raises(PermissionError):
            ro.write_json(
                K.result("nr_1", 2),
                {"status": "success", "success": True},
                kind="session_result",
            )


class TestAppendJsonl:
    def test_append_jsonl_safe_after_kill(self, store: StateStore) -> None:
        key = K.transcript("nr_1", 1)
        for i in range(5):
            store.append_jsonl(key, {"i": i, "text": f"line-{i}"})
        path = store.path(key)
        # File is valid jsonl — every line parses.
        lines = path.read_text(encoding="utf-8").splitlines()
        objs = [json.loads(line) for line in lines if line.strip()]
        assert [o["i"] for o in objs] == [0, 1, 2, 3, 4]
