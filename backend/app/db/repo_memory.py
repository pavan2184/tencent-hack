"""`InMemoryRepo`: the dict-backed `Repo` used by tests and `REPO_BACKEND=memory`.

Implements every `Repo` method with the same semantics as the SQL repo, including a usable
hybrid `search_chunks` (content-token overlap ranking + cosine ranking, fused with RRF).
Single-process, asyncio-safe (no awaits inside critical sections), not thread-safe.
"""

from __future__ import annotations

import math
import re
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from typing import Any

from access_control import Principal

from app.db.repo import RRF_K, Repo, audit_event_hash
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
    utcnow,
)

_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further
    had has have having he her here hers herself him himself his how i if in into is it its itself
    just me more most my myself no nor not of off on once only or other our ours ourselves out over
    own same she should so some such than that the their theirs them themselves then there these
    they this those through to too under until up very was we were what when where which while who
    whom why will with would you your yours yourself yourselves""".split()
)


def search_tokens(text: str) -> list[str]:
    """Lowercased alphanumeric tokens without stopwords (the memory 'tsvector')."""
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _copy[T: Any](model: T | None) -> T | None:
    return None if model is None else model.model_copy(deep=True)  # type: ignore[attr-defined]


class InMemoryRepo(Repo):
    def __init__(self) -> None:
        self.principals: dict[str, Principal] = {}
        self.groups: dict[str, Group] = {}
        self.memberships: set[tuple[str, str]] = set()
        self.sources: dict[str, Source] = {}
        self.pages: dict[str, Page] = {}
        self.page_versions: list[PageVersion] = []
        self.chunks: dict[str, list[Chunk]] = {}
        self.timeline: list[TimelineEntry] = []
        self.tags: dict[str, set[str]] = {}
        self.links: list[Link] = []
        self.ingest_log: list[IngestLogEntry] = []
        self.uploads: list[UploadRecord] = []
        self.counters: dict[tuple[date, str], int] = {}
        self.queries: dict[str, QueryRecord] = {}
        self.audit_events: list[AuditEvent] = []

    # ------------------------------------------------------------------ principals & groups
    def _with_groups(self, principal: Principal) -> Principal:
        groups = sorted(g for p, g in self.memberships if p == principal.id)
        return principal.model_copy(update={"groups": groups}, deep=True)

    async def get_principal(self, principal_id: str) -> Principal | None:
        principal = self.principals.get(principal_id)
        return None if principal is None else self._with_groups(principal)

    async def list_principals(self) -> list[Principal]:
        return [self._with_groups(self.principals[k]) for k in sorted(self.principals)]

    async def upsert_principal(self, principal: Principal) -> Principal:
        self.principals[principal.id] = principal.model_copy(update={"groups": []}, deep=True)
        return self._with_groups(self.principals[principal.id])

    async def upsert_group(self, group: Group) -> Group:
        self.groups[group.id] = group.model_copy()
        return group.model_copy()

    async def list_groups(self) -> list[Group]:
        return [self.groups[k].model_copy() for k in sorted(self.groups)]

    async def add_membership(self, principal_id: str, group_id: str) -> None:
        if principal_id not in self.principals:
            raise ValueError(f"unknown principal {principal_id!r}")
        if group_id not in self.groups:
            raise ValueError(f"unknown group {group_id!r}")
        self.memberships.add((principal_id, group_id))

    async def set_memberships(self, principal_id: str, group_ids: Sequence[str]) -> None:
        self.memberships = {(p, g) for p, g in self.memberships if p != principal_id}
        for group_id in group_ids:
            await self.add_membership(principal_id, group_id)

    # ------------------------------------------------------------------ sources
    async def get_source(self, source_id: str) -> Source | None:
        return _copy(self.sources.get(source_id))

    async def list_sources(self, *, include_archived: bool = False) -> list[Source]:
        return [
            self.sources[k].model_copy(deep=True)
            for k in sorted(self.sources)
            if include_archived or not self.sources[k].archived
        ]

    async def upsert_source(self, source: Source) -> Source:
        existing = self.sources.get(source.id)
        now = utcnow()
        if existing is not None:
            stored = source.model_copy(
                update={
                    "created_at": existing.created_at,
                    "last_sync_at": existing.last_sync_at,
                    "newest_content_at": existing.newest_content_at,
                    "updated_at": now,
                },
                deep=True,
            )
        else:
            stored = source.model_copy(update={"created_at": now, "updated_at": now}, deep=True)
        self.sources[source.id] = stored
        return stored.model_copy(deep=True)

    async def touch_source_sync(
        self,
        source_id: str,
        last_sync_at: datetime,
        newest_content_at: datetime | None = None,
    ) -> None:
        source = self.sources.get(source_id)
        if source is None:
            return
        newest = source.newest_content_at
        if newest_content_at is not None and (newest is None or newest_content_at > newest):
            newest = newest_content_at
        self.sources[source_id] = source.model_copy(
            update={"last_sync_at": last_sync_at, "newest_content_at": newest}
        )

    async def count_pages(self, source_id: str, *, include_deleted: bool = False) -> int:
        return sum(
            1
            for p in self.pages.values()
            if p.source_id == source_id and (include_deleted or p.deleted_at is None)
        )

    # ------------------------------------------------------------------ pages
    async def get_page(self, page_id: str) -> Page | None:
        return _copy(self.pages.get(str(page_id)))

    async def get_pages(self, page_ids: Sequence[str]) -> dict[str, Page]:
        return {pid: self.pages[pid].model_copy(deep=True) for pid in page_ids if pid in self.pages}

    async def get_page_by_slug(self, source_id: str, slug: str) -> Page | None:
        for page in self.pages.values():
            if page.source_id == source_id and page.slug == slug:
                return page.model_copy(deep=True)
        return None

    async def get_page_by_external_id(self, source_id: str, external_object_id: str) -> Page | None:
        for page in self.pages.values():
            if page.source_id == source_id and page.external_object_id == external_object_id:
                return page.model_copy(deep=True)
        return None

    async def list_pages(
        self,
        *,
        source_ids: Sequence[str] | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Page]:
        wanted = set(source_ids) if source_ids is not None else None
        needle = (q or "").strip().lower()
        words = search_tokens(needle)
        out: list[Page] = []
        for page in self.pages.values():
            if wanted is not None and page.source_id not in wanted:
                continue
            if page.deleted_at is not None and not include_deleted:
                continue
            if needle:
                hay = f"{page.title}\n{page.slug}\n{page.compiled_truth}".lower()
                if needle not in hay and not (words and all(w in hay for w in words)):
                    continue
            out.append(page)
        out.sort(key=lambda p: (-p.updated_at.timestamp(), p.id))
        return [p.model_copy(deep=True) for p in out[offset : offset + limit]]

    async def upsert_page(self, page: Page) -> Page:
        existing = None
        if page.external_object_id:
            existing = next(
                (
                    p
                    for p in self.pages.values()
                    if p.source_id == page.source_id
                    and p.external_object_id == page.external_object_id
                ),
                None,
            )
        if existing is None:
            existing = next(
                (
                    p
                    for p in self.pages.values()
                    if p.source_id == page.source_id and p.slug == page.slug
                ),
                None,
            )
        now = utcnow()
        if existing is not None:
            stored = page.model_copy(
                update={"id": existing.id, "created_at": existing.created_at, "updated_at": now},
                deep=True,
            )
        else:
            stored = page.model_copy(update={"created_at": now, "updated_at": now}, deep=True)
        self.pages[stored.id] = stored
        return stored.model_copy(deep=True)

    async def mark_page_deleted(self, page_id: str, *, at: datetime | None = None) -> Page | None:
        page = self.pages.get(page_id)
        if page is None:
            return None
        stored = page.model_copy(update={"deleted_at": at or utcnow(), "updated_at": utcnow()})
        self.pages[page_id] = stored
        self.chunks.pop(page_id, None)
        return stored.model_copy(deep=True)

    async def update_page_fields(self, page_id: str, **fields: Any) -> Page | None:
        bad = (set(fields) - set(Page.model_fields)) | ({"id"} & set(fields))
        if bad:
            raise ValueError(f"cannot update page fields: {sorted(bad)}")
        page = self.pages.get(page_id)
        if page is None:
            return None
        stored = Page.model_validate({**page.model_dump(), **fields, "updated_at": utcnow()})
        self.pages[page_id] = stored
        return stored.model_copy(deep=True)

    async def set_ingest_status(self, page_id: str, status: str) -> None:
        page = self.pages.get(page_id)
        if page is not None:
            self.pages[page_id] = page.model_copy(update={"ingest_status": status})

    async def add_page_version(self, version: PageVersion) -> PageVersion:
        self.page_versions.append(version.model_copy(deep=True))
        return version.model_copy(deep=True)

    async def list_page_versions(self, page_id: str) -> list[PageVersion]:
        rows = [v for v in self.page_versions if v.page_id == page_id]
        rows.sort(key=lambda v: v.snapshot_at, reverse=True)
        return [v.model_copy(deep=True) for v in rows]

    # ------------------------------------------------------------------ chunks & search
    async def replace_chunks(self, page_id: str, chunks: Sequence[Chunk]) -> int:
        self.chunks[page_id] = [c.model_copy(deep=True) for c in chunks]
        if not chunks:
            self.chunks.pop(page_id, None)
        return len(chunks)

    async def list_chunks(self, page_id: str) -> list[Chunk]:
        rows = sorted(self.chunks.get(page_id, []), key=lambda c: c.chunk_index)
        return [c.model_copy(deep=True) for c in rows]

    async def search_chunks(
        self,
        query: str,
        embedding: Sequence[float] | None,
        *,
        limit: int,
        source_ids: Sequence[str] | None = None,
    ) -> list[SearchHit]:
        if limit <= 0:
            return []
        wanted = set(source_ids) if source_ids is not None else None
        q_tokens = set(search_tokens(query))
        candidates: list[tuple[Page, Chunk]] = []
        for page_id, chunks in self.chunks.items():
            page = self.pages.get(page_id)
            if page is None or page.deleted_at is not None:
                continue
            if wanted is not None and page.source_id not in wanted:
                continue
            candidates.extend((page, c) for c in chunks)

        text_scores: dict[str, float] = {}
        for _page, chunk in candidates:
            toks = search_tokens(chunk.chunk_text)
            if not toks or not q_tokens:
                continue
            matched = q_tokens & set(toks)
            if not matched:
                continue
            tf = sum(1 for t in toks if t in matched)
            text_scores[chunk.id] = len(matched) + tf / (len(toks) + 10.0)

        vector_scores: dict[str, float] = {}
        if embedding is not None:
            for _, chunk in candidates:
                if chunk.embedding is not None:
                    vector_scores[chunk.id] = _cosine(embedding, chunk.embedding)

        text_rank = {
            cid: i + 1
            for i, cid in enumerate(sorted(text_scores, key=lambda c: (-text_scores[c], c)))
        }
        vector_order = sorted(vector_scores, key=lambda c: (-vector_scores[c], c))[:limit]
        vector_rank = {cid: i + 1 for i, cid in enumerate(vector_order)}

        fused: list[tuple[float, Page, Chunk]] = []
        for page, chunk in candidates:
            score = 0.0
            if chunk.id in text_rank:
                score += 1.0 / (RRF_K + text_rank[chunk.id])
            if chunk.id in vector_rank:
                score += 1.0 / (RRF_K + vector_rank[chunk.id])
            if score > 0.0:
                fused.append((score, page, chunk))
        fused.sort(key=lambda item: (-item[0], item[2].id))
        hits: list[SearchHit] = []
        for rank, (score, page, chunk) in enumerate(fused[:limit], start=1):
            hits.append(
                SearchHit(
                    chunk_id=chunk.id,
                    page_id=page.id,
                    source_id=page.source_id,
                    source_kind=page.source_kind,
                    slug=page.slug,
                    title=page.title,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.chunk_text,
                    chunk_source=chunk.chunk_source,
                    score=score,
                    text_score=text_scores.get(chunk.id, 0.0),
                    vector_score=vector_scores.get(chunk.id, 0.0),
                    rank=rank,
                )
            )
        return hits

    # ------------------------------------------------------------------ timeline, tags, links
    async def add_timeline_entry(self, entry: TimelineEntry) -> TimelineEntry:
        for existing in self.timeline:
            if (
                existing.page_id == entry.page_id
                and existing.date == entry.date
                and existing.summary == entry.summary
                and existing.source == entry.source
            ):
                return existing.model_copy()
        self.timeline.append(entry.model_copy())
        return entry.model_copy()

    async def list_timeline(self, page_id: str) -> list[TimelineEntry]:
        rows = [e for e in self.timeline if e.page_id == page_id]
        rows.sort(key=lambda e: (e.date, e.created_at))
        return [e.model_copy() for e in rows]

    async def set_tags(self, page_id: str, tags: Sequence[str]) -> None:
        self.tags[page_id] = {str(t) for t in tags}

    async def get_tags(self, page_id: str) -> list[str]:
        return sorted(self.tags.get(page_id, set()))

    async def add_link(self, link: Link) -> Link:
        for existing in self.links:
            if (existing.from_page_id, existing.to_page_id, existing.link_type) == (
                link.from_page_id,
                link.to_page_id,
                link.link_type,
            ):
                return existing.model_copy()
        self.links.append(link.model_copy())
        return link.model_copy()

    async def list_links(self, page_id: str) -> list[Link]:
        return [lk.model_copy() for lk in self.links if lk.from_page_id == page_id]

    # ------------------------------------------------------------------ ingest log
    async def log_ingest(self, entry: IngestLogEntry) -> IngestLogEntry:
        self.ingest_log.append(entry.model_copy(deep=True))
        return entry.model_copy(deep=True)

    async def list_ingest_log(
        self, *, source_id: str | None = None, limit: int = 50
    ) -> list[IngestLogEntry]:
        rows = [e for e in self.ingest_log if source_id is None or e.source_id == source_id]
        rows.sort(key=lambda e: e.created_at, reverse=True)
        return [e.model_copy(deep=True) for e in rows[:limit]]

    # ------------------------------------------------------------------ uploads & counters
    async def record_upload(self, upload: UploadRecord) -> UploadRecord:
        self.uploads.append(upload.model_copy())
        return upload.model_copy()

    async def count_uploads_total(self) -> int:
        return len(self.uploads)

    async def count_uploads_for_actor_today(self, actor_id: str, day: date) -> int:
        return sum(
            1
            for u in self.uploads
            if u.actor_id == actor_id and u.created_at.astimezone(UTC).date() == day
        )

    async def increment_counter(
        self, day: date, key: str, n: int = 1, *, limit: int | None = None
    ) -> int | None:
        current = self.counters.get((day, key), 0)
        new = current + n
        if limit is not None and new > limit:
            return None
        self.counters[(day, key)] = max(0, new)
        return self.counters[(day, key)]

    async def get_counter(self, day: date, key: str) -> int:
        return self.counters.get((day, key), 0)

    # ------------------------------------------------------------------ queries
    async def create_query(self, record: QueryRecord) -> QueryRecord:
        self.queries[record.id] = record.model_copy(deep=True)
        return record.model_copy(deep=True)

    async def set_query_audit_event(self, query_id: str, audit_event_id: str) -> None:
        record = self.queries.get(query_id)
        if record is not None:
            self.queries[query_id] = record.model_copy(update={"audit_event_id": audit_event_id})

    async def get_query(self, query_id: str) -> QueryRecord | None:
        return _copy(self.queries.get(str(query_id)))

    async def list_queries(
        self, actor_id: str | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[QueryRecord]:
        rows = [q for q in self.queries.values() if actor_id is None or q.actor_id == actor_id]
        rows.sort(key=lambda q: (q.created_at, q.id), reverse=True)
        return [q.model_copy(deep=True) for q in rows[offset : offset + limit]]

    # ------------------------------------------------------------------ audit (hash chain)
    async def append_audit_event(self, draft: AuditEventDraft) -> AuditEvent:
        head = self.audit_events[-1] if self.audit_events else None
        seq = (head.seq + 1) if head is not None else 1
        prev_hash = head.hash if head is not None else None
        event = AuditEvent(
            **draft.model_dump(),
            seq=seq,
            prev_hash=prev_hash,
            hash=audit_event_hash(prev_hash, seq, draft.payload),
        )
        self.audit_events.append(event)
        return event.model_copy(deep=True)

    async def get_audit_event(self, event_id: str) -> AuditEvent | None:
        for event in self.audit_events:
            if event.id == event_id:
                return event.model_copy(deep=True)
        return None

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
        def matches(e: AuditEvent) -> bool:
            if actor_id is not None and e.actor_id != actor_id:
                return False
            if action is not None and e.action != action:
                return False
            if subject_type is not None and e.subject_type != subject_type:
                return False
            if subject_id is not None and e.subject_id != subject_id:
                return False
            if since is not None and e.occurred_at < since:
                return False
            if document_id is not None:
                payload = e.payload
                mentioned = (
                    e.subject_id == document_id
                    or payload.get("document_id") == document_id
                    or document_id in (payload.get("retrieved_document_ids") or [])
                    or document_id in (payload.get("cited_document_ids") or [])
                )
                if not mentioned:
                    return False
            return True

        rows = [e for e in reversed(self.audit_events) if matches(e)]
        return [e.model_copy(deep=True) for e in rows[offset : offset + limit]]

    async def iter_audit_events(self) -> AsyncIterator[AuditEvent]:  # type: ignore[override]
        for event in list(self.audit_events):
            yield event.model_copy(deep=True)

    async def audit_head(self) -> AuditEvent | None:
        return _copy(self.audit_events[-1]) if self.audit_events else None


__all__ = ["STOPWORDS", "InMemoryRepo", "search_tokens"]
