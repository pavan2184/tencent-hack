"""Access control glue: per-document contexts, visibility checks, grants and access requests.

Every document read goes through `visible_page` / `filter_pages`, which evaluate the
`access_control` policy fresh on every call (never cached), so a revocation applies to the very
next request. A denied document raises exactly the same `NotFound("Document not found.")` as a
missing one.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from access_control import (
    AccessControlError,
    AccessDecision,
    AccessRequest,
    AccessRequestNotFound,
    AccessRequestStatus,
    DocumentAccessContext,
    Effect,
    FilterResult,
    Grant,
    GrantNotFound,
    Principal,
    SubjectType,
)

from app.core.auth import has_role
from app.core.errors import Conflict, Forbidden, NotFound
from app.schemas.domain import Page
from app.services import audit

if TYPE_CHECKING:
    from app.services.wiring import Services

logger = logging.getLogger(__name__)

DOCUMENT_NOT_FOUND = "Document not found."
MANAGE_ROLES = ("manager", "admin")
ALL_PAGES_LIMIT = 100_000


def document_not_found() -> NotFound:
    """The canonical 404 for a missing OR invisible document (byte-identical bodies)."""
    return NotFound(DOCUMENT_NOT_FOUND)


def is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


async def build_contexts(services: Services, pages: Sequence[Page]) -> list[DocumentAccessContext]:
    """One `DocumentAccessContext` per page (same order): permission snapshot + ALL grants
    (revoked included) + the page's own `permission_version`."""
    ids = [p.id for p in pages]
    if not ids:
        return []
    snapshots = await services.permission_store.get_many(ids)
    grants = await services.grant_store.list_for_documents(ids)
    return [
        DocumentAccessContext(
            document_id=p.id,
            source_id=p.source_id,
            source_kind=p.source_kind,
            classification=p.classification,
            owner_principal_id=p.owner_principal_id,
            source_permissions=snapshots.get(p.id),
            grants=grants.get(p.id, []),
            permission_version=p.permission_version,
        )
        for p in pages
    ]


async def filter_pages(
    services: Services, principal: Principal, pages: Sequence[Page], *, now: datetime | None = None
) -> tuple[FilterResult, list[Page]]:
    """Run the policy over `pages`; returns the full result (audit only) and allowed pages."""
    contexts = await build_contexts(services, pages)
    result = services.access_policy.filter(principal, contexts, now=now or services.clock.now())
    allowed = set(result.allowed_ids)
    return result, [p for p in pages if p.id in allowed]


async def visible_page(
    services: Services, principal: Principal, page_id: str
) -> tuple[Page, AccessDecision]:
    """The page if it exists, is not deleted and the principal may read it; else the canonical
    404 (same for missing, deleted, denied and malformed ids)."""
    if not is_uuid(page_id):
        raise document_not_found()
    page = await services.repo.get_page(page_id)
    if page is None or page.deleted_at is not None:
        raise document_not_found()
    (context,) = await build_contexts(services, [page])
    decision = services.access_policy.decide(principal, context, now=services.clock.now())
    if not decision.allowed:
        raise document_not_found()
    return page, decision


def can_manage(principal: Principal, page: Page) -> bool:
    return page.owner_principal_id == principal.id or has_role(principal, *MANAGE_ROLES)


# ---------------------------------------------------------------------------- grants
async def _all_grants(services: Services) -> list[Grant]:
    pages = await services.repo.list_pages(limit=ALL_PAGES_LIMIT, include_deleted=True)
    by_doc = await services.grant_store.list_for_documents([p.id for p in pages])
    return [g for grants in by_doc.values() for g in grants]


async def find_grant(services: Services, grant_id: str) -> Grant | None:
    for grant in await _all_grants(services):
        if grant.id == grant_id:
            return grant
    return None


async def list_grants(
    services: Services,
    principal: Principal,
    *,
    document_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    include_revoked: bool = False,
) -> list[Grant]:
    privileged = has_role(principal, *MANAGE_ROLES)
    if document_id is not None:
        page, _ = await visible_page(services, principal, document_id)
        if not (privileged or page.owner_principal_id == principal.id):
            raise Forbidden()
        grants = (await services.grant_store.list_for_documents([page.id])).get(page.id, [])
    elif privileged:
        if subject_type and subject_id:
            grants = await services.grant_store.list_for_subject(
                SubjectType(subject_type), subject_id
            )
        else:
            grants = await _all_grants(services)
    else:
        owned = [
            p
            for p in await services.repo.list_pages(limit=ALL_PAGES_LIMIT)
            if p.owner_principal_id == principal.id
        ]
        if not owned:
            raise Forbidden()
        by_doc = await services.grant_store.list_for_documents([p.id for p in owned])
        grants = [g for gs in by_doc.values() for g in gs]
    if subject_type:
        grants = [g for g in grants if g.subject_type == subject_type]
    if subject_id:
        grants = [g for g in grants if g.subject_id == subject_id]
    if not include_revoked:
        grants = [g for g in grants if g.revoked_at is None]
    return grants


