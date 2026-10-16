"""Ingestion: provider object -> gbrain page -> chunks -> embeddings -> `IndexOutcome`.

Two entry points, both reporting to the freshness library:
- `apply_change(services, source, connector, change)` is the `freshness.ApplyChange` used by
  `connector_sync` (seed, scheduled and manual syncs, webhooks): fetch -> upsert page (+version,
  permission snapshot, grants/tags/timeline from frontmatter) -> chunk -> embed.
- `ingest_page(services, page_id)` (re)indexes an already-stored page (uploads, re-index) by
  running a one-change `connector_sync`, so every indexed page has an `object_freshness` row.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import partial
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import frontmatter
from access_control import Effect, Grant, SubjectType
from freshness import (
    ChangeKind,
    ChangePage,
    ConnectorKind,
    ConnectorSyncRequest,
    IndexOutcome,
    ListChangeSource,
    NormalizedChange,
    SyncPath,
)

from app.connectors.base import Connector, FetchedObject
from app.connectors.gbrain_import import parse_datetime
from app.core.errors import NotFound
from app.schemas.domain import (
    Chunk,
    Page,
    PageVersion,
    Source,
    TimelineEntry,
    new_id,
)
from app.services.permission_drift import store_permissions

if TYPE_CHECKING:
    from app.services.wiring import Services

CHUNK_MAX_CHARS = 1200
EMBEDDING_COUNTER_KEY = "embedding_calls"
SENSITIVE_FRONTMATTER = ("permissions", "grants", "simulate")
TIMELINE_RE = re.compile(r"^- \*\*(\d{4}-\d{2}-\d{2})\*\* \| (.+?) — (.+)$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ParsedPage:
    frontmatter: dict[str, Any]
    compiled_truth: str
    timeline: str
    timeline_entries: list[dict[str, Any]] = field(default_factory=list)


def parse_markdown_page(text: str) -> ParsedPage:
    """Split a gbrain page: YAML frontmatter, compiled truth above the first standalone `---`
    line after the frontmatter, timeline below it. Timeline bullets matching
    `- **YYYY-MM-DD** | Source — summary` become structured entries."""
    try:
        post = frontmatter.loads(text)
        meta, body = dict(post.metadata), post.content
    except Exception:  # noqa: BLE001 - malformed YAML: treat the whole text as body
        meta, body = {}, text
    lines = body.splitlines()
    split_at = next((i for i, line in enumerate(lines) if line.strip() == "---"), None)
    if split_at is None:
        compiled, timeline = body.strip(), ""
    else:
        compiled = "\n".join(lines[:split_at]).strip()
        timeline = "\n".join(lines[split_at + 1 :]).strip()
    entries: list[dict[str, Any]] = []
    for line in timeline.splitlines():
        match = TIMELINE_RE.match(line.strip())
        if match:
            entries.append(
                {
                    "date": date.fromisoformat(match.group(1)),
                    "source": match.group(2).strip(),
                    "summary": match.group(3).strip(),
                }
            )
    return ParsedPage(meta, compiled, timeline, entries)


def public_frontmatter(meta: dict[str, Any]) -> dict[str, Any]:
    """Frontmatter safe to show a reader (no membership lists, grants or demo knobs)."""
    return {k: v for k, v in meta.items() if k not in SENSITIVE_FRONTMATTER}


# ---------------------------------------------------------------------------- chunking
def _split_long(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    out: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT.split(paragraph):
        while len(sentence) > max_chars:
            out.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            out.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        out.append(current)
    return out


def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """Paragraph-packed chunks of at most `max_chars` (long paragraphs split on sentences)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for piece in _split_long(paragraph, max_chars):
            if current and len(current) + 2 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def build_chunks(page: Page) -> list[Chunk]:
    chunks: list[Chunk] = []
    for source, text in (("compiled_truth", page.compiled_truth), ("timeline", page.timeline)):
        for piece in chunk_text(text):
            chunks.append(
                Chunk(
                    page_id=page.id,
                    chunk_index=len(chunks),
                    chunk_text=piece,
                    chunk_source=source,  # type: ignore[arg-type]
                    token_count=len(piece.split()),
                )
            )
    return chunks


# ---------------------------------------------------------------------------- embeddings
async def embed_texts(services: Services, texts: list[str]) -> list[list[float]] | None:
    """Embed under the daily embedding-call budget; None when the budget is exhausted."""
    if not texts:
        return []
    day = services.clock.now().date()
    allowed = await services.repo.increment_counter(
        day, EMBEDDING_COUNTER_KEY, 1, limit=services.settings.EMBEDDING_DAILY_CALL_BUDGET
    )
    if allowed is None:
        return None
    return await services.embedder.embed(texts)


