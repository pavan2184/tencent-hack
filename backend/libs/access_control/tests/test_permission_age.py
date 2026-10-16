"""Permission snapshots go stale: a revocation at the source can only go unnoticed for as long
as the classification's maximum snapshot age."""

from __future__ import annotations

from datetime import timedelta

import pytest
from access_control import (
    DEFAULT_MAX_PERMISSION_AGE,
    Classification,
    DefaultAccessPolicy,
    DenyReason,
    Effect,
    SubjectType,
)

STALE_RULE = "R9:permission_snapshot_stale"


def _decide(policy, principal, doc, at):
    return policy.decide(principal, doc, now=at)


@pytest.mark.parametrize(
    "classification",
    [Classification.public, Classification.internal],
)
def test_snapshot_trusted_until_its_maximum_age(
    policy, people, make_doc, seed_blocks, now, classification
):
    doc = make_doc(seed_blocks["confluence"], classification=classification)
    max_age = DEFAULT_MAX_PERMISSION_AGE[classification]

    fresh = _decide(policy, people["jordan"], doc, now + max_age)
    assert fresh.decision == Effect.allow

    stale = _decide(policy, people["jordan"], doc, now + max_age + timedelta(seconds=1))
    assert stale.decision == Effect.deny
    assert stale.reason == DenyReason.unknown_permissions
    assert stale.matched_rule == STALE_RULE


def test_confidential_access_needs_a_snapshot_under_five_minutes(
    policy, people, make_doc, make_grant, seed_blocks, now
):
    doc = make_doc(
        seed_blocks["confluence"],
        classification=Classification.confidential,
        grants=[make_grant(SubjectType.group, "leadership")],
    )
    assert _decide(policy, people["john"], doc, now + timedelta(minutes=5)).allowed
    late = _decide(policy, people["john"], doc, now + timedelta(minutes=5, seconds=1))
    assert late.decision == Effect.deny
    assert late.matched_rule == STALE_RULE


@pytest.mark.parametrize("shortcut", ["owner", "admin", "grant"])
def test_owner_admin_or_grant_cannot_outlive_a_stale_snapshot(
    policy, people, make_doc, make_grant, seed_blocks, now, shortcut
):
    principal = people["john"]
    if shortcut == "admin":
        principal = principal.model_copy(update={"roles": ["admin"]})
    doc = make_doc(
        seed_blocks["confluence"],
        classification=Classification.restricted,
        owner=principal.id if shortcut == "owner" else None,
        grants=[make_grant(SubjectType.principal, principal.id)] if shortcut == "grant" else [],
    )
    assert _decide(policy, principal, doc, now).allowed
    stale = _decide(policy, principal, doc, now + timedelta(minutes=6))
    assert stale.decision == Effect.deny
    assert stale.matched_rule == STALE_RULE


def test_revoked_grant_still_explains_a_stale_denial(
    policy, people, make_doc, make_grant, seed_blocks, now
):
    doc = make_doc(
        seed_blocks["confluence"],
        grants=[make_grant(SubjectType.principal, "jordan.lim", revoked=True)],
    )
    stale = _decide(policy, people["jordan"], doc, now + timedelta(hours=2))
    assert stale.matched_rule == STALE_RULE
    assert stale.reason == DenyReason.grant_revoked


def test_uploads_are_exempt_because_their_permissions_are_local(
    policy, people, make_doc, seed_blocks, now
):
    doc = make_doc(
        seed_blocks["upload"], owner="alex.tan", classification=Classification.restricted
    )
    assert _decide(policy, people["alex"], doc, now + timedelta(days=30)).allowed


def test_snapshot_from_the_future_is_not_trusted(policy, people, make_doc, seed_blocks, now):
    doc = make_doc(seed_blocks["confluence"])
    within_skew = _decide(policy, people["jordan"], doc, now - timedelta(seconds=59))
    assert within_skew.allowed
    beyond_skew = _decide(policy, people["jordan"], doc, now - timedelta(minutes=2))
    assert beyond_skew.decision == Effect.deny
    assert beyond_skew.matched_rule == STALE_RULE


def test_decisions_record_when_the_snapshot_was_captured(
    policy, people, make_doc, seed_blocks, now
):
    doc = make_doc(seed_blocks["confluence"])
    allowed = _decide(policy, people["jordan"], doc, now)
    denied = _decide(policy, people["mei"], doc, now)
    assert allowed.permission_captured_at == denied.permission_captured_at == now
    missing = _decide(policy, people["jordan"], make_doc(None), now)
    assert missing.permission_captured_at is None


def test_age_check_can_be_disabled_for_offline_tools(people, make_doc, seed_blocks, now):
    policy = DefaultAccessPolicy(max_permission_age=None)
    doc = make_doc(seed_blocks["confluence"], classification=Classification.internal)
    assert _decide(policy, people["jordan"], doc, now + timedelta(days=365)).allowed


def test_custom_ages_apply(people, make_doc, seed_blocks, now):
    ages = {c: timedelta(minutes=1) for c in Classification}
    policy = DefaultAccessPolicy(max_permission_age=ages)
    doc = make_doc(seed_blocks["confluence"], classification=Classification.public)
    assert not _decide(policy, people["jordan"], doc, now + timedelta(minutes=2)).allowed


@pytest.mark.parametrize(
    "ages",
    [
        {Classification.public: timedelta(hours=1)},
        {c: timedelta(0) for c in Classification},
        {c: timedelta(minutes=-1) for c in Classification},
    ],
)
def test_incomplete_or_non_positive_ages_are_rejected(ages):
    with pytest.raises(ValueError):
        DefaultAccessPolicy(max_permission_age=ages)
