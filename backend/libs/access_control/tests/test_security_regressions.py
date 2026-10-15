"""Cases the original policy incorrectly authorised."""

from datetime import timedelta

import pytest
from access_control import Classification, DenyReason, Effect, SourceKind, SubjectType


@pytest.mark.parametrize("shortcut", ["owner", "admin", "grant"])
def test_source_ceiling_cannot_be_bypassed(
    policy, people, make_doc, make_grant, seed_blocks, now, shortcut
):
    principal = people["mei"]
    if shortcut == "admin":
        principal = principal.model_copy(update={"roles": ["admin"]})
    doc = make_doc(
        seed_blocks["confluence"],
        owner=principal.id if shortcut == "owner" else None,
        grants=[make_grant(SubjectType.principal, principal.id)] if shortcut == "grant" else [],
        classification=Classification.restricted,
    )
    decision = policy.decide(principal, doc, now=now)
    assert decision.decision == Effect.deny
    assert decision.reason == "no_source_membership"


@pytest.mark.parametrize("shortcut", ["owner", "admin", "grant"])
@pytest.mark.parametrize("snapshot_state", ["missing", "stale"])
def test_unknown_source_permissions_deny_privileged_users(
    policy, people, make_doc, make_grant, seed_blocks, now, shortcut, snapshot_state
):
    principal = people["alex"]
    if shortcut == "admin":
        principal = principal.model_copy(update={"roles": ["admin"]})
    doc = make_doc(
        seed_blocks["confluence"] if snapshot_state == "stale" else None,
        source_kind=SourceKind.confluence,
        snapshot_version="old",
        permission_version="current",
        owner=principal.id if shortcut == "owner" else None,
        grants=[make_grant(SubjectType.principal, principal.id)] if shortcut == "grant" else [],
    )
    assert policy.decide(principal, doc, now=now).reason == "unknown_permissions"


def test_wrong_snapshot_kind_cannot_authorise_a_source(policy, people, make_doc, seed_blocks, now):
    doc = make_doc(seed_blocks["upload"], source_kind=SourceKind.confluence)
    assert not policy.decide(people["alex"], doc, now=now).allowed


def test_uncaptured_ancestor_is_unknown(policy, people, make_doc, seed_blocks, now):
    raw = {**seed_blocks["confluence"], "ancestors": ["possibly-restricted-parent"]}
    assert policy.decide(people["alex"], make_doc(raw), now=now).reason == "unknown_permissions"


def test_unrostered_slack_public_channel_does_not_admit_an_outsider(
    policy, people, make_doc, seed_blocks, now
):
    raw = {**seed_blocks["slack"], "channel_type": "public", "member_ids": []}
    assert not policy.decide(people["mei"], make_doc(raw), now=now).allowed


def test_conflicting_duplicate_candidates_never_release_the_id(
    policy, people, make_doc, make_grant, seed_blocks, now
):
    allowed = make_doc(seed_blocks["confluence"])
    denied = allowed.model_copy(
        update={"grants": [make_grant(SubjectType.principal, people["alex"].id, Effect.deny)]}
    )
    for docs in ([allowed, denied], [denied, allowed]):
        result = policy.filter(people["alex"], docs, now=now)
        assert result.allowed_ids == []
        assert len(result.decisions) == 2


@pytest.mark.parametrize("raw_override", [{"deleted": True}, {"allow_file_discovery": False}])
def test_drive_deleted_or_link_only_shares_do_not_authorise_search(
    policy, people, make_doc, seed_blocks, now, raw_override
):
    ace = {"type": "anyone", "role": "reader", **raw_override}
    doc = make_doc({**seed_blocks["gdrive"], "acl": [ace]})
    assert not policy.decide(people["mei"], doc, now=now).allowed


def test_drive_permission_expires_at_decision_time(policy, people, make_doc, seed_blocks, now):
    raw = {
        **seed_blocks["gdrive"],
        "acl": [
            {
                "type": "user",
                "role": "reader",
                "email_or_domain": people["alex"].email,
                "expiration_time": now + timedelta(seconds=1),
            }
        ],
    }
    doc = make_doc(raw)
    assert policy.decide(people["alex"], doc, now=now).allowed
    assert not policy.decide(people["alex"], doc, now=now + timedelta(seconds=1)).allowed


def test_drive_bound_external_identity_does_not_also_use_local_email(
    policy, people, make_doc, seed_blocks, now
):
    principal = people["alex"].model_copy(
        update={"external_identities": {"gdrive": "different-account@example.com"}}
    )
    raw = {
        **seed_blocks["gdrive"],
        "acl": [{"type": "user", "role": "reader", "email_or_domain": principal.email}],
    }
    assert not policy.decide(principal, make_doc(raw), now=now).allowed


def test_timezone_free_clock_fails_closed_even_for_admin(policy, people, make_doc, now):
    decision = policy.decide(people["root"], make_doc(None), now=now.replace(tzinfo=None))
    assert not decision.allowed and decision.reason == DenyReason.unknown_permissions
