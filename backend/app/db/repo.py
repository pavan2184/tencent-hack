"""The `Repo` ABC: the app's single persistence port for core (non-library) tables.

Two implementations: `app.db.repo_memory.InMemoryRepo` (tests, `REPO_BACKEND=memory`) and
`app.db.repo_sql.SqlRepo` (Postgres via SQLAlchemy async, `REPO_BACKEND=sql`). Library state
(freshness objects/runs/policies/receipts, grants, permission snapshots, access requests) is NOT
here: it lives behind each library's own store Protocols, implemented in `app/adapters/`.

Conventions (both implementations):
- Every method is `async`. `get_*` returns `None` on a miss; nothing raises for "not found"
  except where documented.
- Ids are strings; new UUIDs are `str(uuid4())`; timestamps are timezone-aware UTC.
- Returned objects are copies: mutating them never changes stored state.
- The repo never applies access control. Callers (services) filter with the access policy.

Process-wide accessor: `get_repo()` returns the repo of the active `Services` container (set by
`app.services.wiring.set_services`) or one installed explicitly with `set_repo()`.
`app.core.auth.resolve_principal` calls `get_repo().get_principal(...)`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from typing import Any

from access_control import Principal

from app.core.hashing import chain_hash
from app.schemas.domain import (
    AuditEvent,
    AuditEventDraft,
    Chunk,
    Group,
    IngestLogEntry,
    Link,
    Page,
    PageVersion,
    QueryRecord,
    SearchHit,
    Source,
    TimelineEntry,
    UploadRecord,
)

__all__ = [
    "RRF_K",
    "Repo",
    "audit_event_hash",
    "get_repo",
    "set_repo",
]

RRF_K = 60
"""Reciprocal-rank-fusion constant for hybrid search: score = Σ 1 / (RRF_K + rank)."""


def audit_event_hash(prev_hash: str | None, seq: int, payload: dict[str, Any]) -> str:
    """The audit chain link, shared by every Repo implementation and by `verify_chain`:
    `sha256(f"{prev_hash or ''}|{seq}|{canonical_json(payload)}")` (see 0001_core_init.sql)."""
    return chain_hash(prev_hash, seq, payload)


class Repo(ABC):
    """Async persistence port for principals, sources, pages, chunks, timeline, uploads,
    usage counters, queries and the hash-chained audit log."""

    # ------------------------------------------------------------------ principals & groups
    @abstractmethod
    async def get_principal(self, principal_id: str) -> Principal | None:
        """Principal by id, with `groups` populated from `group_memberships` (sorted).
        Inactive principals ARE returned (`is_active=False`); callers decide."""

    @abstractmethod
    async def list_principals(self) -> list[Principal]:
        """All principals (active and inactive), ordered by id, `groups` populated."""

    @abstractmethod
    async def upsert_principal(self, principal: Principal) -> Principal:
        """Insert or update by id: display_name, email, roles, external_identities, is_active.
        `principal.groups` is IGNORED here (memberships are managed with `add_membership` /
        `set_memberships`). Returns the stored principal with its current groups."""

    @abstractmethod
    async def upsert_group(self, group: Group) -> Group:
        """Insert or update a group by id."""

    @abstractmethod
    async def list_groups(self) -> list[Group]:
        """All groups ordered by id."""

    @abstractmethod
    async def add_membership(self, principal_id: str, group_id: str) -> None:
        """Idempotently add `principal_id` to `group_id` (both must exist)."""

    @abstractmethod
    async def set_memberships(self, principal_id: str, group_ids: Sequence[str]) -> None:
        """Replace the principal's memberships with exactly `group_ids` (seed reload)."""

    # ------------------------------------------------------------------ sources
    @abstractmethod
    async def get_source(self, source_id: str) -> Source | None:
        """Source by id (archived included)."""

    @abstractmethod
    async def list_sources(self, *, include_archived: bool = False) -> list[Source]:
        """Sources ordered by id; archived ones only when `include_archived`."""

    @abstractmethod
    async def upsert_source(self, source: Source) -> Source:
        """Insert or update by id (name, kind, description, local_path, config, archived).
        Keeps `created_at` and the sync timestamps of an existing row; bumps `updated_at`."""

    @abstractmethod
    async def touch_source_sync(
        self,
        source_id: str,
        last_sync_at: datetime,
        newest_content_at: datetime | None = None,
    ) -> None:
        """Record a completed sync: set `last_sync_at`; set `newest_content_at` to the max of the
        stored value and the given one (None leaves it unchanged). Unknown id is a no-op."""

    @abstractmethod
    async def count_pages(self, source_id: str, *, include_deleted: bool = False) -> int:
        """Number of pages in a source (for `GET /api/sources`)."""

    # ------------------------------------------------------------------ pages
    @abstractmethod
    async def get_page(self, page_id: str) -> Page | None:
        """Page by id, INCLUDING soft-deleted pages (check `page.deleted_at`). A malformed id
        (not a UUID) returns None rather than raising."""

    @abstractmethod
    async def get_pages(self, page_ids: Sequence[str]) -> dict[str, Page]:
        """Batch `get_page`: maps each found id to its page; misses (and malformed ids) are
        omitted. Includes soft-deleted pages."""

    @abstractmethod
    async def get_page_by_slug(self, source_id: str, slug: str) -> Page | None:
        """Page by its gbrain identity `(source_id, slug)`, soft-deleted included."""

    @abstractmethod
    async def get_page_by_external_id(self, source_id: str, external_object_id: str) -> Page | None:
        """Page by provider identity `(source_id, external_object_id)`, soft-deleted included."""

    @abstractmethod
    async def list_pages(
        self,
        *,
        source_ids: Sequence[str] | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Page]:
        """Pages ordered by `updated_at DESC, id`. `source_ids` restricts sources; `q` is a
        case-insensitive substring match on title/slug/compiled_truth (SQL may use the tsvector
        or trigram index instead, as long as a plain word in the title matches). NOT
        access-filtered: callers over-fetch and filter."""

    @abstractmethod
    async def upsert_page(self, page: Page) -> Page:
        """Insert or update a page keyed by `(source_id, slug)`.

        On insert the given `page.id` is used. On update the EXISTING id and `created_at` are
        kept and every other column is overwritten from `page` (including `deleted_at`, so an
        upsert of a live page revives a soft-deleted one); `updated_at` is bumped to now.
        If `external_object_id` is set and another page in the source already holds it with a
        different slug, that page is updated instead (provider identity wins). Returns the
        stored page."""

    @abstractmethod
    async def mark_page_deleted(self, page_id: str, *, at: datetime | None = None) -> Page | None:
        """Soft-delete (`deleted_at = at or now`) and remove the page's chunks from search
        (delete its `content_chunks`). Returns the page, or None if unknown."""

    @abstractmethod
    async def update_page_fields(self, page_id: str, **fields: Any) -> Page | None:
        """Patch named `Page` columns (e.g. `classification`, `permission_version`,
        `ingest_status`, `owner_principal_id`); bumps `updated_at`. Unknown field names raise
        `ValueError`. Returns the updated page or None if unknown."""

    @abstractmethod
    async def set_ingest_status(self, page_id: str, status: str) -> None:
        """Set `pages.ingest_status` (`pending|indexed|failed|budget_exceeded|deleted`).
        Does NOT bump `updated_at`. Unknown id is a no-op."""

    @abstractmethod
    async def add_page_version(self, version: PageVersion) -> PageVersion:
        """Append a `page_versions` snapshot."""

    @abstractmethod
    async def list_page_versions(self, page_id: str) -> list[PageVersion]:
        """Snapshots for a page, newest first."""

    # ------------------------------------------------------------------ chunks & search
    @abstractmethod
    async def replace_chunks(self, page_id: str, chunks: Sequence[Chunk]) -> int:
        """Atomically replace all chunks of a page with `chunks` (which carry their embeddings).
        Returns the number written. An empty sequence just deletes."""

    @abstractmethod
    async def list_chunks(self, page_id: str) -> list[Chunk]:
        """A page's chunks ordered by `chunk_index`."""

    @abstractmethod
    async def search_chunks(
        self,
        query: str,
        embedding: Sequence[float] | None,
        *,
        limit: int,
        source_ids: Sequence[str] | None = None,
    ) -> list[SearchHit]:
        """Hybrid chunk search over NON-deleted pages, NOT access-filtered.

        Two rankings fused with reciprocal-rank fusion (`RRF_K`): a keyword ranking (SQL:
        `ts_rank_cd(content_chunks.search_vector, websearch_to_tsquery('english', query))`;
        memory: content-token overlap) and a vector ranking (cosine similarity between
        `embedding` and chunk embeddings; skipped when `embedding` is None). A chunk must match
        at least one keyword OR be in the vector top-`limit` to appear. Ordered by fused
        `score` desc; `rank` is 1-based; `text_score`/`vector_score` are the raw component
        scores. At most `limit` hits."""

    # ------------------------------------------------------------------ timeline, tags, links
    @abstractmethod
    async def add_timeline_entry(self, entry: TimelineEntry) -> TimelineEntry:
        """Append a timeline entry. Dedup on `(page_id, date, summary, source)`: a duplicate
        returns the existing entry unchanged."""

    @abstractmethod
    async def list_timeline(self, page_id: str) -> list[TimelineEntry]:
        """Timeline entries for a page ordered by `(date, created_at)`."""

    @abstractmethod
    async def set_tags(self, page_id: str, tags: Sequence[str]) -> None:
        """Replace a page's tags (de-duplicated)."""

    @abstractmethod
    async def get_tags(self, page_id: str) -> list[str]:
        """A page's tags, sorted."""

    @abstractmethod
    async def add_link(self, link: Link) -> Link:
        """Idempotent on `(from_page_id, to_page_id, link_type)`."""

    @abstractmethod
    async def list_links(self, page_id: str) -> list[Link]:
        """Outgoing links of a page."""

    # ------------------------------------------------------------------ ingest log
    @abstractmethod
    async def log_ingest(self, entry: IngestLogEntry) -> IngestLogEntry:
        """Append an `ingest_log` row."""

    @abstractmethod
    async def list_ingest_log(
        self, *, source_id: str | None = None, limit: int = 50
    ) -> list[IngestLogEntry]:
        """Newest first."""

    # ------------------------------------------------------------------ uploads & counters
    @abstractmethod
    async def record_upload(self, upload: UploadRecord) -> UploadRecord:
        """Append an `uploads` row."""

    @abstractmethod
    async def count_uploads_total(self) -> int:
        """All-time number of uploads."""

    @abstractmethod
    async def count_uploads_for_actor_today(self, actor_id: str, day: date) -> int:
        """Uploads by `actor_id` whose `created_at` falls on UTC `day`."""

    @abstractmethod
    async def increment_counter(
        self, day: date, key: str, n: int = 1, *, limit: int | None = None
    ) -> int | None:
        """Atomically add `n` to `usage_counters(day, key)` (creating it at 0). With `limit`,
        the increment only happens if the result stays `<= limit`; otherwise nothing changes
        and None is returned (cap hit). Returns the new count."""

    @abstractmethod
    async def get_counter(self, day: date, key: str) -> int:
        """Current `usage_counters` value (0 if absent)."""

    # ------------------------------------------------------------------ queries
    @abstractmethod
    async def create_query(self, record: QueryRecord) -> QueryRecord:
        """Insert a `queries` row (id from the record)."""

    @abstractmethod
    async def set_query_audit_event(self, query_id: str, audit_event_id: str) -> None:
        """Attach the audit event id after the `ask` audit append. Unknown id is a no-op."""

    @abstractmethod
    async def get_query(self, query_id: str) -> QueryRecord | None:
        """Query by id (malformed id → None)."""

    @abstractmethod
    async def list_queries(
        self, actor_id: str | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[QueryRecord]:
        """Queries newest first; only `actor_id`'s when given (None = everyone's)."""

    # ------------------------------------------------------------------ audit (hash chain)
    @abstractmethod
    async def append_audit_event(self, draft: AuditEventDraft) -> AuditEvent:
        """Append one event to the chain ATOMICALLY: take `seq` = previous max seq + 1 (SQL:
        `nextval` under `pg_advisory_xact_lock(hashtext('audit_events'))`), `prev_hash` = hash
        of the event with the highest seq (None for genesis), and
        `hash = audit_event_hash(prev_hash, seq, draft.payload)`. Concurrent appends must
        serialise. `draft.payload` is already JSON-mode."""

    @abstractmethod
    async def get_audit_event(self, event_id: str) -> AuditEvent | None:
        """Event by id (malformed id → None)."""

    @abstractmethod
    async def list_audit_events(
        self,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        document_id: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """Events newest first (seq DESC) with AND-ed filters. `document_id` matches events whose
        `subject_id` equals it OR whose payload lists it in `retrieved_document_ids` /
        `cited_document_ids` or has `document_id` equal to it."""

    @abstractmethod
    def iter_audit_events(self) -> AsyncIterator[AuditEvent]:
        """Every event in ascending `seq`, for chain verification. Implement as an
        `async def ... yield` generator (may page internally)."""

    @abstractmethod
    async def audit_head(self) -> AuditEvent | None:
        """The event with the highest seq, or None when the chain is empty."""


# ---------------------------------------------------------------------- process accessor
_repo_override: Repo | None = None


def set_repo(repo: Repo | None) -> None:
    """Install (or clear with None) an explicit repo; takes precedence over the services one."""
    global _repo_override
    _repo_override = repo


def get_repo() -> Repo:
    """The active repo: an explicit `set_repo` override, else the active `Services.repo`
    (building the services container on first use)."""
    if _repo_override is not None:
        return _repo_override
    from app.services.wiring import get_services  # lazy: wiring imports this module

    return get_services().repo
