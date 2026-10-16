"""Rule ordering of ``DefaultAccessPolicy`` (R1–R10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from access_control import (
    AccessPolicy,
    Classification,
    DefaultAccessPolicy,
    DenyReason,
    DocumentAccessContext,
    Effect,
    SourceKind,
    SourcePermissions,
    SubjectType,
)


@pytest.fixture
def confluence(seed_blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    # space visible to finance-ops + engineering; mei.chen (no groups) is outside it
    return seed_blocks["confluence"]


def test_policy_satisfies_protocol(policy: DefaultAccessPolicy) -> None:
    assert isinstance(policy, AccessPolicy)
    assert policy.policy_version == "ac-v2"
    assert DefaultAccessPolicy("custom-policy").policy_version == "custom-policy"


def test_decision_stamps(policy, people, make_doc, confluence, now: datetime) -> None:
    doc = make_doc(confluence, permission_version="pv-42")
    d = policy.decide(people["alex"], doc, now=now)
    assert d.document_id == "doc-1"
    assert d.decision == Effect.allow and d.reason is None
    assert d.matched_rule == "R8:confluence"
    assert d.permission_version == "pv-42"
    assert d.policy_version == "ac-v2"
    assert d.evaluated_at == now


def test_permission_version_falls_back_to_snapshot(policy, people, make_doc, confluence, now):
    doc = make_doc(confluence, permission_version=None, snapshot_version="snap-3")
    assert policy.decide(people["alex"], doc, now=now).permission_version == "snap-3"


# -- R1 -----------------------------------------------------------------------------------


def test_r1_inactive_principal_denied_even_if_owner_or_admin(policy, people, make_doc, now):
    for who in ("alex", "root"):
        inactive = people[who].model_copy(update={"is_active": False})
        doc = make_doc(None, owner=inactive.id)
        d = policy.decide(inactive, doc, now=now)
        assert (d.decision, d.reason, d.matched_rule) == (
            Effect.deny,
            DenyReason.policy_default,
            "R1:inactive_principal",
        )


# -- R2 deny beats allow ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject_type", "subject_id"),
    [
        (SubjectType.principal, "john.tan"),
        (SubjectType.group, "leadership"),
        (SubjectType.role, "manager"),
    ],
)
def test_r2_explicit_deny_beats_allow_grant_and_membership(
    policy, people, make_doc, make_grant, confluence, now, subject_type, subject_id
):
    grants = [
        make_grant(SubjectType.principal, "john.tan", Effect.allow),
        make_grant(subject_type, subject_id, Effect.deny),
    ]
    doc = make_doc(confluence, grants=grants)
    d = policy.decide(people["john"], doc, now=now)
    assert (d.decision, d.reason, d.matched_rule) == (
        Effect.deny,
        DenyReason.explicit_deny,
        "R2:explicit_deny",
    )


def test_r2_explicit_deny_beats_owner_and_admin(policy, people, make_doc, make_grant, now):
    for who in ("alex", "root"):
        p = people[who]
        doc = make_doc(None, owner=p.id, grants=[make_grant(SubjectType.principal, p.id, "deny")])
        d = policy.decide(p, doc, now=now)
        assert d.reason == DenyReason.explicit_deny


def test_revoked_deny_grant_is_ignored(policy, people, make_doc, make_grant, confluence, now):
    grants = [make_grant(SubjectType.principal, "alex.tan", Effect.deny, revoked=True)]
    d = policy.decide(people["alex"], make_doc(confluence, grants=grants), now=now)
    assert d.decision == Effect.allow and d.matched_rule == "R8:confluence"


def test_revoked_deny_grant_never_yields_grant_revoked(
    policy, people, make_doc, make_grant, confluence, now
):
    grants = [make_grant(SubjectType.principal, "mei.chen", Effect.deny, revoked=True)]
    d = policy.decide(people["mei"], make_doc(confluence, grants=grants), now=now)
    assert d.reason == DenyReason.no_source_membership


# -- R3 / R4 ------------------------------------------------------------------------------


def test_r3_owner_allowed_even_restricted_without_snapshot(policy, people, make_doc, now):
    doc = make_doc(None, owner="mei.chen", classification=Classification.restricted)
    d = policy.decide(people["mei"], doc, now=now)
    assert (d.decision, d.matched_rule) == (Effect.allow, "R3:owner")


def test_r4_admin_allowed_restricted(policy, people, make_doc, now):
    doc = make_doc(None, classification=Classification.restricted)
    d = policy.decide(people["root"], doc, now=now)
    assert (d.decision, d.matched_rule) == (Effect.allow, "R4:admin")


# -- R5 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject_type", "subject_id"),
    [
        (SubjectType.principal, "mei.chen"),
        (SubjectType.group, "leadership"),
        (SubjectType.role, "contractor"),
    ],
)
@pytest.mark.parametrize("classification", [Classification.confidential, Classification.restricted])
def test_r5_explicit_grant_allows_confidential_and_restricted(
    policy, people, make_doc, make_grant, now, subject_type, subject_id, classification
):
    who = "john" if subject_id == "leadership" else "mei"
    doc = make_doc(
        None, classification=classification, grants=[make_grant(subject_type, subject_id)]
    )
    d = policy.decide(people[who], doc, now=now)
    assert (d.decision, d.matched_rule) == (Effect.allow, "R5:explicit_grant")


def test_grants_for_other_documents_or_scopes_are_ignored(
    policy, people, make_doc, make_grant, now
):
    grants = [
        make_grant(SubjectType.principal, "mei.chen", document_id="other-doc"),
        make_grant(SubjectType.principal, "mei.chen", scope="write"),
        make_grant(SubjectType.principal, "mei.chen", Effect.deny, document_id="other-doc"),
    ]
    doc = make_doc(None, classification=Classification.confidential, grants=grants)
    d = policy.decide(people["mei"], doc, now=now)
    assert (d.decision, d.reason) == (Effect.deny, DenyReason.classification_requires_grant)


def test_grant_for_other_principal_does_not_apply(policy, people, make_doc, make_grant, now):
    doc = make_doc(
        None,
        classification=Classification.confidential,
        grants=[make_grant(SubjectType.principal, "john.tan")],
    )
    assert policy.decide(people["mei"], doc, now=now).decision == Effect.deny


# -- revoked allow falls through ------------------------------------------------------------


def test_revoked_allow_falls_through_to_classification_reason_grant_revoked(
    policy, people, make_doc, make_grant, seed_blocks, now
):
    # board deck: confidential, leadership grant revoked → john loses it
    deck = seed_blocks["gdrive"]
    live = make_grant(SubjectType.group, "leadership")
    revoked = make_grant(SubjectType.group, "leadership", revoked=True)
    doc_live = make_doc(deck, classification=Classification.confidential, grants=[live])
    doc_revoked = make_doc(deck, classification=Classification.confidential, grants=[revoked])
    assert policy.decide(people["john"], doc_live, now=now).decision == Effect.allow
    d = policy.decide(people["john"], doc_revoked, now=now)
    assert (d.decision, d.reason, d.matched_rule) == (
        Effect.deny,
        DenyReason.grant_revoked,
        "R7:confidential",
    )


def test_revoked_allow_falls_through_to_source_membership(
    policy, people, make_doc, make_grant, confluence, now
):
    revoked = [make_grant(SubjectType.principal, "alex.tan", revoked=True)]
    still_member = policy.decide(people["alex"], make_doc(confluence, grants=revoked), now=now)
    assert (still_member.decision, still_member.matched_rule) == (Effect.allow, "R8:confluence")

    revoked = [make_grant(SubjectType.principal, "mei.chen", revoked=True)]
    outsider = policy.decide(people["mei"], make_doc(confluence, grants=revoked), now=now)
    assert (outsider.decision, outsider.reason, outsider.matched_rule) == (
        Effect.deny,
        DenyReason.grant_revoked,
        "R8:confluence",
    )


def test_revoked_allow_with_missing_snapshot_reports_grant_revoked(
    policy, people, make_doc, make_grant, now
):
    doc = make_doc(None, grants=[make_grant(SubjectType.role, "contractor", revoked=True)])
    d = policy.decide(people["mei"], doc, now=now)
    assert (d.reason, d.matched_rule) == (DenyReason.grant_revoked, "R9:unknown_permissions")


def test_grant_revoked_never_overrides_inactive_or_explicit_deny(
    policy, people, make_doc, make_grant, now
):
    revoked = make_grant(SubjectType.principal, "mei.chen", revoked=True)
    deny = make_grant(SubjectType.principal, "mei.chen", Effect.deny)
    inactive = people["mei"].model_copy(update={"is_active": False})
    assert (
        policy.decide(inactive, make_doc(None, grants=[revoked]), now=now).reason
        == DenyReason.policy_default
    )
    assert (
        policy.decide(people["mei"], make_doc(None, grants=[revoked, deny]), now=now).reason
        == DenyReason.explicit_deny
    )


# -- R6 / R7 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("classification", "rule"),
    [
        (Classification.restricted, "R6:restricted"),
        (Classification.confidential, "R7:confidential"),
    ],
)
def test_classification_requires_grant_even_with_platform_membership(
    policy, people, make_doc, confluence, now, classification, rule
):
    doc = make_doc(confluence, classification=classification)
    # alex is in the space audience, but membership alone cannot unlock confidential/restricted
    d = policy.decide(people["alex"], doc, now=now)
    assert (d.decision, d.reason, d.matched_rule) == (
        Effect.deny,
        DenyReason.classification_requires_grant,
        rule,
    )


def test_public_classification_does_not_bypass_source_membership(
    policy, people, make_doc, confluence, now
):
    doc = make_doc(confluence, classification=Classification.public)
    assert policy.decide(people["mei"], doc, now=now).reason == DenyReason.no_source_membership


# -- R9 / R10 / guard ---------------------------------------------------------------------


def test_r9_missing_snapshot_is_unknown_permissions(policy, people, make_doc, now):
    d = policy.decide(people["alex"], make_doc(None), now=now)
    assert (d.decision, d.reason, d.matched_rule) == (
        Effect.deny,
        DenyReason.unknown_permissions,
        "R9:unknown_permissions",
    )


def test_r9_snapshot_version_drift_fails_closed(policy, people, make_doc, confluence, now):
    doc = make_doc(confluence, permission_version="pv-2", snapshot_version="pv-1")
    d = policy.decide(people["alex"], doc, now=now)
    assert (d.decision, d.reason, d.matched_rule) == (
        Effect.deny,
        DenyReason.unknown_permissions,
        "R9:permission_version_mismatch",
    )
    assert d.permission_version == "pv-2"


def test_r10_default_deny_for_unsupported_raw(policy, people, now):
    snap = SourcePermissions.model_construct(
        kind=SourceKind.gbrain_import, raw=object(), permission_version="pv-1", captured_at=now
    )
    doc = DocumentAccessContext(
        document_id="doc-x", source_id="brain", source_kind=SourceKind.gbrain_import
    )
    doc = doc.model_copy(update={"source_permissions": snap})
    d = policy.decide(people["alex"], doc, now=now)
    assert (d.decision, d.reason, d.matched_rule) == (
        Effect.deny,
        DenyReason.policy_default,
        "R10:default_deny",
    )


def test_decide_never_raises_on_malformed_input(policy, people, now):
    broken = DocumentAccessContext.model_construct(document_id="doc-broken", grants=None)
    for principal, doc in ((people["alex"], broken), (None, broken), (people["alex"], None)):
        d = policy.decide(principal, doc, now=now)  # type: ignore[arg-type]
        assert (d.decision, d.reason, d.matched_rule) == (
            Effect.deny,
            DenyReason.unknown_permissions,
            "ERR:evaluation_error",
        )
    assert policy.decide(people["alex"], broken, now=now).document_id == "doc-broken"


def test_decide_is_deterministic(policy, people, make_doc, make_grant, seed_blocks, now):
    doc = make_doc(seed_blocks["jira"], grants=[make_grant(SubjectType.group, "compliance")])
    first = policy.decide(people["sam"], doc, now=now)
    assert all(policy.decide(people["sam"], doc, now=now) == first for _ in range(5))
