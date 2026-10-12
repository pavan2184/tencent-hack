"""The five mandatory demo scenarios, end to end through REST (in-memory, mock, fixed clock)."""

from __future__ import annotations

import uuid
from typing import Any

from app.tests.conftest import run

ASK = "/api/ask"
DECK = ("gdrive-finance", "files/board-deck-q3")
RUNBOOK = ("confluence-ops", "runbooks/payment-rail-failover")
KYC = ("confluence-ops", "runbooks/kyc-refresh")


def _page_id(services: Any, ref: tuple[str, str]) -> str:
    page = run(services.repo.get_page_by_slug(*ref))
    assert page is not None, ref
    return page.id


def _ask(client: Any, actor: str, question: str, **extra: Any) -> dict[str, Any]:
    response = client.post(ASK, json={"question": question, **extra}, headers={"X-Actor-Id": actor})
    assert response.status_code == 200, response.text
    return response.json()


def _cited(envelope: dict[str, Any]) -> set[str]:
    return {c["document_id"] for c in envelope["citations"]}


def test_unified_cited_query(seeded: Any, client: Any) -> None:
    env = _ask(client, "priya.nair", "What is the plan for the Rail-B cutover?")
    assert env["schema_version"] == 1
    assert env["audit_id"] and env["query_id"]
    assert not env["answer"]["abstained"]
    assert env["claims"] and env["citations"]
    assert len({c["source_id"] for c in env["citations"]}) >= 2
    for citation in env["citations"]:
        assert citation["quote"]
        assert citation["support"] in ("supported", "partially_supported")
        assert citation["url"].endswith(f"/documents/{citation['document_id']}")
    claim_ids = {c["id"] for c in env["claims"]}
    assert {c["claim_id"] for c in env["citations"]} <= claim_ids
    assert env["grounding"]["verdict"] in ("grounded", "partially_grounded")
    assert set(env["timing"]) >= {"retrieval_ms", "access_ms", "freshness_ms", "total_ms"}


def test_bounded_freshness_stale_omitted(seeded: Any, client: Any) -> None:
    runbook_id = _page_id(seeded, RUNBOOK)
    kyc_id = _page_id(seeded, KYC)
    env = _ask(
        client,
        "priya.nair",
        "What is the payment rail failover procedure and the KYC refresh cycle?",
    )
    items = {i["page_id"]: i for i in env["freshness_receipt"]["evidence_items"]}
    stale = items[runbook_id]
    assert stale["evidence_class"] == "critical"
    assert stale["freshness_status"] == "stale"
    assert stale["safe_to_use"] is False
    assert stale["fallback_action"] == "omit"
    assert stale["provider_version"] == "7"
    fresh = items[kyc_id]
    assert fresh["freshness_status"] == "fresh"
    assert fresh["safe_to_use"] is True
    assert fresh["verification_result"] == "fresh"
    cited = _cited(env)
    assert runbook_id not in cited
    assert kyc_id in cited
    assert env["freshness_receipt"]["overall_status"] in ("mixed", "stale")


def test_negative_permission_no_existence_leak(seeded: Any, client: Any) -> None:
    deck_id = _page_id(seeded, DECK)
    env = _ask(client, "mei.chen", "What were the Q3 board deck revenue figures?")
    assert deck_id not in _cited(env)
    receipt_pages = {i["page_id"] for i in env["freshness_receipt"]["evidence_items"]}
    assert deck_id not in receipt_pages
    assert set(env["access_summary"]) == {
        "principal_id",
        "policy_version",
        "allowed_count",
        "evaluated_at",
    }
    # Timestamps can legitimately contain the digits 48.6, independently of document text.
    assert "48.6" not in str((env["answer"], env["claims"], env["citations"]))

    headers = {"X-Actor-Id": "mei.chen", "X-Request-Id": "req-leak-check"}
    denied = client.get(f"/api/documents/{deck_id}", headers=headers)
    missing = client.get(f"/api/documents/{uuid.uuid4()}", headers=headers)
    assert denied.status_code == missing.status_code == 404
    assert denied.content == missing.content


