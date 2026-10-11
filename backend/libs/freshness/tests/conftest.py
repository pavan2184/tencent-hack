"""Shared fixtures. Tests never import this module directly (works under any pytest import mode)."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from freshness import (
    ChangeKind,
    ConnectorKind,
    ConnectorSyncRequest,
    EvidenceClass,
    FailureAction,
    FixedClock,
    FreshnessPolicy,
    FreshnessService,
    FreshnessStatus,
    IndexOutcome,
    InMemoryFreshnessStore,
    NormalizedChange,
    ObjectFreshness,
    SyncPath,
)

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
SOURCE = "confluence-ops"


class RecordingApply:
    """Fake app indexer (stands in for ``ingestion.apply_change``): records every call.

    ``fail`` → raise; ``partial`` → content written but not searchable/embedded;
    ``not_removed`` → a delete whose removal does not complete; ``versions`` → report a fetched
    provider version different from the change's.
    """

    def __init__(self, clock: FixedClock) -> None:
        self.clock = clock
        self.calls: list[NormalizedChange] = []
        self.fail: set[str] = set()
        self.partial: set[str] = set()
        self.not_removed: set[str] = set()
        self.versions: dict[str, tuple[str, int | None]] = {}

    async def __call__(self, change: NormalizedChange) -> IndexOutcome:
        self.calls.append(change)
        oid = change.external_object_id
        if oid in self.fail:
            raise RuntimeError(f"indexing failed for {oid}")
        now = self.clock.now()
        if change.change_kind is ChangeKind.delete:
            if oid in self.not_removed:
                return IndexOutcome(content_written=True, searchable=True, embedded=True)
            return IndexOutcome(content_written=False, searchable=False, embedded=False)
        fetched = self.versions.get(oid)
        extra: dict[str, Any] = {"page_id": f"pg-{oid}", "page_slug": oid}
        if fetched is not None:
            extra |= {"provider_version": fetched[0], "version_order": fetched[1]}
        if oid in self.partial:
            return IndexOutcome(
                content_written=True, searchable=False, embedded=False, indexed_at=now, **extra
            )
        return IndexOutcome(
            content_written=True,
            searchable=True,
            embedded=True,
            indexed_at=now,
            searchable_at=now,
            **extra,
        )

    def count(self, object_id: str) -> int:
        return sum(1 for c in self.calls if c.external_object_id == object_id)


@pytest.fixture
def t0() -> datetime:
    return T0


@pytest.fixture
def source_id() -> str:
    return SOURCE


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def critical_policy() -> FreshnessPolicy:
    return FreshnessPolicy(
        policy_id="confluence.critical",
        connector_kind=ConnectorKind.confluence,
        evidence_class=EvidenceClass.critical,
        max_index_age_seconds=300,
        max_verification_age_seconds=60,
        require_live_verification=True,
        failure_action=FailureAction.omit,
        effective_at=T0,
    )


@pytest.fixture
def standard_policy() -> FreshnessPolicy:
    return FreshnessPolicy(
        policy_id="confluence.standard",
        connector_kind=ConnectorKind.confluence,
        evidence_class=EvidenceClass.standard,
        max_index_age_seconds=3600,
        max_verification_age_seconds=3600,
        require_live_verification=False,
        failure_action=FailureAction.allow_with_warning,
        effective_at=T0,
    )


@pytest.fixture
def store(
    critical_policy: FreshnessPolicy, standard_policy: FreshnessPolicy
) -> InMemoryFreshnessStore:
    return InMemoryFreshnessStore(policies=[critical_policy, standard_policy])


@pytest.fixture
def service(store: InMemoryFreshnessStore, clock: FixedClock) -> FreshnessService:
    return FreshnessService(store, clock)


@pytest.fixture
def apply(clock: FixedClock) -> RecordingApply:
    return RecordingApply(clock)


@pytest.fixture
def make_change(clock: FixedClock) -> Callable[..., NormalizedChange]:
    def _make(
        object_id: str = "page-1",
        version: str | None = "1",
        *,
        kind: ChangeKind = ChangeKind.upsert,
        event_id: str | None = None,
        order: int | None = None,
        source_id: str = SOURCE,
        **extra: Any,
    ) -> NormalizedChange:
        return NormalizedChange(
            source_id=source_id,
            connector_kind=ConnectorKind.confluence,
            provider_event_id=event_id or f"evt-{object_id}-{version}-{kind}",
            external_object_id=object_id,
            change_kind=kind,
            provider_version=version,
            version_order=order,
            observed_at=clock.now(),
            **extra,
        )

    return _make


@pytest.fixture
def make_sync() -> Callable[..., ConnectorSyncRequest]:
    counter = itertools.count(1)

    def _make(
        trigger: SyncPath = SyncPath.delta, *, key: str | None = None, **extra: Any
    ) -> ConnectorSyncRequest:
        return ConnectorSyncRequest(
            source_id=SOURCE,
            connector_kind=ConnectorKind.confluence,
            trigger_kind=trigger,
            idempotency_key=key or f"run-{next(counter)}",
            **extra,
        )

    return _make


@pytest.fixture
def make_object() -> Callable[..., ObjectFreshness]:
    """A fresh, searchable object indexed at T0 (override any field)."""

    def _make(**overrides: Any) -> ObjectFreshness:
        fields: dict[str, Any] = {
            "source_id": SOURCE,
            "external_object_id": "page-1",
            "connector_kind": ConnectorKind.confluence,
            "page_id": "pg-page-1",
            "page_slug": "page-1",
            "provider_version": "7",
            "content_hash": "h7",
            "observed_at": T0,
            "accepted_at": T0,
            "indexed_at": T0,
            "searchable_at": T0,
            "sync_path": SyncPath.delta,
            "freshness_status": FreshnessStatus.fresh,
        }
        fields.update(overrides)
        return ObjectFreshness(**fields)

    return _make
