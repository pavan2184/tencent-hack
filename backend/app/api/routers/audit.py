"""Audit trail (auditor/admin only): events, one event with its reconstruction, chain verify.

Need-to-know: event metadata is always visible to auditors, but answer content (answer text,
citations, quotes) is withheld unless the viewer can read every evidence document right now.
`POST /audit/events/{id}/reveal` shows it after recording an `audit.reveal` event with a reason.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import ServicesDep
from app.core.auth import CurrentPrincipal, require_roles
from app.core.errors import NotFound
from app.schemas.audit import RevealRequest
from app.schemas.domain import AuditEvent
from app.services import access as access_service
from app.services import audit as audit_service
from app.services.access import is_uuid

router = APIRouter(
    prefix="/audit", tags=["audit"], dependencies=[Depends(require_roles("auditor", "admin"))]
)

RECONSTRUCTABLE = ("ask", "mcp.query")


@router.get("/events")
async def list_events(
    services: ServicesDep,
    principal: CurrentPrincipal,
    actor_id: str | None = None,
    document_id: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    events = await audit_service.list_events(
        services,
        actor_id=actor_id,
        action=action,
        document_id=document_id,
        since=since,
        limit=limit,
        offset=offset,
    )
    next_offset = offset + limit if len(events) == limit else None
    readable = await access_service.audit_content_readable(services, principal, events)
    items = [_visible(e.model_dump(mode="json"), e.id in readable) for e in events]
    return {"items": items, "next_offset": next_offset}


@router.get("/verify")
async def verify_chain(services: ServicesDep) -> dict[str, Any]:
    return await audit_service.verify_chain(services)


def _visible(body: dict[str, Any], readable: bool) -> dict[str, Any]:
    return (
        {**body, "content_withheld": False} if readable else access_service.redact_audit_body(body)
    )


async def _event_or_404(services: ServicesDep, event_id: str) -> AuditEvent:
    event = await audit_service.get_event(services, event_id) if is_uuid(event_id) else None
    if event is None:
        raise NotFound("Audit event not found.")
    return event


@router.get("/events/{event_id}")
async def get_event(
    event_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    event = await _event_or_404(services, event_id)
    readable = await access_service.audit_content_readable(services, principal, [event])
    return _visible(await _with_reconstruction(services, event), event.id in readable)


@router.post("/events/{event_id}/reveal")
async def reveal_event(
    event_id: str, body: RevealRequest, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Break-glass: show withheld answer content, recording who looked, at what and why."""
    event = await _event_or_404(services, event_id)
    readable = await access_service.audit_content_readable(services, principal, [event])
    if event.id not in readable:
        await audit_service.record(
            services,
            actor_id=principal.id,
            action=access_service.AUDIT_REVEAL_ACTION,
            subject_type="audit_event",
            subject_id=event.id,
            payload={
                "revealed_event_id": event.id,
                "revealed_seq": event.seq,
                "reason": body.reason,
            },
        )
    return _visible(await _with_reconstruction(services, event), True)


async def _with_reconstruction(services: ServicesDep, event: AuditEvent) -> dict[str, Any]:
    body = event.model_dump(mode="json")
    reconstruction = None
    if event.action in RECONSTRUCTABLE:
        query_id = event.payload.get("query_id") or event.subject_id
        query = await services.repo.get_query(query_id) if query_id else None
        receipt_id = (event.payload.get("freshness_receipt") or {}).get("receipt_id")
        receipt = await services.freshness_store.get_receipt(receipt_id) if receipt_id else None
        reconstruction = {
            "query": query.model_dump(mode="json") if query else None,
            "freshness_receipt": receipt.model_dump(mode="json") if receipt else None,
        }
    body["reconstruction"] = reconstruction
    return body
