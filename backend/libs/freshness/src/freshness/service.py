"""``FreshnessService``: the freshness state machine over a :class:`FreshnessStore`.

Operations (spec "Operation Contracts"): ``accept`` (durable acceptance primitive used by webhook
routes), ``connector_sync`` (webhook/delta/reconcile run), ``freshness_status`` (read-only),
``verify_freshness`` (live check), ``freshness_receipt`` (stable snapshot). ``evaluate`` is the pure
policy function in :mod:`freshness.policy`.
"""

from __future__ import annotations

import contextlib
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from freshness import receipt as receipts
from freshness.enums import (
    ChangeKind,
    CheckpointStatus,
    ConnectorKind,
    EventState,
    EvidenceClass,
    FreshnessStatus,
    RunStatus,
    SyncPath,
    VerificationResult,
)
from freshness.models import (
    AcceptResult,
    ConnectorCheckpoint,
    ConnectorSyncRequest,
    ConnectorSyncResult,
    EvidenceRef,
    FreshnessPolicy,
    FreshnessReceipt,
    FreshnessStatusReport,
    FreshnessStatusRequest,
    IndexOutcome,
    NormalizedChange,
    ObjectFreshness,
    ProviderHead,
    ReceiptItem,
    ReceiptRequest,
    SourceChangeEvent,
    SyncRun,
    VerifyRequest,
    VerifyResult,
)
from freshness.policy import evaluate, evaluate_missing
from freshness.protocols import (
    ChangeSource,
    Clock,
    FreshnessError,
    FreshnessStore,
    PolicyNotFound,
    ProbeUnavailable,
    ProviderProbe,
    VersionRegression,
)
from freshness.versioning import compare

#: The app's indexer: fetch/write/chunk/embed (or remove) one change and report what happened.
ApplyChange = Callable[[NormalizedChange], Awaitable[IndexOutcome]]
#: Chooses a live probe per evidence item for ``freshness_receipt`` (``None`` = don't verify).
ProbeFor = Callable[[EvidenceRef], ProviderProbe | None]

MAX_ATTEMPTS: Final = 3
RETRY_BASE_SECONDS: Final = 60
LEDGER_BATCH_LIMIT: Final = 500
_NON_CURRENT: Final = (
    FreshnessStatus.stale,
    FreshnessStatus.unknown,
    FreshnessStatus.not_searchable,
)


