"""Documents (= pages): ACL-filtered list/get, upload with caps, classification, live verify,
access requests and timeline. Every read is access-checked; invisible == missing (same 404)."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from access_control import Classification, Principal, SourcePermissions, UploadPermissions
from freshness import ConnectorKind, EvidenceClass, VerifyRequest, VerifyResult

from app.connectors.registry import get_connector
from app.core.auth import has_role
from app.core.errors import CapExceeded, Forbidden, NotFound, PayloadTooLarge, ValidationFailed
from app.schemas.domain import UPLOADS_TOTAL_DAY, Page, TimelineEntry, UploadRecord, new_id
from app.services import audit, jobs
from app.services.access import (
    MANAGE_ROLES,
    can_manage,
    filter_pages,
    request_access,
    visible_page,
)
from app.services.ingestion import parse_markdown_page, public_frontmatter
from app.services.sources import ensure_uploads_source

if TYPE_CHECKING:
    from app.services.wiring import Services

LIST_SCAN_LIMIT = 5_000
_HEADING = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_len: int = 60) -> str:
    slug = _SLUG_CHARS.sub("-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "untitled"


# ---------------------------------------------------------------------------- read models
async def freshness_view(services: Services, page: Page) -> dict[str, Any] | None:
    """The page's freshness right now (stored object evaluated under its active policy)."""
    if not page.external_object_id:
        return None
    obj = await services.freshness_store.get_object(page.source_id, page.external_object_id)
    if obj is None:
        return None
    status = obj.freshness_status
    policy = await services.freshness_store.get_active_policy(
        obj.connector_kind, EvidenceClass(page.evidence_class)
    )
    if policy is not None:
        from freshness import evaluate

        status = evaluate(obj, policy, services.clock.now()).freshness_status
    return {
        "freshness_status": str(status),
        "provider_version": obj.provider_version,
        "indexed_at": obj.indexed_at,
        "searchable_at": obj.searchable_at,
        "last_verified_at": obj.last_verified_at,
        "verification_result": str(obj.verification_result) if obj.verification_result else None,
        "sync_path": str(obj.sync_path),
    }


async def document_summary(services: Services, page: Page) -> dict[str, Any]:
    fresh = await freshness_view(services, page)
    return {
        "id": page.id,
        "source_id": page.source_id,
        "source_kind": str(page.source_kind),
        "slug": page.slug,
        "title": page.title,
        "type": page.type,
        "classification": str(page.classification),
        "evidence_class": str(page.evidence_class),
        "owner_principal_id": page.owner_principal_id,
        "provider_version": page.provider_version,
        "provider_modified_at": page.provider_modified_at,
        "updated_at": page.updated_at,
        "freshness_status": fresh["freshness_status"] if fresh else None,
        "ingest_status": page.ingest_status,
        "tags": await services.repo.get_tags(page.id),
    }


