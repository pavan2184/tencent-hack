"""`freshness.FreshnessStore` over Postgres (tables from `0100_freshness_init.sql`).

Every invariant stated in `freshness.protocols.FreshnessStore` is enforced here, mirroring the
executable reference `freshness.memory.InMemoryFreshnessStore`:

- `cas_checkpoint`: compare-and-swap on `cursor_version` under `SELECT … FOR UPDATE`
  (`UPDATE … WHERE cursor_version = :expected`, or `INSERT … ON CONFLICT DO NOTHING` when no
  row exists); a lost race → `CursorConflict`. A changed `last_successful_run_id` must point at a
  `completed` run.
- `accept_event` / `create_run`: `INSERT … ON CONFLICT DO NOTHING RETURNING`, else the EXISTING
  row is returned (callers detect duplicates/replays by id).
- `update_event_state`: only the mutable fields change; an `applied` event is final.
- `upsert_object`: per-object advisory lock + `SELECT … FOR UPDATE`, then
  `freshness.assert_can_replace(stored, obj)` before writing (→ `VersionRegression`).
- `put_policy`: retires every other active row of the same `(connector_kind, evidence_class)`.
- `save_receipt`: a `request_key` collision is resolved by `freshness.receipt.check_replay`
  (same payload hash → existing receipt; different → `ReceiptConflict`); receipts never change.

`created_at`/`updated_at` of checkpoints and objects are omitted from INSERTs when the model
carries None, so the column DEFAULT now() applies. Each method runs in its own transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Collection, Iterable
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any

from freshness import (
    ConnectorCheckpoint,
    ConnectorKind,
    CursorConflict,
    EventState,
    EvidenceClass,
    FreshnessError,
    FreshnessPolicy,
    FreshnessReceipt,
    FreshnessStatus,
    ObjectFreshness,
    PolicyStatus,
    RunStatus,
    SourceChangeEvent,
    SyncRun,
    assert_can_replace,
    verify_receipt_hash,
)
from freshness.receipt import check_replay
from pydantic import BaseModel
from sqlalchemy import Column, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConnectorCheckpointRow,
    FreshnessPolicyRow,
    FreshnessReceiptRow,
    ObjectFreshnessRow,
    SourceChangeEventRow,
    SyncRunRow,
    is_uuid,
)

__all__ = ["SqlFreshnessStore"]

SessionFactory = Callable[[], AsyncSession]

_EVENT_IDENTITY = (
    "source_id",
    "scope_key",
    "connector_kind",
    "provider_event_id",
    "external_object_id",
    "change_kind",
    "provider_version",
    "version_order",
    "observed_at",
    "accepted_at",
    "payload_hash",
)
_EVENT_MUTABLE = (
    "state",
    "attempt_count",
    "next_attempt_at",
    "last_error_code",
    "applied_at",
    "parked_at",
    "noop_reason",
)
_RUN_IDENTITY = ("idempotency_key", "source_id", "scope_key")
_OPTIONAL_TIMESTAMPS = ("created_at", "updated_at")
_C_COLLATION = "C"  # codepoint order, same as Python's sort in the in-memory reference


def _columns(row_cls: Any, model_cls: type[BaseModel]) -> list[Column[Any]]:
    """The table columns that back `model_cls`'s fields (model field names == column names)."""
    table = row_cls.__table__
    return [table.c[name] for name in model_cls.model_fields]


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _values(model: BaseModel, *, omit_none: Iterable[str] = ()) -> dict[str, Any]:
    """Model → column values (enums as their values); `omit_none` keys dropped when None."""
    skip = set(omit_none)
    return {
        name: _plain(value)
        for name, value in model.model_dump(mode="python").items()
        if not (name in skip and value is None)
    }


def _model[M: BaseModel](model_cls: type[M], row: Any) -> M:
    return model_cls.model_validate(dict(row._mapping))


def _lock_key(*parts: str) -> Any:
    """`pg_advisory_xact_lock(hashtextextended(<parts>, 0))` for one logical key."""
    return func.pg_advisory_xact_lock(func.hashtextextended("\x1f".join(parts), 0))