async def create_grant(
    services: Services,
    principal: Principal,
    *,
    document_id: str,
    subject_type: SubjectType,
    subject_id: str,
    effect: Effect = Effect.allow,
    scope: str = "read",
    reason: str | None = None,
) -> Grant:
    page, _ = await visible_page(services, principal, document_id)
    if not (has_role(principal, "admin") or page.owner_principal_id == principal.id):
        raise Forbidden()
    existing = (await services.grant_store.list_for_documents([page.id])).get(page.id, [])
    if any(
        g.subject_type == subject_type
        and g.subject_id == subject_id
        and g.effect == effect
        and g.revoked_at is None
        for g in existing
    ):
        raise Conflict("An identical active grant already exists.")
    grant = await services.grant_store.add(
        Grant(
            document_id=page.id,
            subject_type=subject_type,
            subject_id=subject_id,
            effect=effect,
            scope=scope,
            granted_by=principal.id,
            granted_at=services.clock.now(),
            reason=reason,
        )
    )
    await audit.record(
        services,
        actor_id=principal.id,
        action="grant.create",
        subject_type="grant",
        subject_id=grant.id,
        payload={"document_id": page.id, "grant": grant.model_dump(mode="json")},
    )
    return grant


async def revoke_grant(
    services: Services, principal: Principal, grant_id: str, *, reason: str | None = None
) -> Grant:
    grant = await find_grant(services, grant_id)
    if grant is None:
        raise NotFound("Grant not found.")
    page = await services.repo.get_page(grant.document_id)
    is_owner = page is not None and page.owner_principal_id == principal.id
    if not (has_role(principal, "admin") or is_owner):
        raise Forbidden()
    if grant.revoked_at is not None:
        raise Conflict("Grant is already revoked.")
    try:
        revoked = await services.grant_store.revoke(
            grant_id, by=principal.id, at=services.clock.now()
        )
    except GrantNotFound as exc:
        raise NotFound("Grant not found.") from exc
    await audit.record(
        services,
        actor_id=principal.id,
        action="grant.revoke",
        subject_type="grant",
        subject_id=grant_id,
        payload={
            "document_id": grant.document_id,
            "reason": reason,
            "grant": revoked.model_dump(mode="json"),
        },
    )
    return revoked


# ---------------------------------------------------------------------------- requests
async def request_access(
    services: Services, principal: Principal, document_id: str, reason: str | None
) -> None:
    """Always succeeds (202) whether or not the document exists or is visible. Requests for
    malformed ids are dropped silently (they cannot reference any document)."""
    if is_uuid(document_id):
        try:
            await services.access_request_store.create(
                AccessRequest(
                    document_id=document_id,
                    principal_id=principal.id,
                    reason=reason,
                    created_at=services.clock.now(),
                )
            )
        except AccessControlError:
            logger.warning("access request not stored", exc_info=True)
    await audit.record(
        services,
        actor_id=principal.id,
        action="access_request.create",
        subject_type="document",
        subject_id=document_id,
        payload={"document_id": document_id, "reason": reason},
    )


async def list_requests(services: Services, principal: Principal) -> list[dict[str, Any]]:
    """Pending requests the caller may decide: admins all; owners those for their documents.
    Requests for documents that do not exist never surface."""
    pending = await services.access_request_store.list_pending()
    pages = await services.repo.get_pages([r.document_id for r in pending])
    admin = has_role(principal, "admin")
    out: list[dict[str, Any]] = []
    for req in pending:
        page = pages.get(req.document_id)
        if page is None or page.deleted_at is not None:
            continue
        if not (admin or page.owner_principal_id == principal.id):
            continue
        out.append({**req.model_dump(mode="json"), "document_title": page.title})
    return out


async def decide_request(
    services: Services, principal: Principal, request_id: str, *, approve: bool
) -> tuple[AccessRequest, Grant | None]:
    if not is_uuid(request_id):
        raise NotFound("Access request not found.")
    pending = {r.id: r for r in await services.access_request_store.list_pending()}
    req = pending.get(request_id)
    admin = has_role(principal, "admin")
    if req is None:
        if not admin:
            raise NotFound("Access request not found.")
    else:
        page = await services.repo.get_page(req.document_id)
        if page is None:
            raise NotFound("Access request not found.")
        if not (admin or page.owner_principal_id == principal.id):
            raise Forbidden()
    try:
        decided = await services.access_request_store.decide(
            request_id, approved=approve, by=principal.id, at=services.clock.now()
        )
    except AccessRequestNotFound as exc:
        raise NotFound("Access request not found.") from exc
    except AccessControlError as exc:
        raise Conflict("Access request already decided.") from exc
    grant: Grant | None = None
    if approve and decided.status == AccessRequestStatus.approved:
        existing = (await services.grant_store.list_for_documents([decided.document_id])).get(
            decided.document_id, []
        )
        grant = next(
            (
                g
                for g in existing
                if g.subject_type == SubjectType.principal
                and g.subject_id == decided.principal_id
                and g.effect == Effect.allow
                and g.revoked_at is None
            ),
            None,
        )
        if grant is None:
            grant = await services.grant_store.add(
                Grant(
                    document_id=decided.document_id,
                    subject_type=SubjectType.principal,
                    subject_id=decided.principal_id,
                    effect=Effect.allow,
                    granted_by=principal.id,
                    granted_at=services.clock.now(),
                    reason=f"access request {decided.id}",
                )
            )
    await audit.record(
        services,
        actor_id=principal.id,
        action="access_request.approve" if approve else "access_request.deny",
        subject_type="access_request",
        subject_id=decided.id,
        payload={
            "document_id": decided.document_id,
            "request": decided.model_dump(mode="json"),
            "grant_id": grant.id if grant else None,
        },
    )
    return decided, grant
