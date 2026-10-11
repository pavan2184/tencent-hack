"""Version comparison and reordered delivery (spec: "Reordered delivery")."""

from __future__ import annotations

import pytest
from freshness import (
    ChangePage,
    EventState,
    EvidenceClass,
    FreshnessStatus,
    ListChangeSource,
    ProviderHead,
    ScriptedProbe,
    VerificationResult,
    VerifyRequest,
    VersionRegression,
    compare,
    evaluate,
)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (("7", 7), ("8", 8), "older"),
        (("8", 8), ("7", 7), "newer"),
        (("7", 7), ("7", 7), "same"),
        (("7", 7), ("x7", 7), "incomparable"),  # equal orders, contradicting tokens
        (("r-a", 1), ("r-b", 2), "older"),  # orders decide over opaque tokens
        (("7", None), ("8", None), "older"),  # decimal tokens compare numerically
        (("10", None), ("9", None), "newer"),  # numerically, not lexicographically
        (("07", None), ("7", None), "same"),
        (("abc", None), ("abc", None), "same"),
        (("abc", None), ("xyz", None), "incomparable"),
        ((None, None), ("7", 7), "incomparable"),
        (("7", 7), (None, None), "incomparable"),
        ((None, None), (None, None), "incomparable"),
    ],
)
def test_compare_matrix(a, b, expected) -> None:
    assert compare(a[0], a[1], b[0], b[1]) == expected


async def test_older_comparable_version_never_overwrites_newer(
    service, store, make_change, make_sync, apply
) -> None:
    newer = make_change("page-1", "8", event_id="e-8")
    older = make_change("page-1", "7", event_id="e-7")  # delivered late
    source = ListChangeSource([ChangePage(changes=[newer, older])])

    result = await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert [c.provider_version for c in apply.calls] == ["8"]  # older never reaches apply
    assert result.noop_count == 1
    obj = store.objects[("confluence-ops", "page-1")]
    assert obj.provider_version == "8"
    assert obj.freshness_status is FreshnessStatus.fresh
    older_event = next(e for e in store.events.values() if e.provider_event_id == "e-7")
    assert older_event.state is EventState.applied
    assert older_event.noop_reason == "older_version"


async def test_store_rejects_version_regression(store, make_object) -> None:
    await store.upsert_object(make_object(provider_version="8"))
    with pytest.raises(VersionRegression):
        await store.upsert_object(make_object(provider_version="7"))
    assert store.objects[("confluence-ops", "page-1")].provider_version == "8"


async def test_same_version_redelivery_is_noop(
    service, store, make_change, make_sync, apply
) -> None:
    source = ListChangeSource(
        [
            ChangePage(
                changes=[
                    make_change("page-1", "7", event_id="webhook-7"),
                    make_change("page-1", "7", event_id="delta-7"),  # same version, new id
                ]
            )
        ]
    )

    await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert apply.count("page-1") == 1
    delta = next(e for e in store.events.values() if e.provider_event_id == "delta-7")
    assert delta.noop_reason == "same_version_already_applied"


async def test_incomparable_version_is_applied_but_unknown_until_verified(
    service, store, make_change, make_sync, apply, critical_policy, clock
) -> None:
    first = ListChangeSource([ChangePage(changes=[make_change("page-1", "rev-abc")])])
    await service.connector_sync(make_sync(), change_source=first, apply=apply)
    assert store.objects[("confluence-ops", "page-1")].freshness_status is FreshnessStatus.fresh

    second = ListChangeSource([ChangePage(changes=[make_change("page-1", "rev-xyz")])])
    await service.connector_sync(make_sync(), change_source=second, apply=apply)

    assert apply.count("page-1") == 2  # incomparable requires apply …
    obj = store.objects[("confluence-ops", "page-1")]
    assert obj.provider_version == "rev-xyz"
    assert obj.freshness_status is FreshnessStatus.unknown  # … but is not current yet
    item = evaluate(obj, critical_policy, clock.now())
    assert item.freshness_status is FreshnessStatus.unknown
    assert item.safe_to_use is False

    probe = ScriptedProbe({"page-1": ProviderHead(provider_version="rev-xyz")})
    verified = await service.verify_freshness(
        VerifyRequest(
            source_id="confluence-ops",
            external_object_id="page-1",
            connector_kind="confluence",
            evidence_class=EvidenceClass.critical,
        ),
        probe,
    )
    assert verified.verification_result is VerificationResult.fresh
    assert verified.freshness_status is FreshnessStatus.fresh
    assert verified.safe_to_use is True


async def test_same_version_rearrival_does_not_upgrade_unknown(
    service, store, make_change, make_sync, apply
) -> None:
    for version in ("rev-abc", "rev-xyz"):
        source = ListChangeSource([ChangePage(changes=[make_change("page-1", version)])])
        await service.connector_sync(make_sync(), change_source=source, apply=apply)
    replay = ListChangeSource(
        [ChangePage(changes=[make_change("page-1", "rev-xyz", event_id="another-id")])]
    )

    await service.connector_sync(make_sync(), change_source=replay, apply=apply)

    assert store.objects[("confluence-ops", "page-1")].freshness_status is FreshnessStatus.unknown


async def test_version_actually_fetched_is_recorded(
    service, store, make_change, make_sync, apply
) -> None:
    apply.versions["page-1"] = ("9", 9)  # provider moved on between change and fetch
    source = ListChangeSource([ChangePage(changes=[make_change("page-1", "8", order=8)])])

    await service.connector_sync(make_sync(), change_source=source, apply=apply)

    obj = store.objects[("confluence-ops", "page-1")]
    assert (obj.provider_version, obj.version_order) == ("9", 9)
    assert obj.freshness_status is FreshnessStatus.fresh
