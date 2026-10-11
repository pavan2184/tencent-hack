"""`POST /api/webhooks/{connector_kind}/{source_id}`: secret check, stub 501, accept + dedupe."""

from __future__ import annotations

from typing import Any

import pytest

from app.api.routers import webhooks as webhooks_module
from app.schemas.domain import Source
from app.tasks.common import run_async

SECRET = "s3cret-for-tests"
SOURCE_ID = "confluence-ops"
URL = f"/api/webhooks/confluence/{SOURCE_ID}"
BODY = {
    "provider_event_id": "evt-test-0001",
    "external_object_id": "CONF-OPS-1042",
    "change_kind": "upsert",
    "provider_version": "8",
    "version_order": 8,
}


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        webhooks_module,
        "_enqueue_webhook_sync",
        lambda source_id, idempotency_key: calls.append((source_id, idempotency_key)),
    )
    return calls


def _set_config(services: Any, source_id: str, **config: Any) -> Source:
    source = run_async(services.repo.get_source(source_id))
    assert source is not None
    updated = source.model_copy(update={"config": {**(source.config or {}), **config}})
    return run_async(services.repo.upsert_source(updated))


def _error_code(response: Any) -> str:
    return response.json()["error"]["code"]


def test_wrong_or_missing_secret_is_401(seeded: Any, client: Any, enqueued: list) -> None:
    _set_config(seeded, SOURCE_ID, webhook_secret=SECRET)
    wrong = client.post(URL, json=BODY, headers={"X-Webhook-Secret": "nope"})
    assert wrong.status_code == 401
    assert _error_code(wrong) == "unauthenticated"
    missing = client.post(URL, json=BODY)
    assert missing.status_code == 401
    assert enqueued == []


def test_source_without_configured_secret_rejects_everything(
    seeded: Any, client: Any, enqueued: list
) -> None:
    response = client.post(URL, json=BODY, headers={"X-Webhook-Secret": ""})
    assert response.status_code == 401


def test_unknown_source_or_kind_mismatch_is_404(seeded: Any, client: Any, enqueued: list) -> None:
    _set_config(seeded, SOURCE_ID, webhook_secret=SECRET)
    headers = {"X-Webhook-Secret": SECRET}
    missing = client.post("/api/webhooks/confluence/no-such-source", json=BODY, headers=headers)
    assert missing.status_code == 404
    assert _error_code(missing) == "not_found"
    mismatch = client.post(f"/api/webhooks/slack/{SOURCE_ID}", json=BODY, headers=headers)
    assert mismatch.status_code == 404


def test_stub_connector_is_501(seeded: Any, client: Any, enqueued: list) -> None:
    run_async(
        seeded.repo.upsert_source(
            Source(
                id="slack-live",
                name="Slack (live)",
                kind="slack",
                config={"webhook_secret": SECRET},
            )
        )
    )
    response = client.post(
        "/api/webhooks/slack/slack-live",
        json={"external_object_id": "C1", "provider_event_id": "e1"},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 501
    assert _error_code(response) == "not_implemented"
    assert enqueued == []


def test_non_object_body_is_422(seeded: Any, client: Any, enqueued: list) -> None:
    _set_config(seeded, SOURCE_ID, webhook_secret=SECRET)
    response = client.post(URL, json=["not", "an", "object"], headers={"X-Webhook-Secret": SECRET})
    assert response.status_code == 422
    assert _error_code(response) == "validation_error"


def test_accepts_then_deduplicates_replay(seeded: Any, client: Any, enqueued: list) -> None:
    _set_config(seeded, SOURCE_ID, webhook_secret=SECRET)
    headers = {"X-Webhook-Secret": SECRET}

    first = client.post(URL, json=BODY, headers=headers)
    assert first.status_code == 202, first.text
    accepted = first.json()
    assert accepted["duplicate"] is False
    assert accepted["event_id"] and accepted["accepted_at"]

    replay = client.post(URL, json=BODY, headers=headers)
    assert replay.status_code == 202
    assert replay.json()["duplicate"] is True
    assert replay.json()["event_id"] == accepted["event_id"]

    key = f"webhook:{SOURCE_ID}:{accepted['event_id']}"
    assert enqueued == [(SOURCE_ID, key), (SOURCE_ID, key)]
    events = run_async(seeded.freshness_store.list_events(SOURCE_ID))
    assert [e.provider_event_id for e in events].count("evt-test-0001") == 1
