"""Sources: list, status (admin-only object counts), manual sync (202 run_id), stubs 501."""

from __future__ import annotations

from typing import Any

from app.schemas.domain import Source
from app.tests.conftest import run


def test_list_sources(seeded: Any, client: Any) -> None:
    response = client.get("/api/sources")
    assert response.status_code == 200
    items = {s["id"]: s for s in response.json()["items"]}
    assert len(items) == 6
    assert items["confluence-ops"]["connector"] == "gbrain_import"
    assert items["confluence-ops"]["kind"] == "confluence"
    assert items["uploads"]["connector"] == "upload"
    assert items["confluence-ops"]["last_sync_at"] is not None


def test_source_status(seeded: Any, client: Any) -> None:
    alex = client.get("/api/sources/confluence-ops/status")
    assert alex.status_code == 200
    body = alex.json()
    assert body["source_id"] == "confluence-ops"
    assert body["connector_kind"] == "confluence"
    assert body["last_run"]["status"] == "completed"
    assert "objects_by_status" not in body
    admin = client.get("/api/sources/confluence-ops/status", headers={"X-Actor-Id": "root.admin"})
    assert admin.json()["objects_by_status"] == {"fresh": 2, "stale": 1}
    assert client.get("/api/sources/nope/status").status_code == 404


def test_sync_is_202_with_run_id(seeded: Any, client: Any) -> None:
    manager = {"X-Actor-Id": "john.tan"}
    response = client.post(
        "/api/sources/confluence-ops/sync", json={"trigger_kind": "reconcile"}, headers=manager
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    assert run_id
    stored = run(seeded.freshness_store.get_run(run_id))
    assert stored is not None
    assert str(stored.status) == "completed"  # eager mode: the worker ran inline
    assert client.post("/api/sources/confluence-ops/sync", json={}).status_code == 403
    assert client.post("/api/sources/nope/sync", headers=manager).status_code == 404


def test_stub_source_sync_is_501(seeded: Any, client: Any) -> None:
    run(seeded.repo.upsert_source(Source(id="slack-live", name="Slack (live)", kind="slack")))
    response = client.post("/api/sources/slack-live/sync", headers={"X-Actor-Id": "root.admin"})
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"


def test_add_source_admin_only(seeded: Any, client: Any) -> None:
    body = {"id": "confluence-eng", "name": "Confluence ENG", "kind": "confluence"}
    assert client.post("/api/sources", json=body).status_code == 403
    created = client.post("/api/sources", json=body, headers={"X-Actor-Id": "root.admin"})
    assert created.status_code == 201
    assert created.json()["connector"] == "confluence"
    dup = client.post("/api/sources", json=body, headers={"X-Actor-Id": "root.admin"})
    assert dup.status_code == 409
