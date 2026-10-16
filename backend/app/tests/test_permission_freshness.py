"""Permission snapshots age out and every sync refreshes them, so a revocation at the source is
enforced within the classification's maximum snapshot age (5 minutes for confidential)."""

from __future__ import annotations

from typing import Any

import pytest
from access_control import SourcePermissions

from app.connectors.gbrain_import import GbrainImportConnector
from app.services.sources import run_sync
from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
DECK_FILE_ID = "1BoardDeckQ3ExampleHarbor"
JOHN = {"X-Actor-Id": "john.tan"}


def _deck_id(services: Any) -> str:
    return run(services.repo.get_page_by_slug(*DECK)).id


def _sync(services: Any, key: str) -> None:
    run(run_sync(services, DECK[0], "delta", key))


def test_stale_permissions_deny_until_a_sync_refreshes_them(seeded: Any, client: Any) -> None:
    deck_id = _deck_id(seeded)
    assert client.get(f"/api/documents/{deck_id}", headers=JOHN).status_code == 200

    seeded.clock.advance(6 * 60)  # past the 5-minute limit for confidential documents
    assert client.get(f"/api/documents/{deck_id}", headers=JOHN).status_code == 404

    _sync(seeded, "refresh-1")
    snapshot = run(seeded.permission_store.get_many([deck_id]))[deck_id]
    assert snapshot.captured_at == seeded.clock.now()
    assert client.get(f"/api/documents/{deck_id}", headers=JOHN).status_code == 200


def test_source_side_revocation_is_enforced_by_the_next_sync(
    seeded: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deck_id = _deck_id(seeded)
    question = {"question": "What were the Q3 board deck revenue figures?"}
    before = client.post("/api/ask", json=question, headers=JOHN).json()
    assert deck_id in {c["document_id"] for c in before["citations"]}

    original = GbrainImportConnector.permissions

    async def leadership_removed(self: Any, external_object_id: str) -> SourcePermissions:
        perms = await original(self, external_object_id)
        if external_object_id != DECK_FILE_ID:
            return perms
        acl = [ace for ace in perms.raw.acl if ace.email_or_domain != "leadership"]
        return perms.model_copy(update={"raw": perms.raw.model_copy(update={"acl": acl})})

    # The Drive owner removes the Leadership group from the share; content is unchanged.
    monkeypatch.setattr(GbrainImportConnector, "permissions", leadership_removed)
    seeded.clock.advance(60)
    _sync(seeded, "revoke-1")

    assert client.get(f"/api/documents/{deck_id}", headers=JOHN).status_code == 404
    after = client.post("/api/ask", json=question, headers=JOHN).json()
    assert deck_id not in {c["document_id"] for c in after["citations"]}
    assert "48.6" not in str((after["answer"], after["claims"], after["citations"]))
    event = run(seeded.repo.get_audit_event(after["audit_id"]))
    decisions = {d["document_id"]: d for d in event.payload["access_decisions"]}
    assert decisions[deck_id]["decision"] == "deny"
    assert decisions[deck_id]["reason"] == "no_source_membership"
    assert decisions[deck_id]["permission_captured_at"] == seeded.clock.now().isoformat()


def test_a_failed_permission_read_keeps_the_old_snapshot_which_then_ages_out(
    seeded: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deck_id = _deck_id(seeded)

    async def unavailable(self: Any, external_object_id: str) -> SourcePermissions:
        raise TimeoutError("Drive API unavailable")

    monkeypatch.setattr(GbrainImportConnector, "permissions", unavailable)
    seeded.clock.advance(4 * 60)
    _sync(seeded, "outage-1")
    assert client.get(f"/api/documents/{deck_id}", headers=JOHN).status_code == 200

    seeded.clock.advance(2 * 60)  # 6 minutes since the last good read
    _sync(seeded, "outage-2")
    assert client.get(f"/api/documents/{deck_id}", headers=JOHN).status_code == 404