class SqlFreshnessStore:
    """Async SQL implementation of :class:`freshness.FreshnessStore`."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            yield session

    # ---- connector_checkpoints -------------------------------------------------------------------

    async def get_checkpoint(self, source_id: str, scope_key: str) -> ConnectorCheckpoint | None:
        cols = _columns(ConnectorCheckpointRow, ConnectorCheckpoint)
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*cols).where(
                        ConnectorCheckpointRow.source_id == source_id,
                        ConnectorCheckpointRow.scope_key == scope_key,
                    )
                )
            ).first()
        return _model(ConnectorCheckpoint, row) if row is not None else None

    async def cas_checkpoint(
        self, checkpoint: ConnectorCheckpoint, *, expected_version: int
    ) -> ConnectorCheckpoint:
        T = ConnectorCheckpointRow
        cols = _columns(T, ConnectorCheckpoint)
        key = (checkpoint.source_id, checkpoint.scope_key)
        async with self._tx() as s:
            current = (
                await s.execute(
                    select(*cols)
                    .where(T.source_id == key[0], T.scope_key == key[1])
                    .with_for_update()
                )
            ).first()
            current_version = current.cursor_version if current is not None else 0
            if current_version != expected_version:
                raise CursorConflict(
                    f"checkpoint {key}: expected cursor_version {expected_version}, "
                    f"found {current_version}"
                )
            run_id = checkpoint.last_successful_run_id
            previous = current.last_successful_run_id if current is not None else None
            if run_id is not None and run_id != previous:
                status = (
                    await s.scalar(select(SyncRunRow.status).where(SyncRunRow.id == run_id))
                    if is_uuid(run_id)
                    else None
                )
                if status != RunStatus.completed.value:
                    raise FreshnessError(
                        f"last_successful_run_id {run_id!r} must reference a completed run"
                    )
            values = _values(checkpoint, omit_none=_OPTIONAL_TIMESTAMPS)
            values["cursor_version"] = expected_version + 1
            if current is None:
                stmt = (
                    pg_insert(T)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[T.source_id, T.scope_key])
                    .returning(*cols)
                )
            else:
                changes = {k: v for k, v in values.items() if k not in ("source_id", "scope_key")}
                changes.setdefault("updated_at", func.now())
                stmt = (
                    update(T)
                    .where(
                        T.source_id == key[0],
                        T.scope_key == key[1],
                        T.cursor_version == expected_version,
                    )
                    .values(**changes)
                    .returning(*cols)
                )
            row = (await s.execute(stmt)).first()
            if row is None:  # a concurrent writer won between our read and write
                raise CursorConflict(
                    f"checkpoint {key}: cursor_version moved past {expected_version}"
                )
            return _model(ConnectorCheckpoint, row)

    # ---- source_change_events --------------------------------------------------------------------

    async def accept_event(self, event: SourceChangeEvent) -> SourceChangeEvent:
        T = SourceChangeEventRow
        cols = _columns(T, SourceChangeEvent)
        if not is_uuid(event.id):
            raise FreshnessError(f"event id {event.id!r} is not a UUID")
        async with self._tx() as s:
            try:
                row = (
                    await s.execute(
                        pg_insert(T)
                        .values(**_values(event))
                        .on_conflict_do_nothing(index_elements=[T.source_id, T.provider_event_id])
                        .returning(*cols)
                    )
                ).first()
            except IntegrityError as exc:
                raise FreshnessError(f"event id {event.id!r} already used") from exc
            if row is None:
                row = (
                    await s.execute(
                        select(*cols).where(
                            T.source_id == event.source_id,
                            T.provider_event_id == event.provider_event_id,
                        )
                    )
                ).one()
            return _model(SourceChangeEvent, row)

    async def update_event_state(self, event: SourceChangeEvent) -> SourceChangeEvent:
        T = SourceChangeEventRow
        cols = _columns(T, SourceChangeEvent)
        if not is_uuid(event.id):
            raise FreshnessError(f"unknown event {event.id!r}")
        async with self._tx() as s:
            row = (await s.execute(select(*cols).where(T.id == event.id).with_for_update())).first()
            if row is None:
                raise FreshnessError(f"unknown event {event.id!r}")
            existing = _model(SourceChangeEvent, row)
            for name in _EVENT_IDENTITY:
                if getattr(existing, name) != getattr(event, name):
                    raise FreshnessError(
                        f"event {event.id!r}: identity field {name!r} is immutable"
                    )
            if existing.state is EventState.applied:
                if event != existing:
                    raise FreshnessError(f"event {event.id!r} is applied (terminal)")
                return existing
            values = _values(event)
            row = (
                await s.execute(
                    update(T)
                    .where(T.id == event.id)
                    .values(**{name: values[name] for name in _EVENT_MUTABLE})
                    .returning(*cols)
                )
            ).one()
            return _model(SourceChangeEvent, row)

    async def list_events(
        self,
        source_id: str,
        scope_key: str | None = None,
        *,
        states: Collection[EventState] | None = None,
        limit: int = 1000,
    ) -> list[SourceChangeEvent]:
        T = SourceChangeEventRow
        stmt = select(*_columns(T, SourceChangeEvent)).where(T.source_id == source_id)
        if scope_key is not None:
            stmt = stmt.where(T.scope_key == scope_key)
        if states is not None:
            stmt = stmt.where(T.state.in_([_plain(st) for st in states]))
        stmt = stmt.order_by(T.accepted_at, T.id).limit(limit)
        async with self._tx() as s:
            rows = (await s.execute(stmt)).all()
        return [_model(SourceChangeEvent, r) for r in rows]

    # ---- object_freshness ------------------------------------------------------------------------

    async def get_object(self, source_id: str, external_object_id: str) -> ObjectFreshness | None:
        T = ObjectFreshnessRow
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_columns(T, ObjectFreshness)).where(
                        T.source_id == source_id, T.external_object_id == external_object_id
                    )
                )
            ).first()
        return _model(ObjectFreshness, row) if row is not None else None

    async def upsert_object(self, obj: ObjectFreshness) -> ObjectFreshness:
        T = ObjectFreshnessRow
        cols = _columns(T, ObjectFreshness)
        where = (T.source_id == obj.source_id, T.external_object_id == obj.external_object_id)
        async with self._tx() as s:
            # The row lock alone cannot cover a not-yet-existing row; the advisory lock does.
            await s.execute(select(_lock_key("object", obj.source_id, obj.external_object_id)))
            row = (await s.execute(select(*cols).where(*where).with_for_update())).first()
            stored = _model(ObjectFreshness, row) if row is not None else None
            assert_can_replace(stored, obj)
            values = _values(obj, omit_none=_OPTIONAL_TIMESTAMPS)
            try:
                if stored is None:
                    stmt = pg_insert(T).values(**values).returning(*cols)
                else:
                    changes = {
                        k: v
                        for k, v in values.items()
                        if k not in ("source_id", "external_object_id")
                    }
                    changes.setdefault("updated_at", func.now())
                    stmt = update(T).where(*where).values(**changes).returning(*cols)
                row = (await s.execute(stmt)).one()
            except (IntegrityError, DataError) as exc:
                raise FreshnessError(
                    f"object {obj.source_id}/{obj.external_object_id}: rejected by the database "
                    f"({exc.orig.__class__.__name__ if exc.orig else exc.__class__.__name__})"
                ) from exc
            return _model(ObjectFreshness, row)

    async def list_objects(
        self,
        source_id: str,
        *,
        statuses: Collection[FreshnessStatus] | None = None,
        limit: int = 10_000,
    ) -> list[ObjectFreshness]:
        T = ObjectFreshnessRow
        stmt = select(*_columns(T, ObjectFreshness)).where(T.source_id == source_id)
        if statuses is not None:
            stmt = stmt.where(T.freshness_status.in_([_plain(st) for st in statuses]))
        stmt = stmt.order_by(T.external_object_id.collate(_C_COLLATION)).limit(limit)
        async with self._tx() as s:
            rows = (await s.execute(stmt)).all()
        return [_model(ObjectFreshness, r) for r in rows]

    # ---- sync_runs -------------------------------------------------------------------------------

    async def create_run(self, run: SyncRun) -> SyncRun:
        T = SyncRunRow
        cols = _columns(T, SyncRun)
        if not is_uuid(run.id):
            raise FreshnessError(f"run id {run.id!r} is not a UUID")
        async with self._tx() as s:
            try:
                row = (
                    await s.execute(
                        pg_insert(T)
                        .values(**_values(run))
                        .on_conflict_do_nothing(
                            index_elements=[T.source_id, T.scope_key, T.idempotency_key]
                        )
                        .returning(*cols)
                    )
                ).first()
            except IntegrityError as exc:
                raise FreshnessError(f"run {run.id!r}: rejected by the database") from exc
            if row is None:
                row = (
                    await s.execute(
                        select(*cols).where(
                            T.source_id == run.source_id,
                            T.scope_key == run.scope_key,
                            T.idempotency_key == run.idempotency_key,
                        )
                    )
                ).one()
            return _model(SyncRun, row)

    async def update_run(self, run: SyncRun) -> SyncRun:
        T = SyncRunRow
        cols = _columns(T, SyncRun)
        if not is_uuid(run.id):
            raise FreshnessError(f"unknown run {run.id!r}")
        async with self._tx() as s:
            row = (await s.execute(select(*cols).where(T.id == run.id).with_for_update())).first()
            if row is None:
                raise FreshnessError(f"unknown run {run.id!r}")
            if any(getattr(row, f) != getattr(run, f) for f in _RUN_IDENTITY):
                raise FreshnessError(f"run {run.id!r}: idempotency identity is immutable")
            changes = {k: v for k, v in _values(run).items() if k not in ("id", *_RUN_IDENTITY)}
            changes["updated_at"] = func.now()
            row = (
                await s.execute(update(T).where(T.id == run.id).values(**changes).returning(*cols))
            ).one()
            return _model(SyncRun, row)

    async def get_run(self, run_id: str) -> SyncRun | None:
        if not is_uuid(run_id):
            return None
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_columns(SyncRunRow, SyncRun)).where(SyncRunRow.id == run_id)
                )
            ).first()
        return _model(SyncRun, row) if row is not None else None

    # ---- freshness_policies ----------------------------------------------------------------------

    async def get_active_policy(
        self, connector_kind: ConnectorKind, evidence_class: EvidenceClass
    ) -> FreshnessPolicy | None:
        T = FreshnessPolicyRow
        stmt = (
            select(*_columns(T, FreshnessPolicy))
            .where(
                T.status == PolicyStatus.active.value,
                T.connector_kind == ConnectorKind(connector_kind).value,
                T.evidence_class == EvidenceClass(evidence_class).value,
            )
            .order_by(T.schema_version.desc())
            .limit(1)
        )
        async with self._tx() as s:
            row = (await s.execute(stmt)).first()
        return _model(FreshnessPolicy, row) if row is not None else None

    async def put_policy(self, policy: FreshnessPolicy) -> FreshnessPolicy:
        T = FreshnessPolicyRow
        cols = _columns(T, FreshnessPolicy)
        values = _values(policy)
        async with self._tx() as s:
            await s.execute(
                select(_lock_key("policy", values["connector_kind"], values["evidence_class"]))
            )
            if policy.status is PolicyStatus.active:
                await s.execute(
                    update(T)
                    .where(
                        T.connector_kind == values["connector_kind"],
                        T.evidence_class == values["evidence_class"],
                        T.status == PolicyStatus.active.value,
                        ~(
                            (T.policy_id == policy.policy_id)
                            & (T.schema_version == policy.schema_version)
                        ),
                    )
                    .values(
                        status=PolicyStatus.retired.value,
                        retired_at=policy.effective_at,
                        updated_at=func.now(),
                    )
                )
            changes = {k: v for k, v in values.items() if k not in ("policy_id", "schema_version")}
            stmt = pg_insert(T).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[T.policy_id, T.schema_version],
                set_={**{k: stmt.excluded[k] for k in changes}, "updated_at": func.now()},
            ).returning(*cols)
            row = (await s.execute(stmt)).one()
            return _model(FreshnessPolicy, row)

    # ---- freshness_receipts ----------------------------------------------------------------------

    @staticmethod
    def _receipt_values(receipt: FreshnessReceipt) -> dict[str, Any]:
        values = _values(receipt)
        values["evidence_items"] = [item.model_dump(mode="json") for item in receipt.evidence_items]
        return values

    async def save_receipt(self, receipt: FreshnessReceipt) -> FreshnessReceipt:
        T = FreshnessReceiptRow
        cols = _columns(T, FreshnessReceipt)
        async with self._tx() as s:
            await s.execute(select(_lock_key("receipt", receipt.request_key)))
            row = (
                await s.execute(select(*cols).where(T.request_key == receipt.request_key))
            ).first()
            if row is not None:
                return check_replay(_model(FreshnessReceipt, row), receipt.request_payload_hash)
            if not verify_receipt_hash(receipt):
                raise FreshnessError(f"receipt {receipt.receipt_id!r}: receipt_hash does not match")
            if not is_uuid(receipt.receipt_id):
                raise FreshnessError(f"receipt id {receipt.receipt_id!r} is not a UUID")
            try:
                row = (
                    await s.execute(
                        pg_insert(T).values(**self._receipt_values(receipt)).returning(*cols)
                    )
                ).one()
            except IntegrityError as exc:
                raise FreshnessError(f"receipt id {receipt.receipt_id!r} already used") from exc
            return _model(FreshnessReceipt, row)

    async def get_receipt(self, receipt_id: str) -> FreshnessReceipt | None:
        if not is_uuid(receipt_id):
            return None
        T = FreshnessReceiptRow
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_columns(T, FreshnessReceipt)).where(T.receipt_id == receipt_id)
                )
            ).first()
        return _model(FreshnessReceipt, row) if row is not None else None

    async def get_receipt_by_request_key(self, request_key: str) -> FreshnessReceipt | None:
        T = FreshnessReceiptRow
        async with self._tx() as s:
            row = (
                await s.execute(
                    select(*_columns(T, FreshnessReceipt)).where(T.request_key == request_key)
                )
            ).first()
        return _model(FreshnessReceipt, row) if row is not None else None
