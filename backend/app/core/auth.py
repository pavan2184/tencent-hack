"""Identity for the demo: seeded personas, no auth.

The acting principal comes from the `X-Actor-Id` header (or `?actor=` for MCP clients that
cannot set headers). This is the single replacement point for real authentication later:
swap `resolve_principal` for a JWT/OIDC verifier and nothing else changes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from access_control import Principal
from fastapi import Depends, Header, Query

from app.core.context import actor_id_var
from app.core.errors import Forbidden, Unauthenticated, UnknownActor


async def resolve_principal(actor_id: str | None) -> Principal:
    """Resolve an actor id to an active Principal or raise the 401 envelope errors.

    Usable outside FastAPI dependencies (MCP tools, tasks). Sets the actor ContextVar.
    """
    actor_id = (actor_id or "").strip()
    if not actor_id:
        raise Unauthenticated()
    from app.db.repo import get_repo  # lazy: avoid import cycles with the repo layer

    principal = await get_repo().get_principal(actor_id)
    if principal is None or not principal.is_active:
        raise UnknownActor()
    from app.services.access import with_resolved_groups
    from app.services.wiring import current_services

    services = current_services()
    if services is not None:  # nested groups and platform group ids (D-023)
        (principal,) = await with_resolved_groups(services, [principal])
    actor_id_var.set(principal.id)
    return principal


async def get_principal(
    x_actor_id: str | None = Header(default=None, alias="X-Actor-Id"),
    actor: str | None = Query(default=None),
) -> Principal:
    return await resolve_principal(x_actor_id or actor)


# Annotated alias for routers: `principal: CurrentPrincipal`.
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def has_role(principal: Principal, *roles: str) -> bool:
    return bool(set(roles) & set(principal.roles))


def require_roles(*roles: str) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: `Depends(require_roles("manager", "admin"))` -> 403 otherwise."""

    async def _dep(principal: CurrentPrincipal) -> Principal:
        if not has_role(principal, *roles):
            raise Forbidden()
        return principal

    return _dep
