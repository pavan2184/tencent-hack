"""GET /api/access/map: manager/admin only, scoped to the caller's own visible documents, allow
edges only, and a revocation removes the edge on the very next call."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.services.memory_sync import sync_all_sources
from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
VENDORS = ("gdrive-finance", "files/vendor-list")
PAY_150 = ("jira-payments", "issues/pay-150")
ORIONIX = ("gdrive-finance", "files/orionix-renewal-brief")
ADMIN = {"X-Actor-Id": "root.admin"}
JOHN = {"X-Actor-Id": "john.tan"}


def _id(services: Any, ref: tuple[str, str]) -> str:
    return run(services.repo.get_page_by_slug(*ref)).id


def _edges(body: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(e["principal_id"], e["document_id"]): e for e in body["edges"]}


@pytest.mark.parametrize("actor", ["alex.tan", "sam.lee", "mei.chen", "jordan.lim"])
def test_map_requires_manager_or_admin(seeded: Any, client: Any, actor: str) -> None:
    res = client.get("/api/access/map", headers={"X-Actor-Id": actor})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


def test_manager_map_shows_rules_and_grant_subjects(seeded: Any, client: Any) -> None:
    res = client.get("/api/access/map", headers=JOHN)
    assert res.status_code == 200, res.text
    body = res.json()
    deck, pay150 = _id(seeded, DECK), _id(seeded, PAY_150)

    assert body["policy_version"] == "ac-v2"
    # john reads every seeded document except the compliance-restricted STR register.
    assert len(body["documents"]) == 23
    assert "registers/str-register-q3-2026" not in {d["slug"] for d in body["documents"]}
    assert {p["id"] for p in body["principals"]} >= {"alex.tan", "john.tan", "root.admin"}
    assert "lena.koh" not in {p["id"] for p in body["principals"]}  # inactive
    assert {s["id"] for s in body["sources"]} == {d["source_id"] for d in body["documents"]}

    edges = _edges(body)
    assert edges[("alex.tan", pay150)]["rule"] == "R3:owner"
    assert edges[("jordan.lim", pay150)]["rule"] == "R8:jira"
    grant_edge = edges[("john.tan", deck)]
    assert grant_edge["rule"] == "R5:explicit_grant"
    assert [(v["subject_type"], v["subject_id"]) for v in grant_edge["via"]] == [
        ("group", "leadership")
    ]
    assert edges[("root.admin", deck)] == {
        "principal_id": "root.admin",
        "document_id": deck,
        "rule": "R3:owner",
        "via": [],
    }
    # Ethical wall: engineering is granted the Orionix brief, but Ravi's explicit deny wins.
    orionix = _id(seeded, ORIONIX)
    assert edges[("alex.tan", orionix)]["rule"] == "R5:explicit_grant"
    assert [(v["subject_type"], v["subject_id"]) for v in edges[("alex.tan", orionix)]["via"]] == [
        ("group", "engineering")
    ]
    assert ("ravi.kumar", orionix) not in edges
    # Allow edges only: nobody denied appears, and no edge carries a deny reason.
    assert ("alex.tan", deck) not in edges and ("mei.chen", deck) not in edges
    assert all("reason" not in e and "decision" not in e for e in body["edges"])
    doc_ids = {d["id"] for d in body["documents"]}
    assert {e["document_id"] for e in body["edges"]} <= doc_ids

    events = [e for e in run(seeded.repo.list_audit_events()) if e.action == "access.map"]
    assert len(events) == 1 and events[0].actor_id == "john.tan"
    assert events[0].payload["edge_count"] == len(body["edges"])


def test_admin_map_is_capped_by_admin_source_access(seeded: Any, client: Any) -> None:
    res = client.get("/api/access/map", headers=ADMIN)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {d["id"] for d in body["documents"]} == {_id(seeded, DECK), _id(seeded, VENDORS)}
    assert [s["id"] for s in body["sources"]] == ["gdrive-finance"]
    # Titles of documents the admin cannot read never leak into the response.
    for hidden in ("KYC", "treasury-ops", "PAY-150", "Rail-B cutover"):
        assert hidden not in res.text


def test_revocation_removes_edge_on_next_map(seeded: Any, client: Any) -> None:
    deck = _id(seeded, DECK)
    before = _edges(client.get("/api/access/map", headers=ADMIN).json())
    (grant,) = before[("john.tan", deck)]["via"]

    revoked = client.delete(f"/api/access/grants/{grant['grant_id']}", headers=ADMIN)
    assert revoked.status_code == 200

    admin_after = client.get("/api/access/map", headers=ADMIN).json()
    assert ("john.tan", deck) not in _edges(admin_after)
    assert ("root.admin", deck) in _edges(admin_after)
    john_after = client.get("/api/access/map", headers=JOHN).json()
    assert deck not in {d["id"] for d in john_after["documents"]}
    assert len(john_after["documents"]) == 22


def test_map_reports_when_each_documents_permissions_were_synced(seeded: Any, client: Any) -> None:
    uploaded = client.post(
        "/api/documents/upload",
        files={"file": ("note.md", b"# Note\n\nA local upload.\n", "text/markdown")},
        headers=JOHN,
    )
    assert uploaded.status_code == 201, uploaded.text
    body = client.get("/api/access/map", headers=JOHN).json()
    docs = {d["id"]: d for d in body["documents"]}
    deck = docs[_id(seeded, DECK)]
    now = seeded.clock.now()
    assert deck["permissions_synced_at"] == now.isoformat().replace("+00:00", "Z")
    # Confidential snapshots count for 5 minutes (D-018).
    assert deck["permissions_expire_at"] == (now + timedelta(minutes=5)).isoformat().replace(
        "+00:00", "Z"
    )
    uploads = [d for d in body["documents"] if d["source_kind"] == "upload"]
    assert uploads and all(
        d["permissions_synced_at"] is None and d["permissions_expire_at"] is None for d in uploads
    )


def test_expired_permissions_drop_the_deck_until_the_in_process_sync_runs(
    seeded: Any, client: Any
) -> None:
    """The in-memory API has no Celery beat: without `memory_sync` the board deck leaves the map
    5 minutes after start-up, for everyone, admin and owner included."""
    deck = _id(seeded, DECK)
    assert deck in {
        d["id"] for d in client.get("/api/access/map", headers=ADMIN).json()["documents"]
    }

    seeded.clock.advance(6 * 60)
    stale = client.get("/api/access/map", headers=ADMIN).json()
    assert deck not in {d["id"] for d in stale["documents"]}
    assert deck not in {e["document_id"] for e in stale["edges"]}

    synced = run(sync_all_sources(seeded))
    assert "gdrive-finance" in synced and "uploads" in synced
    fresh = client.get("/api/access/map", headers=ADMIN).json()
    assert deck in {d["id"] for d in fresh["documents"]}
    assert ("john.tan", deck) in _edges(fresh)


def test_in_process_sync_loop_keeps_running_after_a_source_fails(
    seeded: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import sources

    original = sources.run_sync
    calls: list[str] = []

    async def flaky(services: Any, source_id: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(source_id)
        if source_id == "confluence-ops":
            raise TimeoutError("provider down")
        return await original(services, source_id, *args, **kwargs)

    monkeypatch.setattr(sources, "run_sync", flaky)
    synced = run(sync_all_sources(seeded))
    assert "confluence-ops" in calls and "confluence-ops" not in synced
    assert "gdrive-finance" in synced
