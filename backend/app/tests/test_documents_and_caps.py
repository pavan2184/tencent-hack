"""Uploads (validation, size, caps, ownership) and document classification."""

from __future__ import annotations

from typing import Any

from app.tests.conftest import run

RUNBOOK = ("confluence-ops", "runbooks/payment-rail-failover")


def _upload(client: Any, actor: str, name: str = "note.md", body: bytes | None = None) -> Any:
    content = body if body is not None else b"# Smoke test note\n\nRail-B smoke test content.\n"
    return client.post(
        "/api/documents/upload",
        files={"file": (name, content, "text/markdown")},
        headers={"X-Actor-Id": actor},
    )


def _override(services: Any, **values: Any) -> None:
    services.settings = services.settings.model_copy(update=values)


def test_upload_ok_is_ingested_and_visible_to_owner_only(seeded: Any, client: Any) -> None:
    response = _upload(client, "alex.tan")
    assert response.status_code == 201, response.text
    body = response.json()
    doc = body["document"]
    assert body["upload_id"]
    assert doc["source_id"] == "uploads"
    assert doc["owner_principal_id"] == "alex.tan"
    assert doc["title"] == "Smoke test note"
    assert doc["ingest_status"] == "indexed"
    assert doc["freshness_status"] == "fresh"

    assert client.get(f"/api/documents/{doc['id']}").status_code == 200
    listed = client.get("/api/documents", params={"source_id": "uploads"}).json()["items"]
    assert [d["id"] for d in listed] == [doc["id"]]
    hidden = client.get(f"/api/documents/{doc['id']}", headers={"X-Actor-Id": "mei.chen"})
    assert hidden.status_code == 404
    chunks = run(seeded.repo.list_chunks(doc["id"]))
    assert chunks and chunks[0].embedding is not None


def test_upload_ignores_frontmatter_permissions_and_owner(seeded: Any, client: Any) -> None:
    body = (
        b"---\ntitle: Sneaky\nowner: mei.chen\npermissions:\n  kind: upload\n"
        b"  owner_principal_id: mei.chen\ngrants:\n  - {subject_type: principal, "
        b"subject_id: mei.chen, effect: allow}\n---\nSome text about nothing much.\n"
    )
    response = _upload(client, "alex.tan", body=body)
    assert response.status_code == 201
    doc = response.json()["document"]
    assert doc["owner_principal_id"] == "alex.tan"
    detail = client.get(f"/api/documents/{doc['id']}").json()
    assert "permissions" not in detail["frontmatter"]
    assert "grants" not in detail["frontmatter"]
    as_mei = client.get(f"/api/documents/{doc['id']}", headers={"X-Actor-Id": "mei.chen"})
    assert as_mei.status_code == 404


def test_bad_extension_is_422(seeded: Any, client: Any) -> None:
    response = _upload(client, "alex.tan", name="evil.exe", body=b"MZ binary")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_empty_file_is_422(seeded: Any, client: Any) -> None:
    assert _upload(client, "alex.tan", body=b"   \n").status_code == 422


def test_oversize_is_413(seeded: Any, client: Any) -> None:
    _override(seeded, UPLOAD_MAX_FILE_BYTES=64)
    response = _upload(client, "alex.tan", body=b"x" * 65)
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "payload_too_large"
    assert error["details"] == {"limit_bytes": 64}


def test_per_actor_daily_cap_is_429(seeded: Any, client: Any) -> None:
    _override(seeded, UPLOAD_MAX_FILES_PER_ACTOR_PER_DAY=2)
    assert _upload(client, "alex.tan", name="a.md").status_code == 201
    assert _upload(client, "alex.tan", name="b.md").status_code == 201
    third = _upload(client, "alex.tan", name="c.md")
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "cap_exceeded"
    assert third.json()["error"]["details"] == {
        "cap": "uploads_per_actor_per_day",
        "limit": 2,
        "window": "day",
    }
    # Another actor is unaffected.
    assert _upload(client, "john.tan", name="d.md").status_code == 201


def test_total_cap_is_429(seeded: Any, client: Any) -> None:
    _override(seeded, UPLOAD_MAX_FILES_TOTAL=2)
    assert _upload(client, "alex.tan", name="a.md").status_code == 201
    assert _upload(client, "john.tan", name="b.md").status_code == 201
    third = _upload(client, "jordan.lim", name="c.md")
    assert third.status_code == 429
    assert third.json()["error"]["details"] == {
        "cap": "uploads_total",
        "limit": 2,
        "window": "total",
    }
    # The rejected upload was not recorded.
    assert run(seeded.repo.count_uploads_total()) == 2


def test_classification_change_by_owner_ok_by_stranger_denied(seeded: Any, client: Any) -> None:
    page = run(seeded.repo.get_page_by_slug(*RUNBOOK))
    url = f"/api/documents/{page.id}/classification"
    # alex.tan owns the failover runbook.
    owner = client.patch(url, json={"classification": "restricted", "reason": "test"})
    assert owner.status_code == 200, owner.text
    assert owner.json()["classification"] == "restricted"
    # jordan.lim could read it before (finance-ops space group) but does not own it; after the
    # owner restricted it he cannot see it at all -> the canonical 404.
    stranger = client.patch(
        url, json={"classification": "internal"}, headers={"X-Actor-Id": "jordan.lim"}
    )
    assert stranger.status_code == 404
    client.patch(url, json={"classification": "internal"})
    visible_not_owner = client.patch(
        url, json={"classification": "public"}, headers={"X-Actor-Id": "jordan.lim"}
    )
    assert visible_not_owner.status_code == 403
    invisible = client.patch(
        url, json={"classification": "public"}, headers={"X-Actor-Id": "mei.chen"}
    )
    assert invisible.status_code == 404
    events = run(seeded.repo.list_audit_events(action="document.classification"))
    assert len(events) == 2


def test_document_list_is_acl_filtered(seeded: Any, client: Any) -> None:
    mei = client.get("/api/documents", headers={"X-Actor-Id": "mei.chen"}).json()
    # The contractor sees exactly the one Drive file shared with the contractor address.
    assert [d["slug"] for d in mei["items"]] == ["files/rail-b-integration-test-plan"]
    john = client.get("/api/documents", params={"limit": 100}, headers={"X-Actor-Id": "john.tan"})
    slugs = {d["slug"] for d in john.json()["items"]}
    assert "files/board-deck-q3" in slugs
    alex = client.get("/api/documents", params={"limit": 100}).json()
    assert "files/board-deck-q3" not in {d["slug"] for d in alex["items"]}