def test_live_revocation_changes_next_answer(seeded: Any, client: Any) -> None:
    deck_id = _page_id(seeded, DECK)
    question = "What were the Q3 board deck revenue figures?"
    before = _ask(client, "priya.nair", question)
    assert deck_id in _cited(before)

    admin = {"X-Actor-Id": "root.admin"}
    grants = client.get("/api/access/grants", params={"document_id": deck_id}, headers=admin)
    assert grants.status_code == 200
    leadership = [g for g in grants.json()["items"] if g["subject_id"] == "leadership"]
    assert len(leadership) == 1 and leadership[0]["granted_by"] == "system:seed"
    revoked = client.delete(f"/api/access/grants/{leadership[0]['id']}", headers=admin)
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] and revoked.json()["revoked_by"] == "root.admin"

    after = _ask(client, "priya.nair", question)
    assert deck_id not in _cited(after)
    assert after["access_summary"]["allowed_count"] < before["access_summary"]["allowed_count"]

    event = client.get(f"/api/audit/events/{after['audit_id']}", headers={"X-Actor-Id": "sam.lee"})
    assert event.status_code == 200
    decisions = {d["document_id"]: d for d in event.json()["payload"]["access_decisions"]}
    assert decisions[deck_id]["decision"] == "deny"
    assert decisions[deck_id]["reason"] == "grant_revoked"
    first = client.get(f"/api/audit/events/{before['audit_id']}", headers={"X-Actor-Id": "sam.lee"})
    first_decisions = {d["document_id"]: d for d in first.json()["payload"]["access_decisions"]}
    assert first_decisions[deck_id]["decision"] == "allow"


def test_audit_reconstruction(seeded: Any, client: Any) -> None:
    env = _ask(client, "priya.nair", "What is the plan for the Rail-B cutover?")
    auditor = {"X-Actor-Id": "sam.lee"}
    response = client.get(f"/api/audit/events/{env['audit_id']}", headers=auditor)
    assert response.status_code == 200
    event = response.json()
    assert event["action"] == "ask"
    assert event["actor_id"] == "priya.nair"
    assert event["subject_id"] == env["query_id"]
    payload = event["payload"]
    assert payload["question"] == "What is the plan for the Rail-B cutover?"
    assert payload["query_id"] == env["query_id"]
    assert payload["retrieved_document_ids"]
    assert len(payload["access_decisions"]) == len(payload["retrieved_document_ids"])
    for decision in payload["access_decisions"]:
        assert set(decision) == {
            "document_id",
            "decision",
            "reason",
            "matched_rule",
            "permission_version",
            "permission_captured_at",
        }
    receipt = payload["freshness_receipt"]
    assert receipt["receipt_id"] == env["freshness_receipt"]["receipt_id"]
    assert receipt["receipt_hash"] == env["freshness_receipt"]["receipt_hash"]
    assert receipt["evidence_items"]
    assert payload["answer_text"] == env["answer"]["text"]
    assert set(payload["cited_document_ids"]) == _cited(env)
    assert payload["grounding"]["verdict"] == env["grounding"]["verdict"]
    assert payload["started_at"] <= payload["completed_at"]
    reconstruction = event["reconstruction"]
    assert reconstruction["query"]["id"] == env["query_id"]
    assert reconstruction["query"]["audit_event_id"] == env["audit_id"]
    assert reconstruction["freshness_receipt"]["receipt_id"] == receipt["receipt_id"]

    verify = client.get("/api/audit/verify", headers=auditor)
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
    assert verify.json()["length"] >= 2

    forbidden = client.get(
        f"/api/audit/events/{env['audit_id']}", headers={"X-Actor-Id": "alex.tan"}
    )
    assert forbidden.status_code == 403
    assert client.get("/api/audit/verify").status_code == 403
