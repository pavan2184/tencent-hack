"""Final wording around denied access: the approver is told why an approval did not open the
document (in terms they can act on) and what a denial does; the requester learns nothing."""

from __future__ import annotations

from typing import Any

from access_control import Effect, Grant, SubjectType

from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
ADMIN = {"X-Actor-Id": "root.admin"}
ALEX = {"X-Actor-Id": "alex.tan"}


def _deck(services: Any) -> str:
    return run(services.repo.get_page_by_slug(*DECK)).id


def _request(client: Any, doc_id: str, headers: dict[str, str] = ALEX) -> str:
    assert (
        client.post(f"/api/documents/{doc_id}/access-requests", headers=headers).status_code == 202
    )
    (request,) = [
        r
        for r in client.get("/api/access/requests", headers=ADMIN).json()["items"]
        if r["document_id"] == doc_id
    ]
    return request["id"]


def _approve(client: Any, request_id: str) -> dict[str, Any]:
    res = client.post(f"/api/access/requests/{request_id}/approve", headers=ADMIN)
    assert res.status_code == 200, res.text
    return res.json()


def test_denial_says_nothing_changes_and_nobody_is_told(seeded: Any, client: Any) -> None:
    request_id = _request(client, _deck(seeded))
    denied = client.post(f"/api/access/requests/{request_id}/deny", headers=ADMIN).json()
    assert denied["request"]["status"] == "denied"
    assert denied["note"] == "Denied. Nothing changes for Alex Tan, and they aren't notified."
    # The requester has no view of decided requests at all.
    assert client.get("/api/access/requests", headers=ALEX).json()["items"] == []


def test_approval_blocked_by_the_source_names_the_platform(seeded: Any, client: Any) -> None:
    approved = _approve(client, _request(client, _deck(seeded)))
    assert approved["effective"] is False
    assert approved["note"] == (
        "Approved, but Alex Tan still can't open this document: Google Drive doesn't share it "
        "with them. Ask the owner to share it in Google Drive."
    )


def test_approval_while_permissions_are_unconfirmed(seeded: Any, client: Any) -> None:
    request_id = _request(client, _deck(seeded))
    seeded.clock.advance(6 * 60)  # the deck's snapshot has aged out (5 min, confidential)
    note = _approve(client, request_id)["note"]
    assert note.startswith("Approved, but Google Drive hasn't confirmed")
    assert "closed to everyone until the next successful sync" in note


def test_approval_blocked_by_a_deny_grant_says_to_revoke_it(seeded: Any, client: Any) -> None:
    deck = _deck(seeded)
    john = {"X-Actor-Id": "john.tan"}
    request_id = _request(client, deck, john)
    run(
        seeded.grant_store.add(
            Grant(
                document_id=deck,
                subject_type=SubjectType.principal,
                subject_id="john.tan",
                effect=Effect.deny,
                granted_by="root.admin",
                granted_at=seeded.clock.now(),
            )
        )
    )
    assert _approve(client, request_id)["note"] == (
        "Approved, but a deny grant on this document still blocks John Tan. Revoke it to let "
        "them in."
    )


def test_approval_for_an_inactive_requester(seeded: Any, client: Any) -> None:
    request_id = _request(client, _deck(seeded))
    alex = run(seeded.repo.get_principal("alex.tan"))
    run(seeded.repo.upsert_principal(alex.model_copy(update={"is_active": False})))
    assert _approve(client, request_id)["note"] == (
        "Approved, but Alex Tan's account is inactive, so they still can't open it."
    )
