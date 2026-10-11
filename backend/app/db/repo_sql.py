"""`SqlRepo`: the `Repo` port over Postgres (SQLAlchemy async + psycopg v3).

Every method runs in its own short transaction (`async with session.begin()`), so a returned value
is always durable. Malformed (non-UUID) ids read as misses — a denied or unknown document must
never surface as a database error. Library state (freshness, grants, permission snapshots, access
requests) is NOT here: see `app/adapters/`.

Notable SQL:
- `search_chunks`: hybrid keyword (`ts_rank_cd` over `content_chunks.search_vector`) + vector
  (`embedding <=> :vec`, cosine) rankings, each cut to `limit`, fused with reciprocal-rank fusion
  (`RRF_K`) over non-deleted pages. Keyword matching is OR-of-terms (`plainto_tsquery` with `&`
  rewritten to `|`) so a natural-language question matches chunks sharing ANY content word, as the
  ABC requires ("match at least one keyword"); `ts_rank_cd` still ranks multi-term matches higher.
- `append_audit_event`: `pg_advisory_xact_lock(hashtext('audit_events'))` → head hash →
  `nextval(...)` → `chain_hash(prev_hash, seq, payload)` → INSERT with that explicit `seq`.
- `increment_counter`: `INSERT … ON CONFLICT (day, key) DO UPDATE SET count = count + excluded.count
  [WHERE count + excluded.count <= :limit] RETURNING count` (no row ⇒ cap hit ⇒ None).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from typing import Any

from access_control import Principal
from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Column,
    Text,
    and_,
    bindparam,
    delete,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.access_stores import load_principals, replace_memberships, write_principal
from app.db.models import (
    AuditEventRow,
    ChunkRow,
    GroupMembershipRow,
    GroupRow,
    IngestLogRow,
    LinkRow,
    PageRow,
    PageVersionRow,
    QueryRow,
    SourceRow,
    TagRow,
    TimelineEntryRow,
    UploadRow,
    UsageCounterRow,
    canonical_uuid,
    is_uuid,
)
from app.db.repo import RRF_K, Repo, audit_event_hash
from app.db.repo_memory import search_tokens
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

__all__ = ["SqlRepo"]

SessionFactory = Callable[[], AsyncSession]

_AUDIT_PAGE_SIZE = 500
_C = "C"  # codepoint collation: same order as Python's sorted() in the in-memory repo

# `sources.kind` spelling in Postgres for each `access_control.SourceKind` value. The 0002 CHECK on
# disk uses the SourceKind vocabulary ('gdrive'), so this is the identity map; if the CHECK moves
# to the freshness ConnectorKind spelling, set {"gdrive": "google_drive"}. Reads accept both.
_SOURCE_KIND_TO_DB: dict[str, str] = {}
_SOURCE_KIND_FROM_DB: dict[str, str] = {"google_drive": "gdrive"}


def _cols(row_cls: Any, model_cls: type[BaseModel]) -> list[Column[Any]]:
    """Table columns backing `model_cls` (record field names == column names)."""
    table = row_cls.__table__
    return [table.c[name] for name in model_cls.model_fields]


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _values(model: BaseModel, *, exclude: Sequence[str] = ()) -> dict[str, Any]:
    return {k: _plain(v) for k, v in model.model_dump(mode="python").items() if k not in exclude}


def _rec[M: BaseModel](model_cls: type[M], row: Any) -> M:
    return model_cls.model_validate(dict(row._mapping))


def _source(row: Any) -> Source:
    data = dict(row._mapping)
    data["kind"] = _SOURCE_KIND_FROM_DB.get(data["kind"], data["kind"])
    return Source.model_validate(data)


def _chunk(row: Any) -> Chunk:
    data = dict(row._mapping)
    if data.get("embedding") is not None:
        data["embedding"] = [float(x) for x in data["embedding"]]
    return Chunk.model_validate(data)


def _vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


_PAGE_COLS = _cols(PageRow, Page)
_CHUNK_COLS = _cols(ChunkRow, Chunk)
_SOURCE_COLS = _cols(SourceRow, Source)
_AUDIT_COLS = _cols(AuditEventRow, AuditEvent)
_PAGE_MUTABLE = frozenset(Page.model_fields) - {"id"}


class SqlRepo(Repo):
    """Postgres implementation of :class:`app.db.repo.Repo`."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            yield session

    # ------------------------------------------------------------------ principals & groups
    async def get_principal(self, principal_id: str) -> Principal | None:
        async with self._tx() as s:
            found = await load_principals(s, [principal_id])
        return found[0] if found else None

    async def list_principals(self) -> list[Principal]:
        async with self._tx() as s:
            return await load_principals(s)

    async def upsert_principal(self, principal: Principal) -> Principal:
        async with self._tx() as s:
            await write_principal(s, principal)
            return (await load_principals(s, [principal.id]))[0]

    async def upsert_group(self, group: Group) -> Group:
        stmt = pg_insert(GroupRow).values(id=group.id, name=group.name)
        stmt = stmt.on_conflict_do_update(
            index_elements=[GroupRow.id], set_={"name": stmt.excluded.name}
        ).returning(GroupRow.id, GroupRow.name)
        async with self._tx() as s:
            row = (await s.execute(stmt)).one()
        return _rec(Group, row)

    async def list_groups(self) -> list[Group]:
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(GroupRow.id, GroupRow.name).order_by(GroupRow.id.collate(_C))
                )
            ).all()
        return [_rec(Group, r) for r in rows]

    async def add_membership(self, principal_id: str, group_id: str) -> None:
        try:
            async with self._tx() as s:
                await s.execute(
                    pg_insert(GroupMembershipRow)
                    .values(principal_id=principal_id, group_id=group_id)
                    .on_conflict_do_nothing()
                )
        except IntegrityError as exc:
            raise ValueError(
                f"membership {principal_id!r} -> {group_id!r}: principal and group must exist"
            ) from exc

    async def set_memberships(self, principal_id: str, group_ids: Sequence[str]) -> None:
        try:
            async with self._tx() as s:
                await replace_memberships(s, principal_id, group_ids, create_groups=False)
        except IntegrityError as exc:
            raise ValueError(
                f"memberships of {principal_id!r}: principal and every group must exist"
            ) from exc

    # ------------------------------------------------------------------ sources
    async def get_source(self, source_id: str) -> Source | None:
        async with self._tx() as s:
            row = (await s.execute(select(*_SOURCE_COLS).where(SourceRow.id == source_id))).first()
        return _source(row) if row is not None else None

    async def list_sources(self, *, include_archived: bool = False) -> list[Source]:
        stmt = select(*_SOURCE_COLS).order_by(SourceRow.id.collate(_C))
        if not include_archived:
            stmt = stmt.where(SourceRow.archived.is_(False))
        async with self._tx() as s:
            rows = (await s.execute(stmt)).all()
        return [_source(r) for r in rows]

    async def upsert_source(self, source: Source) -> Source:
        values = _values(source)
        values["kind"] = _SOURCE_KIND_TO_DB.get(values["kind"], values["kind"])
        values["created_at"] = values["updated_at"] = func.now()
        stmt = pg_insert(SourceRow).values(**values)
        mutable = ("name", "kind", "description", "local_path", "config", "archived", "archived_at")
        stmt = stmt.on_conflict_do_update(
            index_elements=[SourceRow.id],
            set_={**{k: stmt.excluded[k] for k in mutable}, "updated_at": func.now()},
        ).returning(*_SOURCE_COLS)
        async with self._tx() as s:
            row = (await s.execute(stmt)).one()
        return _source(row)

    async def touch_source_sync(
        self,
        source_id: str,
        last_sync_at: datetime,
        newest_content_at: datetime | None = None,
    ) -> None:
        changes: dict[str, Any] = {"last_sync_at": last_sync_at}
        if newest_content_at is not None:
            # GREATEST ignores NULLs, so an unset stored value takes the new one.
            changes["newest_content_at"] = func.greatest(
                SourceRow.newest_content_at, newest_content_at
            )
        async with self._tx() as s:
            await s.execute(update(SourceRow).where(SourceRow.id == source_id).values(**changes))

    async def count_pages(self, source_id: str, *, include_deleted: bool = False) -> int:
        stmt = select(func.count()).select_from(PageRow).where(PageRow.source_id == source_id)
        if not include_deleted:
            stmt = stmt.where(PageRow.deleted_at.is_(None))
        async with self._tx() as s:
            return int(await s.scalar(stmt) or 0)

    # ------------------------------------------------------------------ pages
    async def get_page(self, page_id: str) -> Page | None:
        if not is_uuid(page_id):
            return None
        async with self._tx() as s:
            row = (await s.execute(select(*_PAGE_COLS).where(PageRow.id == page_id))).first()
        return _rec(Page, row) if row is not None else None

    async def get_pages(self, page_ids: Sequence[str]) -> dict[str, Page]:
        canon: dict[str, list[str]] = {}
        for pid in dict.fromkeys(page_ids):
            c = canonical_uuid(pid)
            if c is not None:
                canon.setdefault(c, []).append(pid)
        if not canon:
            return {}
        async with self._tx() as s:
            rows = (await s.execute(select(*_PAGE_COLS).where(PageRow.id.in_(list(canon))))).all()
        out: dict[str, Page] = {}
        for row in rows:
            page = _rec(Page, row)
            for key in canon.get(page.id, []):
                out[key] = page
        return out

    async def get_page_by_slug(self, source_id: str, slug: str) -> Page | None:
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_PAGE_COLS).where(PageRow.source_id == source_id, PageRow.slug == slug)
                )
            ).first()
        return _rec(Page, row) if row is not None else None

    async def get_page_by_external_id(self, source_id: str, external_object_id: str) -> Page | None:
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_PAGE_COLS).where(
                        PageRow.source_id == source_id,
                        PageRow.external_object_id == external_object_id,
                    )
                )
            ).first()
        return _rec(Page, row) if row is not None else None

    async def list_pages(
        self,
        *,
        source_ids: Sequence[str] | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Page]:
        stmt = select(*_PAGE_COLS)
        if source_ids is not None:
            stmt = stmt.where(PageRow.source_id.in_(list(source_ids)))
        if not include_deleted:
            stmt = stmt.where(PageRow.deleted_at.is_(None))
        if q and q.strip():
            # Same rule as the in-memory repo: the whole needle as a substring of
            # title/slug/compiled_truth, OR every non-stopword token somewhere in them.
            needle = q.strip()
            hay = func.concat_ws("\n", PageRow.title, PageRow.slug, PageRow.compiled_truth)
            match = hay.icontains(needle, autoescape=True)
            words = search_tokens(needle)
            if words:
                match = or_(match, and_(*[hay.icontains(w, autoescape=True) for w in words]))
            stmt = stmt.where(match)
        stmt = stmt.order_by(PageRow.updated_at.desc(), PageRow.id).limit(limit).offset(offset)
        async with self._tx() as s:
            rows = (await s.execute(stmt)).all()
        return [_rec(Page, r) for r in rows]

    async def upsert_page(self, page: Page) -> Page:
        values = _values(page)
        async with self._tx() as s:
            # Serialise page upserts per source: the (source_id, slug) / external-id lookups and
            # the write below must not interleave with a concurrent upsert of the same identity.
            await s.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended("pages\x1f" + page.source_id, 0)
                    )
                )
            )
            by_ext = None
            if page.external_object_id is not None:
                by_ext = (
                    await s.execute(
                        select(PageRow.id, PageRow.slug)
                        .where(
                            PageRow.source_id == page.source_id,
                            PageRow.external_object_id == page.external_object_id,
                        )
                        .with_for_update()
                    )
                ).first()
            by_slug = (
                await s.execute(
                    select(PageRow.id)
                    .where(PageRow.source_id == page.source_id, PageRow.slug == page.slug)
                    .with_for_update()
                )
            ).first()
            if by_ext is not None and by_slug is not None and by_ext.id != by_slug.id:
                raise ValueError(
                    f"page {page.source_id}/{page.slug}: external_object_id "
                    f"{page.external_object_id!r} belongs to {page.source_id}/{by_ext.slug}, and "
                    "the slug is held by another page"
                )
            target = by_ext.id if by_ext is not None else (by_slug.id if by_slug else None)
            if target is None:
                if not is_uuid(page.id):
                    raise ValueError(f"page id {page.id!r} is not a UUID")
                values["created_at"] = values["updated_at"] = func.now()
                stmt = pg_insert(PageRow).values(**values).returning(*_PAGE_COLS)
            else:
                changes = {k: v for k, v in values.items() if k not in ("id", "created_at")}
                changes["updated_at"] = func.now()
                stmt = (
                    update(PageRow)
                    .where(PageRow.id == target)
                    .values(**changes)
                    .returning(*_PAGE_COLS)
                )
            row = (await s.execute(stmt)).one()
        return _rec(Page, row)

    async def mark_page_deleted(self, page_id: str, *, at: datetime | None = None) -> Page | None:
        if not is_uuid(page_id):
            return None
        async with self._tx() as s:
            row = (
                await s.execute(
                    update(PageRow)
                    .where(PageRow.id == page_id)
                    .values(deleted_at=at if at is not None else func.now(), updated_at=func.now())
                    .returning(*_PAGE_COLS)
                )
            ).first()
            if row is None:
                return None
            await s.execute(delete(ChunkRow).where(ChunkRow.page_id == page_id))
        return _rec(Page, row)

    async def update_page_fields(self, page_id: str, **fields: Any) -> Page | None:
        unknown = set(fields) - _PAGE_MUTABLE
        if unknown:
            raise ValueError(f"unknown or immutable page field(s): {sorted(unknown)}")
        if not is_uuid(page_id):
            return None
        changes = {k: _plain(v) for k, v in fields.items()}
        changes.setdefault("updated_at", func.now())
        async with self._tx() as s:
            row = (
                await s.execute(
                    update(PageRow)
                    .where(PageRow.id == page_id)
                    .values(**changes)
                    .returning(*_PAGE_COLS)
                )
            ).first()
        return _rec(Page, row) if row is not None else None

    async def set_ingest_status(self, page_id: str, status: str) -> None:
        if not is_uuid(page_id):
            return
        async with self._tx() as s:
            await s.execute(
                update(PageRow).where(PageRow.id == page_id).values(ingest_status=status)
            )

    async def add_page_version(self, version: PageVersion) -> PageVersion:
        async with self._tx() as s:
            row = (
                await s.execute(
                    pg_insert(PageVersionRow)
                    .values(**_values(version))
                    .returning(*_cols(PageVersionRow, PageVersion))
                )
            ).one()
        return _rec(PageVersion, row)

    async def list_page_versions(self, page_id: str) -> list[PageVersion]:
        if not is_uuid(page_id):
            return []
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(*_cols(PageVersionRow, PageVersion))
                    .where(PageVersionRow.page_id == page_id)
                    .order_by(PageVersionRow.snapshot_at.desc(), PageVersionRow.id.desc())
                )
            ).all()
        return [_rec(PageVersion, r) for r in rows]

    # ------------------------------------------------------------------ chunks & search
    async def replace_chunks(self, page_id: str, chunks: Sequence[Chunk]) -> int:
        if not is_uuid(page_id):
            raise ValueError(f"page id {page_id!r} is not a UUID")
        rows = [{**_values(chunk), "page_id": page_id} for chunk in chunks]
        try:
            async with self._tx() as s:
                await s.execute(delete(ChunkRow).where(ChunkRow.page_id == page_id))
                if rows:
                    await s.execute(pg_insert(ChunkRow), rows)
        except DataError as exc:  # e.g. an embedding of the wrong dimension
            raise ValueError(f"chunks of page {page_id!r} rejected: {exc.orig}") from exc
        return len(rows)

    async def list_chunks(self, page_id: str) -> list[Chunk]:
        if not is_uuid(page_id):
            return []
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(*_CHUNK_COLS)
                    .where(ChunkRow.page_id == page_id)
                    .order_by(ChunkRow.chunk_index)
                )
            ).all()
        return [_chunk(r) for r in rows]

    async def search_chunks(
        self,
        query: str,
        embedding: Sequence[float] | None,
        *,
        limit: int,
        source_ids: Sequence[str] | None = None,
    ) -> list[SearchHit]:
        if limit <= 0 or (source_ids is not None and not list(source_ids)):
            return []
        params: dict[str, Any] = {"q": query or "", "limit": limit}
        binds = []
        source_filter = ""
        if source_ids is not None:
            source_filter = "AND p.source_id = ANY(:source_ids)"
            params["source_ids"] = list(source_ids)
            binds.append(bindparam("source_ids", type_=ARRAY(Text)))
        ctes = [
            f"""
            q AS (
                SELECT CAST(replace(CAST(plainto_tsquery('english', :q) AS text), ' & ', ' | ')
                            AS tsquery) AS tsq
            ),
            kw AS (
                SELECT c.id AS chunk_id,
                       ts_rank_cd(c.search_vector, q.tsq) AS text_score,
                       row_number() OVER (
                           ORDER BY ts_rank_cd(c.search_vector, q.tsq) DESC, c.id
                       ) AS rnk
                FROM content_chunks c
                JOIN pages p ON p.id = c.page_id
                CROSS JOIN q
                WHERE p.deleted_at IS NULL AND c.search_vector @@ q.tsq {source_filter}
                ORDER BY rnk
                LIMIT :limit
            )"""
        ]
        if embedding is not None:
            params["vec"] = _vector_literal(embedding)
            ctes.append(
                f"""
            vec AS (
                SELECT v.chunk_id,
                       1 - v.distance AS vector_score,
                       row_number() OVER (ORDER BY v.distance, v.chunk_id) AS rnk
                FROM (
                    SELECT c.id AS chunk_id, c.embedding <=> CAST(:vec AS vector) AS distance
                    FROM content_chunks c
                    JOIN pages p ON p.id = c.page_id
                    WHERE p.deleted_at IS NULL AND c.embedding IS NOT NULL {source_filter}
                    ORDER BY c.embedding <=> CAST(:vec AS vector)
                    LIMIT :limit
                ) v
            )"""
            )
            fused = f"""
            fused AS (
                SELECT COALESCE(kw.chunk_id, vec.chunk_id) AS chunk_id,
                       COALESCE(kw.text_score, 0) AS text_score,
                       COALESCE(vec.vector_score, 0) AS vector_score,
                       COALESCE(1.0 / ({RRF_K} + kw.rnk), 0)
                         + COALESCE(1.0 / ({RRF_K} + vec.rnk), 0) AS score
                FROM kw FULL OUTER JOIN vec ON vec.chunk_id = kw.chunk_id
            )"""
        else:
            fused = f"""
            fused AS (
                SELECT kw.chunk_id, kw.text_score, 0 AS vector_score,
                       1.0 / ({RRF_K} + kw.rnk) AS score
                FROM kw
            )"""
        ctes.append(fused)
        sql = (
            "WITH "
            + ",".join(ctes)
            + """
            SELECT f.chunk_id, c.page_id, p.source_id, p.source_kind, p.slug, p.title,
                   c.chunk_index, c.chunk_text, c.chunk_source,
                   CAST(f.score AS float8) AS score,
                   CAST(f.text_score AS float8) AS text_score,
                   CAST(f.vector_score AS float8) AS vector_score
            FROM fused f
            JOIN content_chunks c ON c.id = f.chunk_id
            JOIN pages p ON p.id = c.page_id
            ORDER BY f.score DESC, f.chunk_id
            LIMIT :limit
            """
        )
        stmt = text(sql).bindparams(*binds) if binds else text(sql)
        try:
            async with self._tx() as s:
                rows = (await s.execute(stmt, params)).all()
        except DataError as exc:  # e.g. query embedding of the wrong dimension
            raise ValueError(f"search rejected: {exc.orig}") from exc
        return [
            SearchHit(
                chunk_id=str(r.chunk_id),
                page_id=str(r.page_id),
                source_id=r.source_id,
                source_kind=r.source_kind,
                slug=r.slug,
                title=r.title,
                chunk_index=r.chunk_index,
                chunk_text=r.chunk_text,
                chunk_source=r.chunk_source,
                score=float(r.score),
                text_score=float(r.text_score),
                vector_score=float(r.vector_score),
                rank=i,
            )
            for i, r in enumerate(rows, start=1)
        ]

    # ------------------------------------------------------------------ timeline, tags, links
    async def add_timeline_entry(self, entry: TimelineEntry) -> TimelineEntry:
        T = TimelineEntryRow
        cols = _cols(T, TimelineEntry)
        async with self._tx() as s:
            # No target: absorbs the uq_timeline_dedup expression index (and an id clash).
            row = (
                await s.execute(
                    pg_insert(T).values(**_values(entry)).on_conflict_do_nothing().returning(*cols)
                )
            ).first()
            if row is None:
                row = (
                    await s.execute(
                        select(*cols).where(
                            T.page_id == entry.page_id,
                            T.date == entry.date,
                            T.summary == entry.summary,
                            T.source == entry.source,
                        )
                    )
                ).first() or (await s.execute(select(*cols).where(T.id == entry.id))).one()
        return _rec(TimelineEntry, row)

    async def list_timeline(self, page_id: str) -> list[TimelineEntry]:
        if not is_uuid(page_id):
            return []
        T = TimelineEntryRow
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(*_cols(T, TimelineEntry))
                    .where(T.page_id == page_id)
                    .order_by(T.date, T.created_at, T.id)
                )
            ).all()
        return [_rec(TimelineEntry, r) for r in rows]

    async def set_tags(self, page_id: str, tags: Sequence[str]) -> None:
        if not is_uuid(page_id):
            raise ValueError(f"page id {page_id!r} is not a UUID")
        unique = list(dict.fromkeys(tags))
        async with self._tx() as s:
            await s.execute(delete(TagRow).where(TagRow.page_id == page_id))
            if unique:
                await s.execute(
                    pg_insert(TagRow)
                    .values([{"page_id": page_id, "tag": tag} for tag in unique])
                    .on_conflict_do_nothing()
                )

    async def get_tags(self, page_id: str) -> list[str]:
        if not is_uuid(page_id):
            return []
        async with self._tx() as s:
            tags = (await s.execute(select(TagRow.tag).where(TagRow.page_id == page_id))).scalars()
            return sorted(tags)

    async def add_link(self, link: Link) -> Link:
        T = LinkRow
        cols = _cols(T, Link)
        async with self._tx() as s:
            row = (
                await s.execute(
                    pg_insert(T)
                    .values(**_values(link))
                    .on_conflict_do_nothing(
                        index_elements=[T.from_page_id, T.to_page_id, T.link_type]
                    )
                    .returning(*cols)
                )
            ).first()
            if row is None:
                row = (
                    await s.execute(
                        select(*cols).where(
                            T.from_page_id == link.from_page_id,
                            T.to_page_id == link.to_page_id,
                            T.link_type == link.link_type,
                        )
                    )
                ).one()
        return _rec(Link, row)

    async def list_links(self, page_id: str) -> list[Link]:
        if not is_uuid(page_id):
            return []
        T = LinkRow
        async with self._tx() as s:
            rows = (
                await s.execute(
                    select(*_cols(T, Link))
                    .where(T.from_page_id == page_id)
                    .order_by(T.created_at, T.id)
                )
            ).all()
        return [_rec(Link, r) for r in rows]

    # ------------------------------------------------------------------ ingest log
    async def log_ingest(self, entry: IngestLogEntry) -> IngestLogEntry:
        T = IngestLogRow
        async with self._tx() as s:
            row = (
                await s.execute(
                    pg_insert(T).values(**_values(entry)).returning(*_cols(T, IngestLogEntry))
                )
            ).one()
        return _rec(IngestLogEntry, row)

    async def list_ingest_log(
        self, *, source_id: str | None = None, limit: int = 50
    ) -> list[IngestLogEntry]:
        T = IngestLogRow
        stmt = select(*_cols(T, IngestLogEntry))
        if source_id is not None:
            stmt = stmt.where(T.source_id == source_id)
        stmt = stmt.order_by(T.created_at.desc(), T.id.desc()).limit(limit)
        async with self._tx() as s:
            rows = (await s.execute(stmt)).all()
        return [_rec(IngestLogEntry, r) for r in rows]

    # ------------------------------------------------------------------ uploads & counters
    async def record_upload(self, upload: UploadRecord) -> UploadRecord:
        T = UploadRow
        async with self._tx() as s:
            row = (
                await s.execute(
                    pg_insert(T).values(**_values(upload)).returning(*_cols(T, UploadRecord))
                )
            ).one()
        return _rec(UploadRecord, row)

    async def count_uploads_total(self) -> int:
        async with self._tx() as s:
            return int(await s.scalar(select(func.count()).select_from(UploadRow)) or 0)

    async def count_uploads_for_actor_today(self, actor_id: str, day: date) -> int:
        start, end = _day_bounds(day)
        stmt = (
            select(func.count())
            .select_from(UploadRow)
            .where(
                UploadRow.actor_id == actor_id,
                UploadRow.created_at >= start,
                UploadRow.created_at < end,
            )
        )
        async with self._tx() as s:
            return int(await s.scalar(stmt) or 0)

    async def increment_counter(
        self, day: date, key: str, n: int = 1, *, limit: int | None = None
    ) -> int | None:
        if limit is not None and n > limit:
            return None  # cannot fit even from zero: nothing changes
        T = UsageCounterRow
        # `excluded.count` is max(0, n) on a fresh row, so carry the signed delta separately.
        delta = bindparam("delta", n, type_=BigInteger)
        stmt = pg_insert(T).values(day=day, key=key, count=max(0, n))
        stmt = stmt.on_conflict_do_update(
            index_elements=[T.day, T.key],
            set_={"count": func.greatest(0, T.count + delta), "updated_at": func.now()},
            where=(T.count + delta <= limit) if limit is not None else None,
        ).returning(T.count)
        async with self._tx() as s:
            count = (await s.execute(stmt)).scalar_one_or_none()
        return int(count) if count is not None else None

    async def get_counter(self, day: date, key: str) -> int:
        stmt = select(UsageCounterRow.count).where(
            UsageCounterRow.day == day, UsageCounterRow.key == key
        )
        async with self._tx() as s:
            return int(await s.scalar(stmt) or 0)

    # ------------------------------------------------------------------ queries
    async def create_query(self, record: QueryRecord) -> QueryRecord:
        T = QueryRow
        async with self._tx() as s:
            row = (
                await s.execute(
                    pg_insert(T).values(**_values(record)).returning(*_cols(T, QueryRecord))
                )
            ).one()
        return _rec(QueryRecord, row)

    async def set_query_audit_event(self, query_id: str, audit_event_id: str) -> None:
        if not (is_uuid(query_id) and is_uuid(audit_event_id)):
            return
        async with self._tx() as s:
            await s.execute(
                update(QueryRow)
                .where(QueryRow.id == query_id)
                .values(audit_event_id=audit_event_id)
            )

    async def get_query(self, query_id: str) -> QueryRecord | None:
        if not is_uuid(query_id):
            return None
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_cols(QueryRow, QueryRecord)).where(QueryRow.id == query_id)
                )
            ).first()
        return _rec(QueryRecord, row) if row is not None else None

    async def list_queries(
        self, actor_id: str | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[QueryRecord]:
        stmt = select(*_cols(QueryRow, QueryRecord))
        if actor_id is not None:
            stmt = stmt.where(QueryRow.actor_id == actor_id)
        stmt = (
            stmt.order_by(QueryRow.created_at.desc(), QueryRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._tx() as s:
            rows = (await s.execute(stmt)).all()
        return [_rec(QueryRecord, r) for r in rows]

    # ------------------------------------------------------------------ audit (hash chain)
    async def append_audit_event(self, draft: AuditEventDraft) -> AuditEvent:
        if not is_uuid(draft.id):
            raise ValueError(f"audit event id {draft.id!r} is not a UUID")
        T = AuditEventRow
        async with self._tx() as s:
            await s.execute(text("SELECT pg_advisory_xact_lock(hashtext('audit_events'))"))
            prev_hash = await s.scalar(select(T.hash).order_by(T.seq.desc()).limit(1))
            seq = int(
                await s.scalar(
                    text("SELECT nextval(pg_get_serial_sequence('audit_events', 'seq'))")
                )
            )
            values = {
                **_values(draft),
                "seq": seq,
                "prev_hash": prev_hash,
                "hash": audit_event_hash(prev_hash, seq, draft.payload),
            }
            row = (await s.execute(pg_insert(T).values(**values).returning(*_AUDIT_COLS))).one()
        return _rec(AuditEvent, row)

    async def get_audit_event(self, event_id: str) -> AuditEvent | None:
        if not is_uuid(event_id):
            return None
        async with self._tx() as s:
            row = (
                await s.execute(select(*_AUDIT_COLS).where(AuditEventRow.id == event_id))
            ).first()
        return _rec(AuditEvent, row) if row is not None else None

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
        T = AuditEventRow
        stmt = select(*_AUDIT_COLS)
        if actor_id is not None:
            stmt = stmt.where(T.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(T.action == action)
        if subject_type is not None:
            stmt = stmt.where(T.subject_type == subject_type)
        if subject_id is not None:
            stmt = stmt.where(T.subject_id == subject_id)
        if document_id is not None:
            stmt = stmt.where(
                or_(
                    T.subject_id == document_id,
                    T.payload.contains({"retrieved_document_ids": [document_id]}),
                    T.payload.contains({"cited_document_ids": [document_id]}),
                    T.payload.contains({"document_id": document_id}),
                )
            )
        if since is not None:
            stmt = stmt.where(T.occurred_at >= since)
        stmt = stmt.order_by(T.seq.desc()).limit(limit).offset(offset)
        async with self._tx() as s:
            rows = (await s.execute(stmt)).all()
        return [_rec(AuditEvent, r) for r in rows]

    async def iter_audit_events(self) -> AsyncIterator[AuditEvent]:
        last_seq: int | None = None
        while True:
            stmt = select(*_AUDIT_COLS).order_by(AuditEventRow.seq).limit(_AUDIT_PAGE_SIZE)
            if last_seq is not None:
                stmt = stmt.where(AuditEventRow.seq > last_seq)
            async with self._tx() as s:
                rows = (await s.execute(stmt)).all()
            if not rows:
                return
            for row in rows:
                yield _rec(AuditEvent, row)
            last_seq = rows[-1].seq

    async def audit_head(self) -> AuditEvent | None:
        async with self._tx() as s:
            row = (
                await s.execute(select(*_AUDIT_COLS).order_by(AuditEventRow.seq.desc()).limit(1))
            ).first()
        return _rec(AuditEvent, row) if row is not None else None
