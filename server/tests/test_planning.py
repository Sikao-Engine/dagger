"""Planning endpoints: ledger refresh + plan GET."""

from __future__ import annotations

from pathlib import Path


def test_ledger_refresh_and_plan(client, items_dir: Path) -> None:
    # Refresh: scan items_dir via tiny's ItemSource.
    res = client.post(
        "/api/v1/projects/proj-1/ledger/refresh",
        json={"domain_id": "tiny", "items_dir": str(items_dir)},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["project_id"] == "proj-1"
    assert body["domain_id"] == "tiny"
    assert body["items_upserted"] == 3
    assert body["milestones_upserted"] == 0

    # GET ledger.
    res = client.get("/api/v1/projects/proj-1/ledger")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 3
    ids = {i["item_id"] for i in items}
    assert ids == {"alpha", "beta", "gamma"}
    assert all(i["status"] == "unseen" for i in items)

    # GET plan.
    res = client.get("/api/v1/projects/proj-1/plan")
    assert res.status_code == 200
    plan = res.json()
    assert plan["project_id"] == "proj-1"
    assert plan["total_items"] == 3
    assert plan["by_status"].get("unseen") == 3


def test_ledger_refresh_idempotent(client, items_dir: Path) -> None:
    """Re-refresh updates existing rows instead of duplicating."""
    client.post(
        "/api/v1/projects/proj-2/ledger/refresh",
        json={"domain_id": "tiny", "items_dir": str(items_dir)},
    )
    client.post(
        "/api/v1/projects/proj-2/ledger/refresh",
        json={"domain_id": "tiny", "items_dir": str(items_dir)},
    )
    res = client.get("/api/v1/projects/proj-2/ledger")
    assert len(res.json()) == 3  # no duplicates


def test_ledger_refresh_bad_domain(client) -> None:
    res = client.post(
        "/api/v1/projects/proj-x/ledger/refresh",
        json={"domain_id": "nope", "items_dir": "/tmp"},
    )
    assert res.status_code in (404, 500)


def test_plan_empty_project(client) -> None:
    res = client.get("/api/v1/projects/proj-empty/plan")
    assert res.status_code == 200
    assert res.json()["total_items"] == 0
