"""Access control glue: per-document contexts, visibility checks, grants and access requests.

Every document read goes through `visible_page` / `filter_pages`, which evaluate the
`access_control` policy fresh on every call (never cached), so a revocation applies to the very
next request. A denied document raises exactly the same `NotFound("Document not found.")` as a
missing one. Stored answers are re-authorised the same way each time they are served
(`readable_query_records`), so query history cannot replay evidence after a revocation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from access_control import (
    AccessControlError,
    AccessDecision,
    AccessRequest,
    AccessRequestNotFound,
    AccessRequestStatus,
    DenyReason,
    DocumentAccessContext,
    Effect,
    FilterResult,
    Grant,
    GrantNotFound,
    Principal,
    SourceKind,
    SubjectType,
    resolve_groups,
)

from app.core.auth import has_role
from app.core.errors import Conflict, Forbidden, NotFound
from app.schemas.access import (
    AccessMap,
    AccessMapDocument,
    AccessMapEdge,
    AccessMapGrantRef,
    AccessMapGroup,
    AccessMapPrincipal,
    AccessMapSource,
)
from app.schemas.domain import AuditEvent, Page, QueryRecord
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


async def with_resolved_groups(
    services: Services, principals: Sequence[Principal]
) -> list[Principal]:
    """Each principal with nested groups expanded and platform group ids bound (D-023), as the
    policy needs them. Run on every principal loaded for an access decision."""
    definitions = await services.group_directory.list_definitions()
    return [resolve_groups(p, definitions) for p in principals]


def can_manage(principal: Principal, page: Page) -> bool:
    return page.owner_principal_id == principal.id or has_role(principal, *MANAGE_ROLES)


# ---------------------------------------------------------------------------- stored answers
QUERY_WITHHELD_STATUS = "withheld"
QUERY_WITHHELD_TEXT = (
    "This answer used sources you can no longer access. Ask again to get an answer from the "
    "sources you can read now."
)


def _evidence_document_ids(payload: dict[str, Any], cited: Iterable[str]) -> set[str] | None:
    """Documents whose content may appear in a stored answer, from its `ask` audit payload.

    `evidence_document_ids` lists exactly the documents behind the spans the composer saw. Older
    events lack it: spans are drawn only from receipt items marked `safe_to_use`, so those page
    ids are a safe superset, and without a receipt every document allowed at ask time is. Cited
    ids are always included. `None` means the evidence cannot be determined."""
    receipt = payload.get("freshness_receipt")
    if isinstance(payload.get("evidence_document_ids"), list):
        ids = {i for i in payload["evidence_document_ids"] if isinstance(i, str) and i}
    elif isinstance(receipt, dict) and isinstance(receipt.get("evidence_items"), list):
        ids = {
            item["page_id"]
            for item in receipt["evidence_items"]
            if isinstance(item, dict) and item.get("safe_to_use") and item.get("page_id")
        }
    elif isinstance(payload.get("access_decisions"), list):
        ids = {
            d["document_id"]
            for d in payload["access_decisions"]
            if isinstance(d, dict) and d.get("decision") == Effect.allow and d.get("document_id")
        }
    else:
        return None
    return ids | {c for c in cited if isinstance(c, str) and c}


async def _readable_document_ids(
    services: Services, principal: Principal, ids: set[str]
) -> set[str]:
    """The subset of `ids` the principal may read right now (missing or deleted: not readable)."""
    if not ids:
        return set()
    pages = await services.repo.get_pages(sorted(ids))
    live = [p for p in pages.values() if p.deleted_at is None]
    _, allowed = await filter_pages(services, principal, live)
    return {p.id for p in allowed}


def _withheld(record: QueryRecord) -> QueryRecord:
    return record.model_copy(
        update={
            "status": QUERY_WITHHELD_STATUS,
            "answer_text": QUERY_WITHHELD_TEXT,
            "citations": [],
            "grounding_report": None,
            "freshness_receipt_id": None,
        }
    )


async def readable_query_records(
    services: Services, principal: Principal, records: Sequence[QueryRecord]
) -> list[QueryRecord]:
    """Re-authorise stored answers for the viewer, now.

    A stored answer is only as visible as its least visible evidence document: if the viewer
    cannot read every one of them at this moment (revoked, deleted, or undeterminable), the
    answer text, citations, grounding report and receipt id are withheld. Only the viewer's own
    question and the fact of withholding remain; which document changed is never disclosed.
    Auditors still reach the original through the audit trail."""
    evidence: dict[str, set[str] | None] = {}
    for record in records:
        if record.answer_text is None and not record.citations and not record.grounding_report:
            evidence[record.id] = set()  # failed ask: nothing derived from any document
            continue
        event = (
            await services.repo.get_audit_event(record.audit_event_id)
            if record.audit_event_id
            else None
        )
        evidence[record.id] = (
            _evidence_document_ids(event.payload, (c.get("document_id") for c in record.citations))
            if event is not None and event.subject_id == record.id
            else None
        )
    wanted = set().union(*(ids for ids in evidence.values() if ids))
    readable = await _readable_document_ids(services, principal, wanted)
    return [
        record
        if (ids := evidence[record.id]) is not None and ids <= readable
        else _withheld(record)
        for record in records
    ]


# ---------------------------------------------------------------------------- audit content
# Audit actions whose payload carries document-derived answer content.
AUDIT_CONTENT_ACTIONS = ("ask",)
AUDIT_REVEAL_ACTION = "audit.reveal"


def _audit_evidence(event: AuditEvent) -> set[str] | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    cited = payload.get("cited_document_ids")
    return _evidence_document_ids(payload, cited if isinstance(cited, list) else [])


async def audit_content_readable(
    services: Services, principal: Principal, events: Sequence[AuditEvent]
) -> set[str]:
    """Ids of `events` whose answer content the viewer may see without a recorded reveal.

    Auditors see every event's metadata (asker, question, retrieved ids, each allow/deny, the
    receipt and the grounding verdict). Answer text and quotes are document content, so they
    follow the same rule as saved answers: visible only if the viewer can read every evidence
    document now. Events without answer content are always readable."""
    evidence = {e.id: _audit_evidence(e) for e in events if e.action in AUDIT_CONTENT_ACTIONS}
    wanted = set().union(*(ids for ids in evidence.values() if ids))
    readable_docs = await _readable_document_ids(services, principal, wanted)
    return {e.id for e in events if e.id not in evidence} | {
        event_id for event_id, ids in evidence.items() if ids is not None and ids <= readable_docs
    }


def redact_audit_body(body: dict[str, Any]) -> dict[str, Any]:
    """Strip document-derived content from a serialised audit event and its reconstruction.

    The stored event and its hash are untouched; only this response copy changes."""
    payload = dict(body.get("payload") or {})
    if payload.get("answer_text") is not None:
        payload["answer_text"] = None
    redacted = {**body, "payload": payload, "content_withheld": True}
    reconstruction = body.get("reconstruction")
    if isinstance(reconstruction, dict) and isinstance(reconstruction.get("query"), dict):
        query = {
            **reconstruction["query"],
            "answer_text": None,
            "citations": [],
            "grounding_report": None,
        }
        redacted["reconstruction"] = {**reconstruction, "query": query}
    return redacted


# ---------------------------------------------------------------------------- access map
def _grant_refs(
    context: DocumentAccessContext, decision: AccessDecision
) -> list[AccessMapGrantRef]:
    """The grants the policy itself reported as satisfying the decision (`R5` only)."""
    used = set(decision.grant_ids)
    return [
        AccessMapGrantRef(grant_id=g.id, subject_type=g.subject_type, subject_id=g.subject_id)
        for g in context.grants
        if g.id in used
    ]


async def access_map(services: Services, principal: Principal) -> AccessMap:
    """Who can read what, and by which rule, over the documents the CALLER can read.

    Managers and admins only. Source access is a ceiling for the caller too, so documents the
    caller cannot read never appear (no titles, no counts). Every active principal is evaluated
    with the same policy `filter` as retrieval; only allow decisions are returned.
    """
    if not has_role(principal, *MANAGE_ROLES):
        raise Forbidden()
    now = services.clock.now()
    pages = await services.repo.list_pages(limit=ALL_PAGES_LIMIT)
    caller_result, visible = await filter_pages(services, principal, pages, now=now)
    caller_decisions = {d.document_id: d for d in caller_result.decisions if d.allowed}
    visible.sort(key=lambda p: (p.source_id, p.title, p.id))
    contexts = await build_contexts(services, visible)
    people = await with_resolved_groups(
        services, [p for p in await services.repo.list_principals() if p.is_active]
    )

    edges: list[AccessMapEdge] = []
    for person in people:
        result = services.access_policy.filter(person, contexts, now=now)
        allowed = set(result.allowed_ids)
        for context, decision in zip(contexts, result.decisions, strict=True):
            if decision.document_id not in allowed:
                continue
            edges.append(
                AccessMapEdge(
                    principal_id=person.id,
                    document_id=decision.document_id,
                    rule=decision.matched_rule,
                    via=_grant_refs(context, decision),
                )
            )

    source_ids = {p.source_id for p in visible}
    access = AccessMap(
        policy_version=services.access_policy.policy_version,
        generated_at=now,
        principals=[
            AccessMapPrincipal(id=p.id, display_name=p.display_name, roles=p.roles, groups=p.groups)
            for p in people
        ],
        groups=[AccessMapGroup(id=g.id, name=g.name) for g in await services.repo.list_groups()],
        sources=[
            AccessMapSource(id=s.id, name=s.name, kind=str(s.kind))
            for s in await services.repo.list_sources()
            if s.id in source_ids
        ],
        documents=[
            AccessMapDocument(
                id=p.id,
                title=p.title,
                slug=p.slug,
                source_id=p.source_id,
                source_kind=str(p.source_kind),
                classification=str(p.classification),
                permissions_synced_at=caller_decisions[p.id].permission_captured_at
                if p.source_kind != SourceKind.upload
                else None,
                permissions_expire_at=caller_decisions[p.id].permission_expires_at,
            )
            for p in visible
        ],
        edges=edges,
    )
    await audit.record(
        services,
        actor_id=principal.id,
        action="access.map",
        subject_type="access_map",
        payload={
            "mapped_document_ids": [p.id for p in visible],
            "principal_ids": [p.id for p in people],
            "edge_count": len(edges),
            "policy_version": access.policy_version,
        },
    )
    return access


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
_PLATFORM_NAMES = {
    SourceKind.confluence: "Confluence",
    SourceKind.jira: "Jira",
    SourceKind.slack: "Slack",
    SourceKind.gdrive: "Google Drive",
    SourceKind.email: "the mailbox",
}


async def approval_effect(services: Services, req: AccessRequest) -> tuple[bool, str | None]:
    """Whether an approved request actually lets the requester read the document now.

    A local grant cannot widen what the source platform allows (ac-v2), so an approval can leave
    the requester blocked. The approver (owner or admin) is told why, in terms they can act on;
    the requester learns nothing new."""
    page = await services.repo.get_page(req.document_id)
    requester = await services.repo.get_principal(req.principal_id)
    if page is None or requester is None:
        return False, "Approved, but we couldn't check whether the requester can open it now."
    name = requester.display_name
    if not requester.is_active:
        return False, f"Approved, but {name}'s account is inactive, so they still can't open it."
    (requester,) = await with_resolved_groups(services, [requester])
    (context,) = await build_contexts(services, [page])
    decision = services.access_policy.decide(requester, context, now=services.clock.now())
    if decision.allowed:
        return True, None
    platform = _PLATFORM_NAMES.get(page.source_kind, "the source system")
    if decision.reason == DenyReason.no_source_membership:
        return False, (
            f"Approved, but {name} still can't open this document: {platform} doesn't share it "
            f"with them. Ask the owner to share it in {platform}."
        )
    if decision.reason == DenyReason.unknown_permissions:
        return False, (
            f"Approved, but {platform} hasn't confirmed this document's permissions recently, "
            "so it stays closed to everyone until the next successful sync."
        )
    if decision.reason == DenyReason.explicit_deny:
        return False, (
            f"Approved, but a deny grant on this document still blocks {name}. "
            "Revoke it to let them in."
        )
    return False, f"Approved, but another access rule still blocks {name}."


async def denial_note(services: Services, req: AccessRequest) -> str:
    """What the approver is told after denying: nothing changes, and nobody is told. The
    requester has no view of decided requests, so a denial never confirms the document exists."""
    requester = await services.repo.get_principal(req.principal_id)
    name = requester.display_name if requester is not None else "The requester"
    return f"Denied. Nothing changes for {name}, and they aren't notified."


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
