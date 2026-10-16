"""Grants CRUD, live effect on visibility, and access requests (always 202; approve -> grant)."""

from __future__ import annotations

import uuid
from typing import Any

from app.tests.conftest import run

KYC = ("confluence-ops", "runbooks/kyc-refresh")
ADMIN = {"X-Actor-Id": "root.admin"}
OWNER = {"X-Actor-Id": "john.tan"}


def _kyc_id(services: Any) -> str:
    return run(services.repo.get_page_by_slug(*KYC)).id


def test_grant_create_list_revoke_does_not_expand_source_access(seeded: Any, client: Any) -> None:
    kyc_id = _kyc_id(seeded)
    assert client.get(f"/api/documents/{kyc_id}").status_code == 404  # alex: not finance-ops

    body = {
        "document_id": kyc_id,
        "subject_type": "principal",
        "subject_id": "alex.tan",
        "effect": "allow",
    }
    created = client.post("/api/access/grants", json=body, headers=OWNER)
    assert created.status_code == 201, created.text
    grant = created.json()
    assert grant["granted_by"] == "john.tan"
    assert client.post("/api/access/grants", json=body, headers=OWNER).status_code == 409
    assert client.get(f"/api/documents/{kyc_id}").status_code == 404
    assert client.get(f"/api/documents/{kyc_id}", headers=ADMIN).status_code == 404

    listed = client.get("/api/access/grants", params={"document_id": kyc_id}, headers=OWNER)
    assert [g["id"] for g in listed.json()["items"]] == [grant["id"]]

    revoked = client.delete(f"/api/access/grants/{grant['id']}", headers=ADMIN)
    assert revoked.status_code == 200
    assert client.delete(f"/api/access/grants/{grant['id']}", headers=ADMIN).status_code == 409
    assert client.get(f"/api/documents/{kyc_id}").status_code == 404
    with_revoked = client.get(
        "/api/access/grants",
        params={"document_id": kyc_id, "include_revoked": "true"},
        headers=OWNER,
    )
    assert len(with_revoked.json()["items"]) == 1
    actions = [e.action for e in run(seeded.repo.list_audit_events())]
    assert "grant.create" in actions and "grant.revoke" in actions


def test_grant_rules(seeded: Any, client: Any) -> None:
    kyc_id = _kyc_id(seeded)
    body = {"document_id": kyc_id, "subject_type": "group", "subject_id": "engineering"}
    # jordan.lim can read the KYC runbook but neither owns it nor is admin.
    jordan = client.post("/api/access/grants", json=body, headers={"X-Actor-Id": "jordan.lim"})
    assert jordan.status_code == 403
    # alex.tan cannot see it: identical to a missing document.
    alex = client.post("/api/access/grants", json=body)
    assert alex.status_code == 404
    assert client.get("/api/access/grants").status_code in (200, 403)
    missing = client.delete(f"/api/access/grants/{uuid.uuid4()}", headers=ADMIN)
    assert missing.status_code == 404


def test_local_upload_grant_unlocks_then_revocation_removes_access(
    seeded: Any, client: Any
) -> None:
    uploaded = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "grant-test.md",
                b"# Local grant test\nPrivate uploaded evidence.\n",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201
    doc_id = uploaded.json()["document"]["id"]
    reader = {"X-Actor-Id": "mei.chen"}
    assert client.get(f"/api/documents/{doc_id}", headers=reader).status_code == 404
    grant = client.post(
        "/api/access/grants",
        json={
            "document_id": doc_id,
            "subject_type": "principal",
            "subject_id": "mei.chen",
        },
    )
    assert grant.status_code == 201
    assert client.get(f"/api/documents/{doc_id}", headers=reader).status_code == 200
    assert client.delete(f"/api/access/grants/{grant.json()['id']}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}", headers=reader).status_code == 404


def test_access_request_always_202(seeded: Any, client: Any) -> None:
    kyc_id = _kyc_id(seeded)
    for target in (kyc_id, str(uuid.uuid4()), "not-a-uuid"):
        response = client.post(
            f"/api/documents/{target}/access-requests", json={"reason": "need it"}
        )
        assert response.status_code == 202
        assert response.json() == {"status": "received"}
    no_body = client.post(f"/api/documents/{kyc_id}/access-requests")
    assert no_body.status_code == 202


def test_access_request_approve_creates_grant(seeded: Any, client: Any) -> None:
    kyc_id = _kyc_id(seeded)
    client.post(f"/api/documents/{kyc_id}/access-requests", json={"reason": "KYC review"})
    client.post(f"/api/documents/{uuid.uuid4()}/access-requests", json={"reason": "probe"})

    inbox = client.get("/api/access/requests", headers=ADMIN).json()["items"]
    assert [r["document_id"] for r in inbox] == [kyc_id]  # nonexistent targets never surface
    assert inbox[0]["document_title"] == "KYC Periodic Refresh Runbook"
    assert client.get("/api/access/requests").json()["items"] == []  # alex owns nothing

    request_id = inbox[0]["id"]
    approved = client.post(f"/api/access/requests/{request_id}/approve", headers=ADMIN)
    assert approved.status_code == 200, approved.text
    assert approved.json()["request"]["status"] == "approved"
    grant = approved.json()["grant"]
    assert grant["subject_type"] == "principal" and grant["subject_id"] == "alex.tan"
    assert client.get(f"/api/documents/{kyc_id}").status_code == 404
    again = client.post(f"/api/access/requests/{request_id}/approve", headers=ADMIN)
    assert again.status_code == 409


def test_access_request_deny(seeded: Any, client: Any) -> None:
    kyc_id = _kyc_id(seeded)
    client.post(f"/api/documents/{kyc_id}/access-requests", json={"reason": "pls"})
    request_id = client.get("/api/access/requests", headers=ADMIN).json()["items"][0]["id"]
    # The KYC runbook's owner (john.tan) may decide too; a stranger may not.
    stranger = client.post(
        f"/api/access/requests/{request_id}/deny", headers={"X-Actor-Id": "jordan.lim"}
    )
    assert stranger.status_code == 403
    denied = client.post(
        f"/api/access/requests/{request_id}/deny", headers={"X-Actor-Id": "john.tan"}
    )
    assert denied.status_code == 200
    assert denied.json()["request"]["status"] == "denied"
    assert client.get(f"/api/documents/{kyc_id}").status_code == 404
