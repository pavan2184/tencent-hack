"""Opt-in integration test for the SQL layer against a live Postgres (pgvector).

Skipped unless `DATABASE_URL` is set in the environment. Use a THROWAWAY database: the test applies
the migrations and leaves its rows behind (audit events cannot be deleted). Every test uses fresh
random ids, so re-running against the same database is safe.

    docker run --rm -d --name pg-it -p 55433:5432 -e POSTGRES_USER=brain \
        -e POSTGRES_PASSWORD=brain -e POSTGRES_DB=brain pgvector/pgvector:pg16
    DATABASE_URL=postgresql+psycopg://brain:brain@localhost:55433/brain \
        uv run pytest -q app/tests/test_sql_integration.py -m integration
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from access_control import (
    AccessControlError,
    AccessRequest,
    AccessRequestNotFound,
    AccessRequestStatus,
    AccessRequestStore,
    Effect,
    Grant,
    GrantNotFound,
    GrantStore,
    PermissionSnapshotStore,
    Principal,
    PrincipalDirectory,
    SourceKind,
    SourcePermissions,
    SubjectType,
)
from freshness import (
    ChangeKind,
    ChangePage,
    ConnectorCheckpoint,
    ConnectorKind,
    ConnectorSyncRequest,
    CursorConflict,
    EventState,
    EvidenceClass,
    EvidenceRef,
    FailureAction,
    FreshnessError,
    FreshnessPolicy,
    FreshnessService,
    FreshnessStatus,
    FreshnessStore,
    IndexOutcome,
    ListChangeSource,
    NormalizedChange,
    ObjectFreshness,
    PolicyStatus,
    ReceiptConflict,
    ReceiptRequest,
    RunStatus,
    SourceChangeEvent,
    SyncPath,
    SyncRun,
    VersionRegression,
    verify_receipt_hash,
)
from freshness.receipt import build_receipt, request_payload_hash
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.access_stores import (
    SqlAccessRequestStore,
    SqlGrantStore,
    SqlPermissionSnapshotStore,
    SqlPrincipalDirectory,
)
from app.adapters.freshness_store import SqlFreshnessStore
from app.config import settings
from app.db.migrate import run_migrations, to_psycopg_dsn
from app.db.models import Base
from app.db.repo import audit_event_hash
from app.db.repo_sql import SqlRepo
from app.db.session import make_engine, make_session_factory
from app.schemas.domain import AuditEventDraft, Chunk, Group, Page, Source

_DB_URL = os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DB_URL, reason="needs a live Postgres: set DATABASE_URL"),
]

DIM = settings.EMBEDDING_DIM


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid4().hex[:10]}"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _onehot(i: int) -> list[float]:
    vec = [0.0] * DIM
    vec[i % DIM] = 1.0
    return vec


@pytest.fixture(scope="module")
def migrated() -> list[tuple[str, str]]:
    assert _DB_URL is not None
    return run_migrations(_DB_URL, embedding_dim=DIM, out=lambda _line: None)


@pytest.fixture
async def sf(migrated: list[tuple[str, str]]) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine(_DB_URL, pool_size=3)
    try:
        yield make_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def repo(sf: async_sessionmaker[AsyncSession]) -> SqlRepo:
    return SqlRepo(sf)


async def _source(repo: SqlRepo, kind: SourceKind = SourceKind.confluence) -> Source:
    sid = _uid("src-")
    return await repo.upsert_source(Source(id=sid, name=sid, kind=kind))


async def _page(repo: SqlRepo, source: Source, **fields: object) -> Page:
    slug = str(fields.pop("slug", _uid("page-")))
    return await repo.upsert_page(
        Page(
            source_id=source.id,
            slug=slug,
            title=str(fields.pop("title", slug)),
            source_kind=source.kind,
            **fields,  # type: ignore[arg-type]
        )
    )


# ---------------------------------------------------------------------------------- migrations


def test_migrations_create_every_model_table(migrated: list[tuple[str, str]]) -> None:
    assert _DB_URL is not None
    again = run_migrations(_DB_URL, embedding_dim=DIM, out=lambda _line: None)
    assert again and all(status == "skipped" for _, status in again)
    with psycopg.connect(to_psycopg_dsn(_DB_URL)) as conn:
        rows = conn.execute(
            "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        ).fetchall()
        dims = conn.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'content_chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
    db: dict[str, dict[str, bool]] = {}
    for table, column, nullable in rows:
        db.setdefault(table, {})[column] = nullable == "YES"
    for table in Base.metadata.sorted_tables:
        assert table.name in db, f"table {table.name} missing after migrating"
        assert set(db[table.name]) == {c.name for c in table.columns}, table.name
        for column in table.columns:
            assert db[table.name][column.name] == column.nullable, f"{table.name}.{column.name}"
    assert dims == (f"vector({DIM})",)


async def test_check_db_and_protocols(sf: async_sessionmaker[AsyncSession]) -> None:
    from app.db import session as session_mod

    assert await session_mod.check_db() is True
    await session_mod.dispose_engine()
    assert isinstance(SqlFreshnessStore(sf), FreshnessStore)
    assert isinstance(SqlGrantStore(sf), GrantStore)
    assert isinstance(SqlPermissionSnapshotStore(sf), PermissionSnapshotStore)
    assert isinstance(SqlPrincipalDirectory(sf), PrincipalDirectory)
    assert isinstance(SqlAccessRequestStore(sf), AccessRequestStore)


# ---------------------------------------------------------------------------------- principals


async def test_principal_round_trip(repo: SqlRepo, sf: async_sessionmaker[AsyncSession]) -> None:
    g1, g2 = _uid("grp-b-"), _uid("grp-a-")
    await repo.upsert_group(Group(id=g1, name="B"))
    await repo.upsert_group(Group(id=g2, name="A"))
    pid = _uid("person.")
    stored = await repo.upsert_principal(
        Principal(
            id=pid,
            display_name="Person",
            email="p@example.test",
            roles=["employee", "manager"],
            groups=["ignored-by-upsert"],
            external_identities={"slack": "U_P"},
        )
    )
    assert stored.groups == []
    await repo.set_memberships(pid, [g1, g2])
    got = await repo.get_principal(pid)
    assert got is not None
    assert got.groups == sorted([g1, g2])
    assert got.roles == ["employee", "manager"]
    assert got.external_identities == {"slack": "U_P"}
    assert got.is_active

    await repo.upsert_principal(got.model_copy(update={"is_active": False}))
    directory = SqlPrincipalDirectory(sf)
    inactive = await directory.get(pid)
    assert inactive is not None and inactive.is_active is False
    assert inactive.groups == sorted([g1, g2])
    assert await directory.groups_of(pid) == sorted([g1, g2])
    assert await directory.groups_of("nobody-" + _uid()) == []
    assert await directory.get("nobody-" + _uid()) is None
    assert pid in {p.id for p in await directory.list()}

    await repo.set_memberships(pid, [g2])
    assert (await repo.get_principal(pid)).groups == [g2]  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        await repo.add_membership(pid, "missing-" + _uid())


# ---------------------------------------------------------------------------- pages and search


async def test_pages_chunks_and_hybrid_search(repo: SqlRepo) -> None:
    source = await _source(repo, SourceKind.gdrive)
    assert (await repo.get_source(source.id)).kind is SourceKind.gdrive  # type: ignore[union-attr]

    runbook = await _page(
        repo,
        source,
        title="Payment rail failover runbook",
        compiled_truth="Switch the payment rail to the secondary processor during an outage.",
        external_object_id=_uid("ext-"),
    )
    other = await _page(
        repo, source, title="Expense policy", compiled_truth="Meals are reimbursed up to $40."
    )
    assert (
        await repo.replace_chunks(
            runbook.id,
            [
                Chunk(
                    page_id=runbook.id,
                    chunk_index=0,
                    chunk_text="Failover: switch the payment rail to the secondary processor.",
                    embedding=_onehot(1),
                ),
                Chunk(
                    page_id=runbook.id, chunk_index=1, chunk_text="Escalate to treasury on-call."
                ),
            ],
        )
        == 2
    )
    await repo.replace_chunks(
        other.id,
        [
            Chunk(
                page_id=other.id,
                chunk_index=0,
                chunk_text="Meals are reimbursed up to $40 per day.",
                embedding=_onehot(2),
            )
        ],
    )
    chunks = await repo.list_chunks(runbook.id)
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert chunks[0].embedding == _onehot(1) and chunks[1].embedding is None

    # Keyword only: a natural-language question matches on ANY content word.
    hits = await repo.search_chunks(
        "What is the failover procedure for the payment rail?",
        None,
        limit=5,
        source_ids=[source.id],
    )
    assert hits and hits[0].page_id == runbook.id
    assert hits[0].rank == 1 and hits[0].text_score > 0
    assert hits[0].source_kind is SourceKind.gdrive
    assert all(h.page_id != other.id for h in hits)

    # Hybrid: the vector side pulls in the expense chunk too; the keyword hit stays first.
    hybrid = await repo.search_chunks(
        "payment rail failover", _onehot(1), limit=5, source_ids=[source.id]
    )
    assert hybrid[0].page_id == runbook.id and hybrid[0].vector_score == pytest.approx(1.0)
    assert {h.page_id for h in hybrid} == {runbook.id, other.id}
    assert [h.rank for h in hybrid] == list(range(1, len(hybrid) + 1))
    assert hybrid == sorted(hybrid, key=lambda h: -h.score)
    assert await repo.search_chunks("payment", None, limit=5, source_ids=[]) == []

    # Upsert by (source_id, slug) keeps id + created_at; provider identity wins over slug.
    again = await repo.upsert_page(
        Page(
            source_id=source.id,
            slug=runbook.slug,
            title="Payment rail failover runbook v2",
            source_kind=source.kind,
            external_object_id=runbook.external_object_id,
        )
    )
    assert again.id == runbook.id and again.created_at == runbook.created_at
    renamed = await repo.upsert_page(
        Page(
            source_id=source.id,
            slug=_uid("renamed-"),
            title="Renamed",
            source_kind=source.kind,
            external_object_id=runbook.external_object_id,
        )
    )
    assert renamed.id == runbook.id
    assert (
        await repo.get_page_by_external_id(source.id, runbook.external_object_id)
    ).id == runbook.id  # type: ignore[arg-type,union-attr]

    assert await repo.get_page("not-a-uuid") is None
    assert set(await repo.get_pages([runbook.id, other.id, "junk"])) == {runbook.id, other.id}
    listed = await repo.list_pages(source_ids=[source.id], q="expense")
    assert [p.id for p in listed] == [other.id]
    assert await repo.count_pages(source.id) == 2

    patched = await repo.update_page_fields(other.id, classification="confidential")
    assert patched is not None and patched.classification.value == "confidential"
    with pytest.raises(ValueError):
        await repo.update_page_fields(other.id, nope=1)

    deleted = await repo.mark_page_deleted(runbook.id)
    assert deleted is not None and deleted.deleted_at is not None
    assert await repo.list_chunks(runbook.id) == []
    after = await repo.search_chunks("payment rail failover", None, limit=5, source_ids=[source.id])
    assert all(h.page_id != runbook.id for h in after)
    assert await repo.count_pages(source.id) == 1


# ------------------------------------------------------------------------------- audit chain


async def test_audit_chain_appends_and_verifies(repo: SqlRepo, sf: async_sessionmaker) -> None:
    doc = str(uuid4())
    appended = []
    for i in range(3):
        appended.append(
            await repo.append_audit_event(
                AuditEventDraft(
                    actor_id="sam.lee",
                    action="ask",
                    subject_type="query",
                    subject_id=str(uuid4()),
                    payload={"i": i, "retrieved_document_ids": [doc], "score": 0.25 * i},
                )
            )
        )
    # Concurrent appends (separate connections) must still serialise into one chain.
    others = [SqlRepo(sf) for _ in range(4)]
    await asyncio.gather(
        *(
            r.append_audit_event(AuditEventDraft(action="probe", payload={"n": n}))
            for n, r in enumerate(others)
        )
    )
    seqs = [e.seq for e in appended]
    assert seqs == sorted(seqs)
    for prev, cur in zip(appended, appended[1:], strict=False):
        assert cur.prev_hash == prev.hash
    assert appended[0].hash == audit_event_hash(appended[0].prev_hash, seqs[0], appended[0].payload)

    previous_hash: str | None = None
    count = 0
    async for event in repo.iter_audit_events():
        assert event.prev_hash == previous_hash, f"chain broken at seq {event.seq}"
        assert event.hash == audit_event_hash(event.prev_hash, event.seq, event.payload)
        previous_hash = event.hash
        count += 1
    assert count >= 7
    head = await repo.audit_head()
    assert head is not None and head.hash == previous_hash

    by_doc = await repo.list_audit_events(document_id=doc)
    assert [e.id for e in by_doc] == [e.id for e in reversed(appended)]
    assert (await repo.get_audit_event(appended[1].id)) == appended[1]
    assert await repo.get_audit_event("nope") is None


# ---------------------------------------------------------------------------- usage counters


async def test_usage_counters(repo: SqlRepo) -> None:
    key, day = _uid("uploads:"), date(2026, 10, 12)
    assert await repo.increment_counter(day, key) == 1
    assert await repo.increment_counter(day, key, 2) == 3
    assert await repo.increment_counter(day, key, 1, limit=3) is None
    assert await repo.get_counter(day, key) == 3
    assert await repo.increment_counter(day, key, 1, limit=4) == 4
    assert await repo.increment_counter(day, _uid("fresh:"), 5, limit=4) is None
    assert await repo.get_counter(day, _uid("absent:")) == 0


# ---------------------------------------------------------------------------- freshness store


def _policy(kind: ConnectorKind, cls: EvidenceClass, pid: str, version: int = 1) -> FreshnessPolicy:
    return FreshnessPolicy(
        policy_id=pid,
        schema_version=version,
        connector_kind=kind,
        evidence_class=cls,
        max_index_age_seconds=3600,
        max_verification_age_seconds=300,
        failure_action=FailureAction.omit,
        status=PolicyStatus.active,
        effective_at=_now() - timedelta(minutes=5),
    )


async def test_freshness_store_semantics(repo: SqlRepo, sf: async_sessionmaker) -> None:
    store = SqlFreshnessStore(sf)
    source = await _source(repo)
    kind = ConnectorKind.confluence

    # --- checkpoint CAS
    cp = ConnectorCheckpoint(source_id=source.id, connector_kind=kind, cursor_value="c1")
    first = await store.cas_checkpoint(cp, expected_version=0)
    assert first.cursor_version == 1 and first.created_at is not None
    with pytest.raises(CursorConflict):
        await store.cas_checkpoint(cp.evolve(cursor_value="c2"), expected_version=0)
    assert (await store.get_checkpoint(source.id, cp.scope_key)).cursor_value == "c1"  # type: ignore[union-attr]
    second = await store.cas_checkpoint(first.evolve(cursor_value="c2"), expected_version=1)
    assert second.cursor_version == 2 and second.cursor_value == "c2"

    # --- runs: idempotent create; a non-completed run never stamps success
    now = _now()
    run = SyncRun(
        id=str(uuid4()),
        idempotency_key="k1",
        source_id=source.id,
        connector_kind=kind,
        trigger_kind=SyncPath.delta,
        started_at=now,
        status=RunStatus.running,
    )
    assert (await store.create_run(run)) == run
    replay = await store.create_run(run.evolve(id=str(uuid4())))
    assert replay.id == run.id
    with pytest.raises(FreshnessError):
        await store.cas_checkpoint(second.evolve(last_successful_run_id=run.id), expected_version=2)
    done = await store.update_run(run.evolve(status=RunStatus.completed, completed_at=now))
    assert done.status is RunStatus.completed and (await store.get_run(run.id)) == done
    stamped = await store.cas_checkpoint(
        second.evolve(last_successful_run_id=run.id), expected_version=2
    )
    assert stamped.last_successful_run_id == run.id

    # --- events: duplicate returns the existing row; applied is terminal
    event = SourceChangeEvent(
        id=str(uuid4()),
        source_id=source.id,
        connector_kind=kind,
        provider_event_id="evt-1",
        external_object_id="page-1",
        change_kind=ChangeKind.upsert,
        provider_version="2",
        observed_at=now,
        accepted_at=now,
        payload_hash="h",
    )
    accepted = await store.accept_event(event)
    assert accepted == event
    duplicate = await store.accept_event(event.evolve(id=str(uuid4()), payload_hash="other"))
    assert duplicate.id == event.id and duplicate.payload_hash == "h"
    applied = await store.update_event_state(
        event.evolve(state=EventState.applied, applied_at=now, attempt_count=1)
    )
    assert applied.state is EventState.applied
    assert await store.update_event_state(applied) == applied  # identical re-write is a no-op
    with pytest.raises(FreshnessError):
        await store.update_event_state(applied.evolve(noop_reason="late"))
    with pytest.raises(FreshnessError):
        await store.update_event_state(event.evolve(id=str(uuid4())))
    listed = await store.list_events(source.id, states=[EventState.applied])
    assert [e.id for e in listed] == [event.id]

    # --- objects: older comparable versions never overwrite newer state
    obj = ObjectFreshness(
        source_id=source.id,
        external_object_id="page-1",
        connector_kind=kind,
        provider_version="2",
        observed_at=now,
        indexed_at=now,
        searchable_at=now,
        sync_path=SyncPath.delta,
        freshness_status=FreshnessStatus.fresh,
        last_run_id=run.id,
    )
    stored = await store.upsert_object(obj)
    assert stored.created_at is not None and stored.provider_version == "2"
    with pytest.raises(VersionRegression):
        await store.upsert_object(obj.evolve(provider_version="1"))
    assert (await store.get_object(source.id, "page-1")).provider_version == "2"  # type: ignore[union-attr]
    newer = await store.upsert_object(obj.evolve(provider_version="3"))
    assert newer.provider_version == "3" and newer.created_at == stored.created_at
    assert [o.external_object_id for o in await store.list_objects(source.id)] == ["page-1"]
    assert await store.list_objects(source.id, statuses=[FreshnessStatus.stale]) == []

    # --- policies: one active per (kind, class)
    p1 = await store.put_policy(_policy(kind, EvidenceClass.critical, _uid("pol-")))
    assert await store.put_policy(p1) == p1  # idempotent re-put
    p2 = await store.put_policy(_policy(kind, EvidenceClass.critical, _uid("pol-")))
    active = await store.get_active_policy(kind, EvidenceClass.critical)
    assert active == p2

    # --- receipts: replay returns the original; a different request is a conflict
    request = ReceiptRequest(
        request_key=_uid("q-"),
        evidence=[
            EvidenceRef(source_id=source.id, external_object_id="page-1", connector_kind=kind)
        ],
    )
    service = FreshnessService(store, _FixedClock(now))
    receipt = await service.freshness_receipt(request)
    assert verify_receipt_hash(receipt)
    fetched = await store.get_receipt(receipt.receipt_id)
    assert fetched == receipt and verify_receipt_hash(fetched)
    assert await store.get_receipt_by_request_key(request.request_key) == receipt
    rebuilt = build_receipt(
        request=request,
        request_hash=request_payload_hash(request),
        items=list(receipt.evidence_items),
        receipt_id=str(uuid4()),
        created_at=now + timedelta(seconds=30),
    )
    assert (await store.save_receipt(rebuilt)).receipt_id == receipt.receipt_id
    conflicting = build_receipt(
        request=request,
        request_hash="different",
        items=list(receipt.evidence_items),
        receipt_id=str(uuid4()),
        created_at=now,
    )
    with pytest.raises(ReceiptConflict):
        await store.save_receipt(conflicting)
    assert await store.get_receipt("nope") is None


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


async def test_connector_sync_end_to_end(repo: SqlRepo, sf: async_sessionmaker) -> None:
    store = SqlFreshnessStore(sf)
    source = await _source(repo)
    kind = ConnectorKind.confluence
    now = _now()
    page = await _page(repo, source, external_object_id="doc-9")

    async def apply(change: NormalizedChange) -> IndexOutcome:
        return IndexOutcome(
            content_written=True,
            searchable=True,
            embedded=True,
            indexed_at=now,
            searchable_at=now,
            page_id=page.id,
            page_slug=page.slug,
        )

    feed = ListChangeSource(
        [
            ChangePage(
                changes=[
                    NormalizedChange(
                        source_id=source.id,
                        connector_kind=kind,
                        provider_event_id="",
                        external_object_id="doc-9",
                        change_kind=ChangeKind.upsert,
                        provider_version="7",
                        observed_at=now,
                    )
                ],
                next_cursor="cursor-1",
            )
        ]
    )
    service = FreshnessService(store, _FixedClock(now))
    req = ConnectorSyncRequest(
        source_id=source.id, connector_kind=kind, trigger_kind=SyncPath.delta, idempotency_key="i1"
    )
    result = await service.connector_sync(req, change_source=feed, apply=apply)
    assert result.status is RunStatus.completed and result.applied_count == 1
    obj = await store.get_object(source.id, "doc-9")
    assert obj is not None and obj.freshness_status is FreshnessStatus.fresh
    assert obj.page_id == page.id and obj.provider_version == "7"
    checkpoint = await store.get_checkpoint(source.id, req.scope_key)
    assert checkpoint is not None and checkpoint.last_successful_run_id == result.run_id

    replay = await service.connector_sync(req, change_source=feed, apply=apply)
    assert replay.run_id == result.run_id and replay.replayed


# ------------------------------------------------------------------------------ access stores


async def test_grant_store(repo: SqlRepo, sf: async_sessionmaker) -> None:
    grants = SqlGrantStore(sf)
    source = await _source(repo)
    doc = await _page(repo, source)
    now = _now()
    grant = Grant(
        document_id=doc.id,
        subject_type=SubjectType.group,
        subject_id="leadership",
        effect=Effect.allow,
        granted_by="system:seed",
        granted_at=now,
    )
    assert await grants.add(grant) == grant
    with pytest.raises(AccessControlError):
        await grants.add(grant)  # duplicate id
    with pytest.raises(AccessControlError):
        await grants.add(grant.model_copy(update={"id": str(uuid4())}))  # second active grant

    missing = str(uuid4())
    by_doc = await grants.list_for_documents([doc.id, missing, "junk"])
    assert by_doc == {doc.id: [grant], missing: [], "junk": []}

    revoked = await grants.revoke(grant.id, by="root.admin", at=now + timedelta(minutes=1))
    assert revoked.revoked_by == "root.admin" and revoked.is_revoked
    again = await grants.revoke(grant.id, by="someone.else", at=now + timedelta(minutes=2))
    assert again == revoked  # first revocation wins
    assert (await grants.list_for_documents([doc.id]))[doc.id] == [revoked]  # revoked kept
    with pytest.raises(GrantNotFound):
        await grants.revoke(str(uuid4()), by="x", at=now)
    with pytest.raises(GrantNotFound):
        await grants.revoke("junk", by="x", at=now)

    # "Insertion order" is (granted_at, id): grants has no sequence column.
    regrant = await grants.add(
        grant.model_copy(update={"id": str(uuid4()), "granted_at": now + timedelta(minutes=3)})
    )
    subject = await grants.list_for_subject(SubjectType.group, "leadership")
    assert [g.id for g in subject if g.document_id == doc.id] == [grant.id, regrant.id]


_RAW_BY_KIND: dict[str, dict[str, object]] = {
    "confluence": {
        "kind": "confluence",
        "space_key": "OPS",
        "page_id": 1042,
        "space_view_groups": ["finance-ops"],
        "page_view_users": ["john.tan"],
        "ancestors": ["1000", {"page_id": "1001", "view_groups": ["leadership"]}],
    },
    "jira": {
        "kind": "jira",
        "project_key": "PAY",
        "issue_key": "PAY-142",
        "project_roles": {"developers": ["engineering"]},
        "browse_roles": ["developers"],
        "issue_security_level": "finance-only",
        "security_level_members": ["finance-ops"],
    },
    "slack": {
        "kind": "slack",
        "workspace_id": "T1",
        "channel_id": "C_TREASURY",
        "channel_type": "private",
        "member_ids": ["U_JORDAN", "U_JOHN"],
    },
    "gdrive": {
        "kind": "gdrive",
        "file_id": "f1",
        "acl": [
            {
                "type": "domain",
                "role": "reader",
                "email_or_domain": "example.test",
                "expiration_time": "2099-01-01T00:00:00Z",
                "allow_file_discovery": False,
            },
            {"type": "anyone", "role": "reader", "inherited": True, "deleted": True},
        ],
    },
    "email": {"kind": "email", "message_id": "m1", "from": "vendor@x.test", "to": ["john"]},
    "upload": {"kind": "upload", "owner_principal_id": "alex.tan", "shared_with_groups": ["eng"]},
    "mcp_external": {"kind": "mcp_external", "app_name": "crm", "allowed_principals": ["a"]},
}


async def test_permission_snapshot_round_trip_every_kind(
    repo: SqlRepo, sf: async_sessionmaker
) -> None:
    snapshots = SqlPermissionSnapshotStore(sf)
    source = await _source(repo)
    now = _now()
    expected: dict[str, SourcePermissions] = {}
    for raw in _RAW_BY_KIND.values():
        doc = await _page(repo, source)
        perms = SourcePermissions.from_raw(
            raw, permission_version="v1", captured_at=now, connector_run_id=str(uuid4())
        )
        await snapshots.put(doc.id, perms)
        expected[doc.id] = perms
    got = await snapshots.get_many([*expected, str(uuid4()), "junk"])
    assert got == expected
    assert {p.kind.value for p in got.values()} == set(_RAW_BY_KIND)

    doc_id = next(iter(expected))
    replacement = SourcePermissions.from_raw(
        _RAW_BY_KIND["upload"], permission_version="v2", captured_at=now
    )
    await snapshots.put(doc_id, replacement)
    assert (await snapshots.get_many([doc_id]))[doc_id] == replacement


async def test_access_request_store(repo: SqlRepo, sf: async_sessionmaker) -> None:
    requests = SqlAccessRequestStore(sf)
    pid = _uid("asker.")
    await repo.upsert_principal(Principal(id=pid, display_name="Asker"))
    now = _now()
    req = AccessRequest(document_id=str(uuid4()), principal_id=pid, reason="audit", created_at=now)
    assert await requests.create(req) == req
    with pytest.raises(AccessControlError):
        await requests.create(req)
    assert req.id in [r.id for r in await requests.list_pending()]
    decided = await requests.decide(req.id, approved=True, by="root.admin", at=now)
    assert decided.status is AccessRequestStatus.approved and decided.decided_by == "root.admin"
    assert req.id not in [r.id for r in await requests.list_pending()]
    with pytest.raises(AccessControlError):
        await requests.decide(req.id, approved=False, by="root.admin", at=now)
    with pytest.raises(AccessRequestNotFound):
        await requests.decide(str(uuid4()), approved=True, by="x", at=now)
