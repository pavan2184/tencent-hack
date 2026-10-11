"""Ports the app implements (store, clock, probe, change source) and the library's error types.

The app implements :class:`FreshnessStore` in ``app/adapters/freshness_store.py`` over the
``0100_freshness_init.sql`` tables (SQLAlchemy async). Each method docstring states the invariant
the implementation MUST enforce itself; :class:`freshness.memory.InMemoryFreshnessStore` is the
executable reference and the library's tests run against it.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Protocol, runtime_checkable

from freshness.enums import ConnectorKind, EventState, EvidenceClass, FreshnessStatus
from freshness.models import (
    ChangePage,
    ConnectorCheckpoint,
    FreshnessPolicy,
    FreshnessReceipt,
    ObjectFreshness,
    ProviderHead,
    SourceChangeEvent,
    SyncRun,
)

# --------------------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------------------


class FreshnessError(Exception):
    """Base class. ``code`` is a stable, machine-readable error code (safe to put in envelopes)."""

    code = "freshness_error"


class CursorConflict(FreshnessError):
    """A checkpoint compare-and-swap lost: someone else moved the cursor first."""

    code = "cursor_conflict"


class VersionRegression(FreshnessError):
    """An older comparable provider version tried to overwrite newer object state."""

    code = "version_regression"


class ReceiptConflict(FreshnessError):
    """Same ``request_key`` was reused for a different request payload."""

    code = "receipt_conflict"


class ProbeUnavailable(FreshnessError):
    """The provider could not be reached; provider truth is unknown (never 'fresh')."""

    code = "provider_unavailable"


class PolicyNotFound(FreshnessError):
    """No active policy for a (connector_kind, evidence_class) pair."""

    code = "policy_not_found"


# --------------------------------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------------------------------


@runtime_checkable
class Clock(Protocol):
    """Source of time. The service never calls ``datetime.now()`` itself."""

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        ...


@runtime_checkable
class ProviderProbe(Protocol):
    """Live, lightweight provider read used by ``verify_freshness``."""

    async def head(self, external_object_id: str) -> ProviderHead:
        """Return provider truth for one object.

        Invariant: on transport failure, timeout, or rate limiting raise :class:`ProbeUnavailable`;
        never guess or return cached state. A deleted object returns ``deleted=True``.
        """
        ...


@runtime_checkable
class ChangeSource(Protocol):
    """Paged provider change listing (a connector's delta/reconcile feed)."""

    async def list_changes(self, cursor: str | None, *, limit: int) -> ChangePage:
        """Return up to ``limit`` changes after ``cursor`` (``None`` = from the beginning).

        Invariant: ``next_cursor`` is the opaque position *after* this page; listing it again must
        not skip changes. ``has_more=False`` means the feed is drained for now.
        """
        ...


@runtime_checkable
class FreshnessStore(Protocol):
    """Durable freshness state. Every method is async; every invariant below is the store's job.

    Rows are keyed source-scoped: ``(source_id, scope_key)``, ``(source_id, provider_event_id)``,
    ``(source_id, external_object_id)``, ``(source_id, scope_key, idempotency_key)``,
    ``(policy_id, schema_version)``, ``request_key``.
    """

    # ---- connector_checkpoints -------------------------------------------------------------------

    async def get_checkpoint(self, source_id: str, scope_key: str) -> ConnectorCheckpoint | None:
        """Return the checkpoint for one scope, or ``None`` if the scope has never been written."""
        ...

    async def cas_checkpoint(
        self, checkpoint: ConnectorCheckpoint, *, expected_version: int
    ) -> ConnectorCheckpoint:
        """Compare-and-swap write of a whole checkpoint row.

        Invariant: let ``current`` be the stored ``cursor_version`` (0 when no row exists). If
        ``current != expected_version`` raise :class:`CursorConflict` and write nothing. Otherwise
        write ``checkpoint`` with ``cursor_version = expected_version + 1`` and return the stored
        row. A ``last_successful_run_id`` that changes must reference a ``completed`` run
        (raise :class:`FreshnessError` otherwise) — a failed/partial run never stamps success.
        SQL: ``UPDATE … WHERE cursor_version = :expected`` (or ``INSERT … ON CONFLICT DO UPDATE …
        WHERE cursor_version = 0`` when expected is 0); zero rows affected → ``CursorConflict``.
        """
        ...

    # ---- source_change_events --------------------------------------------------------------------

    async def accept_event(self, event: SourceChangeEvent) -> SourceChangeEvent:
        """Durably append ``event`` unless ``(source_id, provider_event_id)`` already exists.

        Invariant: on duplicate, write nothing and return the EXISTING row (callers detect a
        duplicate by ``returned.id != event.id``). Never returns before the row is durable.
        """
        ...

    async def update_event_state(self, event: SourceChangeEvent) -> SourceChangeEvent:
        """Persist the mutable fields of an existing event (matched by ``event.id``).

        Mutable fields: ``state, attempt_count, next_attempt_at, last_error_code, applied_at,
        parked_at, noop_reason``. Identity fields never change. Invariant: an ``applied`` event is
        terminal — any further change raises :class:`FreshnessError`. Unknown id raises too.
        """
        ...

    async def list_events(
        self,
        source_id: str,
        scope_key: str | None = None,
        *,
        states: Collection[EventState] | None = None,
        limit: int = 1000,
    ) -> list[SourceChangeEvent]:
        """Return events for a source (optionally one scope / some states), oldest first.

        Ordered by ``(accepted_at, id)``; at most ``limit`` rows.
        """
        ...

    # ---- object_freshness ------------------------------------------------------------------------

    async def get_object(self, source_id: str, external_object_id: str) -> ObjectFreshness | None:
        """Return current state of one provider object, or ``None``."""
        ...

    async def upsert_object(self, obj: ObjectFreshness) -> ObjectFreshness:
        """Insert or replace the row for ``(obj.source_id, obj.external_object_id)``.

        Invariant: call :func:`freshness.versioning.assert_can_replace(stored, obj)` against the
        locked current row (``SELECT … FOR UPDATE``) before writing. It raises
        :class:`VersionRegression` when an older comparable version would overwrite a newer one, or
        when a tombstone would be cleared by anything but a strictly newer comparable version.
        """
        ...

    async def list_objects(
        self,
        source_id: str,
        *,
        statuses: Collection[FreshnessStatus] | None = None,
        limit: int = 10_000,
    ) -> list[ObjectFreshness]:
        """Return objects of a source (optionally filtered by status), ordered by object id."""
        ...

    # ---- sync_runs -------------------------------------------------------------------------------

    async def create_run(self, run: SyncRun) -> SyncRun:
        """Insert ``run`` unless ``(source_id, scope_key, idempotency_key)`` exists.

        Invariant: on an existing key, write nothing and return the EXISTING run, so a replayed
        request finds the same run (callers detect replay by ``returned.id != run.id``).
        """
        ...

    async def update_run(self, run: SyncRun) -> SyncRun:
        """Replace an existing run (matched by ``run.id``); its idempotency triple never changes."""
        ...

    async def get_run(self, run_id: str) -> SyncRun | None:
        """Return one run by id, or ``None``."""
        ...

    # ---- freshness_policies ----------------------------------------------------------------------

    async def get_active_policy(
        self, connector_kind: ConnectorKind, evidence_class: EvidenceClass
    ) -> FreshnessPolicy | None:
        """Return the single ``active`` policy for the pair, or ``None`` (caller decides)."""
        ...

    async def put_policy(self, policy: FreshnessPolicy) -> FreshnessPolicy:
        """Upsert by ``(policy_id, schema_version)``.

        Invariant: at most one ``active`` policy per ``(connector_kind, evidence_class)`` — writing
        an active policy retires any other active row for that pair. Revisions are new
        ``schema_version`` rows; idempotent re-puts of the same row are allowed (seeding).
        """
        ...

    # ---- freshness_receipts ----------------------------------------------------------------------

    async def save_receipt(self, receipt: FreshnessReceipt) -> FreshnessReceipt:
        """Atomically reserve ``receipt.request_key`` and store the immutable receipt.

        Invariant: if the key exists, resolve with :func:`freshness.receipt.check_replay`: same
        ``request_payload_hash`` → return the EXISTING receipt unchanged (even if state changed
        since); different hash → raise :class:`ReceiptConflict`. Receipts are never updated.
        """
        ...

    async def get_receipt(self, receipt_id: str) -> FreshnessReceipt | None:
        """Return one receipt by id, or ``None``."""
        ...

    async def get_receipt_by_request_key(self, request_key: str) -> FreshnessReceipt | None:
        """Return the receipt that owns ``request_key``, or ``None``."""
        ...
