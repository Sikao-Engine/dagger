"""Agent process endpoints: list + status + stop (process_manager is empty in tests)."""

from __future__ import annotations


def test_list_processes_empty(client) -> None:
    res = client.get("/api/v1/agents/processes")
    assert res.status_code == 200
    assert res.json() == []


def test_status_text(client) -> None:
    res = client.get("/api/v1/agents/processes/status")
    assert res.status_code == 200
    assert "no agentcli processes" in res.json()["status"]


def test_stop_unknown_returns_404(client) -> None:
    res = client.post("/api/v1/agents/processes/no-such-key/stop")
    assert res.status_code == 404


def test_stop_all(client) -> None:
    res = client.post("/api/v1/agents/processes/stop-all")
    assert res.status_code == 201
    assert res.json()["stopped"] == 0
