"""Attempt transcript + stream endpoints."""

from __future__ import annotations

import json
from pathlib import Path


def _create_run(client, items_dir: Path) -> str:
    res = client.post(
        "/api/v1/runs",
        json={
            "domain_id": "tiny",
            "items_dir": str(items_dir),
            "shards": 1,
            "backend": "mock",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["run_id"]


def test_transcript_empty_for_mock_run(client, items_dir: Path) -> None:
    """Mock dispatcher writes no transcript → empty array."""
    run_id = _create_run(client, items_dir)
    # Find an agent node (work/report), not the builtin init.
    res = client.get(f"/api/v1/runs/{run_id}/pipeline")
    node = next(n for n in res.json()["nodes"] if n["node_type"] != "tiny.init")
    res = client.get(f"/api/v1/nodes/{node['id']}/attempts")
    attempt_id = res.json()[0]["id"]
    res = client.get(f"/api/v1/attempts/{attempt_id}/transcript")
    assert res.status_code == 200
    assert res.json() == []


def test_transcript_reads_written_jsonl(
    client, items_dir: Path, data_dir: Path
) -> None:
    """Write a fake transcript.jsonl → GET returns its lines."""
    from loom_kernel.state import K, StateStore

    run_id = _create_run(client, items_dir)
    # Find an attempt + its node_run.
    res = client.get(f"/api/v1/runs/{run_id}/pipeline")
    nodes = res.json()["nodes"]
    # Pick an agent node (work/report), not init.
    node = next(n for n in nodes if n["node_type"] != "tiny.init")
    node_id = node["id"]
    res = client.get(f"/api/v1/nodes/{node_id}/attempts")
    attempt = res.json()[0]
    attempt_id = attempt["id"]
    attempt_num = attempt["attempt"]

    # Reconstruct the store + write a transcript.
    run = client.get(f"/api/v1/runs/{run_id}").json()
    store = StateStore(data_dir / Path(run["state_root_rel"]).parent, run_id=run_id)
    path = store.path(K.transcript(node_id, attempt_num))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"kind": "text", "text": "hello"})
        + "\n"
        + json.dumps({"kind": "tool", "tool": "edit"})
        + "\n",
        encoding="utf-8",
    )

    res = client.get(f"/api/v1/attempts/{attempt_id}/transcript")
    assert res.status_code == 200
    lines = res.json()
    assert len(lines) == 2
    assert lines[0]["kind"] == "text"
    assert lines[1]["tool"] == "edit"


def test_transcript_not_found(client) -> None:
    res = client.get("/api/v1/attempts/no-such/transcript")
    assert res.status_code == 404


def test_attempt_stream_not_found(client) -> None:
    res = client.get("/api/v1/attempts/no-such/stream")
    assert res.status_code == 404
