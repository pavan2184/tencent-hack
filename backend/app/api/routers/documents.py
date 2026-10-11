"""Documents (= pages). Every route checks visibility first; invisible == missing (same 404)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import ServicesDep
from app.core.auth import CurrentPrincipal
from app.schemas.documents import AccessRequestCreate, ClassificationUpdate, TimelineEntryCreate
from app.services import documents as docs

router = APIRouter(prefix="/documents", tags=["documents"])


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@router.get("")
async def list_documents(
    services: ServicesDep,
    principal: CurrentPrincipal,
    q: str | None = Query(default=None, max_length=500),
    source_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await docs.list_documents(
        services, principal, q=q, source_id=source_id, limit=limit, offset=offset
    )


@router.post("/upload", status_code=201)
async def upload_document(
    services: ServicesDep,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    title: str | None = Form(default=None),
    classification: str | None = Form(default=None),
    shared_with_principals: str | None = Form(default=None),
    shared_with_groups: str | None = Form(default=None),
) -> dict[str, Any]:
    # Read at most one byte past the cap so an oversize upload is rejected without buffering it.
    content = await file.read(services.settings.UPLOAD_MAX_FILE_BYTES + 1)
    return await docs.upload_document(
        services,
        principal,
        filename=file.filename or "upload",
        content=content,
        content_type=file.content_type or "application/octet-stream",
        title=title,
        classification=classification,
        shared_with_principals=_csv(shared_with_principals),
        shared_with_groups=_csv(shared_with_groups),
    )


@router.get("/{document_id}")
async def get_document(
    document_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await docs.get_document(services, principal, document_id)


@router.get("/{document_id}/timeline")
async def get_timeline(
    document_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    entries = await docs.get_timeline(services, principal, document_id)
    return {"items": [e.model_dump(mode="json") for e in entries]}


@router.post("/{document_id}/timeline", status_code=201)
async def add_timeline_entry(
    document_id: str,
    body: TimelineEntryCreate,
    services: ServicesDep,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    entry = await docs.add_timeline_entry(
        services,
        principal,
        document_id,
        entry_date=body.date,
        summary=body.summary,
        source=body.source,
        detail=body.detail,
    )
    return entry.model_dump(mode="json")


@router.patch("/{document_id}/classification")
async def set_classification(
    document_id: str,
    body: ClassificationUpdate,
    services: ServicesDep,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    return await docs.set_classification(
        services, principal, document_id, body.classification, reason=body.reason
    )


@router.post("/{document_id}/verify")
async def verify_document(
    document_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    return await docs.verify_document(services, principal, document_id)


@router.post("/{document_id}/access-requests", status_code=202)
async def request_access(
    document_id: str,
    services: ServicesDep,
    principal: CurrentPrincipal,
    body: AccessRequestCreate | None = None,
) -> JSONResponse:
    result = await docs.request_document_access(
        services, principal, document_id, body.reason if body else None
    )
    return JSONResponse(status_code=202, content=result)
