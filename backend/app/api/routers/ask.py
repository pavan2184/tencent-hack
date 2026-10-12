"""`POST /api/ask` (governed pipeline) and the asker's query history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import ServicesDep
from app.core.auth import CurrentPrincipal, has_role
from app.core.errors import Forbidden, NotFound
from app.schemas.ask import AnswerEnvelope, AskRequest
from app.services import retrieval

router = APIRouter(tags=["ask"])

AUDIT_ROLES = ("auditor", "admin")


@router.post("/ask", response_model=AnswerEnvelope)
async def ask(body: AskRequest, services: ServicesDep, principal: CurrentPrincipal) -> Any:
    return await retrieval.ask(
        services,
        principal,
        body.question,
        source_ids=body.source_ids,
        top_k=body.top_k,
        require_fresh=body.require_fresh,
    )


@router.get("/queries")
async def list_queries(
    services: ServicesDep,
    principal: CurrentPrincipal,
    actor_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    target = principal.id
    if actor_id is not None and actor_id != principal.id:
        if not has_role(principal, *AUDIT_ROLES):
            raise Forbidden()
        target = actor_id
    rows = await services.repo.list_queries(target, limit=limit, offset=offset)
    return {
        "items": [
            r.model_dump(
                mode="json",
                include={
                    "id",
                    "actor_id",
                    "question",
                    "status",
                    "answer_text",
                    "created_at",
                    "latency_ms",
                    "audit_event_id",
                },
            )
            for r in rows
        ]
    }


@router.get("/queries/{query_id}")
async def get_query(
    query_id: str, services: ServicesDep, principal: CurrentPrincipal
) -> dict[str, Any]:
    from app.services.access import is_uuid

    record = await services.repo.get_query(query_id) if is_uuid(query_id) else None
    if record is None or (
        record.actor_id != principal.id and not has_role(principal, *AUDIT_ROLES)
    ):
        raise NotFound("Query not found.")
    return record.model_dump(mode="json")
