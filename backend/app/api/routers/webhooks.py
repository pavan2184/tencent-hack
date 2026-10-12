"""`POST /api/webhooks/{connector_kind}/{source_id}`: the webhook fast path.

Authenticate with the source's shared secret (`sources.config["webhook_secret"]`, compared in
constant time) -> the source's connector normalises the provider body into a
`freshness.NormalizedChange` -> `FreshnessService.accept` durably records it in the event ledger
(deduplicated on `(source_id, provider_event_id)`) -> a `sync_source(trigger_kind="webhook")` is
enqueued to apply it -> 202 `{event_id, accepted_at, duplicate}`.

Acceptance never indexes content. If enqueueing fails (broker down) the event stays `accepted`
in the ledger and the next delta sync drains it, so the response is still 202.

Errors (envelope): unknown source, or a `connector_kind` that is neither the source's kind nor
its connector -> 404; missing/wrong secret, or no secret configured -> 401; stub connector
-> 501 `not_implemented`; body not a JSON object or over 1 MB -> 422 / 413.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, Request
from freshness import ConnectorKind
from pydantic import BaseModel

from app.core.errors import (
    NotFound,
    NotImplementedFeature,
    PayloadTooLarge,
    Unauthenticated,
    ValidationFailed,
)
from app.schemas.domain import Source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

MAX_WEBHOOK_BYTES = 1_000_000


class WebhookAccepted(BaseModel):
    event_id: str
    accepted_at: datetime
    duplicate: bool


def _kind_matches(path_kind: str, source: Source) -> bool:
    def norm(value: str) -> str:
        value = value.strip().lower()
        try:
            return ConnectorKind(value).value
        except ValueError:
            return value

    from app.connectors.registry import connector_name

    wanted = norm(path_kind)
    return wanted in {norm(str(source.kind)), norm(connector_name(source))}


def _check_secret(source: Source, presented: str | None) -> None:
    expected = (source.config or {}).get("webhook_secret")
    if not expected or not presented:
        raise Unauthenticated("Missing or invalid webhook secret.")
    if not hmac.compare_digest(str(expected).encode(), presented.encode()):
        raise Unauthenticated("Missing or invalid webhook secret.")


async def _read_json_object(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise PayloadTooLarge("Webhook body exceeds 1 MB.")
    try:
        body = json.loads(raw or b"null")
    except ValueError as exc:
        raise ValidationFailed("Webhook body must be JSON.") from exc
    if not isinstance(body, dict):
        raise ValidationFailed("Webhook body must be a JSON object.")
    return body


def _enqueue_webhook_sync(source_id: str, idempotency_key: str) -> None:
    """Prefer the app's enqueue helper; fall back to the task. Never fails the webhook."""
    try:
        try:
            from app.services.jobs import enqueue_sync
        except ImportError:
            from app.tasks.sync import sync_source_task

            sync_source_task.apply_async(
                kwargs={
                    "source_id": source_id,
                    "trigger_kind": "webhook",
                    "idempotency_key": idempotency_key,
                }
            )
        else:
            enqueue_sync(source_id, trigger_kind="webhook", idempotency_key=idempotency_key)
    except Exception:
        logger.exception("webhook sync enqueue failed; the next delta sync drains the event")


@router.post("/{connector_kind}/{source_id}", status_code=202, response_model=WebhookAccepted)
async def receive_webhook(
    connector_kind: str,
    source_id: str,
    request: Request,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> WebhookAccepted:
    from app.connectors.registry import get_connector
    from app.services.wiring import get_services

    services = get_services()
    source = await services.repo.get_source(source_id)
    if source is None or source.archived or not _kind_matches(connector_kind, source):
        raise NotFound()
    _check_secret(source, x_webhook_secret)
    body = await _read_json_object(request)

    connector = get_connector(source, services)
    try:
        change = connector.normalize_webhook(body)
    except NotImplementedError as exc:
        raise NotImplementedFeature(
            str(exc) or "Webhooks are not implemented for this connector."
        ) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationFailed("Webhook body could not be normalised.") from exc
    if change.source_id != source.id:
        raise ValidationFailed("Webhook change does not belong to this source.")

    result = await services.freshness.accept(change)
    event = result.event
    _enqueue_webhook_sync(source.id, idempotency_key=f"webhook:{source.id}:{event.id}")
    logger.info(
        "webhook accepted",
        extra={"source_id": source.id, "event_id": event.id, "duplicate": result.duplicate},
    )
    return WebhookAccepted(
        event_id=event.id, accepted_at=event.accepted_at, duplicate=result.duplicate
    )
