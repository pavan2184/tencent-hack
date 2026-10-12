"""Hash-chained audit log: links, verification, tamper and deletion detection."""

from __future__ import annotations

from typing import Any

from app.core.hashing import chain_hash
from app.services import audit
from app.tests.conftest import run


def _record_three(services: Any) -> list[Any]:
    return [
        run(
            audit.record(
                services,
                actor_id="alex.tan",
                action=f"test.{i}",
                subject_type="test",
                subject_id=str(i),
                payload={"n": i, "nested": {"ok": True}},
            )
        )
        for i in range(3)
    ]


def test_chain_links_and_hashes(services: Any) -> None:
    events = _record_three(services)
    assert [e.seq for e in events] == [1, 2, 3]
    assert events[0].prev_hash is None
    assert events[1].prev_hash == events[0].hash
    assert events[2].prev_hash == events[1].hash
    for event in events:
        assert event.hash == chain_hash(event.prev_hash, event.seq, event.payload)
        # Event columns are copied into the hashed payload.
        assert event.payload["actor_id"] == "alex.tan"
        assert event.payload["action"] == event.action
    result = run(audit.verify_chain(services))
    assert result == {
        "ok": True,
        "length": 3,
        "head_hash": events[2].hash,
        "first_broken_seq": None,
    }


def test_tampered_payload_is_detected(services: Any) -> None:
    _record_three(services)
    stored = services.repo.audit_events
    stored[1] = stored[1].model_copy(update={"payload": {**stored[1].payload, "n": 999}})
    result = run(audit.verify_chain(services))
    assert result["ok"] is False
    assert result["first_broken_seq"] == 2


def test_deleted_event_is_detected(services: Any) -> None:
    _record_three(services)
    del services.repo.audit_events[1]
    result = run(audit.verify_chain(services))
    assert result["ok"] is False
    assert result["first_broken_seq"] == 3


def test_empty_chain_is_ok(services: Any) -> None:
    assert run(audit.verify_chain(services)) == {
        "ok": True,
        "length": 0,
        "head_hash": None,
        "first_broken_seq": None,
    }


def test_audit_list_filters(seeded: Any, client: Any) -> None:
    client.post(
        "/api/ask",
        json={"question": "What is the plan for the Rail-B cutover?"},
        headers={"X-Actor-Id": "priya.nair"},
    )
    auditor = {"X-Actor-Id": "sam.lee"}
    asks = client.get("/api/audit/events", params={"action": "ask"}, headers=auditor).json()
    assert len(asks["items"]) == 1
    assert asks["items"][0]["actor_id"] == "priya.nair"
    cited = asks["items"][0]["payload"]["cited_document_ids"][0]
    by_doc = client.get("/api/audit/events", params={"document_id": cited}, headers=auditor)
    assert any(e["action"] == "ask" for e in by_doc.json()["items"])
    seed_events = client.get(
        "/api/audit/events", params={"action": "seed.loaded"}, headers=auditor
    ).json()["items"]
    assert len(seed_events) == 1
