"""T7.1: per-item artifacts REST surface.

GET /api/v1/runs/{run_id}/items/{item_id}/artifacts
GET /api/v1/runs/{run_id}/items/{item_id}/artifacts/{slot}
"""

from __future__ import annotations

from pathlib import Path


def _create_run(client, items_dir: Path) -> str:
    res = client.post(
        "/api/v1/runs",
        json={
            "domain_id": "tiny",
            "items_dir": str(items_dir),
            "shards": 3,
            "backend": "mock",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["run_id"]


def test_domain_lists_artifact_spec(client) -> None:
    res = client.get("/api/v1/domains")
    assert res.status_code == 200
    tiny = next(d for d in res.json() if d["id"] == "tiny")
    assert tiny["artifact_spec"] is not None
    assert tiny["artifact_spec"]["default_view"] == "tabs"
    slot_names = [s["name"] for s in tiny["artifact_spec"]["slots"]]
    assert slot_names == ["summary"]


def test_item_artifacts_groups_by_spec(client, items_dir: Path) -> None:
    run_id = _create_run(client, items_dir)
    # alpha is the first item in the items_dir fixture.
    res = client.get(f"/api/v1/runs/{run_id}/items/alpha/artifacts")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["run_id"] == run_id
    assert body["item_id"] == "alpha"
    assert body["spec"] is not None
    assert body["spec"]["slots"][0]["name"] == "summary"
    slots = body["slots"]
    summary = next(s for s in slots if s["slot"]["name"] == "summary")
    assert summary["ref"] is not None
    assert summary["undeclared"] is False
    assert summary["ref"]["sha256"]


def test_item_artifact_bytes_returns_raw(client, items_dir: Path) -> None:
    run_id = _create_run(client, items_dir)
    res = client.get(f"/api/v1/runs/{run_id}/items/alpha/artifacts/summary")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    body = res.content
    assert b"alpha" in body
    assert res.headers.get("X-DivDag-Slot") == "summary"
    assert res.headers.get("X-DivDag-Sha256")


def test_item_artifact_bytes_missing_slot_404(client, items_dir: Path) -> None:
    run_id = _create_run(client, items_dir)
    res = client.get(f"/api/v1/runs/{run_id}/items/alpha/artifacts/does-not-exist")
    assert res.status_code == 404


def test_item_artifacts_missing_item_returns_empty_slots(
    client, items_dir: Path
) -> None:
    """An item with no written artifacts still returns the declared slots,
    each with ref=None, so the UI shows placeholders rather than an empty list."""
    run_id = _create_run(client, items_dir)
    res = client.get(f"/api/v1/runs/{run_id}/items/never-written/artifacts")
    assert res.status_code == 200
    body = res.json()
    assert body["spec"] is not None
    summary = next(s for s in body["slots"] if s["slot"]["name"] == "summary")
    assert summary["ref"] is None
    assert summary["undeclared"] is False


def test_item_artifacts_run_not_found(client) -> None:
    res = client.get("/api/v1/runs/nope/items/whatever/artifacts")
    assert res.status_code == 404
