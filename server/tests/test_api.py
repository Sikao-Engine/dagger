"""T5.5: REST surface — end-to-end via Litestar TestClient.

POST /api/v1/runs creates + schedules + runs the tiny domain synchronously,
then GET endpoints read back the run, pipeline, node states, and state index.
"""

from __future__ import annotations

from pathlib import Path


def test_list_domains(client) -> None:
    res = client.get("/api/v1/domains")
    assert res.status_code == 200
    data = res.json()
    ids = [d["id"] for d in data]
    assert "tiny" in ids


def test_list_executors(client) -> None:
    res = client.get("/api/v1/executors")
    assert res.status_code == 200
    keys = [e["key"] for e in res.json()]
    assert "tiny.work" in keys


def test_list_templates_filtered(client) -> None:
    res = client.get("/api/v1/templates", params={"domain": "tiny"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["domain_id"] == "tiny"


def test_create_run_end_to_end(client, items_dir: Path) -> None:
    payload = {
        "domain_id": "tiny",
        "items_dir": str(items_dir),
        "shards": 3,
        "backend": "mock",
    }
    res = client.post("/api/v1/runs", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "completed"
    assert body["completed"] == 5
    assert body["failed"] == 0
    run_id = body["run_id"]

    # GET /runs/:id
    res = client.get(f"/api/v1/runs/{run_id}")
    assert res.status_code == 200
    assert res.json()["domain_id"] == "tiny"

    # GET /runs/:id/pipeline
    res = client.get(f"/api/v1/runs/{run_id}/pipeline")
    assert res.status_code == 200
    pipe = res.json()
    assert pipe["run_id"] == run_id
    assert pipe["status"] == "completed"
    assert pipe["completed"] == 5
    assert len(pipe["nodes"]) == 5
    assert all(n["status"] == "success" for n in pipe["nodes"])
    assert len(pipe["shards"]) == 3

    # GET /runs/:id/events
    res = client.get(f"/api/v1/runs/{run_id}/events")
    assert res.status_code == 200
    types = [e["type"] for e in res.json()]
    assert "run.started" in types
    assert "run.completed" in types

    # GET /nodes/:id
    work_node = next(n for n in pipe["nodes"] if n["node_type"] == "tiny.work")
    res = client.get(f"/api/v1/nodes/{work_node['id']}")
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # GET /nodes/:id/attempts
    res = client.get(f"/api/v1/nodes/{work_node['id']}/attempts")
    assert res.status_code == 200
    atts = res.json()
    assert len(atts) == 1
    assert atts[0]["status"] == "success"
    assert atts[0]["transcript_path_rel"]  # relative path populated

    # GET /runs/:id/state (index — all layers: 5 contract results + 1 control plan)
    res = client.get(f"/api/v1/runs/{run_id}/state")
    assert res.status_code == 200
    entries = res.json()
    contract_entries = [e for e in entries if e["layer"] == "contract"]
    assert len(contract_entries) == 5
    assert all(e["kind"] == "session_result" for e in contract_entries)

    # GET /runs/:id/state/object?layer=contract&node_run_id=...
    res = client.get(
        f"/api/v1/runs/{run_id}/state/object",
        params={"layer": "contract", "node_run_id": work_node["id"]},
    )
    assert res.status_code == 200
    obj = res.json()
    assert obj["body"]["success"] is True
    assert obj["kind"] == "session_result"


def test_get_run_not_found(client) -> None:
    res = client.get("/api/v1/runs/nope")
    assert res.status_code == 404


def test_create_run_bad_domain(client, items_dir: Path) -> None:
    payload = {"domain_id": "nope", "items_dir": str(items_dir), "shards": 1}
    res = client.post("/api/v1/runs", json=payload)
    assert res.status_code == 404


def test_create_run_empty_items(client, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    payload = {"domain_id": "tiny", "items_dir": str(empty), "shards": 1}
    res = client.post("/api/v1/runs", json=payload)
    assert res.status_code == 404
