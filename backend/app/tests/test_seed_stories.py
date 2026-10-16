"""The access and freshness stories the seeded corpus is built to show, end to end through REST.

Each test names one story from `backend/seed/corpus/README.md` ("Access stories" and "Freshness
stories"). Hidden documents must look exactly like missing ones.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.tests.conftest import run

ORIONIX = ("gdrive-finance", "files/orionix-renewal-brief")
DM = ("slack-ops", "dms/john-daniel/2026-10-11")
APPROVAL = ("email-ops", "messages/2026-10-12-cutover-approval")
LIQUIDITY = ("confluence-ops", "treasury/liquidity-prefunding-policy")
STR_REGISTER = ("confluence-compliance", "registers/str-register-q3-2026")
FAQ = ("gdrive-finance", "files/rail-b-support-faq")
DUE_DILIGENCE = ("gdrive-finance", "files/vegaline-due-diligence")
TEST_PLAN = ("gdrive-finance", "files/rail-b-integration-test-plan")
INCIDENT_REVIEW = ("confluence-ops", "incidents/2026-09-14-rail-a-sev2-review")
OLD_ESCALATION = ("confluence-ops", "runbooks/rail-a-escalation-contacts-2025")


def _id(services: Any, ref: tuple[str, str]) -> str:
    page = run(services.repo.get_page_by_slug(*ref))
    assert page is not None, ref
    return page.id


def _status(client: Any, actor: str, page_id: str) -> int:
    return client.get(f"/api/documents/{page_id}", headers={"X-Actor-Id": actor}).status_code


def _assert_hidden(client: Any, actor: str, page_id: str) -> None:
    """Denied must be byte-identical to missing for the same request id."""
    headers = {"X-Actor-Id": actor, "X-Request-Id": "req-seed-story"}
    denied = client.get(f"/api/documents/{page_id}", headers=headers)
    missing = client.get(f"/api/documents/{uuid.uuid4()}", headers=headers)
    assert denied.status_code == missing.status_code == 404
    assert denied.content == missing.content


def _ask(client: Any, actor: str, question: str) -> dict[str, Any]:
    res = client.post("/api/ask", json={"question": question}, headers={"X-Actor-Id": actor})
    assert res.status_code == 200, res.text
    return res.json()


def test_ethical_wall_deny_beats_group_grant(seeded: Any, client: Any) -> None:
    brief = _id(seeded, ORIONIX)
    assert _status(client, "alex.tan", brief) == 200  # engineering group grant
    _assert_hidden(client, "ravi.kumar", brief)  # same group, explicit deny
    env = _ask(client, "ravi.kumar", "What is our negotiating position for the Orionix renewal?")
    assert brief not in {c["document_id"] for c in env["citations"]}
    assert "0.17 per transfer" not in str((env["answer"], env["claims"], env["citations"]))


def test_direct_message_is_visible_to_its_two_members_only(seeded: Any, client: Any) -> None:
    dm = _id(seeded, DM)
    assert _status(client, "john.tan", dm) == 200
    assert _status(client, "daniel.wong", dm) == 200
    for outsider in ("jordan.lim", "root.admin", "alex.tan"):
        _assert_hidden(client, outsider, dm)


def test_bcc_recipient_reads_the_approval_email(seeded: Any, client: Any) -> None:
    email = _id(seeded, APPROVAL)
    for reader in ("john.tan", "jordan.lim", "daniel.wong"):  # from, cc, bcc
        assert _status(client, reader, email) == 200
    _assert_hidden(client, "alex.tan", email)


def test_inherited_confluence_restriction(seeded: Any, client: Any) -> None:
    policy = _id(seeded, LIQUIDITY)
    assert _status(client, "jordan.lim", policy) == 200
    # The OPS space admits engineering, but the parent Treasury page is finance-ops only.
    _assert_hidden(client, "alex.tan", policy)


def test_restricted_register_needs_ownership_or_a_role_grant(seeded: Any, client: Any) -> None:
    register = _id(seeded, STR_REGISTER)
    assert _status(client, "nora.ibrahim", register) == 200  # owner
    assert _status(client, "sam.lee", register) == 200  # `auditor` role grant
    _assert_hidden(client, "john.tan", register)  # finance-ops: in the space, not on the page
    _assert_hidden(client, "root.admin", register)  # admin is not a source-access bypass

    (grant,) = run(seeded.grant_store.list_for_documents([register]))[register]
    assert (grant.subject_type, grant.subject_id) == ("role", "auditor")
    owner = {"X-Actor-Id": "nora.ibrahim"}
    assert client.delete(f"/api/access/grants/{grant.id}", headers=owner).status_code == 200
    _assert_hidden(client, "sam.lee", register)
    assert _status(client, "nora.ibrahim", register) == 200


def test_drive_shares_expire_and_links_are_not_discoverable(seeded: Any, client: Any) -> None:
    mei = client.get("/api/documents", headers={"X-Actor-Id": "mei.chen"}).json()
    assert [d["id"] for d in mei["items"]] == [_id(seeded, TEST_PLAN)]
    _assert_hidden(client, "mei.chen", _id(seeded, DUE_DILIGENCE))  # share expired 30 Sep

    faq = _id(seeded, FAQ)
    assert _status(client, "john.tan", faq) == 200
    _assert_hidden(client, "alex.tan", faq)  # "anyone with the link", discovery off


def test_inactive_principal_cannot_act(seeded: Any, client: Any) -> None:
    res = client.get("/api/documents", headers={"X-Actor-Id": "lena.koh"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unknown_actor"
    listed = client.get("/api/principals").json()["items"]
    assert "lena.koh" not in {p["id"] for p in listed}


def test_standard_stale_evidence_is_used_with_a_warning(seeded: Any, client: Any) -> None:
    review = _id(seeded, INCIDENT_REVIEW)
    env = _ask(client, "alex.tan", "What happened in the September Rail-A SEV-2 incident?")
    item = next(i for i in env["freshness_receipt"]["evidence_items"] if i["page_id"] == review)
    assert item["evidence_class"] == "standard"
    assert item["freshness_status"] == "stale"
    assert item["safe_to_use"] is True
    assert review in {c["document_id"] for c in env["citations"]}


def test_page_deleted_upstream_is_never_cited(seeded: Any, client: Any) -> None:
    old = _id(seeded, OLD_ESCALATION)
    env = _ask(client, "alex.tan", "Who do we escalate Rail-A incidents to?")
    item = next(i for i in env["freshness_receipt"]["evidence_items"] if i["page_id"] == old)
    assert item["evidence_class"] == "critical"
    assert item["safe_to_use"] is False
    assert item["fallback_action"] == "omit"
    assert old not in {c["document_id"] for c in env["citations"]}
