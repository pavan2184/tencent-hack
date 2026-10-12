"""Hash-chained audit log.

`record()` copies the event columns into the payload (so the chain hash covers them), normalises
it to JSON mode (so the hash survives a JSONB round-trip), and lets the repo append it atomically
with `hash = sha256(prev_hash | seq | canonical_json(payload))`. `verify_chain()` recomputes
every link.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.context import get_request_id
from app.core.hashing import canonical_json
from app.db.repo import audit_event_hash
from app.schemas.domain import AuditEvent, AuditEventDraft, utcnow

if TYPE_CHECKING:
    from app.services.wiring import Services

AUDIT_SCHEMA_VERSION = 1


def json_mode(value: Any) -> Any:
    """Plain JSON types only (datetimes -> ISO strings, models -> dicts, sets -> sorted lists)."""
    return json.loads(canonical_json(value))


async def record(
    services: Services,
    *,
    actor_id: str | None,
    action: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    occurred_at = occurred_at or utcnow()
    request_id = request_id if request_id is not None else get_request_id()
    body: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "actor_id": actor_id,
        "action": action,
        "occurred_at": occurred_at.isoformat(),
        "request_id": request_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
    }
    body.update(payload or {})
    draft = AuditEventDraft(
        occurred_at=occurred_at,
        actor_id=actor_id,
        action=action,
        request_id=request_id,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=json_mode(body),
    )
    return await services.repo.append_audit_event(draft)


async def list_events(
    services: Services,
    *,
    actor_id: str | None = None,
    action: str | None = None,
    document_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    return await services.repo.list_audit_events(
        actor_id=actor_id,
        action=action,
        document_id=document_id,
        subject_type=subject_type,
        subject_id=subject_id,
        since=since,
        limit=limit,
        offset=offset,
    )


async def get_event(services: Services, event_id: str) -> AuditEvent | None:
    return await services.repo.get_audit_event(event_id)


def verify_events(events: list[AuditEvent]) -> dict[str, Any]:
    """Pure chain check over events in ascending seq (used by `verify_chain` and tests)."""
    prev_hash: str | None = None
    first_broken: int | None = None
    for event in events:
        expected = audit_event_hash(event.prev_hash, event.seq, event.payload)
        if event.prev_hash != prev_hash or event.hash != expected:
            first_broken = event.seq
            break
        prev_hash = event.hash
    head = events[-1].hash if events else None
    return {
        "ok": first_broken is None,
        "length": len(events),
        "head_hash": head,
        "first_broken_seq": first_broken,
    }


async def verify_chain(services: Services) -> dict[str, Any]:
    """`{ok, length, head_hash, first_broken_seq}` over the whole chain."""
    events = [event async for event in services.repo.iter_audit_events()]
    return verify_events(events)