async def index_page(
    services: Services, page: Page, *, indexed_at: datetime | None = None
) -> IndexOutcome:
    """Chunk + embed one stored page and replace its chunks. Never touches freshness rows."""
    chunks = build_chunks(page)
    vectors = await embed_texts(services, [c.chunk_text for c in chunks])
    version_order = page.frontmatter.get("version_order")
    common: dict[str, Any] = {
        "page_id": page.id,
        "page_slug": page.slug,
        "provider_version": page.provider_version,
        "version_order": int(version_order) if isinstance(version_order, int) else None,
        "content_hash": page.content_hash,
        "provider_modified_at": page.provider_modified_at,
    }
    if vectors is None:
        await services.repo.set_ingest_status(page.id, "budget_exceeded")
        return IndexOutcome(
            content_written=True,
            searchable=False,
            embedded=False,
            error_code="budget_exceeded",
            **common,
        )
    now = services.clock.now()
    model = getattr(services.embedder, "name", "embedding")
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.model = model
        chunk.embedded_at = now
    await services.repo.replace_chunks(page.id, chunks)
    await services.repo.set_ingest_status(page.id, "indexed")
    at = indexed_at or now
    return IndexOutcome(
        content_written=True,
        searchable=True,
        embedded=True,
        indexed_at=at,
        searchable_at=at,
        **common,
    )


# ---------------------------------------------------------------------------- pages
async def upsert_fetched_page(
    services: Services,
    source: Source,
    fetched: FetchedObject,
    *,
    granted_by: str = "system:sync",
) -> Page:
    """Write a fetched provider object as a page + version, permission snapshot, tags, timeline
    entries and frontmatter grants (added only when no identical active grant exists)."""
    repo = services.repo
    parsed = parse_markdown_page(fetched.markdown)
    existing = await repo.get_page_by_external_id(
        source.id, fetched.external_object_id
    ) or await repo.get_page_by_slug(source.id, fetched.slug)
    perms = fetched.permissions
    permission_version = fetched.permission_version or (perms.permission_version if perms else None)
    meta = dict(parsed.frontmatter)
    if fetched.version_order is not None:
        meta.setdefault("version_order", fetched.version_order)
    page = Page(
        id=existing.id if existing else new_id(),
        source_id=source.id,
        slug=fetched.slug,
        type=fetched.page_type,
        title=fetched.title,
        compiled_truth=parsed.compiled_truth,
        timeline=parsed.timeline,
        frontmatter=_jsonable(meta),
        content_hash=fetched.content_hash,
        effective_date=fetched.modified_at,
        source_kind=source.kind,
        external_object_id=fetched.external_object_id,
        classification=fetched.classification,
        owner_principal_id=fetched.owner_principal_id,
        permission_version=permission_version,
        provider_version=fetched.provider_version,
        provider_modified_at=fetched.modified_at,
        evidence_class=fetched.evidence_class,
        ingest_status="pending",
        deleted_at=None,
    )
    stored = await repo.upsert_page(page)
    if (
        existing is None
        or existing.provider_version != stored.provider_version
        or existing.content_hash != stored.content_hash
    ):
        await repo.add_page_version(
            PageVersion(
                page_id=stored.id,
                compiled_truth=stored.compiled_truth,
                frontmatter=stored.frontmatter,
                provider_version=stored.provider_version,
            )
        )
    if perms is not None:
        if permission_version and perms.permission_version != permission_version:
            perms = perms.model_copy(update={"permission_version": permission_version})
        await store_permissions(services, stored, perms, observed_via="ingest")
    await repo.set_tags(stored.id, fetched.tags)
    for entry in parsed.timeline_entries:
        await repo.add_timeline_entry(TimelineEntry(page_id=stored.id, **entry))
    await sync_frontmatter_grants(services, stored.id, fetched.grants, granted_by=granted_by)
    return stored


async def sync_frontmatter_grants(
    services: Services, document_id: str, grants: list[dict[str, Any]], *, granted_by: str
) -> int:
    if not grants:
        return 0
    current = (await services.grant_store.list_for_documents([document_id])).get(document_id, [])
    added = 0
    for spec in grants:
        try:
            subject_type = SubjectType(str(spec["subject_type"]))
            effect = Effect(str(spec.get("effect", "allow")))
            subject_id = str(spec["subject_id"])
        except (KeyError, ValueError):
            continue
        duplicate = any(
            g.subject_type == subject_type
            and g.subject_id == subject_id
            and g.effect == effect
            and g.revoked_at is None
            for g in current
        )
        if duplicate:
            continue
        grant = Grant(
            document_id=document_id,
            subject_type=subject_type,
            subject_id=subject_id,
            effect=effect,
            scope=str(spec.get("scope", "read")),
            granted_by=granted_by,
            granted_at=services.clock.now(),
            reason=spec.get("reason"),
        )
        current.append(await services.grant_store.add(grant))
        added += 1
    return added


