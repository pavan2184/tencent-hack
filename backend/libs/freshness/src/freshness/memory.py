"""In-memory implementations of the ports, used by this library's tests and the app's conftest.

``InMemoryFreshnessStore`` enforces every store invariant from :mod:`freshness.protocols` itself
(uniqueness, CAS, version regression, terminal events, receipt replay/conflict, successful-run
stamping), so it doubles as the executable reference for ``app/adapters/freshness_store.py``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import UTC, datetime, timedelta

from freshness.enums import (
    ConnectorKind,
    EventState,
    EvidenceClass,
    FreshnessStatus,
    PolicyStatus,
    RunStatus,
)
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
from freshness.protocols import CursorConflict, FreshnessError, ProbeUnavailable
from freshness.receipt import check_replay, verify_receipt_hash
from freshness.versioning import assert_can_replace

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


class InMemoryFreshnessStore:
    """Dict-backed :class:`~freshness.protocols.FreshnessStore`. Not thread-safe; asyncio-safe."""

    def __init__(self, *, policies: Iterable[FreshnessPolicy] = ()) -> None:
        self.checkpoints: dict[tuple[str, str], ConnectorCheckpoint] = {}
        self.events: dict[str, SourceChangeEvent] = {}
        self.objects: dict[tuple[str, str], ObjectFreshness] = {}
        self.runs: dict[str, SyncRun] = {}
        self.policies: dict[tuple[str, int], FreshnessPolicy] = {}
        self.receipts: dict[str, FreshnessReceipt] = {}
        self._event_keys: dict[tuple[str, str], str] = {}
        self._run_keys: dict[tuple[str, str, str], str] = {}
        self._receipt_keys: dict[str, str] = {}
        for policy in policies:
            self._put_policy(policy)

    # ---- connector_checkpoints -------------------------------------------------------------------

    async def get_checkpoint(self, source_id: str, scope_key: str) -> ConnectorCheckpoint | None:
        return self.checkpoints.get((source_id, scope_key))

    async def cas_checkpoint(
        self, checkpoint: ConnectorCheckpoint, *, expected_version: int
    ) -> ConnectorCheckpoint:
        key = (checkpoint.source_id, checkpoint.scope_key)
        current = self.checkpoints.get(key)
        current_version = current.cursor_version if current is not None else 0
        if current_version != expected_version:
            raise CursorConflict(
                f"checkpoint {key}: expected cursor_version {expected_version}, "
                f"found {current_version}"
            )
        run_id = checkpoint.last_successful_run_id
        previous = current.last_successful_run_id if current is not None else None
        if run_id is not None and run_id != previous:
            run = self.runs.get(run_id)
            if run is None or run.status is not RunStatus.completed:
                raise FreshnessError(
                    f"last_successful_run_id {run_id!r} must reference a completed run"
                )
        written = checkpoint.evolve(cursor_version=expected_version + 1)
        self.checkpoints[key] = written
        return written

    # ---- source_change_events --------------------------------------------------------------------

    async def accept_event(self, event: SourceChangeEvent) -> SourceChangeEvent:
        key = (event.source_id, event.provider_event_id)
        existing_id = self._event_keys.get(key)
        if existing_id is not None:
            return self.events[existing_id]
        if event.id in self.events:
            raise FreshnessError(f"event id {event.id!r} already used")
        self.events[event.id] = event
        self._event_keys[key] = event.id
        return event

    async def update_event_state(self, event: SourceChangeEvent) -> SourceChangeEvent:
        existing = self.events.get(event.id)
        if existing is None:
            raise FreshnessError(f"unknown event {event.id!r}")
        for name in _EVENT_IDENTITY:
            if getattr(existing, name) != getattr(event, name):
                raise FreshnessError(f"event {event.id!r}: identity field {name!r} is immutable")
        if existing.state is EventState.applied and event != existing:
            raise FreshnessError(f"event {event.id!r} is applied (terminal)")
        self.events[event.id] = event
        return event

    async def list_events(
        self,
        source_id: str,
        scope_key: str | None = None,
        *,
        states: Collection[EventState] | None = None,
        limit: int = 1000,
    ) -> list[SourceChangeEvent]:
        rows = [
            e
            for e in self.events.values()
            if e.source_id == source_id
            and (scope_key is None or e.scope_key == scope_key)
            and (states is None or e.state in states)
        ]
        rows.sort(key=lambda e: (e.accepted_at, e.id))
        return rows[:limit]

    # ---- object_freshness ------------------------------------------------------------------------

    async def get_object(self, source_id: str, external_object_id: str) -> ObjectFreshness | None:
        return self.objects.get((source_id, external_object_id))

    async def upsert_object(self, obj: ObjectFreshness) -> ObjectFreshness:
        key = (obj.source_id, obj.external_object_id)
        assert_can_replace(self.objects.get(key), obj)
        self.objects[key] = obj
        return obj

    async def list_objects(
        self,
        source_id: str,
        *,
        statuses: Collection[FreshnessStatus] | None = None,
        limit: int = 10_000,
    ) -> list[ObjectFreshness]:
        rows = [
            o
            for o in self.objects.values()
            if o.source_id == source_id and (statuses is None or o.freshness_status in statuses)
        ]
        rows.sort(key=lambda o: o.external_object_id)
        return rows[:limit]

    # ---- sync_runs -------------------------------------------------------------------------------

    async def create_run(self, run: SyncRun) -> SyncRun:
        key = (run.source_id, run.scope_key, run.idempotency_key)
        existing_id = self._run_keys.get(key)
        if existing_id is not None:
            return self.runs[existing_id]
        self.runs[run.id] = run
        self._run_keys[key] = run.id
        return run

    async def update_run(self, run: SyncRun) -> SyncRun:
        existing = self.runs.get(run.id)
        if existing is None:
            raise FreshnessError(f"unknown run {run.id!r}")
        identity = ("idempotency_key", "source_id", "scope_key")
        if any(getattr(existing, f) != getattr(run, f) for f in identity):
            raise FreshnessError(f"run {run.id!r}: idempotency identity is immutable")
        self.runs[run.id] = run
        return run

    async def get_run(self, run_id: str) -> SyncRun | None:
        return self.runs.get(run_id)

    # ---- freshness_policies ----------------------------------------------------------------------

    async def get_active_policy(
        self, connector_kind: ConnectorKind, evidence_class: EvidenceClass
    ) -> FreshnessPolicy | None:
        active = [
            p
            for p in self.policies.values()
            if p.status is PolicyStatus.active
            and p.connector_kind == connector_kind
            and p.evidence_class == evidence_class
        ]
        return max(active, key=lambda p: p.schema_version) if active else None

    async def put_policy(self, policy: FreshnessPolicy) -> FreshnessPolicy:
        return self._put_policy(policy)

    def _put_policy(self, policy: FreshnessPolicy) -> FreshnessPolicy:
        key = (policy.policy_id, policy.schema_version)
        if policy.status is PolicyStatus.active:
            for other_key, other in list(self.policies.items()):
                if (
                    other_key != key
                    and other.status is PolicyStatus.active
                    and other.connector_kind == policy.connector_kind
                    and other.evidence_class == policy.evidence_class
                ):
                    self.policies[other_key] = other.evolve(
                        status=PolicyStatus.retired, retired_at=policy.effective_at
                    )
        self.policies[key] = policy
        return policy

    # ---- freshness_receipts ----------------------------------------------------------------------

    async def save_receipt(self, receipt: FreshnessReceipt) -> FreshnessReceipt:
        existing_id = self._receipt_keys.get(receipt.request_key)
        if existing_id is not None:
            return check_replay(self.receipts[existing_id], receipt.request_payload_hash)
        if not verify_receipt_hash(receipt):
            raise FreshnessError(f"receipt {receipt.receipt_id!r}: receipt_hash does not match")
        self.receipts[receipt.receipt_id] = receipt
        self._receipt_keys[receipt.request_key] = receipt.receipt_id
        return receipt

    async def get_receipt(self, receipt_id: str) -> FreshnessReceipt | None:
        return self.receipts.get(receipt_id)

    async def get_receipt_by_request_key(self, request_key: str) -> FreshnessReceipt | None:
        receipt_id = self._receipt_keys.get(request_key)
        return self.receipts.get(receipt_id) if receipt_id is not None else None


class FixedClock:
    """Deterministic :class:`~freshness.protocols.Clock` for tests (logical time)."""

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = now.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now = self._now + timedelta(seconds=seconds)
        return self._now


class ScriptedProbe:
    """:class:`~freshness.protocols.ProviderProbe` answering from a dict.

    A value that is an ``Exception`` is raised; an id with no entry raises
    :class:`ProbeUnavailable`. ``heads`` stays mutable so tests can change provider truth.
    """

    def __init__(self, heads: dict[str, ProviderHead | Exception]) -> None:
        self.heads = heads
        self.calls: list[str] = []

    async def head(self, external_object_id: str) -> ProviderHead:
        self.calls.append(external_object_id)
        value = self.heads.get(external_object_id)
        if value is None:
            raise ProbeUnavailable(f"no scripted head for {external_object_id!r}")
        if isinstance(value, Exception):
            raise value
        return value


class ListChangeSource:
    """:class:`~freshness.protocols.ChangeSource` replaying fixed pages.

    ``pages[0]`` is returned for cursor ``start`` (default ``None``); page ``i`` for
    ``pages[i-1].next_cursor``. An ``Exception`` entry is raised when reached. Any other cursor
    returns an empty, drained page (re-listing after the last page yields nothing). ``limit`` is
    ignored (pages are pre-cut). Handy for one-off feeds too, e.g. a single uploaded document.
    """

    def __init__(self, pages: list[ChangePage | Exception], *, start: str | None = None) -> None:
        self.pages = pages
        self.start = start
        self.calls: list[str | None] = []

    async def list_changes(self, cursor: str | None, *, limit: int) -> ChangePage:
        self.calls.append(cursor)
        expected: str | None = self.start
        for index, page in enumerate(self.pages):
            if index > 0:
                previous = self.pages[index - 1]
                if isinstance(previous, Exception):
                    break
                expected = previous.next_cursor
                if expected is None:
                    break
            if cursor == expected:
                if isinstance(page, Exception):
                    raise page
                return page
        return ChangePage(changes=[], next_cursor=cursor, has_more=False)
