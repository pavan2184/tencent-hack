"""Deletion and tombstones (spec: "Deletion"; hard gate tombstone_accuracy = 1.0)."""

from __future__ import annotations

import pytest
from freshness import (
    ChangeKind,
    ChangePage,
    EventState,
    EvidenceClass,
    FailureAction,
    FreshnessStatus,
    ListChangeSource,
    ProviderHead,
    RunStatus,
    ScriptedProbe,
    VerificationResult,
    VerifyRequest,
    VersionRegression,
    evaluate,
)

KEY = ("confluence-ops", "page-1")


async def _sync(service, make_sync, apply, *changes):
    source = ListChangeSource([ChangePage(changes=list(changes))])
    return await service.connector_sync(make_sync(), change_source=source, apply=apply)


async def test_delete_creates_tombstone_never_fresh_never_searchable(
    service, store, make_change, make_sync, apply, standard_policy, clock
) -> None:
    await _sync(service, make_sync, apply, make_change("page-1", "1"))
    result = await _sync(
        service, make_sync, apply, make_change("page-1", "2", kind=ChangeKind.delete)
    )

    assert result.tombstoned_count == 1
    assert result.status is RunStatus.completed
    obj = store.objects[KEY]
    assert obj.freshness_status is FreshnessStatus.deleted
    assert obj.deleted_at is not None
    assert obj.tombstone_version == "2"
    assert obj.searchable_at is None and obj.indexed_at is None and obj.content_hash is None

    # Even a lenient standard policy (allow_with_warning) never makes a tombstone usable.
    assert standard_policy.failure_action is FailureAction.allow_with_warning
    item = evaluate(obj, standard_policy, clock.now())
    assert item.freshness_status is FreshnessStatus.deleted
    assert item.tombstoned is True
    assert item.safe_to_use is False
    assert item.fallback_action is FailureAction.omit


async def test_older_or_same_version_upsert_cannot_resurrect_tombstone(
    service, store, make_change, make_sync, apply
) -> None:
    await _sync(service, make_sync, apply, make_change("page-1", "2"))
    await _sync(service, make_sync, apply, make_change("page-1", "3", kind=ChangeKind.delete))
    calls_before = len(apply.calls)

    await _sync(
        service,
        make_sync,
        apply,
        make_change("page-1", "2", event_id="late-2"),
        make_change("page-1", "3", event_id="late-3"),
    )

    assert len(apply.calls) == calls_before
    assert store.objects[KEY].freshness_status is FreshnessStatus.deleted
    reasons = {e.provider_event_id: e.noop_reason for e in store.events.values()}
    assert reasons["late-2"] == "older_version"
    assert reasons["late-3"] == "tombstone_requires_newer_version"


async def test_incomparable_upsert_cannot_clear_tombstone(
    service, store, make_change, make_sync, apply
) -> None:
    await _sync(service, make_sync, apply, make_change("page-1", "2"))
    await _sync(service, make_sync, apply, make_change("page-1", "3", kind=ChangeKind.delete))

    await _sync(service, make_sync, apply, make_change("page-1", "rev-opaque"))

    assert store.objects[KEY].freshness_status is FreshnessStatus.deleted


async def test_strictly_newer_version_clears_tombstone(
    service, store, make_change, make_sync, apply
) -> None:
    await _sync(service, make_sync, apply, make_change("page-1", "2"))
    await _sync(service, make_sync, apply, make_change("page-1", "3", kind=ChangeKind.delete))

    await _sync(service, make_sync, apply, make_change("page-1", "4"))

    obj = store.objects[KEY]
    assert obj.freshness_status is FreshnessStatus.fresh
    assert obj.deleted_at is None and obj.tombstone_version is None


async def test_unversioned_delete_keeps_version_high_water(
    service, store, make_change, make_sync, apply
) -> None:
    await _sync(service, make_sync, apply, make_change("page-1", "5"))
    await _sync(
        service,
        make_sync,
        apply,
        make_change("page-1", None, kind=ChangeKind.delete, event_id="del-no-version"),
    )

    obj = store.objects[KEY]
    assert obj.freshness_status is FreshnessStatus.deleted
    assert obj.provider_version == "5"  # high-water retained


async def test_failed_removal_is_never_a_clean_delete(
    service, store, make_change, make_sync, apply, standard_policy, clock
) -> None:
    await _sync(service, make_sync, apply, make_change("page-1", "1"))
    apply.not_removed.add("page-1")

    result = await _sync(
        service, make_sync, apply, make_change("page-1", "2", kind=ChangeKind.delete)
    )

    assert result.status is RunStatus.partial
    assert result.tombstoned_count == 0
    assert result.parked_count == 1
    obj = store.objects[KEY]
    assert obj.freshness_status is FreshnessStatus.stale  # explicit unsafe state
    assert obj.deleted_at is not None
    event = next(e for e in store.events.values() if e.change_kind is ChangeKind.delete)
    assert event.state is EventState.parked
    assert event.last_error_code == "delete_not_removed"
    assert evaluate(obj, standard_policy, clock.now()).freshness_status is FreshnessStatus.stale


async def test_store_rejects_clearing_tombstone_without_newer_version(
    store, make_object, t0
) -> None:
    tombstone = make_object(
        provider_version="3",
        freshness_status=FreshnessStatus.deleted,
        deleted_at=t0,
        indexed_at=None,
        searchable_at=None,
    )
    await store.upsert_object(tombstone)
    with pytest.raises(VersionRegression, match="tombstone"):
        await store.upsert_object(make_object(provider_version="3"))
    await store.upsert_object(make_object(provider_version="4"))  # strictly newer is fine


async def test_verification_never_revives_a_tombstone(
    service, store, make_change, make_sync, apply
) -> None:
    await _sync(service, make_sync, apply, make_change("page-1", "1"))
    await _sync(service, make_sync, apply, make_change("page-1", "2", kind=ChangeKind.delete))
    request = VerifyRequest(
        source_id="confluence-ops",
        external_object_id="page-1",
        connector_kind="confluence",
        evidence_class=EvidenceClass.critical,
    )

    confirmed = await service.verify_freshness(
        request, ScriptedProbe({"page-1": ProviderHead(provider_version="2", deleted=True)})
    )
    alive = await service.verify_freshness(
        request, ScriptedProbe({"page-1": ProviderHead(provider_version="9")})
    )

    assert confirmed.verification_result is VerificationResult.fresh
    assert alive.verification_result is VerificationResult.stale
    for result in (confirmed, alive):
        assert result.freshness_status is FreshnessStatus.deleted
        assert result.safe_to_use is False
    assert store.objects[KEY].freshness_status is FreshnessStatus.deleted
