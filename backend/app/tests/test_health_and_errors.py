"""Health, the error envelope, request ids, and the canonical (non-leaking) document 404."""

from __future__ import annotations

import uuid
from typing import Any

from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")


def _deck_id(services: Any) -> str:
    page = run(services.repo.get_page_by_slug(*DECK))
    assert page is not None
    return page.id


def test_healthz(client: Any) -> None:
    for path in ("/healthz", "/api/healthz"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["provider_mode"] == "mock"
        assert body["db"] == "memory"


def test_request_id_is_echoed_or_generated(client: Any) -> None:
    echoed = client.get("/healthz", headers={"X-Request-Id": "req-test-123"})
    assert echoed.headers["X-Request-Id"] == "req-test-123"
    generated = client.get("/healthz", headers={"X-Request-Id": "bad id with spaces"})
    assert generated.headers["X-Request-Id"].startswith("req_")


def test_missing_actor_is_401_unauthenticated(seeded: Any, client: Any) -> None:
    response = client.get("/api/me", headers={"X-Actor-Id": ""})
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "unauthenticated"
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["request_id"] == response.headers["X-Request-Id"]


def test_unknown_actor_is_401_unknown_actor(seeded: Any, client: Any) -> None:
    response = client.get("/api/me", headers={"X-Actor-Id": "nobody"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unknown_actor"


def test_me_and_principals(seeded: Any, client: Any) -> None:
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["id"] == "alex.tan"
    assert me.json()["groups"] == ["engineering"]
    principals = client.get("/api/principals", headers={"X-Actor-Id": ""})
    assert principals.status_code == 200
    assert {p["id"] for p in principals.json()["items"]} >= {"alex.tan", "mei.chen", "sam.lee"}


def test_validation_error_is_rewritten_into_the_envelope(seeded: Any, client: Any) -> None:
    response = client.post("/api/ask", json={})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["errors"]


def test_denied_document_404_identical_to_missing(seeded: Any, client: Any) -> None:
    deck_id = _deck_id(seeded)
    headers = {"X-Actor-Id": "mei.chen", "X-Request-Id": "req-same"}
    denied = client.get(f"/api/documents/{deck_id}", headers=headers)
    missing = client.get(f"/api/documents/{uuid.uuid4()}", headers=headers)
    malformed = client.get("/api/documents/not-a-uuid", headers=headers)
    assert denied.status_code == missing.status_code == malformed.status_code == 404
    assert denied.content == missing.content == malformed.content
    assert denied.json()["error"] == {
        "code": "not_found",
        "message": "Document not found.",
        "details": {},
        "request_id": "req-same",
    }
    # Sub-resources of an invisible document answer the same way.
    timeline = client.get(f"/api/documents/{deck_id}/timeline", headers=headers)
    assert timeline.content == missing.content
