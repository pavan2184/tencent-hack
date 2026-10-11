"""Sources: list, add (admin), freshness status, manual sync (202 `{run_id}`)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import ServicesDep
from app.connectors.registry import connector_name
from app.core.auth import CurrentPrincipal, has_role, require_roles
from app.schemas.domain import Source
from app.schemas.sources import SourceCreate, SourceOut, SyncRequest
from app.services import jobs
from app.services import sources as sources_service

router = APIRouter(prefix="/sources", tags=["sources"])


def source_out(source: Source) -> dict[str, Any]:
    return SourceOut(
        id=source.id,
        name=source.name,
        kind=str(source.kind),
        description=source.description,
        connector=connector_name(source),
        last_sync_at=source.last_sync_at,
        newest_content_at=source.newest_content_at,
        archived=source.archived,
    ).model_dump(mode="json")


@router.get("")
async def list_sources(services: ServicesDep, principal: CurrentPrincipal) -> dict[str, Any]:
    return {"items": [source_out(s) for s in await sources_service.list_sources(services)]}


@router.post("", status_code=201, dependencies=[Depends(require_roles("admin"))])
async def add_source(body: SourceCreate, services: ServicesDep) -> dict[str, Any]:
    source = await sources_service.add_source(
        services,
        id=body.id,
        name=body.name,
        kind=str(body.kind),
        local_path=body.local_path,
        config=body.config,
        description=body.description,
        replace=False,
    )
    return source_out(source)


@router.get("/{source_id}/status")
async def source_status(
    source_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await sources_service.source_status(
        services, source_id, admin=has_role(principal, "admin")
    )


@router.post("/{source_id}/sync", dependencies=[Depends(require_roles("manager", "admin"))])
async def sync_source(
    source_id: str, services: ServicesDep, body: SyncRequest | None = None
) -> JSONResponse:
    trigger = body.trigger_kind if body else "reconcile"
    run_id = await sources_service.queue_sync(services, source_id, trigger)
    if jobs.runs_inline():
        await jobs.flush_inline()
    return JSONResponse(status_code=202, content={"run_id": run_id, "status": "queued"})