class SystemClock:
    """Production :class:`Clock` (UTC wall time)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return f"apply_error:{type(exc).__name__}"


def _retry_due(event: SourceChangeEvent, now: datetime) -> bool:
    """Whether an unapplied event may be (re)processed now."""
    if event.state is EventState.applied:
        return False
    if event.state is EventState.parked:
        if event.attempt_count >= MAX_ATTEMPTS:
            return False  # poison: terminal until an operator intervenes
        return event.next_attempt_at is None or event.next_attempt_at <= now
    return True  # accepted, or processing left behind by an interrupted worker


def _change_from_event(event: SourceChangeEvent) -> NormalizedChange:
    return NormalizedChange(
        source_id=event.source_id,
        scope_key=event.scope_key,
        connector_kind=event.connector_kind,
        provider_event_id=event.provider_event_id,
        external_object_id=event.external_object_id,
        change_kind=event.change_kind,
        provider_version=event.provider_version,
        version_order=event.version_order,
        observed_at=event.observed_at,
    )


@dataclass
class _Tally:
    observed: int = 0
    accepted: int = 0
    duplicate: int = 0
    applied: int = 0
    noop: int = 0
    tombstoned: int = 0
    parked: int = 0
    retry: int = 0
    next_attempt_at: datetime | None = None
    seen: set[str] = field(default_factory=set)

    def count_parked(self, event: SourceChangeEvent) -> None:
        self.parked += 1
        if event.next_attempt_at is not None:
            self.retry += 1
            if self.next_attempt_at is None or event.next_attempt_at < self.next_attempt_at:
                self.next_attempt_at = event.next_attempt_at


@dataclass
class _Drain:
    checkpoint: ConnectorCheckpoint
    complete: bool
    failed: bool = False
    error: str | None = None


@dataclass
class _Guard:
    apply: bool
    noop_reason: str | None = None


class FreshnessService:
    """Freshness operations. Construct once per store/clock; methods are safe to call repeatedly.

    Concurrency: one ``connector_sync`` per ``(source_id, scope_key)`` at a time is the caller's job
    (Celery lock / task routing). The checkpoint CAS turns a lost race into :class:`CursorConflict`
    rather than a skipped change.
    """

    def __init__(self, store: FreshnessStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise FreshnessError("Clock.now() must return a timezone-aware UTC datetime")
        return now.astimezone(UTC)

    async def _policy(
        self, connector_kind: ConnectorKind, evidence_class: EvidenceClass
    ) -> FreshnessPolicy:
        policy = await self._store.get_active_policy(connector_kind, evidence_class)
        if policy is None:
            raise PolicyNotFound(
                f"no active freshness policy for {connector_kind}/{evidence_class}"
            )
        return policy

    # ---------------------------------------------------------------------------------------------
    # accept
    # ---------------------------------------------------------------------------------------------

    async def accept(self, change: NormalizedChange) -> AcceptResult:
        """Durably accept one normalized change (the webhook fast-path primitive).

        A duplicate ``(source_id, provider_event_id)`` returns the existing event with
        ``duplicate=True`` and changes nothing. Acceptance never indexes content.
        """
        candidate = SourceChangeEvent(
            id=_new_id(),
            source_id=change.source_id,
            scope_key=change.scope_key,
            connector_kind=change.connector_kind,
            provider_event_id=change.provider_event_id,
            external_object_id=change.external_object_id,
            change_kind=change.change_kind,
            provider_version=change.provider_version,
            version_order=change.version_order,
            observed_at=change.observed_at,
            accepted_at=self._now(),
            payload_hash=receipts.canonical_hash(change, exclude={"observed_at"}),
        )
        stored = await self._store.accept_event(candidate)
        return AcceptResult(event=stored, duplicate=stored.id != candidate.id)

    # ---------------------------------------------------------------------------------------------
    # connector_sync
    # ---------------------------------------------------------------------------------------------

    async def queue_sync(self, req: ConnectorSyncRequest) -> SyncRun:
        """Create (or find) the ``queued`` run for ``req.idempotency_key`` so a route can return its
        ``run_id`` before the worker runs; ``connector_sync`` with the same key resumes it."""
        checkpoint = await self._store.get_checkpoint(req.source_id, req.scope_key)
        return await self._store.create_run(
            SyncRun(
                id=_new_id(),
                idempotency_key=req.idempotency_key,
                source_id=req.source_id,
                scope_key=req.scope_key,
                connector_kind=req.connector_kind,
                trigger_kind=req.trigger_kind,
                cursor_before=checkpoint.cursor_value if checkpoint else None,
                started_at=self._now(),
                status=RunStatus.queued,
            )
        )

    async def connector_sync(
        self,
        req: ConnectorSyncRequest,
        *,
        change_source: ChangeSource,
        apply: ApplyChange,
    ) -> ConnectorSyncResult:
        """Run webhook/delta/reconcile work for one source scope.

        1. Find-or-create the run by idempotency key; a ``completed`` run is returned as-is.
        2. Process due ledger events for the scope (webhook-accepted, parked-and-due, interrupted).
        3. Page through ``change_source`` from the checkpoint cursor (reconcile: from ``None``, and
           the delta cursor is never moved). Per change: accept → version guard → ``apply`` →
           object write; failures and partial indexing park the event and mark the object
           non-current. The cursor is CAS-advanced only after a whole page is accounted for.
        4. Close the run (completed / partial / failed) and stamp the checkpoint; only a
           ``completed`` run becomes ``last_successful_run_id``.

        ``apply`` is called at most once per change per run, never for an event already
        ``applied``, never for an older version, and never twice for one duplicate delivery.
        """
        now = self._now()
        checkpoint = await self._store.get_checkpoint(
            req.source_id, req.scope_key
        ) or ConnectorCheckpoint(
            source_id=req.source_id,
            scope_key=req.scope_key,
            connector_kind=req.connector_kind,
            created_at=now,
            updated_at=now,
        )
        candidate = SyncRun(
            id=_new_id(),
            idempotency_key=req.idempotency_key,
            source_id=req.source_id,
            scope_key=req.scope_key,
            connector_kind=req.connector_kind,
            trigger_kind=req.trigger_kind,
            cursor_before=checkpoint.cursor_value,
            started_at=now,
            status=RunStatus.running,
        )
        run = await self._store.create_run(candidate)
        if run.id != candidate.id:
            if run.status is RunStatus.completed:
                return self._result(run, _Tally(), replayed=True)
            # Resume queued/partial/failed/parked work under the same run id; counts restart.
            run = await self._store.update_run(
                run.evolve(
                    status=RunStatus.running,
                    cursor_before=checkpoint.cursor_value,
                    cursor_after=None,
                    started_at=now,
                    completed_at=None,
                    observed_count=0,
                    applied_count=0,
                    tombstoned_count=0,
                    retry_count=0,
                    failed_count=0,
                    next_attempt_at=None,
                    error_summary=None,
                )
            )

        tally = _Tally()
        try:
            await self._drain_ledger(req, run, apply, tally)
            drain = await self._drain_pages(req, run, checkpoint, change_source, apply, tally)
        except Exception as exc:
            # Unaccounted work (store failure, CAS conflict, bad change): the cursor stays at the
            # last fully accounted page. Recording the failure is best effort (store may be down).
            code = getattr(exc, "code", None) or f"sync_aborted:{type(exc).__name__}"
            with contextlib.suppress(Exception):
                current = await self._store.get_checkpoint(req.source_id, req.scope_key)
                cursor = current.cursor_value if current is not None else checkpoint.cursor_value
                await self._close_run(run, tally, RunStatus.failed, cursor, code)
            raise

        if drain.failed:
            status = RunStatus.failed
        elif tally.parked or not drain.complete:
            status = RunStatus.partial
        else:
            status = RunStatus.completed
        run = await self._close_run(run, tally, status, drain.checkpoint.cursor_value, drain.error)
        await self._stamp_checkpoint(drain.checkpoint, run, req.trigger_kind)
        return self._result(run, tally)

    async def _drain_ledger(
        self, req: ConnectorSyncRequest, run: SyncRun, apply: ApplyChange, tally: _Tally
    ) -> None:
        now = self._now()
        pending = await self._store.list_events(
            req.source_id,
            req.scope_key,
            states=(EventState.accepted, EventState.processing, EventState.parked),
            limit=LEDGER_BATCH_LIMIT,
        )
        for event in pending:
            if _retry_due(event, now):
                await self._process(_change_from_event(event), run, apply, tally, event=event)

    async def _drain_pages(
        self,
        req: ConnectorSyncRequest,
        run: SyncRun,
        checkpoint: ConnectorCheckpoint,
        change_source: ChangeSource,
        apply: ApplyChange,
        tally: _Tally,
    ) -> _Drain:
        reconcile = req.trigger_kind is SyncPath.reconcile
        # TODO(Pavan): slim reconciliation — diff the full listing against ``list_objects`` to
        # synthesise deletes/tombstones for vanished objects and flag permission-version drift.
        # Today a reconcile run trusts the listing (explicit delete changes only).
        cursor = None if reconcile else checkpoint.cursor_value
        for _ in range(req.max_pages):
            if req.deadline_at is not None and self._now() >= req.deadline_at:
                return _Drain(checkpoint, complete=False, error="deadline_exceeded")
            try:
                page = await change_source.list_changes(cursor, limit=req.page_limit)
            except Exception as exc:
                return _Drain(
                    checkpoint,
                    complete=False,
                    failed=True,
                    error=f"change_source_error:{type(exc).__name__}",
                )
            for change in page.changes:
                if change.source_id != req.source_id or change.connector_kind != req.connector_kind:
                    raise FreshnessError(
                        f"change for {change.source_id}/{change.connector_kind} listed in "
                        f"{req.source_id}/{req.connector_kind} sync"
                    )
                scoped = change.evolve(scope_key=req.scope_key)
                await self._process(scoped, run, apply, tally)
            # Every change on this page is now applied or durably parked: the cursor may move.
            next_cursor = page.next_cursor
            if not reconcile and next_cursor is not None and next_cursor != checkpoint.cursor_value:
                checkpoint = await self._store.cas_checkpoint(
                    checkpoint.evolve(cursor_value=next_cursor, updated_at=self._now()),
                    expected_version=checkpoint.cursor_version,
                )
            if not page.has_more:
                return _Drain(checkpoint, complete=True)
            if next_cursor is None or next_cursor == cursor:
                return _Drain(checkpoint, complete=False, error="cursor_not_advancing")
            cursor = next_cursor
        return _Drain(checkpoint, complete=False, error="max_pages_exhausted")

    def _guard(self, change: NormalizedChange, stored: ObjectFreshness | None) -> _Guard:
        """Version guard deciding whether ``apply`` may run for ``change``."""
        if stored is None:
            return _Guard(apply=True)
        relation = compare(
            change.provider_version,
            change.version_order,
            stored.provider_version,
            stored.version_order,
        )
        if relation == "older":
            return _Guard(apply=False, noop_reason="older_version")
        tombstoned = stored.freshness_status is FreshnessStatus.deleted
        if change.change_kind is ChangeKind.delete:
            if tombstoned and relation != "newer":
                return _Guard(apply=False, noop_reason="already_tombstoned")
            return _Guard(apply=True)
        if tombstoned and relation != "newer":
            return _Guard(apply=False, noop_reason="tombstone_requires_newer_version")
        if (
            relation == "same"
            and change.change_kind is ChangeKind.upsert
            and stored.freshness_status is not FreshnessStatus.not_searchable
        ):
            return _Guard(apply=False, noop_reason="same_version_already_applied")
        return _Guard(apply=True)

    async def _process(
        self,
        change: NormalizedChange,
        run: SyncRun,
        apply: ApplyChange,
        tally: _Tally,
        *,
        event: SourceChangeEvent | None = None,
    ) -> None:
        """Account for one change: applied, no-op, or durably parked. Store errors propagate.

        Each ledger event is handled at most once per run, so ``apply`` runs at most once per change
        per run even if the same change arrives via the ledger and a page.
        """
        if event is None:
            accepted = await self.accept(change)
            event = accepted.event
            if event.id in tally.seen:
                return
            if accepted.duplicate:
                tally.duplicate += 1
            else:
                tally.accepted += 1
        elif event.id in tally.seen:
            return
        tally.seen.add(event.id)
        tally.observed += 1
        now = self._now()
        if event.state is EventState.applied:
            return  # duplicate of completed work: never applied twice
        if not _retry_due(event, now):
            tally.count_parked(event)  # parked and not yet due (or poison): still accounted
            return

        stored = await self._store.get_object(change.source_id, change.external_object_id)
        guard = self._guard(change, stored)
        if not guard.apply:
            await self._store.update_event_state(
                event.evolve(
                    state=EventState.applied,
                    applied_at=now,
                    parked_at=None,
                    next_attempt_at=None,
                    noop_reason=guard.noop_reason,
                )
            )
            tally.noop += 1
            return

        event = await self._store.update_event_state(
            event.evolve(
                state=EventState.processing,
                attempt_count=event.attempt_count + 1,
                next_attempt_at=None,
            )
        )
        try:
            outcome = await apply(change)
        except Exception as exc:
            await self._park(event, change, run, tally, code=_error_code(exc))
            return

        obj, failure = self._object_after_apply(change, event, stored, outcome, run)
        try:
            await self._store.upsert_object(obj)
        except VersionRegression as exc:
            await self._park(event, change, run, tally, code=exc.code)
            return
        if failure is not None:
            await self._park(event, change, run, tally, code=failure, mark_object=False)
            return

        await self._store.update_event_state(
            event.evolve(
                state=EventState.applied,
                applied_at=self._now(),
                parked_at=None,
                next_attempt_at=None,
            )
        )
        if change.change_kind is ChangeKind.delete:
            tally.tombstoned += 1
        else:
            tally.applied += 1

    def _object_after_apply(
        self,
        change: NormalizedChange,
        event: SourceChangeEvent,
        stored: ObjectFreshness | None,
        outcome: IndexOutcome,
        run: SyncRun,
    ) -> tuple[ObjectFreshness, str | None]:
        """Object row implied by ``outcome`` plus the park code if the outcome is incomplete."""
        now = self._now()
        common = {
            "source_id": change.source_id,
            "external_object_id": change.external_object_id,
            "connector_kind": change.connector_kind,
            "page_id": outcome.page_id or (stored.page_id if stored else None),
            "page_slug": outcome.page_slug or (stored.page_slug if stored else None),
            "observed_at": change.observed_at,
            "accepted_at": event.accepted_at,
            "sync_path": run.trigger_kind,
            "last_run_id": run.id,
            "created_at": stored.created_at if stored and stored.created_at else now,
            "updated_at": now,
        }

        if change.change_kind is ChangeKind.delete:
            deleted_at = change.provider_modified_at or change.observed_at
            if outcome.searchable:
                # Removal did not complete: explicit unsafe state + retry, never a clean delete.
                base = stored.model_dump() if stored else {}
                obj = ObjectFreshness.model_validate(
                    {
                        **base,
                        **common,
                        "provider_version": stored.provider_version
                        if stored
                        else change.provider_version,
                        "version_order": stored.version_order if stored else change.version_order,
                        "deleted_at": deleted_at,
                        "tombstone_version": change.provider_version,
                        "freshness_status": FreshnessStatus.stale,
                        "indexed_at": stored.indexed_at if stored else None,
                        "searchable_at": stored.searchable_at if stored else None,
                    }
                )
                return obj, outcome.error_code or "delete_not_removed"
            newer = (
                stored is None
                or compare(
                    change.provider_version,
                    change.version_order,
                    stored.provider_version,
                    stored.version_order,
                )
                == "newer"
            )
            obj = ObjectFreshness(
                **common,
                provider_version=change.provider_version if newer else stored.provider_version,
                version_order=change.version_order if newer else stored.version_order,
                content_hash=None,
                provider_modified_at=change.provider_modified_at,
                indexed_at=None,
                searchable_at=None,
                last_verified_at=stored.last_verified_at if stored else None,
                verification_result=stored.verification_result if stored else None,
                deleted_at=deleted_at,
                tombstone_version=change.provider_version,
                freshness_status=FreshnessStatus.deleted,
            )
            return obj, None

        # upsert / metadata_change
        if outcome.provider_version is not None:
            version, order = outcome.provider_version, outcome.version_order
        else:
            version, order = change.provider_version, change.version_order
        relation = (
            compare(version, order, stored.provider_version, stored.version_order)
            if stored is not None
            else "newer"
        )
        complete = outcome.content_written and outcome.searchable and outcome.embedded
        if not outcome.content_written:
            # Nothing new reached the index: keep what is there, but it is no longer current.
            return self._non_current(stored, change, event, run), (
                outcome.error_code or "content_not_written"
            )
        indexed_at = outcome.indexed_at or now
        searchable_at = max(outcome.searchable_at or indexed_at, indexed_at) if complete else None
        if not complete:
            status = FreshnessStatus.not_searchable
        elif relation == "incomparable":
            status = FreshnessStatus.unknown  # forced provider read: unknown until verified
        elif (
            relation == "same"
            and stored is not None
            and stored.freshness_status
            in (
                FreshnessStatus.unknown,
                FreshnessStatus.stale,
            )
        ):
            status = stored.freshness_status  # re-arrival of the same version proves nothing new
        else:
            status = FreshnessStatus.fresh
        keep_verification = stored is not None and relation == "same"
        obj = ObjectFreshness(
            **common,
            provider_version=version,
            version_order=order,
            content_hash=outcome.content_hash or change.content_hash,
            provider_modified_at=outcome.provider_modified_at or change.provider_modified_at,
            indexed_at=indexed_at,
            searchable_at=searchable_at,
            last_verified_at=stored.last_verified_at if keep_verification else None,
            verification_result=stored.verification_result if keep_verification else None,
            deleted_at=None,
            tombstone_version=None,
            freshness_status=status,
        )
        return obj, None if complete else (outcome.error_code or "partial_index")

    def _non_current(
        self,
        stored: ObjectFreshness | None,
        change: NormalizedChange,
        event: SourceChangeEvent,
        run: SyncRun,
    ) -> ObjectFreshness:
        """``stored`` marked non-current (or a placeholder when the object is new)."""
        now = self._now()
        if stored is None:
            return ObjectFreshness(
                source_id=change.source_id,
                external_object_id=change.external_object_id,
                connector_kind=change.connector_kind,
                provider_version=change.provider_version,
                version_order=change.version_order,
                observed_at=change.observed_at,
                accepted_at=event.accepted_at,
                sync_path=run.trigger_kind,
                freshness_status=FreshnessStatus.not_searchable,
                last_run_id=run.id,
                created_at=now,
                updated_at=now,
            )
        if stored.freshness_status is FreshnessStatus.deleted:
            return stored  # a tombstone is already non-searchable
        status = (
            FreshnessStatus.stale
            if stored.searchable_at is not None
            else FreshnessStatus.not_searchable
        )
        return stored.evolve(freshness_status=status, last_run_id=run.id, updated_at=now)

    async def _park(
        self,
        event: SourceChangeEvent,
        change: NormalizedChange,
        run: SyncRun,
        tally: _Tally,
        *,
        code: str,
        mark_object: bool = True,
    ) -> None:
        """Durably park ``event`` (retryable until attempts run out); object marked non-current."""
        now = self._now()
        if mark_object:
            # Re-read: a concurrent writer may have moved the object since the guard ran.
            current = await self._store.get_object(change.source_id, change.external_object_id)
            marked = self._non_current(current, change, event, run)
            if marked is not current:
                await self._store.upsert_object(marked)
        attempts = event.attempt_count
        # TODO(Pavan): backoff with jitter + provider retry hints (Retry-After, 429 windows).
        next_at = (
            None
            if attempts >= MAX_ATTEMPTS
            else now + timedelta(seconds=RETRY_BASE_SECONDS * max(attempts, 1))
        )
        parked = await self._store.update_event_state(
            event.evolve(
                state=EventState.parked,
                parked_at=now,
                applied_at=None,
                next_attempt_at=next_at,
                last_error_code=code,
            )
        )
        tally.count_parked(parked)

    async def _close_run(
        self,
        run: SyncRun,
        tally: _Tally,
        status: RunStatus,
        cursor_after: str | None,
        error: str | None,
    ) -> SyncRun:
        return await self._store.update_run(
            run.evolve(
                status=status,
                cursor_after=cursor_after,
                completed_at=self._now(),
                observed_count=tally.observed,
                applied_count=tally.applied,
                tombstoned_count=tally.tombstoned,
                retry_count=tally.retry,
                failed_count=tally.parked,
                next_attempt_at=tally.next_attempt_at,
                error_summary=error,
            )
        )

    async def _stamp_checkpoint(
        self, checkpoint: ConnectorCheckpoint, run: SyncRun, trigger: SyncPath
    ) -> ConnectorCheckpoint:
        now = self._now()
        updates: dict[str, object] = {
            "updated_at": now,
            "status": CheckpointStatus.ready
            if run.status is RunStatus.completed
            else CheckpointStatus.degraded,
        }
        if run.status in (RunStatus.completed, RunStatus.partial):
            updates["last_reconciled_at" if trigger is SyncPath.reconcile else "last_polled_at"] = (
                now
            )
        if run.status is RunStatus.completed:
            updates["last_successful_run_id"] = run.id
        return await self._store.cas_checkpoint(
            checkpoint.evolve(**updates), expected_version=checkpoint.cursor_version
        )

    @staticmethod
    def _result(run: SyncRun, tally: _Tally, *, replayed: bool = False) -> ConnectorSyncResult:
        return ConnectorSyncResult(
            run_id=run.id,
            status=run.status,
            replayed=replayed,
            cursor_before=run.cursor_before,
            cursor_after=run.cursor_after,
            observed_count=run.observed_count,
            accepted_count=tally.accepted,
            duplicate_count=tally.duplicate,
            applied_count=run.applied_count,
            noop_count=tally.noop,
            tombstoned_count=run.tombstoned_count,
            parked_count=run.failed_count,
            retry_count=run.retry_count,
            next_attempt_at=run.next_attempt_at,
            error_summary=run.error_summary,
        )

    # ---------------------------------------------------------------------------------------------
    # freshness_status
    # ---------------------------------------------------------------------------------------------

    async def freshness_status(self, req: FreshnessStatusRequest) -> FreshnessStatusReport:
        """Read-only report for a source scope (and one object when requested). Writes nothing."""
        now = self._now()
        checkpoint = await self._store.get_checkpoint(req.source_id, req.scope_key)
        last_success_at = None
        if checkpoint is not None and checkpoint.last_successful_run_id:
            run = await self._store.get_run(checkpoint.last_successful_run_id)
            last_success_at = run.completed_at if run is not None else None
        objects = await self._store.list_objects(req.source_id)
        counts = Counter(obj.freshness_status for obj in objects)
        non_current_ages = [
            max(0, int((now - obj.observed_at).total_seconds()))
            for obj in objects
            if obj.freshness_status in _NON_CURRENT
        ]
        pending = await self._store.list_events(
            req.source_id, req.scope_key, states=(EventState.accepted, EventState.processing)
        )
        parked = await self._store.list_events(
            req.source_id, req.scope_key, states=(EventState.parked,)
        )
        obj = evaluation = None
        if req.external_object_id is not None:
            obj = await self._store.get_object(req.source_id, req.external_object_id)
            if obj is not None:
                policy = await self._store.get_active_policy(obj.connector_kind, req.evidence_class)
                if policy is not None:
                    evaluation = evaluate(obj, policy, now)
        return FreshnessStatusReport(
            source_id=req.source_id,
            scope_key=req.scope_key,
            generated_at=now,
            checkpoint=checkpoint,
            last_successful_run_at=last_success_at,
            object_counts={status: counts.get(status, 0) for status in FreshnessStatus},
            pending_event_count=len(pending),
            parked_event_count=len(parked),
            oldest_non_current_age_seconds=max(non_current_ages) if non_current_ages else None,
            object=obj,
            evaluation=evaluation,
        )

    # ---------------------------------------------------------------------------------------------
    # verify_freshness
    # ---------------------------------------------------------------------------------------------

    async def verify_freshness(self, req: VerifyRequest, probe: ProviderProbe) -> VerifyResult:
        """Live-check one object against its provider and record the verification.

        ``fresh`` only when the provider version matches the indexed, searchable version.
        Transport failure (:class:`ProbeUnavailable` or any probe error) → ``unknown``, never fresh.
        Critical evidence that ends non-fresh gets ``safe_to_use=False`` and the policy's
        ``fallback_action``. Raises :class:`PolicyNotFound` when no policy applies.
        """
        policy = await self._policy(req.connector_kind, req.evidence_class)
        now = self._now()
        ref = EvidenceRef(
            source_id=req.source_id,
            external_object_id=req.external_object_id,
            connector_kind=req.connector_kind,
            evidence_class=req.evidence_class,
        )
        obj = await self._store.get_object(req.source_id, req.external_object_id)
        if obj is None:
            item = evaluate_missing(ref, policy)
            return self._verify_result(
                req, item, now, VerificationResult.unknown, None, None, "object_not_found"
            )

        head: ProviderHead | None = None
        try:
            head = await probe.head(req.external_object_id)
        except ProbeUnavailable:
            result, reason = VerificationResult.unknown, "probe_unavailable"
        except Exception:
            result, reason = VerificationResult.unknown, "probe_error"
        else:
            result, reason = _judge(obj, head)

        updated = _record_verification(obj, result, now)
        try:
            updated = await self._store.upsert_object(updated)
        except VersionRegression:
            # A sync wrote a newer version meanwhile: this check proves nothing about it.
            result, reason = VerificationResult.unknown, "concurrent_update"
            updated = _record_verification(obj, result, now)
        item = evaluate(
            updated, policy, now, ref=ref.evolve(page_id=obj.page_id, page_slug=obj.page_slug)
        )
        observed = head.provider_version if head is not None else None
        return self._verify_result(req, item, now, result, obj.provider_version, observed, reason)

    @staticmethod
    def _verify_result(
        req: VerifyRequest,
        item: ReceiptItem,
        now: datetime,
        result: VerificationResult,
        indexed_version: str | None,
        observed_version: str | None,
        reason: str | None,
    ) -> VerifyResult:
        return VerifyResult(
            source_id=req.source_id,
            external_object_id=req.external_object_id,
            connector_kind=req.connector_kind,
            evidence_class=req.evidence_class,
            page_id=item.page_id,
            page_slug=item.page_slug,
            indexed_provider_version=indexed_version,
            observed_provider_version=observed_version,
            verified_at=now,
            verification_result=result,
            freshness_status=item.freshness_status,
            budget_seconds=item.budget_seconds,
            safe_to_use=item.safe_to_use,
            fallback_action=item.fallback_action,
            reason=reason or item.reason,
            item=item,
        )

    # ---------------------------------------------------------------------------------------------
    # freshness_receipt
    # ---------------------------------------------------------------------------------------------

    async def freshness_receipt(
        self, req: ReceiptRequest, *, probe_for: ProbeFor | None = None
    ) -> FreshnessReceipt:
        """Snapshot the ordered evidence set; optionally live-verify items first.

        Items come back in input order; unknown/stale/deleted/missing evidence is retained with its
        status (never dropped). ``persist=True``: the same ``request_key`` + same request returns
        the stored receipt untouched; a different request raises :class:`ReceiptConflict`.
        """
        request_hash = receipts.request_payload_hash(req)
        if req.persist:
            existing = await self._store.get_receipt_by_request_key(req.request_key)
            if existing is not None:
                return receipts.check_replay(existing, request_hash)
        now = self._now()
        items = [await self._receipt_item(ref, probe_for, now) for ref in req.evidence]
        built = receipts.build_receipt(
            request=req,
            request_hash=request_hash,
            items=items,
            receipt_id=_new_id(),
            created_at=now,
        )
        if req.persist:
            built = await self._store.save_receipt(built)
        return built

    async def _receipt_item(
        self, ref: EvidenceRef, probe_for: ProbeFor | None, now: datetime
    ) -> ReceiptItem:
        policy = await self._store.get_active_policy(ref.connector_kind, ref.evidence_class)
        if policy is None:
            return evaluate_missing(ref, None, reason="policy_not_found")
        probe = probe_for(ref) if probe_for is not None else None
        if probe is not None:
            verified = await self.verify_freshness(VerifyRequest.from_ref(ref), probe)
            item = verified.item
            return item.evolve(
                page_id=ref.page_id or item.page_id, page_slug=ref.page_slug or item.page_slug
            )
        obj = await self._store.get_object(ref.source_id, ref.external_object_id)
        if obj is None:
            return evaluate_missing(ref, policy)
        return evaluate(obj, policy, now, ref=ref)


def _judge(obj: ObjectFreshness, head: ProviderHead) -> tuple[VerificationResult, str | None]:
    """Compare provider truth with indexed state."""
    if obj.freshness_status is FreshnessStatus.deleted or obj.deleted_at is not None:
        if head.deleted:
            return VerificationResult.fresh, "provider_confirms_deletion"
        return VerificationResult.stale, "provider_has_live_object"
    if head.deleted:
        return VerificationResult.stale, "provider_deleted"
    relation = compare(
        head.provider_version, head.version_order, obj.provider_version, obj.version_order
    )
    if relation == "same":
        if head.content_hash and obj.content_hash and head.content_hash != obj.content_hash:
            return VerificationResult.stale, "content_hash_mismatch"
        return VerificationResult.fresh, None
    if relation == "newer":
        return VerificationResult.stale, "provider_newer"
    if relation == "older":
        return VerificationResult.unknown, "provider_older_than_index"
    if head.provider_version is not None and obj.provider_version is not None:
        return VerificationResult.stale, "provider_version_mismatch"
    return VerificationResult.unknown, "version_unavailable"


def _record_verification(
    obj: ObjectFreshness, result: VerificationResult, now: datetime
) -> ObjectFreshness:
    """Object after a verification. Only a matching check can make it fresh; unknown never does."""
    status = obj.freshness_status
    if status is not FreshnessStatus.deleted:
        if result is VerificationResult.fresh:
            if (
                obj.deleted_at is None
                and obj.searchable_at is not None
                and status is not FreshnessStatus.not_searchable
            ):
                status = FreshnessStatus.fresh
        elif result is VerificationResult.stale:
            status = FreshnessStatus.stale
        elif result is VerificationResult.unknown and status is FreshnessStatus.fresh:
            status = FreshnessStatus.unknown
    return obj.evolve(
        last_verified_at=now,
        verification_result=result,
        freshness_status=status,
        updated_at=now,
    )


__all__ = [
    "MAX_ATTEMPTS",
    "RETRY_BASE_SECONDS",
    "ApplyChange",
    "FreshnessService",
    "ProbeFor",
    "SystemClock",
]
