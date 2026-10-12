"""`upload` connector: the provider IS our own `pages` table (source `uploads`).

Uploads are written by `services.documents.upload_document` (or MCP `put_page`/`capture`); this
connector lets the freshness machinery treat them like any other provider object: `list_changes`
lists the source's pages, `fetch` returns the stored markdown, `head` reports the stored version
(so live verification of an upload is `fresh` unless it was deleted), and `permissions` returns
the owner/shared `UploadPermissions` snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from access_control import SourcePermissions, UploadPermissions
from freshness import (
    ChangeKind,
    ChangePage,
    Clock,
    NormalizedChange,
    ProbeUnavailable,
    ProviderHead,
    SystemClock,
)

from app.connectors.base import FetchedObject, freshness_kind
from app.schemas.domain import Page, Source

if TYPE_CHECKING:
    from app.services.wiring import Services

UPLOAD_LIST_LIMIT = 10_000


def page_markdown(page: Page) -> str:
    """Re-assemble the stored gbrain page body: compiled truth, `---`, timeline."""
    if page.timeline.strip():
        return f"{page.compiled_truth.rstrip()}\n\n---\n\n{page.timeline.strip()}\n"
    return page.compiled_truth


class UploadConnector:
    kind = "upload"

    def __init__(
        self, source: Source, services: Services | None = None, *, clock: Clock | None = None
    ) -> None:
        self.source = source
        self._services = services
        self.clock: Clock = clock or (services.clock if services is not None else SystemClock())

    @property
    def services(self) -> Services:
        if self._services is None:
            from app.services.wiring import get_services

            self._services = get_services()
        return self._services

    async def _page(self, external_object_id: str) -> Page | None:
        return await self.services.repo.get_page_by_external_id(self.source.id, external_object_id)

    async def list_changes(self, cursor: str | None, *, limit: int = 100) -> ChangePage:
        pages = await self.services.repo.list_pages(
            source_ids=[self.source.id], limit=UPLOAD_LIST_LIMIT, include_deleted=True
        )
        pages = sorted((p for p in pages if p.external_object_id), key=lambda p: p.id)
        try:
            offset = max(0, int(cursor)) if cursor else 0
        except ValueError:
            offset = 0
        now = self.clock.now()
        window = pages[offset : offset + limit]
        has_more = offset + limit < len(pages)
        changes = [
            NormalizedChange.model_validate(
                {
                    "source_id": self.source.id,
                    "connector_kind": freshness_kind(self.source),
                    "provider_event_id": "",
                    "external_object_id": p.external_object_id,
                    "change_kind": ChangeKind.delete if p.deleted_at else ChangeKind.upsert,
                    "provider_version": p.provider_version,
                    "provider_modified_at": p.provider_modified_at,
                    "observed_at": now,
                    "content_hash": p.content_hash or p.id,
                }
            )
            for p in window
        ]
        return ChangePage(
            changes=changes,
            next_cursor=str(offset + limit) if has_more else "0",
            has_more=has_more,
        )

    async def fetch(self, external_object_id: str) -> FetchedObject:
        page = await self._page(external_object_id)
        if page is None or page.deleted_at is not None:
            raise KeyError(external_object_id)
        perms = await self.services.permission_store.get_many([page.id])
        tags = await self.services.repo.get_tags(page.id)
        return FetchedObject(
            external_object_id=external_object_id,
            markdown=page_markdown(page),
            provider_version=page.provider_version,
            modified_at=page.provider_modified_at,
            content_hash=page.content_hash,
            permissions=perms.get(page.id),
            evidence_class=page.evidence_class,
            classification=page.classification,
            owner_principal_id=page.owner_principal_id,
            title=page.title,
            slug=page.slug,
            page_type=page.type,
            tags=tags,
            permission_version=page.permission_version,
            raw={"page_id": page.id, "frontmatter": page.frontmatter, "stored": True},
        )

    async def head(self, external_object_id: str) -> ProviderHead:
        try:
            page = await self._page(external_object_id)
        except Exception as exc:  # the store is the provider here: unreachable -> unknown
            raise ProbeUnavailable(f"upload: store unavailable: {type(exc).__name__}") from exc
        if page is None or page.deleted_at is not None:
            return ProviderHead(deleted=True)
        return ProviderHead(
            provider_version=page.provider_version,
            modified_at=page.provider_modified_at,
            deleted=False,
            content_hash=page.content_hash,
        )

    async def permissions(self, external_object_id: str) -> SourcePermissions:
        page = await self._page(external_object_id)
        if page is None:
            raise KeyError(external_object_id)
        perms = await self.services.permission_store.get_many([page.id])
        if page.id in perms:
            return perms[page.id]
        return SourcePermissions.from_raw(
            UploadPermissions(owner_principal_id=page.owner_principal_id or "").model_dump(),
            permission_version=page.permission_version or "v1",
            captured_at=self.clock.now(),
        )

    def normalize_webhook(self, body: dict[str, Any]) -> NormalizedChange:
        raise NotImplementedError("upload connector has no webhooks: uploads arrive via the API")
