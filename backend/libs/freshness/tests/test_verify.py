"""Query-time live verification (spec: "Query-time verification", "Live-verification failure")."""

from __future__ import annotations

import pytest
from freshness import (
    ChangePage,
    EvidenceClass,
    FailureAction,
    FreshnessStatus,
    ListChangeSource,
    PolicyNotFound,
    ProbeUnavailable,
    ProviderHead,
    ScriptedProbe,
    VerificationResult,
    VerifyRequest,
)

KEY = ("confluence-ops", "page-1")


def _request(evidence_class: EvidenceClass = EvidenceClass.critical, **extra) -> VerifyRequest:
    return VerifyRequest(
        source_id="confluence-ops",
        external_object_id=extra.pop("object_id", "page-1"),
        connector_kind=extra.pop("kind", "confluence"),
        evidence_class=evidence_class,
    )


@pytest.fixture
async def indexed(service, make_change, make_sync, apply) -> None:
    """page-1 indexed at provider version 7 (fresh, never verified)."""
    source = ListChangeSource([ChangePage(changes=[make_change("page-1", "7", content_hash="h7")])])
    await service.connector_sync(make_sync(), change_source=source, apply=apply)


async def test_matching_head_verifies_fresh(service, store, indexed, clock) -> None:
    probe = ScriptedProbe({"page-1": ProviderHead(provider_version="7", content_hash="h7")})

    result = await service.verify_freshness(_request(), probe)

    assert result.verification_result is VerificationResult.fresh
    assert result.freshness_status is FreshnessStatus.fresh
    assert result.safe_to_use is True and result.fallback_action is None
    assert (result.indexed_provider_version, result.observed_provider_version) == ("7", "7")
    obj = store.objects[KEY]
    assert obj.last_verified_at == clock.now()
    assert obj.verification_result is VerificationResult.fresh


async def test_mismatch_is_stale_and_critical_is_unsafe(service, store, indexed) -> None:
    probe = ScriptedProbe({"page-1": ProviderHead(provider_version="8")})

    result = await service.verify_freshness(_request(), probe)

    assert result.verification_result is VerificationResult.stale
    assert result.freshness_status is FreshnessStatus.stale
    assert result.safe_to_use is False
    assert result.fallback_action is FailureAction.omit
    assert result.reason == "provider_newer"
    assert store.objects[KEY].freshness_status is FreshnessStatus.stale


async def test_probe_transport_failure_is_unknown_never_fresh(service, store, indexed) -> None:
    ok = ScriptedProbe({"page-1": ProviderHead(provider_version="7")})
    await service.verify_freshness(_request(), ok)
    assert store.objects[KEY].freshness_status is FreshnessStatus.fresh

    down = ScriptedProbe({"page-1": ProbeUnavailable("timeout")})
    result = await service.verify_freshness(_request(), down)

    assert result.verification_result is VerificationResult.unknown
    assert result.freshness_status is FreshnessStatus.unknown
    assert result.reason == "probe_unavailable"
    assert result.safe_to_use is False
    assert store.objects[KEY].freshness_status is FreshnessStatus.unknown  # downgraded, not kept


@pytest.mark.parametrize(
    ("heads", "reason"),
    [
        ({"page-1": RuntimeError("boom")}, "probe_error"),
        ({}, "probe_unavailable"),  # no answer for this object
    ],
)
async def test_any_probe_failure_is_unknown(service, indexed, heads, reason) -> None:
    result = await service.verify_freshness(_request(), ScriptedProbe(heads))

    assert result.verification_result is VerificationResult.unknown
    assert result.freshness_status is not FreshnessStatus.fresh
    assert result.reason == reason


async def test_provider_deletion_is_stale(service, indexed) -> None:
    probe = ScriptedProbe({"page-1": ProviderHead(provider_version="7", deleted=True)})

    result = await service.verify_freshness(_request(), probe)

    assert result.verification_result is VerificationResult.stale
    assert result.reason == "provider_deleted"
    assert result.safe_to_use is False


async def test_content_hash_mismatch_is_stale(service, indexed) -> None:
    probe = ScriptedProbe({"page-1": ProviderHead(provider_version="7", content_hash="other")})

    result = await service.verify_freshness(_request(), probe)

    assert result.verification_result is VerificationResult.stale
    assert result.reason == "content_hash_mismatch"


async def test_standard_mismatch_is_allowed_with_warning(service, indexed) -> None:
    probe = ScriptedProbe({"page-1": ProviderHead(provider_version="8")})

    result = await service.verify_freshness(_request(EvidenceClass.standard), probe)

    assert result.freshness_status is FreshnessStatus.stale
    assert result.safe_to_use is True
    assert result.fallback_action is FailureAction.allow_with_warning


async def test_matching_head_does_not_make_unsearchable_content_fresh(
    service, store, make_change, make_sync, apply
) -> None:
    apply.partial.add("page-1")
    source = ListChangeSource([ChangePage(changes=[make_change("page-1", "7")])])
    await service.connector_sync(make_sync(), change_source=source, apply=apply)

    result = await service.verify_freshness(
        _request(), ScriptedProbe({"page-1": ProviderHead(provider_version="7")})
    )

    assert result.verification_result is VerificationResult.fresh
    assert result.freshness_status is FreshnessStatus.not_searchable
    assert result.safe_to_use is False


async def test_unknown_object_is_unknown_and_unsafe(service) -> None:
    result = await service.verify_freshness(
        _request(object_id="never-seen"), ScriptedProbe({"never-seen": ProviderHead()})
    )

    assert result.verification_result is VerificationResult.unknown
    assert result.reason == "object_not_found"
    assert result.safe_to_use is False


async def test_missing_policy_raises(service, indexed) -> None:
    with pytest.raises(PolicyNotFound):
        await service.verify_freshness(_request(kind="slack"), ScriptedProbe({}))
