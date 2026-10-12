"""Domain records returned by the `Repo` (memory and SQL implementations alike).

These mirror the core tables in `infra/postgres/migrations/0001_core_init.sql` and
`0002_core_gbrain_pages.sql`. Ids are strings (UUIDs rendered as text; principal/group/source ids
are human-readable slugs). Timestamps are timezone-aware UTC. `Principal` is reused from the
`access_control` library rather than redefined here.

API response schemas (what the UI sees) live next to their routers' schemas in this package and
are built from these records; never return a domain record that carries data the caller may not
see (e.g. a denied page) without going through the access policy first.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import uuid4

from access_control import Classification, Principal, SourceKind
from freshness import EvidenceClass
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AuditEvent",
    "AuditEventDraft",
    "Chunk",
    "Group",
    "IngestLogEntry",
    "Link",
    "Page",
    "PageVersion",
    "Principal",
    "QueryRecord",
    "SearchHit",
    "Source",
    "TimelineEntry",
    "UploadRecord",
    "new_id",
    "utcnow",
]

UPLOADS_TOTAL_DAY = date(1970, 1, 1)
"""Sentinel `usage_counters.day` for all-time counters such as `uploads_total`."""


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Record(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=False)


class Group(_Record):
    id: str
    name: str


class Source(_Record):
    """A scoping unit (gbrain `sources`). `kind` drives permission semantics; the connector that
    syncs it is `config.get("connector", kind)` (`gbrain_import` for the seeded corpus)."""

    id: str
    name: str
    kind: SourceKind
    description: str = ""
    local_path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    last_sync_at: datetime | None = None
    newest_content_at: datetime | None = None
    archived: bool = False
    archived_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def connector_kind(self) -> str:
        return str(self.config.get("connector") or self.kind)


class Page(_Record):
    """A governed document (gbrain page). Identity is `(source_id, slug)`; `external_object_id`
    is the provider's id within the source. `pages` IS the documents table."""

    id: str = Field(default_factory=new_id)
    source_id: str
    slug: str
    type: str = "note"
    page_kind: Literal["markdown", "code", "image"] = "markdown"
    title: str
    compiled_truth: str = ""
    timeline: str = ""
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    deleted_at: datetime | None = None
    effective_date: datetime | None = None
    # ours: governed-document columns
    source_kind: SourceKind
    external_object_id: str | None = None
    classification: Classification = Classification.internal
    owner_principal_id: str | None = None
    permission_version: str | None = None
    provider_version: str | None = None
    provider_modified_at: datetime | None = None
    evidence_class: EvidenceClass = EvidenceClass.standard
    ingest_status: str = "pending"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class PageVersion(_Record):
    id: str = Field(default_factory=new_id)
    page_id: str
    compiled_truth: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    provider_version: str | None = None
    snapshot_at: datetime = Field(default_factory=utcnow)


class Chunk(_Record):
    """A retrieval unit. `embedding` is `None` until embedded; its length is `EMBEDDING_DIM`."""

    id: str = Field(default_factory=new_id)
    page_id: str
    chunk_index: int
    chunk_text: str
    chunk_source: Literal["compiled_truth", "timeline"] = "compiled_truth"
    embedding: list[float] | None = None
    model: str | None = None
    token_count: int | None = None
    embedded_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SearchHit(_Record):
    """One chunk-level hybrid-search hit with denormalised page metadata.

    NOT access-filtered: `Repo.search_chunks` returns candidates; the governed pipeline drops
    denied pages before anything leaves the service layer. `score` is the fused (RRF) score,
    higher is better; `rank` is 1-based within the result list.
    """

    chunk_id: str
    page_id: str
    source_id: str
    source_kind: SourceKind
    slug: str
    title: str
    chunk_index: int
    chunk_text: str
    chunk_source: str = "compiled_truth"
    score: float
    text_score: float = 0.0
    vector_score: float = 0.0
    rank: int = 0
    # filled in by services (never by the repo)
    freshness_status: str | None = None


class TimelineEntry(_Record):
    id: str = Field(default_factory=new_id)
    page_id: str
    date: date
    source: str = ""
    summary: str
    detail: str = ""
    actor_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Link(_Record):
    id: str = Field(default_factory=new_id)
    from_page_id: str
    to_page_id: str
    link_type: str = ""
    context: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class IngestLogEntry(_Record):
    id: str = Field(default_factory=new_id)
    source_id: str
    source_type: str
    source_ref: str
    pages_updated: list[str] = Field(default_factory=list)
    summary: str = ""
    actor_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class UploadRecord(_Record):
    id: str = Field(default_factory=new_id)
    actor_id: str
    page_id: str | None = None
    filename: str
    bytes: int
    content_type: str
    created_at: datetime = Field(default_factory=utcnow)


class QueryRecord(_Record):
    """One governed ask (`queries` table). `citations`, `grounding_report` and
    `access_summary` are JSON-mode dumps of the envelope parts."""

    id: str = Field(default_factory=new_id)
    actor_id: str
    request_id: str | None = None
    question: str
    status: str
    answer_text: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    grounding_report: dict[str, Any] | None = None
    freshness_receipt_id: str | None = None
    access_summary: dict[str, Any] | None = None
    audit_event_id: str | None = None
    latency_ms: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AuditEventDraft(_Record):
    """An audit event before it is chained. `payload` must already be JSON-mode (plain
    dict/list/str/int/float/bool/None) so the hash survives a JSONB round-trip; the audit service
    normalises it."""

    id: str = Field(default_factory=new_id)
    occurred_at: datetime = Field(default_factory=utcnow)
    actor_id: str | None = None
    action: str
    request_id: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(AuditEventDraft):
    """A chained audit event: `hash = app.core.hashing.chain_hash(prev_hash, seq, payload)`."""

    seq: int
    prev_hash: str | None = None
    hash: str