def _jsonable(value: Any) -> Any:
    """YAML may yield dates/datetimes; keep frontmatter JSON-serialisable for JSONB."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------- ApplyChange
async def apply_change(
    services: Services,
    source: Source,
    connector: Connector,
    change: NormalizedChange,
    *,
    granted_by: str = "system:sync",
) -> IndexOutcome:
    """`freshness.ApplyChange` for one source change (raise = failure -> the event is parked)."""
    repo = services.repo
    if change.change_kind is ChangeKind.delete:
        page = await repo.get_page_by_external_id(source.id, change.external_object_id)
        if page is not None:
            await repo.mark_page_deleted(page.id, at=change.provider_modified_at)
            await repo.set_ingest_status(page.id, "deleted")
        return IndexOutcome(
            content_written=True,
            searchable=False,
            embedded=False,
            page_id=page.id if page else None,
            page_slug=page.slug if page else None,
        )

    if connector.kind == "upload":
        page = await repo.get_page_by_external_id(source.id, change.external_object_id)
        if page is None or page.deleted_at is not None:
            raise KeyError(change.external_object_id)
        return await index_page(services, page)

    fetched = await connector.fetch(change.external_object_id)
    page = await upsert_fetched_page(services, source, fetched, granted_by=granted_by)
    simulate = fetched.raw.get("simulate") or {}
    indexed_at = parse_datetime(simulate.get("indexed_at")) if simulate else None
    return await index_page(services, page, indexed_at=indexed_at)


async def ingest_page(services: Services, page_id: str) -> IndexOutcome:
    """(Re)index a stored page through a one-change `connector_sync` (so its freshness row is
    written by the freshness library), and return the indexing outcome."""
    repo = services.repo
    page = await repo.get_page(page_id)
    if page is None:
        raise NotFound("Document not found.")
    if page.deleted_at is not None or not page.external_object_id:
        return IndexOutcome(
            content_written=False, searchable=False, embedded=False, page_id=page.id
        )
    kind = ConnectorKind(str(page.source_kind))
    stored = await services.freshness_store.get_object(page.source_id, page.external_object_id)
    change = NormalizedChange(
        source_id=page.source_id,
        scope_key=f"ingest:{page.id}",
        connector_kind=kind,
        provider_event_id=f"ingest:{page.id}:{uuid4().hex}",
        external_object_id=page.external_object_id,
        change_kind=ChangeKind.upsert if stored is None else ChangeKind.metadata_change,
        provider_version=page.provider_version,
        version_order=page.frontmatter.get("version_order")
        if isinstance(page.frontmatter.get("version_order"), int)
        else None,
        provider_modified_at=page.provider_modified_at,
        observed_at=services.clock.now(),
        content_hash=page.content_hash
        or hashlib.sha256(page.compiled_truth.encode("utf-8")).hexdigest(),
    )
    outcomes: list[IndexOutcome] = []

    async def _apply(ch: NormalizedChange, *, _page: Page = page) -> IndexOutcome:
        current = await repo.get_page(_page.id) or _page
        outcome = await index_page(services, current)
        outcomes.append(outcome)
        return outcome

    req = ConnectorSyncRequest(
        source_id=page.source_id,
        scope_key=f"ingest:{page.id}",
        connector_kind=kind,
        trigger_kind=SyncPath.webhook,
        idempotency_key=f"ingest:{page.id}:{uuid4().hex}",
    )
    await services.freshness.connector_sync(
        req, change_source=ListChangeSource([ChangePage(changes=[change])]), apply=_apply
    )
    if outcomes:
        return outcomes[-1]
    current = await repo.get_page(page.id) or page
    return IndexOutcome(
        content_written=current.ingest_status == "indexed",
        searchable=current.ingest_status == "indexed",
        embedded=current.ingest_status == "indexed",
        page_id=page.id,
        page_slug=page.slug,
    )


def make_apply(
    services: Services, source: Source, connector: Connector, *, granted_by: str = "system:sync"
):  # type: ignore[no-untyped-def]
    """`freshness.ApplyChange` bound to one source/connector."""
    return partial(apply_change, services, source, connector, granted_by=granted_by)


__all__ = [
    "ParsedPage",
    "apply_change",
    "build_chunks",
    "chunk_text",
    "embed_texts",
    "index_page",
    "ingest_page",
    "make_apply",
    "parse_markdown_page",
    "public_frontmatter",
    "upsert_fetched_page",
]
