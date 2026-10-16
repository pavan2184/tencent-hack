"""The permission-drift hook (D-024): a source ACL change seen by a sync, even with unchanged
content, is audited (fingerprints only) and handed to freshness as a `metadata_change`, which
the next sync re-applies."""

from __future__ import annotations

import json
from typing import Any

import pytest
from freshness import ChangeKind, EventState

from app.connectors.gbrain_import import GbrainImportConnector
from app.services.permission_drift import DRIFT_ACTION, store_permissions
from app.services.sources import run_sync
from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
DECK_FILE_ID = "1BoardDeckQ3ExampleHarbor"
JOHN = {"X-Actor-Id": "john.tan"}


def _drift_events(services: Any) -> list[Any]:
    return [e for e in run(services.repo.list_audit_events()) if e.action == DRIFT_ACTION]


def _remove_leadership_share(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Drive owner removes the Leadership group from the deck; content is unchanged."""
    original = GbrainImportConnector._permissions

    def without_leadership(self: Any, entry: Any) -> Any:
        perms = original(self, entry)
        if perms is None or entry.external_object_id != DECK_FILE_ID:
            return perms
        acl = [ace for ace in perms.raw.acl if ace.email_or_domain != "leadership"]
        return perms.model_copy(update={"raw": perms.raw.model_copy(update={"acl": acl})})

    monkeypatch.setattr(GbrainImportConnector, "_permissions", without_leadership)


def test_seeding_and_unchanged_syncs_record_no_drift(seeded: Any) -> None:
    assert _drift_events(seeded) == []  # first captures are not drift
    run(run_sync(seeded, DECK[0], "delta", "steady-1"))
    assert _drift_events(seeded) == []


def test_source_acl_change_is_audited_and_reaches_freshness(
    seeded: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deck = run(seeded.repo.get_page_by_slug(*DECK))
    _remove_leadership_share(monkeypatch)
    seeded.clock.advance(60)
    run(run_sync(seeded, DECK[0], "delta", "drift-1"))

    (event,) = _drift_events(seeded)
    assert event.subject_id == deck.id and event.actor_id is None
    assert event.payload["observed_via"] == "refresh"
    assert event.payload["freshness_notified"] is True
    assert event.payload["previous_fingerprint"] != event.payload["current_fingerprint"]
    assert "leadership" not in json.dumps(event.payload)  # who changed is not logged
    assert client.get(f"/api/documents/{deck.id}", headers=JOHN).status_code == 404

    (change,) = [
        e
        for e in run(seeded.freshness_store.list_events(DECK[0]))
        if e.change_kind == ChangeKind.metadata_change
    ]
    assert change.id == event.payload["freshness_event_id"]
    assert change.external_object_id == DECK_FILE_ID and change.state == EventState.accepted

    # The next sync re-applies the object; the ACL is unchanged since, so no second drift.
    seeded.clock.advance(60)
    run(run_sync(seeded, DECK[0], "delta", "drift-2"))
    (applied,) = [e for e in run(seeded.freshness_store.list_events(DECK[0])) if e.id == change.id]
    assert applied.state == EventState.applied
    assert len(_drift_events(seeded)) == 1
    assert client.get(f"/api/documents/{deck.id}", headers=JOHN).status_code == 404


def test_drift_seen_while_ingesting_is_audited_without_a_freshness_event(seeded: Any) -> None:
    deck = run(seeded.repo.get_page_by_slug(*DECK))
    current = run(seeded.permission_store.get_many([deck.id]))[deck.id]
    changed = current.model_copy(
        update={"raw": current.raw.model_copy(update={"acl": []}), "permission_version": "pv-x"}
    )
    drift = run(store_permissions(seeded, deck, changed, observed_via="ingest"))
    assert drift is not None and drift.current_version == "pv-x"
    (event,) = _drift_events(seeded)
    assert event.payload["observed_via"] == "ingest"
    assert event.payload["freshness_notified"] is False
    assert run(seeded.permission_store.get_many([deck.id]))[deck.id].raw.acl == []
