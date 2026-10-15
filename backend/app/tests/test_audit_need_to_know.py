"""Auditors see every decision but only the answer content they could read themselves; anything
more needs a recorded break-glass reveal. Approvals report when the source still blocks access."""

from __future__ import annotations

from typing import Any

from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
KYC = ("confluence-ops", "runbooks/kyc-refresh")
QUESTION = "What were the Q3 board deck revenue figures?"
FIGURE = "48.6"
PRIYA = {"X-Actor-Id": "priya.nair"}
AUDITOR = {"X-Actor-Id": "sam.lee"}
ADMIN = {"X-Actor-Id": "root.admin"}
REASON = {"reason": "Investigating board deck access for compliance case 42"}


def _page_id(services: Any, ref: tuple[str, str]) -> str:
    return run(services.repo.get_page_by_slug(*ref)).id


def _ask_deck(client: Any) -> dict[str, Any]:
    env = client.post("/api/ask", json={"question": QUESTION}, headers=PRIYA).json()
    assert FIGURE in env["answer"]["text"]
    return env


def test_auditor_sees_decisions_but_not_content_they_cannot_read(seeded: Any, client: Any) -> None:
    deck_id = _page_id(seeded, DECK)
    env = _ask_deck(client)
    event = client.get(f"/api/audit/events/{env['audit_id']}", headers=AUDITOR).json()

    assert event["content_withheld"] is True
    assert FIGURE not in str(event)
    payload = event["payload"]
    assert payload["question"] == QUESTION
    assert deck_id in payload["retrieved_document_ids"]
    assert deck_id in payload["cited_document_ids"]
    decisions = {d["document_id"]: d["decision"] for d in payload["access_decisions"]}
    assert decisions[deck_id] == "allow"
    query = event["reconstruction"]["query"]
    assert query["answer_text"] is None and query["citations"] == []
    assert query["grounding_report"] is None


def test_list_view_applies_the_same_rule(seeded: Any, client: Any) -> None:
    env = _ask_deck(client)
    items = client.get("/api/audit/events", params={"action": "ask"}, headers=AUDITOR).json()
    (item,) = [i for i in items["items"] if i["id"] == env["audit_id"]]
    assert item["content_withheld"] is True and FIGURE not in str(item)
    seed_events = client.get(
        "/api/audit/events", params={"action": "seed.loaded"}, headers=AUDITOR
    ).json()["items"]
    assert all(e["content_withheld"] is False for e in seed_events)


def test_reveal_needs_a_reason_and_is_itself_audited(seeded: Any, client: Any) -> None:
    env = _ask_deck(client)
    path = f"/api/audit/events/{env['audit_id']}/reveal"
    assert client.post(path, json={"reason": "why"}, headers=AUDITOR).status_code == 422
    assert client.post(path, json={}, headers=AUDITOR).status_code == 422

    revealed = client.post(path, json=REASON, headers=AUDITOR)
    assert revealed.status_code == 200
    assert revealed.json()["content_withheld"] is False
    assert FIGURE in revealed.json()["payload"]["answer_text"]

    reveals = client.get(
        "/api/audit/events", params={"action": "audit.reveal"}, headers=AUDITOR
    ).json()["items"]
    assert len(reveals) == 1
    reveal = reveals[0]
    assert reveal["actor_id"] == "sam.lee"
    assert reveal["subject_type"] == "audit_event" and reveal["subject_id"] == env["audit_id"]
    assert reveal["payload"]["reason"] == REASON["reason"]
    assert client.get("/api/audit/verify", headers=AUDITOR).json()["ok"] is True


def test_reveal_is_auditor_or_admin_only(seeded: Any, client: Any) -> None:
    env = _ask_deck(client)
    path = f"/api/audit/events/{env['audit_id']}/reveal"
    assert client.post(path, json=REASON, headers=PRIYA).status_code == 403


def test_viewer_who_can_read_the_evidence_needs_no_reveal(seeded: Any, client: Any) -> None:
    # root.admin asks, so every evidence document is one root.admin can read.
    env = client.post("/api/ask", json={"question": QUESTION}, headers=ADMIN).json()
    assert FIGURE in env["answer"]["text"]
    event = client.get(f"/api/audit/events/{env['audit_id']}", headers=ADMIN).json()
    assert event["content_withheld"] is False
    assert FIGURE in event["payload"]["answer_text"]
    path = f"/api/audit/events/{env['audit_id']}/reveal"
    assert client.post(path, json=REASON, headers=ADMIN).status_code == 200
    reveals = client.get(
        "/api/audit/events", params={"action": "audit.reveal"}, headers=ADMIN
    ).json()["items"]
    assert reveals == []  # nothing was withheld, so nothing to record
    # The same event is still withheld from an auditor who cannot read the deck.
    assert client.get(f"/api/audit/events/{env['audit_id']}", headers=AUDITOR).json()[
        "content_withheld"
    ]


def test_approval_reports_when_the_source_still_blocks_access(seeded: Any, client: Any) -> None:
    kyc_id = _page_id(seeded, KYC)
    alex = {"X-Actor-Id": "alex.tan"}
    assert client.post(f"/api/documents/{kyc_id}/access-requests", headers=alex).status_code == 202
    (request,) = [
        r
        for r in client.get("/api/access/requests", headers=ADMIN).json()["items"]
        if r["document_id"] == kyc_id
    ]
    approved = client.post(f"/api/access/requests/{request['id']}/approve", headers=ADMIN).json()
    assert approved["request"]["status"] == "approved"
    assert approved["effective"] is False
    assert "Confluence" in approved["note"] and "Alex Tan" in approved["note"]
    assert client.get(f"/api/documents/{kyc_id}", headers=alex).status_code == 404


def test_approval_of_a_local_upload_takes_effect(seeded: Any, client: Any) -> None:
    owner = {"X-Actor-Id": "alex.tan"}
    reader = {"X-Actor-Id": "mei.chen"}
    uploaded = client.post(
        "/api/documents/upload",
        files={"file": ("notes.md", b"# Notes\nShared with a reviewer.\n", "text/markdown")},
        headers=owner,
    )
    doc_id = uploaded.json()["document"]["id"]
    assert (
        client.post(f"/api/documents/{doc_id}/access-requests", headers=reader).status_code == 202
    )
    (request,) = [
        r
        for r in client.get("/api/access/requests", headers=owner).json()["items"]
        if r["document_id"] == doc_id
    ]
    approved = client.post(f"/api/access/requests/{request['id']}/approve", headers=owner).json()
    assert approved["effective"] is True and approved["note"] is None
    assert client.get(f"/api/documents/{doc_id}", headers=reader).status_code == 200
