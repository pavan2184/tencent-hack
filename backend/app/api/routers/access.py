"""Grants and access requests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import ServicesDep
from app.core.auth import CurrentPrincipal
from app.schemas.access import GrantCreate, GrantRevoke
from app.services import access as access_service

router = APIRouter(prefix="/access", tags=["access"])


@router.get("/grants")
async def list_grants(
    services: ServicesDep,
    principal: CurrentPrincipal,
    document_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    include_revoked: bool = Query(default=False),
) -> dict[str, Any]:
    grants = await access_service.list_grants(
        services,
        principal,
        document_id=document_id,
        subject_type=subject_type,
        subject_id=subject_id,
        include_revoked=include_revoked,
    )
    return {"items": [g.model_dump(mode="json") for g in grants]}


@router.post("/grants", status_code=201)
async def create_grant(
    body: GrantCreate, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    grant = await access_service.create_grant(
        services,
        principal,
        document_id=body.document_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        effect=body.effect,
        scope=body.scope,
        reason=body.reason,
    )
    return grant.model_dump(mode="json")


@router.delete("/grants/{grant_id}")
async def revoke_grant(
    grant_id: str,
    services: ServicesDep,
    principal: CurrentPrincipal,
    body: GrantRevoke | None = None,
) -> dict[str, Any]:
    grant = await access_service.revoke_grant(
        services, principal, grant_id, reason=body.reason if body else None
    )
    return grant.model_dump(mode="json")


@router.get("/requests")
async def list_requests(services: ServicesDep, principal: CurrentPrincipal) -> dict[str, Any]:
    return {"items": await access_service.list_requests(services, principal)}


@router.post("/requests/{request_id}/approve")
async def approve_request(
    request_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    req, grant = await access_service.decide_request(services, principal, request_id, approve=True)
    return {
        "request": req.model_dump(mode="json"),
        "grant": grant.model_dump(mode="json") if grant else None,
    }


@router.post("/requests/{request_id}/deny")
async def deny_request(
    request_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    req, _ = await access_service.decide_request(services, principal, request_id, approve=False)
    return {"request": req.model_dump(mode="json")}