async def list_documents(
    services: Services,
    principal: Principal,
    *,
    q: str | None = None,
    source_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Visible documents only; pagination is over the visible set (no hidden totals)."""
    candidates = await services.repo.list_pages(
        source_ids=[source_id] if source_id else None, q=q, limit=LIST_SCAN_LIMIT
    )
    _, allowed = await filter_pages(services, principal, candidates)
    window = allowed[offset : offset + limit]
    items = [await document_summary(services, p) for p in window]
    next_offset = offset + limit if offset + limit < len(allowed) else None
    return {"items": items, "limit": limit, "offset": offset, "next_offset": next_offset}


async def get_document(services: Services, principal: Principal, page_id: str) -> dict[str, Any]:
    page, decision = await visible_page(services, principal, page_id)
    body = await document_summary(services, page)
    body.update(
        {
            "compiled_truth": page.compiled_truth,
            "timeline": page.timeline,
            "frontmatter": public_frontmatter(page.frontmatter),
            "freshness": await freshness_view(services, page),
            "access": {
                "decision": str(decision.decision),
                "matched_rule": decision.matched_rule,
                "permission_version": decision.permission_version,
            },
            "can_manage": can_manage(principal, page),
        }
    )
    return body


# ---------------------------------------------------------------------------- mutations
async def set_classification(
    services: Services,
    principal: Principal,
    page_id: str,
    classification: Classification | str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    page, _ = await visible_page(services, principal, page_id)
    if not can_manage(principal, page):
        raise Forbidden()
    new = Classification(str(classification))
    updated = await services.repo.update_page_fields(page.id, classification=new)
    await audit.record(
        services,
        actor_id=principal.id,
        action="document.classification",
        subject_type="document",
        subject_id=page.id,
        payload={
            "document_id": page.id,
            "from": str(page.classification),
            "to": str(new),
            "reason": reason,
        },
    )
    return await get_document(services, principal, (updated or page).id)


async def verify_object(
    services: Services, source_id: str, external_object_id: str
) -> VerifyResult:
    """Live verification of one provider object (NOT access-checked; callers check first)."""
    source = await services.repo.get_source(source_id)
    if source is None:
        raise NotFound()
    page = await services.repo.get_page_by_external_id(source_id, external_object_id)
    obj = await services.freshness_store.get_object(source_id, external_object_id)
    kind = obj.connector_kind if obj is not None else ConnectorKind(str(source.kind))
    req = VerifyRequest(
        source_id=source_id,
        external_object_id=external_object_id,
        connector_kind=kind,
        evidence_class=EvidenceClass(page.evidence_class) if page else EvidenceClass.standard,
    )
    return await services.freshness.verify_freshness(req, get_connector(source, services))


async def verify_document(services: Services, principal: Principal, page_id: str) -> dict[str, Any]:
    page, _ = await visible_page(services, principal, page_id)
    if not has_role(principal, *MANAGE_ROLES):
        raise Forbidden()
    if not page.external_object_id:
        raise NotFound("Document not found.")
    result = await verify_object(services, page.source_id, page.external_object_id)
    await audit.record(
        services,
        actor_id=principal.id,
        action="document.verify",
        subject_type="document",
        subject_id=page.id,
        payload={"document_id": page.id, "result": result.model_dump(mode="json")},
    )
    return {
        "schema_version": result.schema_version,
        "document_id": page.id,
        "source_id": page.source_id,
        "external_object_id": page.external_object_id,
        "evidence_class": str(result.evidence_class),
        "expected_provider_version": result.indexed_provider_version,
        "observed_provider_version": result.observed_provider_version,
        "verified_at": result.verified_at,
        "verification_result": str(result.verification_result),
        "freshness_status": str(result.freshness_status),
        "safe_use": result.safe_to_use,
        "safe_to_use": result.safe_to_use,
        "fallback_action": str(result.fallback_action) if result.fallback_action else None,
        "reason": result.reason,
    }


async def request_document_access(
    services: Services, principal: Principal, page_id: str, reason: str | None
) -> dict[str, str]:
    await request_access(services, principal, page_id, reason)
    return {"status": "received"}


async def get_timeline(
    services: Services, principal: Principal, page_id: str
) -> list[TimelineEntry]:
    page, _ = await visible_page(services, principal, page_id)
    return await services.repo.list_timeline(page.id)


async def add_timeline_entry(
    services: Services,
    principal: Principal,
    page_id: str,
    *,
    entry_date: date,
    summary: str,
    source: str = "",
    detail: str = "",
) -> TimelineEntry:
    page, _ = await visible_page(services, principal, page_id)
    entry = await services.repo.add_timeline_entry(
        TimelineEntry(
            page_id=page.id,
            date=entry_date,
            source=source,
            summary=summary,
            detail=detail,
            actor_id=principal.id,
        )
    )
    await audit.record(
        services,
        actor_id=principal.id,
        action="document.timeline.add",
        subject_type="document",
        subject_id=page.id,
        payload={"document_id": page.id, "entry": entry.model_dump(mode="json")},
    )
    return entry


# ---------------------------------------------------------------------------- upload
def _validation(message: str, field: str = "file", **extra: Any) -> ValidationFailed:
    return ValidationFailed(
        message, details={"errors": [{"loc": [field], "msg": message, **extra}]}
    )


async def _reserve_upload_caps(services: Services, actor_id: str, today: date) -> None:
    s = services.settings
    repo = services.repo
    actor_key = f"uploads:{actor_id}"
    if (
        await repo.increment_counter(
            today, actor_key, 1, limit=s.UPLOAD_MAX_FILES_PER_ACTOR_PER_DAY
        )
        is None
    ):
        raise CapExceeded(
            "Daily upload limit reached.",
            details={
                "cap": "uploads_per_actor_per_day",
                "limit": s.UPLOAD_MAX_FILES_PER_ACTOR_PER_DAY,
                "window": "day",
            },
        )
    if (
        await repo.increment_counter(
            UPLOADS_TOTAL_DAY, "uploads_total", 1, limit=s.UPLOAD_MAX_FILES_TOTAL
        )
        is None
    ):
        await repo.increment_counter(today, actor_key, -1)
        raise CapExceeded(
            "Total upload limit reached.",
            details={"cap": "uploads_total", "limit": s.UPLOAD_MAX_FILES_TOTAL, "window": "total"},
        )


async def upload_document(
    services: Services,
    principal: Principal,
    *,
    filename: str,
    content: bytes,
    content_type: str = "text/markdown",
    title: str | None = None,
    classification: str | None = None,
    shared_with_principals: list[str] | None = None,
    shared_with_groups: list[str] | None = None,
    slug: str | None = None,
) -> dict[str, Any]:
    """Validate -> caps -> page in source `uploads` owned by the actor (+ UploadPermissions
    snapshot) -> enqueue ingest -> audit `document.upload`. Frontmatter `permissions`, `grants`,
    `owner` and `simulate` in an uploaded file are ignored."""
    s = services.settings
    ext = PurePath(filename or "").suffix.lower().lstrip(".")
    if ext not in s.upload_allowed_extensions:
        raise _validation(
            "File extension not allowed.", allowed=sorted(s.upload_allowed_extensions)
        )
    if len(content) > s.UPLOAD_MAX_FILE_BYTES:
        raise PayloadTooLarge(details={"limit_bytes": s.UPLOAD_MAX_FILE_BYTES})
    if not content.strip():
        raise _validation("File is empty.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _validation("File is not UTF-8 text.") from exc
    try:
        cls = Classification(classification or "internal")
    except ValueError as exc:
        raise _validation("Unknown classification.", field="classification") from exc

    now = services.clock.now()
    await _reserve_upload_caps(services, principal.id, now.date())

    if ext == "md":
        parsed = parse_markdown_page(text)
        meta = public_frontmatter(parsed.frontmatter)
        meta.pop("owner", None)
        compiled, timeline = parsed.compiled_truth, parsed.timeline
    else:
        meta, compiled, timeline = {}, text.strip(), ""
    heading = _HEADING.search(compiled)
    final_title = (
        (title or "").strip()
        or str(meta.get("title") or "").strip()
        or (heading.group(1).strip() if heading else "")
        or PurePath(filename).stem
    )
    source = await ensure_uploads_source(services)
    page_id = new_id()
    base_slug = slug or f"uploads/{principal.id}/{now.date().isoformat()}-{slugify(final_title)}"
    final_slug = base_slug
    if await services.repo.get_page_by_slug(source.id, final_slug) is not None:
        final_slug = f"{base_slug}-{page_id[:8]}"
    content_hash = hashlib.sha256(content).hexdigest()
    permission_version = f"pv-upload-{page_id[:8]}-1"
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    page = await services.repo.upsert_page(
        Page(
            id=page_id,
            source_id=source.id,
            slug=final_slug,
            type=str(meta.get("type") or "note"),
            title=final_title,
            compiled_truth=compiled,
            timeline=timeline,
            frontmatter={**meta, "title": final_title, "filename": filename},
            content_hash=content_hash,
            source_kind=source.kind,
            external_object_id=f"upload:{page_id}",
            classification=cls,
            owner_principal_id=principal.id,
            permission_version=permission_version,
            provider_version="1",
            provider_modified_at=now,
            evidence_class=EvidenceClass.standard,
            ingest_status="pending",
        )
    )
    await services.repo.set_tags(page.id, [str(t) for t in tags])
    await services.permission_store.put(
        page.id,
        SourcePermissions.from_raw(
            UploadPermissions(
                owner_principal_id=principal.id,
                shared_with_principals=list(shared_with_principals or []),
                shared_with_groups=list(shared_with_groups or []),
            ).model_dump(),
            permission_version=permission_version,
            captured_at=now,
        ),
    )
    upload = await services.repo.record_upload(
        UploadRecord(
            actor_id=principal.id,
            page_id=page.id,
            filename=filename,
            bytes=len(content),
            content_type=content_type or "application/octet-stream",
        )
    )
    await audit.record(
        services,
        actor_id=principal.id,
        action="document.upload",
        subject_type="document",
        subject_id=page.id,
        payload={
            "document_id": page.id,
            "upload_id": upload.id,
            "filename": filename,
            "bytes": len(content),
            "content_hash": content_hash,
            "classification": str(cls),
        },
    )
    jobs.enqueue_ingest(page.id)
    inline = jobs.runs_inline()
    if inline:
        await jobs.flush_inline()
    stored = await services.repo.get_page(page.id) or page
    return {
        "upload_id": upload.id,
        "document": await document_summary(services, stored),
        "ingest": {"status": "completed" if inline else "queued", "task_id": None},
    }
