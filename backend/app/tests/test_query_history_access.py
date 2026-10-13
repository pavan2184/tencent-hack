"""Stored answers cannot replay evidence after a revocation: query history is re-authorised on
every read (`access.readable_query_records`)."""

from __future__ import annotations

from typing import Any

from access_control import Effect, Grant, SubjectType

from app.schemas.domain import QueryRecord
from app.services.access import QUERY_WITHHELD_STATUS, QUERY_WITHHELD_TEXT
from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
DECK_QUESTION = "What were the Q3 board deck revenue figures?"
DECK_FIGURE = "48.6"
PRIYA = {"X-Actor-Id": "priya.nair"}
ADMIN = {"X-Actor-Id": "root.admin"}
AUDITOR = {"X-Actor-Id": "sam.lee"}


def _deck_id(services: Any) -> str:
    return run(services.repo.get_page_by_slug(*DECK)).id


def _ask(client: Any, headers: dict[str, str], question: str) -> dict[str, Any]:
    response = client.post("/api/ask", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _revoke_leadership(client: Any, deck_id: str) -> None:
    grants = client.get("/api/access/grants", params={"document_id": deck_id}, headers=ADMIN)
    (leadership,) = [g for g in grants.json()["items"] if g["subject_id"] == "leadership"]
    assert client.delete(f"/api/access/grants/{leadership['id']}", headers=ADMIN).status_code == 200


def _assert_withheld(body: dict[str, Any], deck_id: str) -> None:
    assert body["status"] == QUERY_WITHHELD_STATUS
    assert body["answer_text"] == QUERY_WITHHELD_TEXT
    assert DECK_FIGURE not in str(body)
    assert deck_id not in str(body)


def test_history_withholds_answer_after_revocation(seeded: Any, client: Any) -> None:
    deck_id = _deck_id(seeded)
    before = _ask(client, PRIYA, DECK_QUESTION)
    assert deck_id in {c["document_id"] for c in before["citations"]}
    stored = client.get(f"/api/queries/{before['query_id']}", headers=PRIYA).json()
    assert DECK_FIGURE in stored["answer_text"]  # readable while access lasts

    _revoke_leadership(client, deck_id)
    assert client.get(f"/api/documents/{deck_id}", headers=PRIYA).status_code == 404

    detail = client.get(f"/api/queries/{before['query_id']}", headers=PRIYA)
    assert detail.status_code == 200
    body = detail.json()
    _assert_withheld(body, deck_id)
    assert body["citations"] == [] and body["grounding_report"] is None
    assert body["freshness_receipt_id"] is None
    assert body["question"] == DECK_QUESTION

    (listed,) = [
        i
        for i in client.get("/api/queries", headers=PRIYA).json()["items"]
        if i["id"] == before["query_id"]
    ]
    _assert_withheld(listed, deck_id)

    # A new question reflects the revocation too, so no path replays the old evidence.
    after = _ask(client, PRIYA, DECK_QUESTION)
    assert DECK_FIGURE not in str((after["answer"], after["claims"], after["citations"]))


def test_history_reauthorises_the_viewer_not_the_original_asker(seeded: Any, client: Any) -> None:
    deck_id = _deck_id(seeded)
    asked = _ask(client, PRIYA, DECK_QUESTION)
    # An auditor without access to the deck cannot read its content through query history...
    viewed = client.get(f"/api/queries/{asked['query_id']}", headers=AUDITOR).json()
    _assert_withheld(viewed, deck_id)
    # ...nor through the audit trail, except by a recorded break-glass reveal.
    event = client.get(f"/api/audit/events/{asked['audit_id']}", headers=AUDITOR).json()
    assert event["content_withheld"] is True and DECK_FIGURE not in str(event)
    revealed = client.post(
        f"/api/audit/events/{asked['audit_id']}/reveal",
        json={"reason": "Investigating board deck access"},
        headers=AUDITOR,
    ).json()
    assert DECK_FIGURE in revealed["payload"]["answer_text"]


def test_restored_access_restores_history(seeded: Any, client: Any) -> None:
    deck_id = _deck_id(seeded)
    asked = _ask(client, PRIYA, DECK_QUESTION)
    _revoke_leadership(client, deck_id)
    assert client.get(f"/api/queries/{asked['query_id']}", headers=PRIYA).json()["status"] == (
        QUERY_WITHHELD_STATUS
    )
    run(
        seeded.grant_store.add(
            Grant(
                document_id=deck_id,
                subject_type=SubjectType.principal,
                subject_id="priya.nair",
                effect=Effect.allow,
                granted_by="root.admin",
                granted_at=seeded.clock.now(),
            )
        )
    )
    restored = client.get(f"/api/queries/{asked['query_id']}", headers=PRIYA).json()
    assert restored["status"] == asked_status(asked)
    assert DECK_FIGURE in restored["answer_text"]


def asked_status(envelope: dict[str, Any]) -> str:
    return "abstained" if envelope["answer"]["abstained"] else "answered"


def test_revocation_for_another_document_leaves_unrelated_history(seeded: Any, client: Any) -> None:
    deck_id = _deck_id(seeded)
    asked = _ask(client, {"X-Actor-Id": "jordan.lim"}, "What is the plan for the Rail-B cutover?")
    _revoke_leadership(client, deck_id)  # Jordan never had the deck
    body = client.get(f"/api/queries/{asked['query_id']}", headers={"X-Actor-Id": "jordan.lim"})
    assert body.json()["status"] == asked_status(asked)
    assert body.json()["answer_text"] == asked["answer"]["text"]


def test_only_answers_built_on_the_revoked_document_are_withheld(seeded: Any, client: Any) -> None:
    deck_id = _deck_id(seeded)
    unrelated = _ask(client, PRIYA, "What is the plan for the Rail-B cutover?")
    event = run(seeded.repo.get_audit_event(unrelated["audit_id"]))
    assert deck_id not in event.payload["evidence_document_ids"]  # precondition
    related = _ask(client, PRIYA, DECK_QUESTION)
    assert deck_id in event_evidence(seeded, related)

    _revoke_leadership(client, deck_id)
    kept = client.get(f"/api/queries/{unrelated['query_id']}", headers=PRIYA).json()
    assert kept["status"] == asked_status(unrelated)
    assert kept["answer_text"] == unrelated["answer"]["text"]
    gone = client.get(f"/api/queries/{related['query_id']}", headers=PRIYA).json()
    assert gone["status"] == QUERY_WITHHELD_STATUS


def event_evidence(services: Any, envelope: dict[str, Any]) -> list[str]:
    return run(services.repo.get_audit_event(envelope["audit_id"])).payload["evidence_document_ids"]


def test_history_without_audit_evidence_fails_closed(seeded: Any, client: Any) -> None:
    record = run(
        seeded.repo.create_query(
            QueryRecord(
                actor_id="priya.nair",
                question="orphaned row",
                status="answered",
                answer_text="Text derived from evidence that can no longer be traced.",
            )
        )
    )
    body = client.get(f"/api/queries/{record.id}", headers=PRIYA).json()
    assert body["status"] == QUERY_WITHHELD_STATUS
    assert body["answer_text"] == QUERY_WITHHELD_TEXT
