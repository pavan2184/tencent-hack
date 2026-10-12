"""Audit trail (auditor/admin only): events, one event with its reconstruction, chain verify."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import ServicesDep
from app.core.auth import require_roles
from app.core.errors import NotFound
from app.services import audit as audit_service
from app.services.access import is_uuid

router = APIRouter(
    prefix="/audit", tags=["audit"], dependencies=[Depends(require_roles("auditor", "admin"))]
)

RECONSTRUCTABLE = ("ask", "mcp.query")


@router.get("/events")
async def list_events(
    services: ServicesDep,
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
    return {"items": [e.model_dump(mode="json") for e in events], "next_offset": next_offset}


@router.get("/verify")
async def verify_chain(services: ServicesDep) -> dict[str, Any]:
    return await audit_service.verify_chain(services)


@router.get("/events/{event_id}")
async def get_event(event_id: str, services: ServicesDep) -> dict[str, Any]:
    event = await audit_service.get_event(services, event_id) if is_uuid(event_id) else None
    if event is None:
        raise NotFound("Audit event not found.")
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
