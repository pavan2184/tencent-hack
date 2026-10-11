"""Personas: `GET /api/principals` (no actor) and `GET /api/me`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import ServicesDep
from app.core.auth import CurrentPrincipal

router = APIRouter(tags=["identity"])


@router.get("/principals")
async def list_principals(services: ServicesDep) -> dict[str, Any]:
    principals = await services.repo.list_principals()
    return {
        "items": [
            p.model_dump(
                mode="json", include={"id", "display_name", "email", "roles", "groups", "is_active"}
            )
            for p in principals
            if p.is_active
        ]
    }


@router.get("/me")
async def me(principal: CurrentPrincipal) -> dict[str, Any]:
    return principal.model_dump(mode="json")
