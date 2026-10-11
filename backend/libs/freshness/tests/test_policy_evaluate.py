"""Pure policy evaluation: budgets, verification age, safe-use and fallbacks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from freshness import (
    ConnectorKind,
    EvidenceClass,
    EvidenceRef,
    FailureAction,
    FreshnessPolicy,
    FreshnessStatus,
    VerificationResult,
    evaluate,
    evaluate_missing,
)


def test_fresh_within_budget(make_object, standard_policy, t0) -> None:
    item = evaluate(make_object(), standard_policy, t0 + timedelta(seconds=10))

    assert item.freshness_status is FreshnessStatus.fresh
    assert item.age_seconds == 10
    assert item.budget_seconds == 3600
    assert item.safe_to_use is True
    assert item.fallback_action is None
    assert item.verification_result is VerificationResult.not_required
    assert (item.policy_id, item.policy_schema_version) == ("confluence.standard", 1)


def test_index_age_budget_boundary(make_object, standard_policy, t0) -> None:
    at_budget = evaluate(make_object(), standard_policy, t0 + timedelta(seconds=3600))
    over = evaluate(make_object(), standard_policy, t0 + timedelta(seconds=3601))

    assert at_budget.freshness_status is FreshnessStatus.fresh
    assert over.freshness_status is FreshnessStatus.stale
    assert over.reason == "index_age_exceeded"


def test_age_uses_last_verified_at_when_verification_matched(
    make_object, critical_policy, t0
) -> None:
    obj = make_object(
        last_verified_at=t0 + timedelta(seconds=280),
        verification_result=VerificationResult.fresh,
    )
    item = evaluate(obj, critical_policy, t0 + timedelta(seconds=310))

    assert item.age_seconds == 30  # now − last_verified_at, not now − searchable_at (310)
    assert item.freshness_status is FreshnessStatus.fresh


def test_required_live_verification_missing_is_unknown(make_object, critical_policy, t0) -> None:
    item = evaluate(make_object(), critical_policy, t0 + timedelta(seconds=5))

    assert item.freshness_status is FreshnessStatus.unknown
    assert item.reason == "verification_missing"
    assert item.safe_to_use is False


def test_verification_older_than_budget_is_unknown_not_fresh(
    make_object, critical_policy, t0
) -> None:
    obj = make_object(last_verified_at=t0, verification_result=VerificationResult.fresh)

    within = evaluate(obj, critical_policy, t0 + timedelta(seconds=60))
    expired = evaluate(obj, critical_policy, t0 + timedelta(seconds=61))

    assert within.freshness_status is FreshnessStatus.fresh
    assert expired.freshness_status is FreshnessStatus.unknown
    assert expired.reason == "verification_expired"
    assert expired.safe_to_use is False


def test_unknown_verification_never_upgrades_to_fresh(make_object, standard_policy, t0) -> None:
    # A probe failure seconds ago: the timestamp is recent, but it proved nothing.
    obj = make_object(last_verified_at=t0, verification_result=VerificationResult.unknown)
    assert evaluate(obj, standard_policy, t0).freshness_status is FreshnessStatus.unknown

    stored_unknown = make_object(
        freshness_status=FreshnessStatus.unknown,
        last_verified_at=t0,
        verification_result=VerificationResult.fresh,
    )
    assert evaluate(stored_unknown, standard_policy, t0).freshness_status is FreshnessStatus.unknown


def test_written_but_not_searchable_is_never_fresh(make_object, standard_policy, t0) -> None:
    obj = make_object(freshness_status=FreshnessStatus.not_searchable, searchable_at=None)
    item = evaluate(obj, standard_policy, t0)

    assert item.freshness_status is FreshnessStatus.not_searchable
    assert item.age_seconds is None


def test_critical_non_fresh_is_unsafe_with_policy_fallback(
    make_object, critical_policy, t0
) -> None:
    stale = make_object(freshness_status=FreshnessStatus.stale)
    abstain_policy = critical_policy.evolve(
        policy_id="confluence.critical.v2", schema_version=2, failure_action=FailureAction.abstain
    )
    ref = EvidenceRef(
        source_id="confluence-ops",
        external_object_id="page-1",
        connector_kind=ConnectorKind.confluence,
        evidence_class=EvidenceClass.critical,
    )

    omitted = evaluate(stale, critical_policy, t0, ref=ref)
    abstained = evaluate(stale, abstain_policy, t0, ref=ref)

    assert (omitted.safe_to_use, omitted.fallback_action) == (False, FailureAction.omit)
    assert (abstained.safe_to_use, abstained.fallback_action) == (False, FailureAction.abstain)
    assert omitted.freshness_status is FreshnessStatus.stale


def test_standard_evidence_follows_policy_failure_action(make_object, standard_policy, t0) -> None:
    stale = make_object(freshness_status=FreshnessStatus.stale)
    strict = standard_policy.evolve(failure_action=FailureAction.omit)

    warned = evaluate(stale, standard_policy, t0)
    omitted = evaluate(stale, strict, t0)

    assert warned.freshness_status is FreshnessStatus.stale  # status preserved
    assert (warned.safe_to_use, warned.fallback_action) == (
        True,
        FailureAction.allow_with_warning,
    )
    assert (omitted.safe_to_use, omitted.fallback_action) == (False, FailureAction.omit)


def test_missing_object_or_policy_is_unknown_and_never_defaults_to_fresh() -> None:
    ref = EvidenceRef(
        source_id="s",
        external_object_id="o",
        connector_kind=ConnectorKind.slack,
        evidence_class=EvidenceClass.standard,
    )
    no_policy = evaluate_missing(ref, None, reason="policy_not_found")

    assert no_policy.freshness_status is FreshnessStatus.unknown
    assert (no_policy.safe_to_use, no_policy.fallback_action) == (False, FailureAction.omit)
    critical_missing = evaluate_missing(
        ref.evolve(evidence_class=EvidenceClass.critical),
        FreshnessPolicy(
            policy_id="slack.critical",
            connector_kind=ConnectorKind.slack,
            evidence_class=EvidenceClass.critical,
            max_index_age_seconds=60,
            max_verification_age_seconds=60,
            failure_action=FailureAction.abstain,
            effective_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )
    assert critical_missing.safe_to_use is False
    assert critical_missing.fallback_action is FailureAction.abstain


def test_evaluate_is_pure(make_object, critical_policy, t0) -> None:
    obj = make_object()
    snapshot = obj.model_dump()

    first = evaluate(obj, critical_policy, t0)
    second = evaluate(obj, critical_policy, t0)

    assert first == second
    assert obj.model_dump() == snapshot
