"""SQLAlchemy 2.x models mirroring `infra/postgres/migrations/*.sql` BY HAND.

The SQL files are the schema source of truth; these classes exist so the app can build typed
queries. There is no autogenerate and `Base.metadata.create_all` is never called — the migration
runner (`app.db.migrate`) owns DDL. When a migration changes a table, change the class here in the
same PR (`app/tests/test_sql_integration.py` asserts every table below exists after migrating).

Conventions:
- UUID columns are `UUID(as_uuid=False)`: ids travel through the app as `str` (see
  `app/schemas/domain.py` and the libraries' models).
- `TSVECTOR` columns are mapped but never written by the app: `pages.search_vector` is set by the
  `trg_pages_search_vector` trigger, `content_chunks.search_vector` is `GENERATED ALWAYS`.
- `content_chunks.embedding` is `vector(EMBEDDING_DIM)`; the runner substitutes the same setting
  into the DDL, so changing `EMBEDDING_DIM` needs `make reset`.
- CHECK constraints and non-unique indexes live in the SQL only (not repeated here).
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

__all__ = [
    "AccessRequestRow",
    "AuditEventRow",
    "Base",
    "ChunkRow",
    "ConnectorCheckpointRow",
    "FreshnessPolicyRow",
    "FreshnessReceiptRow",
    "GrantRow",
    "GroupMembershipRow",
    "GroupRow",
    "IngestLogRow",
    "LinkRow",
    "ObjectFreshnessRow",
    "PageRow",
    "PageVersionRow",
    "PrincipalRow",
    "QueryRow",
    "RawDataRow",
    "SchemaMigrationRow",
    "SourceChangeEventRow",
    "SourcePermissionRow",
    "SourceRow",
    "SyncRunRow",
    "TagRow",
    "TimelineEntryRow",
    "UploadRow",
    "UsageCounterRow",
    "canonical_uuid",
    "is_uuid",
]

TZ = DateTime(timezone=True)
UUID_STR = UUID(as_uuid=False)
_GEN_UUID = text("gen_random_uuid()")
_NOW = func.now()
_EMPTY_JSON_OBJ = text("'{}'::jsonb")
_EMPTY_JSON_ARR = text("'[]'::jsonb")


class Base(DeclarativeBase):
    pass


def is_uuid(value: object) -> bool:
    """True when `value` can be bound to a UUID column (malformed ids must read as misses,
    never as a database error — a denied/unknown document must look identical)."""
    if not isinstance(value, str):
        return False
    return canonical_uuid(value) is not None


def canonical_uuid(value: object) -> str | None:
    """The canonical (lowercase, hyphenated) form Postgres returns, or None if not a UUID."""
    if not isinstance(value, str):
        return None
    try:
        return str(_uuid.UUID(value))
    except ValueError:
        return None


def _uuid_pk() -> Mapped[str]:
    return mapped_column(UUID_STR, primary_key=True, server_default=_GEN_UUID)


def _created_at() -> Mapped[datetime]:
    return mapped_column(TZ, nullable=False, server_default=_NOW)


# =============================================================================================
# 0001_core_init.sql
# =============================================================================================


class SchemaMigrationRow(Base):
    __tablename__ = "schema_migrations"

    filename: Mapped[str] = mapped_column(Text, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)


class PrincipalRow(Base):
    __tablename__ = "principals"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    external_identities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_OBJ
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)


class GroupRow(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class GroupMembershipRow(Base):
    __tablename__ = "group_memberships"

    principal_id: Mapped[str] = mapped_column(
        Text, ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[str] = mapped_column(
        Text, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )


class UploadRow(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = _uuid_pk()
    actor_id: Mapped[str] = mapped_column(Text, ForeignKey("principals.id"), nullable=False)
    # FK added in 0002 (uploads_page_id_fkey) once `pages` exists.
    page_id: Mapped[str | None] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class UsageCounterRow(Base):
    __tablename__ = "usage_counters"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)


class QueryRow(Base):
    __tablename__ = "queries"

    id: Mapped[str] = _uuid_pk()
    actor_id: Mapped[str] = mapped_column(Text, ForeignKey("principals.id"), nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_ARR
    )
    grounding_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    freshness_receipt_id: Mapped[str | None] = mapped_column(UUID_STR)  # soft ref, no FK
    access_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    audit_event_id: Mapped[str | None] = mapped_column(UUID_STR)  # soft ref, no FK
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


class AuditEventRow(Base):
    """Append-only (trigger rejects UPDATE/DELETE). `seq` is a BIGSERIAL; the repo takes it from
    `nextval()` under an advisory lock and inserts it explicitly (see `append_audit_event`)."""

    __tablename__ = "audit_events"

    id: Mapped[str] = _uuid_pk()
    seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True, server_default=FetchedValue()
    )
    occurred_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text)
    subject_type: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_OBJ
    )
    prev_hash: Mapped[str | None] = mapped_column(Text)  # NULL only for the genesis event
    hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class AccessRequestRow(Base):
    """`document_id` deliberately has NO foreign key (POST always answers 202)."""

    __tablename__ = "access_requests"

    id: Mapped[str] = _uuid_pk()
    document_id: Mapped[str] = mapped_column(UUID_STR, nullable=False)
    principal_id: Mapped[str] = mapped_column(Text, ForeignKey("principals.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    created_at: Mapped[datetime] = _created_at()
    decided_at: Mapped[datetime | None] = mapped_column(TZ)
    decided_by: Mapped[str | None] = mapped_column(Text)


# =============================================================================================
# 0002_core_gbrain_pages.sql
# =============================================================================================


class SourceRow(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    local_path: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_OBJ
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(TZ)
    newest_content_at: Mapped[datetime | None] = mapped_column(TZ)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    archived_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)


class PageRow(Base):
    """`pages` IS the documents table. Identity `(source_id, slug)`."""

    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("source_id", "slug", name="pages_source_slug_key"),
        Index(
            "uq_pages_source_external_object",
            "source_id",
            "external_object_id",
            unique=True,
            postgresql_where=text("external_object_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = _uuid_pk()
    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'note'"))
    page_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'markdown'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    compiled_truth: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    timeline: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    frontmatter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_OBJ
    )
    content_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)
    deleted_at: Mapped[datetime | None] = mapped_column(TZ)
    effective_date: Mapped[datetime | None] = mapped_column(TZ)
    # Written ONLY by trigger trg_pages_search_vector (title A, compiled_truth B, timeline C).
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        nullable=True,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
        deferred=True,
    )
    # ours: governed-document columns
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    external_object_id: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'internal'")
    )
    owner_principal_id: Mapped[str | None] = mapped_column(Text)
    permission_version: Mapped[str | None] = mapped_column(Text)
    provider_version: Mapped[str | None] = mapped_column(Text)
    provider_modified_at: Mapped[datetime | None] = mapped_column(TZ)
    evidence_class: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'standard'")
    )
    ingest_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )


class ChunkRow(Base):
    __tablename__ = "content_chunks"
    __table_args__ = (
        UniqueConstraint("page_id", "chunk_index", name="content_chunks_page_index_key"),
    )

    id: Mapped[str] = _uuid_pk()
    page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'compiled_truth'")
    )
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(settings.EMBEDDING_DIM))
    model: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedded_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _created_at()
    # GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED — never written.
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', chunk_text)", persisted=True),
        nullable=True,
        deferred=True,
    )


class LinkRow(Base):
    __tablename__ = "links"
    __table_args__ = (
        UniqueConstraint("from_page_id", "to_page_id", "link_type", name="links_from_to_type_key"),
    )

    id: Mapped[str] = _uuid_pk()
    from_page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    to_page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    context: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_at: Mapped[datetime] = _created_at()


class TagRow(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("page_id", "tag", name="tags_page_tag_key"),)

    id: Mapped[str] = _uuid_pk()
    page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(Text, nullable=False)


class TimelineEntryRow(Base):
    """Dedup: UNIQUE INDEX uq_timeline_dedup ON (page_id, date, md5(summary), source)."""

    __tablename__ = "timeline_entries"

    id: Mapped[str] = _uuid_pk()
    page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    actor_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class RawDataRow(Base):
    __tablename__ = "raw_data"
    __table_args__ = (UniqueConstraint("page_id", "source", name="raw_data_page_source_key"),)

    id: Mapped[str] = _uuid_pk()
    page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Any] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)


class PageVersionRow(Base):
    __tablename__ = "page_versions"

    id: Mapped[str] = _uuid_pk()
    page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    compiled_truth: Mapped[str] = mapped_column(Text, nullable=False)
    frontmatter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_OBJ
    )
    provider_version: Mapped[str | None] = mapped_column(Text)
    snapshot_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)


class IngestLogRow(Base):
    __tablename__ = "ingest_log"

    id: Mapped[str] = _uuid_pk()
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    pages_updated: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_ARR
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    actor_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


# =============================================================================================
# 0100_freshness_init.sql
# =============================================================================================


class SyncRunRow(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "scope_key", "idempotency_key", name="sync_runs_source_scope_idem_key"
        ),
    )

    id: Mapped[str] = _uuid_pk()
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    connector_kind: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_kind: Mapped[str] = mapped_column(Text, nullable=False)
    cursor_before: Mapped[str | None] = mapped_column(Text)
    cursor_after: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    observed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    applied_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tombstoned_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(TZ)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)


class ConnectorCheckpointRow(Base):
    __tablename__ = "connector_checkpoints"
    __table_args__ = (PrimaryKeyConstraint("source_id", "scope_key"),)

    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    connector_kind: Mapped[str] = mapped_column(Text, nullable=False)
    cursor_value: Mapped[str | None] = mapped_column(Text)
    cursor_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_polled_at: Mapped[datetime | None] = mapped_column(TZ)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(TZ)
    last_successful_run_id: Mapped[str | None] = mapped_column(
        UUID_STR, ForeignKey("sync_runs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ready'"))
    # nullable with DEFAULT now(): the lib's model carries optional created_at/updated_at.
    created_at: Mapped[datetime | None] = mapped_column(TZ, server_default=_NOW)
    updated_at: Mapped[datetime | None] = mapped_column(TZ, server_default=_NOW)


class SourceChangeEventRow(Base):
    __tablename__ = "source_change_events"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "provider_event_id",
            name="source_change_events_source_provider_event_key",
        ),
    )

    id: Mapped[str] = _uuid_pk()
    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    connector_kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_object_id: Mapped[str] = mapped_column(Text, nullable=False)
    change_kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider_version: Mapped[str | None] = mapped_column(Text)
    version_order: Mapped[int | None] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'accepted'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(TZ)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(TZ)
    parked_at: Mapped[datetime | None] = mapped_column(TZ)
    noop_reason: Mapped[str | None] = mapped_column(Text)


class ObjectFreshnessRow(Base):
    __tablename__ = "object_freshness"
    __table_args__ = (PrimaryKeyConstraint("source_id", "external_object_id"),)

    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    external_object_id: Mapped[str] = mapped_column(Text, nullable=False)
    connector_kind: Mapped[str] = mapped_column(Text, nullable=False)
    page_id: Mapped[str | None] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="SET NULL")
    )
    page_slug: Mapped[str | None] = mapped_column(Text)
    provider_version: Mapped[str | None] = mapped_column(Text)
    version_order: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str | None] = mapped_column(Text)
    provider_modified_at: Mapped[datetime | None] = mapped_column(TZ)
    observed_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    indexed_at: Mapped[datetime | None] = mapped_column(TZ)
    searchable_at: Mapped[datetime | None] = mapped_column(TZ)
    last_verified_at: Mapped[datetime | None] = mapped_column(TZ)
    verification_result: Mapped[str | None] = mapped_column(Text)
    sync_path: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(TZ)
    tombstone_version: Mapped[str | None] = mapped_column(Text)
    freshness_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'not_searchable'")
    )
    last_run_id: Mapped[str | None] = mapped_column(
        UUID_STR, ForeignKey("sync_runs.id", ondelete="SET NULL")
    )
    # nullable with DEFAULT now(): the lib's model carries optional created_at/updated_at.
    created_at: Mapped[datetime | None] = mapped_column(TZ, server_default=_NOW)
    updated_at: Mapped[datetime | None] = mapped_column(TZ, server_default=_NOW)


class FreshnessPolicyRow(Base):
    """Immutable versioned budgets; at most one ACTIVE row per (connector_kind, evidence_class)
    (partial unique index uq_freshness_policies_one_active)."""

    __tablename__ = "freshness_policies"
    __table_args__ = (
        PrimaryKeyConstraint("policy_id", "schema_version"),
        Index(
            "uq_freshness_policies_one_active",
            "connector_kind",
            "evidence_class",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    policy_id: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    connector_kind: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_class: Mapped[str] = mapped_column(Text, nullable=False)
    max_index_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_verification_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    require_live_verification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    failure_action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    effective_at: Mapped[datetime | None] = mapped_column(TZ)
    retired_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)


class FreshnessReceiptRow(Base):
    __tablename__ = "freshness_receipts"
    __table_args__ = (UniqueConstraint("request_key", name="freshness_receipts_request_key_key"),)

    receipt_id: Mapped[str] = mapped_column(UUID_STR, primary_key=True, server_default=_GEN_UUID)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    # NULL unless every item was evaluated under one policy revision (soft refs, no FK).
    policy_id: Mapped[str | None] = mapped_column(Text)
    policy_schema_version: Mapped[int | None] = mapped_column(Integer)
    evidence_items: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_ARR
    )
    oldest_evidence_age_seconds: Mapped[int | None] = mapped_column(Integer)
    overall_status: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_hash: Mapped[str] = mapped_column(Text, nullable=False)


# =============================================================================================
# 0200_access_init.sql
# =============================================================================================


class SourcePermissionRow(Base):
    """One raw (never flattened) permission snapshot per document."""

    __tablename__ = "source_permissions"

    page_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    permission_version: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)
    connector_run_id: Mapped[str | None] = mapped_column(UUID_STR)  # soft ref to sync_runs


class GrantRow(Base):
    """Soft-revoked (rows never deleted). uq_grants_active: one ACTIVE grant per
    (document_id, subject_type, subject_id, effect, scope)."""

    __tablename__ = "grants"
    __table_args__ = (
        Index(
            "uq_grants_active",
            "document_id",
            "subject_type",
            "subject_id",
            "effect",
            "scope",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[str] = _uuid_pk()
    document_id: Mapped[str] = mapped_column(
        UUID_STR, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'read'"))
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=_NOW)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_by: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
