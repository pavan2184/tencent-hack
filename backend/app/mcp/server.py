"""Governed MCP server (`mcp` 2.x `MCPServer`, streamable HTTP, JSON responses) mounted at `/mcp`.

Tools mirror gbrain's operations plus ours (freshness, access requests, audit). Every tool:

1. resolves the caller with `_principal(ctx)` -> `app.core.auth.resolve_principal(actor_id)`;
   the actor id is the `X-Actor-Id` header (or `?actor=`) of the HTTP request carrying the
   JSON-RPC message, read from `ctx.request_context.request` (the SDK exposes the Starlette
   request per message). Fallback when no request object is attached: the ContextVar
   `app.core.context.actor_id_var`, set by the `/mcp` ASGI entry before delegating.
2. runs through the same governed services as REST (access control before any LLM; a denied
   document is reported exactly like a missing one: `app.services.access.document_not_found()`),
3. appends an audit event `mcp.<tool>` (actor, sha256 of the canonical-JSON arguments, outcome),
4. maps `AppError` to a tool error result (`isError=true`, text = the REST error envelope JSON).

Host wiring (`app/main.py`): call `mount_mcp(app)` at construction and enter
`mcp_lifespan(app)` inside the FastAPI lifespan. The SDK's session manager can run only once,
so each lifespan builds a fresh streamable-HTTP app (tests start many lifespans per process).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from access_control import Principal
from fastapi import FastAPI
from freshness import FreshnessStatusRequest, ProbeUnavailable
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.config import settings
from app.core.auth import has_role, resolve_principal
from app.core.context import actor_id_var, new_request_id, request_id_var
from app.core.errors import (
    AppError,
    Forbidden,
    NotFound,
    ProviderUnavailable,
    ValidationFailed,
    envelope,
)
from app.core.hashing import canonical_json, sha256_hex

if TYPE_CHECKING:
    from app.schemas.domain import Page
    from app.services.wiring import Services

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"
UPLOADS_SOURCE_ID = "uploads"

TOOL_NAMES: tuple[str, ...] = (
    "whoami",
    "search",
    "query",
    "assemble_evidence",
    "get_page",
    "put_page",
    "list_pages",
    "capture",
    "add_timeline_entry",
    "get_timeline",
    "log_ingest",
    "sources_list",
    "sources_status",
    "sources_add",
    "freshness_status",
    "verify_freshness",
    "request_access",
    "audit_lookup",
)

mcp: MCPServer = MCPServer(
    "brain-sauce",
    title="Brain Sauce",
    version="0.1.0",
    instructions=(
        "Governed company brain. Every tool acts as the principal named by the X-Actor-Id header "
        "(or ?actor=). Results are access-filtered before any model sees them; documents you "
        "cannot read are indistinguishable from documents that do not exist. `query` returns a "
        "cited, freshness-checked answer envelope with an audit_id."
    ),
)


# ------------------------------------------------------------------------------------------------
# identity, errors, audit
# ------------------------------------------------------------------------------------------------


def _request_of(ctx: Context | None) -> Any | None:
    if ctx is None:
        return None
    try:
        return ctx.request_context.request
    except (ValueError, AttributeError):
        return None


def _actor_from_request(request: Any) -> str | None:
    headers = getattr(request, "headers", None)
    actor = headers.get(settings.ACTOR_HEADER) if headers is not None else None
    if not actor:
        query_params = getattr(request, "query_params", None)
        actor = query_params.get("actor") if query_params is not None else None
    return actor


async def _principal(ctx: Context | None) -> Principal:
    """The calling principal. Header/query of the HTTP request when the SDK attaches it (always
    for streamable HTTP); otherwise the ContextVar set by the `/mcp` ASGI entry."""
    request = _request_of(ctx)
    actor = _actor_from_request(request) if request is not None else actor_id_var.get()
    return await resolve_principal(actor)


def _services() -> Services:
    from app.services.wiring import get_services

    return get_services()


def _jsonable(value: Any) -> Any:
    """Plain JSON data (dicts/lists/str/num/bool/None) from models, enums, datetimes, sets."""
    return json.loads(canonical_json(value))


def _error_envelope(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, AppError):
        return exc.to_envelope()
    if isinstance(exc, ProbeUnavailable):
        return ProviderUnavailable().to_envelope()
    if isinstance(exc, ValidationError | ValueError):
        return ValidationFailed(str(exc).splitlines()[0][:300]).to_envelope()
    return envelope("internal_error", "Internal error.")


async def _audit(
    svc: Services | None,
    tool: str,
    actor: str | None,
    args: dict[str, Any],
    outcome: str,
    *,
    error_code: str | None = None,
    subject: tuple[str, str] | None = None,
) -> None:
    """Append `mcp.<tool>`; never let an audit failure mask the tool result (logged instead)."""
    if svc is None:
        return
    payload: dict[str, Any] = {
        "tool": tool,
        "args_hash": sha256_hex(canonical_json(args)),
        "outcome": outcome,
    }
    if error_code:
        payload["error_code"] = error_code
    try:
        from app.services.audit import record as audit_record

        await audit_record(
            svc,
            action=f"mcp.{tool}",
            actor_id=actor,
            subject_type=subject[0] if subject else "mcp_tool",
            subject_id=subject[1] if subject else tool,
            payload=payload,
        )
    except Exception:
        logger.exception("mcp audit append failed", extra={"tool": tool})


ToolImpl = Callable[["Services", Principal], Awaitable[Any]]


async def _governed(ctx: Context | None, tool: str, args: dict[str, Any], impl: ToolImpl) -> Any:
    """Resolve the principal, run `impl`, audit `mcp.<tool>`, map errors to tool errors.

    Success: a JSON dict (structured content). Failure: a `CallToolResult(is_error=True)` whose
    only text block is exactly the REST error envelope JSON. Returning it (instead of raising
    `ToolError`) keeps the SDK's "Error executing tool ..." prefix out of the envelope; the SDK
    passes a returned `CallToolResult` through and skips output validation for errors.
    """
    request_id_var.set(new_request_id())
    svc: Services | None = None
    actor: str | None = None
    try:
        svc = _services()
        principal = await _principal(ctx)
        actor = principal.id
        result = await impl(svc, principal)
    except Exception as exc:
        env = _error_envelope(exc)
        if not isinstance(exc, AppError | ValidationError | ValueError | ProbeUnavailable):
            logger.exception("mcp tool crashed", extra={"tool": tool})
        else:
            logger.info("mcp tool error", extra={"tool": tool, "code": env["error"]["code"]})
        await _audit(svc, tool, actor, args, "error", error_code=env["error"]["code"])
        text = json.dumps(env, separators=(",", ":"))
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
    await _audit(svc, tool, actor, args, "ok")
    data = _jsonable(result)
    return data if isinstance(data, dict) else {"result": data}


def _require_roles(principal: Principal, *roles: str) -> None:
    if not has_role(principal, *roles):
        raise Forbidden()


# ------------------------------------------------------------------------------------------------
# page helpers (access-checked; denied == missing)
# ------------------------------------------------------------------------------------------------


def _document_not_found() -> NotFound:
    """The canonical 404 for a missing OR invisible document (same text as REST)."""
    from app.services.access import document_not_found

    return document_not_found()


async def _visible(svc: Services, principal: Principal, page: Page | None) -> Page:
    """`page` if it exists, is live and readable by `principal`; else the canonical 404."""
    from app.services.access import visible_page

    if page is None or page.deleted_at is not None:
        raise _document_not_found()
    visible, _ = await visible_page(svc, principal, page.id)
    return visible


async def _pages_by_slug(svc: Services, slug: str, source_id: str | None) -> list[Page]:
    if source_id:
        page = await svc.repo.get_page_by_slug(source_id, slug)
        return [page] if page is not None else []
    pages: list[Page] = []
    for source in await svc.repo.list_sources(include_archived=False):
        page = await svc.repo.get_page_by_slug(source.id, slug)
        if page is not None:
            pages.append(page)
    return pages


async def _readable_page_by_slug(
    svc: Services, principal: Principal, slug: str, source_id: str | None = None
) -> Page:
    """First live page with this slug the caller may read; else the canonical 404."""
    for page in await _pages_by_slug(svc, slug, source_id):
        try:
            return await _visible(svc, principal, page)
        except NotFound:
            continue
    raise _document_not_found()


_SECRET_KEY = re.compile(r"secret|token|password|api[_-]?key|credential", re.IGNORECASE)


def _redact(value: Any) -> Any:
    """Drop secret-looking keys (e.g. `config.webhook_secret`) from source payloads."""
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items() if not _SECRET_KEY.search(str(k))}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _parse_date(value: str | None, field: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValidationFailed(f"{field} must be an ISO date (YYYY-MM-DD).") from exc


def _parse_datetime(value: str | None, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailed(f"{field} must be an ISO-8601 timestamp.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _write_upload(
    svc: Services,
    principal: Principal,
    *,
    slug: str,
    content: str,
    classification: str,
) -> Any:
    """A new page in the `uploads` source through the REST upload service: same caps, owner
    forced to the caller, frontmatter `permissions`/`grants`/`owner`/`simulate` ignored. The
    service never overwrites: a taken slug gets a unique suffix (see `document.slug`)."""
    from app.services.documents import upload_document

    name = slug.strip("/").rsplit("/", 1)[-1] or "page"
    return await upload_document(
        svc,
        principal,
        filename=f"{name}.md",
        content=content.encode("utf-8"),
        content_type="text/markdown",
        classification=classification,
        slug=slug,
    )


# ------------------------------------------------------------------------------------------------
# tools
# ------------------------------------------------------------------------------------------------


@mcp.tool(description="Who am I? The resolved principal (id, roles, groups) for this session.")
async def whoami(ctx: Context) -> dict[str, Any]:
    async def impl(svc: Services, principal: Principal) -> Any:
        return principal.model_dump(mode="json")

    return await _governed(ctx, "whoami", {}, impl)


@mcp.tool(description="Access-filtered hybrid search over the brain. Returns ranked chunks.")
async def search(
    query: str,
    ctx: Context,
    limit: int = 20,
    offset: int = 0,
    source_id: str | None = None,
) -> dict[str, Any]:
    args = {"query": query, "limit": limit, "offset": offset, "source_id": source_id}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.retrieval import search as governed_search

        hits = await governed_search(
            svc, principal, query, limit=limit, offset=offset, source_id=source_id
        )
        return {"results": hits, "count": len(hits)}

    return await _governed(ctx, "search", args, impl)


@mcp.tool(
    description=(
        "Governed question answering: access filter -> freshness check -> grounded, cited "
        "answer (or abstention). Returns the full answer envelope incl. audit_id, citations "
        "and freshness_receipt."
    )
)
async def query(
    query: str,
    ctx: Context,
    limit: int = 8,
    source_id: str | None = None,
    require_fresh: bool = False,
) -> dict[str, Any]:
    args = {"query": query, "limit": limit, "source_id": source_id, "require_fresh": require_fresh}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.retrieval import ask

        return await ask(
            svc,
            principal,
            query,
            top_k=limit,
            source_ids=[source_id] if source_id else None,
            require_fresh=require_fresh,
        )

    return await _governed(ctx, "query", args, impl)


@mcp.tool(
    description=(
        "Access-filtered, sanitized evidence spans plus a freshness receipt for a question, "
        "without composing an answer (bring your own model)."
    )
)
async def assemble_evidence(
    query: str,
    ctx: Context,
    limit: int = 8,
    source_id: str | None = None,
) -> dict[str, Any]:
    args = {"query": query, "limit": limit, "source_id": source_id}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.retrieval import assemble_evidence as governed_evidence

        return await governed_evidence(svc, principal, query, limit=limit, source_id=source_id)

    return await _governed(ctx, "assemble_evidence", args, impl)


@mcp.tool(description="Get one page by slug (metadata; content only with include_content=true).")
async def get_page(
    slug: str,
    ctx: Context,
    source_id: str | None = None,
    include_content: bool = False,
) -> dict[str, Any]:
    args = {"slug": slug, "source_id": source_id, "include_content": include_content}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.documents import get_document

        page = await _readable_page_by_slug(svc, principal, slug, source_id)
        doc = await get_document(svc, principal, page.id)
        if not include_content:
            doc.pop("compiled_truth", None)
            doc.pop("timeline", None)
        return doc

    return await _governed(ctx, "get_page", args, impl)


@mcp.tool(
    description=(
        "Create or update a markdown page you own in the 'uploads' source. Owner is always you; "
        "frontmatter permissions are ignored. The page is ingested asynchronously."
    )
)
async def put_page(
    slug: str,
    content: str,
    ctx: Context,
    source_id: str = UPLOADS_SOURCE_ID,
    classification: str = "internal",
) -> dict[str, Any]:
    args = {
        "slug": slug,
        "content_sha256": sha256_hex(content),
        "source_id": source_id,
        "classification": classification,
    }

    async def impl(svc: Services, principal: Principal) -> Any:
        if source_id != UPLOADS_SOURCE_ID:
            raise Forbidden("put_page writes only to the 'uploads' source.")
        return await _write_upload(
            svc, principal, slug=slug, content=content, classification=classification
        )

    return await _governed(ctx, "put_page", args, impl)


@mcp.tool(description="List pages you can read (newest first), optionally by type/tag/source.")
async def list_pages(
    ctx: Context,
    type: str | None = None,
    tag: str | None = None,
    source_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    updated_after: str | None = None,
) -> dict[str, Any]:
    args = {
        "type": type,
        "tag": tag,
        "source_id": source_id,
        "limit": limit,
        "offset": offset,
        "updated_after": updated_after,
    }

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.documents import list_documents

        after = _parse_datetime(updated_after, "updated_after")
        listing = _jsonable(
            await list_documents(svc, principal, source_id=source_id, limit=500, offset=0)
        )
        items = listing.get("items", []) if isinstance(listing, dict) else listing
        selected: list[dict[str, Any]] = []
        for item in items:
            if type and item.get("type") != type:
                continue
            if after is not None:
                updated = _parse_datetime(item.get("updated_at"), "updated_at")
                if updated is None or updated <= after:
                    continue
            if tag:
                tags = item.get("tags")
                if tags is None:
                    tags = await svc.repo.get_tags(item["id"])
                if tag not in tags:
                    continue
            selected.append(item)
        page = selected[offset : offset + limit]
        return {"items": page, "count": len(page), "offset": offset, "limit": limit}

    return await _governed(ctx, "list_pages", args, impl)


@mcp.tool(
    description=(
        "Quick capture of a note into your inbox (uploads source). Slug defaults to "
        "inbox/YYYY-MM-DD-<sha8>."
    )
)
async def capture(
    content: str,
    ctx: Context,
    slug: str | None = None,
    type: str = "note",
) -> dict[str, Any]:
    args = {"content_sha256": sha256_hex(content), "slug": slug, "type": type}

    async def impl(svc: Services, principal: Principal) -> Any:
        target = slug or (
            f"inbox/{svc.clock.now().date().isoformat()}-"
            f"{hashlib.sha256(content.encode('utf-8')).hexdigest()[:8]}"
        )
        body = content
        if type != "note" and not content.lstrip().startswith("---"):
            body = f"---\ntype: {json.dumps(type)}\n---\n{content}"
        return await _write_upload(
            svc, principal, slug=target, content=body, classification="internal"
        )

    return await _governed(ctx, "capture", args, impl)


@mcp.tool(description="Append a dated entry to a page's timeline (YYYY-MM-DD).")
async def add_timeline_entry(
    slug: str,
    date: str,
    summary: str,
    ctx: Context,
    detail: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    args = {"slug": slug, "date": date, "summary": summary, "detail": detail, "source": source}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.documents import add_timeline_entry as governed_add

        on = _parse_date(date, "date")
        if on is None:
            raise ValidationFailed("date is required (YYYY-MM-DD).")
        page = await _readable_page_by_slug(svc, principal, slug)
        return await governed_add(
            svc,
            principal,
            page.id,
            entry_date=on,
            summary=summary,
            detail=detail or "",
            source=source or "mcp",
        )

    return await _governed(ctx, "add_timeline_entry", args, impl)


@mcp.tool(description="A page's timeline entries, optionally between two dates (YYYY-MM-DD).")
async def get_timeline(
    slug: str,
    ctx: Context,
    after: str | None = None,
    before: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    args = {"slug": slug, "after": after, "before": before, "limit": limit}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.documents import get_timeline as governed_timeline

        lo, hi = _parse_date(after, "after"), _parse_date(before, "before")
        page = await _readable_page_by_slug(svc, principal, slug)
        entries = await governed_timeline(svc, principal, page.id)
        kept = [  # inclusive date bounds
            e for e in entries if (lo is None or e.date >= lo) and (hi is None or e.date <= hi)
        ][:limit]
        return {"slug": page.slug, "items": kept, "count": len(kept)}

    return await _governed(ctx, "get_timeline", args, impl)


@mcp.tool(description="Record that you ingested something (e.g. a meeting) into the brain.")
async def log_ingest(
    source_type: str,
    source_ref: str,
    pages_updated: list[str],
    summary: str,
    ctx: Context,
) -> dict[str, Any]:
    args = {
        "source_type": source_type,
        "source_ref": source_ref,
        "pages_updated": pages_updated,
        "summary": summary,
    }

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.schemas.domain import IngestLogEntry
        from app.services.sources import ensure_uploads_source

        await ensure_uploads_source(svc)
        return await svc.repo.log_ingest(
            IngestLogEntry(
                source_id=UPLOADS_SOURCE_ID,
                source_type=source_type,
                source_ref=source_ref,
                pages_updated=list(pages_updated),
                summary=summary,
                actor_id=principal.id,
            )
        )

    return await _governed(ctx, "log_ingest", args, impl)


@mcp.tool(description="List sources (connectors) and their sync timestamps.")
async def sources_list(ctx: Context, include_archived: bool = False) -> dict[str, Any]:
    args = {"include_archived": include_archived}

    async def impl(svc: Services, principal: Principal) -> Any:
        sources = await svc.repo.list_sources(include_archived=include_archived)
        items = [_redact(_jsonable(s)) for s in sources]
        return {"items": items, "count": len(items)}

    return await _governed(ctx, "sources_list", args, impl)


@mcp.tool(description="Sync status of one source (checkpoint, last run, freshness counts).")
async def sources_status(source_id: str, ctx: Context) -> dict[str, Any]:
    args = {"source_id": source_id}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.sources import source_status

        report = await source_status(svc, source_id, admin=has_role(principal, "admin"))
        return _redact(_jsonable(report))

    return await _governed(ctx, "sources_status", args, impl)


@mcp.tool(description="Register a source (admin only). kind: connector kind, path: brain dir.")
async def sources_add(
    id: str,
    kind: str,
    ctx: Context,
    name: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    args = {"id": id, "kind": kind, "name": name, "path": path}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.sources import add_source

        _require_roles(principal, "admin")
        created = await add_source(svc, id=id, kind=kind, name=name or id, local_path=path)
        return _redact(_jsonable(created))

    return await _governed(ctx, "sources_add", args, impl)


@mcp.tool(
    description=(
        "Freshness of a source (object counts for admins only) or of one object you can read "
        "(external_object_id): stored state + policy evaluation, no live call."
    )
)
async def freshness_status(
    source_id: str,
    ctx: Context,
    external_object_id: str | None = None,
) -> dict[str, Any]:
    args = {"source_id": source_id, "external_object_id": external_object_id}

    async def impl(svc: Services, principal: Principal) -> Any:
        if external_object_id is None:
            # Same view as REST `GET /api/sources/{id}/status`: per-status object counts cover
            # documents the caller may not see, so only admins get them.
            from app.services.sources import source_status

            report = await source_status(svc, source_id, admin=has_role(principal, "admin"))
            return _redact(_jsonable(report))
        page = await _visible(
            svc, principal, await svc.repo.get_page_by_external_id(source_id, external_object_id)
        )
        report = await svc.freshness.freshness_status(
            FreshnessStatusRequest(
                source_id=source_id,
                external_object_id=external_object_id,
                evidence_class=page.evidence_class,
            )
        )
        return {
            "source_id": source_id,
            "external_object_id": external_object_id,
            "page_id": page.id,
            "slug": page.slug,
            "evidence_class": page.evidence_class,
            "generated_at": report.generated_at,
            "object": report.object,
            "evaluation": report.evaluation,
        }

    return await _governed(ctx, "freshness_status", args, impl)


@mcp.tool(
    description=(
        "Live-verify one object you can read against its provider (manager/admin). Records the "
        "verification and returns fresh/stale/unknown with the policy decision."
    )
)
async def verify_freshness(
    source_id: str,
    external_object_id: str,
    ctx: Context,
) -> dict[str, Any]:
    args = {"source_id": source_id, "external_object_id": external_object_id}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.documents import verify_document

        # Same path as REST `POST /api/documents/{id}/verify`: visibility (canonical 404), then
        # manager/admin, then live verify + `document.verify` audit.
        page = await svc.repo.get_page_by_external_id(source_id, external_object_id)
        if page is None or page.deleted_at is not None:
            raise _document_not_found()
        return await verify_document(svc, principal, page.id)

    return await _governed(ctx, "verify_freshness", args, impl)


@mcp.tool(
    description=(
        "Ask the owner for read access to a document (by id or slug). Always answers the same "
        "way, whether or not the document exists."
    )
)
async def request_access(
    ctx: Context,
    document_id: str | None = None,
    slug: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    args = {"document_id": document_id, "slug": slug, "reason": reason}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.documents import request_document_access

        target = document_id
        if target is None and slug:
            pages = [p for p in await _pages_by_slug(svc, slug, None) if p.deleted_at is None]
            # An unknown slug goes through the same call (a non-UUID id is dropped there but
            # still audited), so the reply is identical whether or not the slug exists.
            target = pages[0].id if pages else f"slug:{slug}"
        if not target:
            raise ValidationFailed("Provide document_id or slug.")
        return await request_document_access(svc, principal, target, reason or None)

    return await _governed(ctx, "request_access", args, impl)


@mcp.tool(description="Look up one audit event by id (auditor/admin), e.g. an answer's audit_id.")
async def audit_lookup(audit_id: str, ctx: Context) -> dict[str, Any]:
    args = {"audit_id": audit_id}

    async def impl(svc: Services, principal: Principal) -> Any:
        from app.services.audit import get_event

        _require_roles(principal, "auditor", "admin")
        event = await get_event(svc, audit_id)
        if event is None:
            raise NotFound("Audit event not found.")
        return event

    return await _governed(ctx, "audit_lookup", args, impl)


# ------------------------------------------------------------------------------------------------
# HTTP mounting
# ------------------------------------------------------------------------------------------------

# Identity is a spoofable persona header in this demo (see SECURITY_REVIEW.md), so the SDK's
# Host/Origin DNS-rebinding check would add no protection while rejecting every non-localhost
# Host (TestClient's `testserver`, compose's `api:8000`, Caddy, a cloud hostname). CORS stays
# enforced by the host FastAPI app.
_TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)

_http: dict[str, Starlette | None] = {"app": None}


def _build_http_app() -> Starlette:
    """A fresh SDK streamable-HTTP app (and session manager; `run()` is single-use)."""
    app = mcp.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        transport_security=_TRANSPORT_SECURITY,
    )
    _http["app"] = app
    return app


class McpHttpEntry:
    """ASGI entry for `/mcp` and `/mcp/`.

    Sets `actor_id_var` from `X-Actor-Id` / `?actor=` (fallback identity path) and delegates to
    the current SDK app. `exact=True` serves the bare `/mcp` path directly (no 307 to `/mcp/`).
    """

    def __init__(self, *, exact: bool = False) -> None:
        self.exact = exact

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        inner = _http["app"] or _build_http_app()
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return
        if self.exact:
            scope = dict(scope)
            scope["root_path"] = scope.get("root_path", "") + MCP_PATH
            scope["path"] = scope["path"] + "/"
            if isinstance(scope.get("raw_path"), bytes):
                scope["raw_path"] = scope["raw_path"] + b"/"
        actor = _scope_actor(scope)
        token = actor_id_var.set(actor.strip() if actor else None)
        try:
            await inner(scope, receive, send)
        finally:
            actor_id_var.reset(token)


def _scope_actor(scope: Scope) -> str | None:
    wanted = settings.ACTOR_HEADER.lower().encode("latin-1")
    for name, value in scope.get("headers") or []:
        if name.lower() == wanted:
            return value.decode("latin-1")
    from urllib.parse import parse_qs

    query = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
    values = query.get("actor")
    return values[0] if values else None


def mount_mcp(app: FastAPI) -> None:
    """Serve the MCP server at `/mcp` (and `/mcp/`) on the host FastAPI app."""
    app.router.routes.append(
        Route(MCP_PATH, endpoint=McpHttpEntry(exact=True), methods=["GET", "POST", "DELETE"])
    )
    app.mount(MCP_PATH, McpHttpEntry())


@asynccontextmanager
async def mcp_lifespan(app: FastAPI | None = None) -> AsyncIterator[None]:
    """Enter inside the host lifespan: runs the MCP session manager for the app's lifetime."""
    _build_http_app()
    async with mcp.session_manager.run():
        yield


__all__ = [
    "TOOL_NAMES",
    "McpHttpEntry",
    "mcp",
    "mcp_lifespan",
    "mount_mcp",
]
