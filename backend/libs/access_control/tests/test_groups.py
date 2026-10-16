"""Group resolution: nested groups count as their ancestors, and a bound platform group id
replaces the local id on that platform without ever widening access."""

from __future__ import annotations

import pytest
from access_control import (
    AccessControlService,
    Classification,
    GroupDefinition,
    InMemoryGrantStore,
    InMemoryGroupDirectory,
    InMemoryPermissionSnapshotStore,
    InMemoryPrincipalDirectory,
    SubjectType,
    expand_groups,
    resolve_groups,
)
from pydantic import ValidationError

DEFINITIONS = [
    GroupDefinition(id="treasury", parent_ids=["finance-ops"]),
    GroupDefinition(
        id="finance-ops",
        parent_ids=["all-staff"],
        platform_ids={"gdrive": "finance-ops@harbor.example", "confluence": "conf-finance"},
    ),
    GroupDefinition(id="leadership", platform_ids={"gdrive": "Leadership@harbor.example"}),
    # A cycle must not loop or crash.
    GroupDefinition(id="loop-a", parent_ids=["loop-b"]),
    GroupDefinition(id="loop-b", parent_ids=["loop-a"]),
]


def test_nested_groups_expand_to_every_ancestor():
    assert expand_groups(["treasury"], DEFINITIONS) == ["all-staff", "finance-ops", "treasury"]
    assert expand_groups(["loop-a"], DEFINITIONS) == ["loop-a", "loop-b"]
    assert expand_groups(["unknown"], DEFINITIONS) == ["unknown"]  # undefined: itself only
    assert expand_groups([], DEFINITIONS) == []


def test_platform_ids_replace_local_ids_per_platform(people):
    jordan = people["jordan"].model_copy(update={"groups": ["treasury", "leadership"]})
    resolved = resolve_groups(jordan, DEFINITIONS)
    assert resolved.groups == ["all-staff", "finance-ops", "leadership", "treasury"]
    assert resolved.platform_groups == {
        "confluence": ["all-staff", "conf-finance", "leadership", "treasury"],
        "gdrive": [
            "Leadership@harbor.example",
            "all-staff",
            "finance-ops@harbor.example",
            "treasury",
        ],
    }
    assert jordan.groups == ["treasury", "leadership"]  # the input is not mutated
    assert resolve_groups(resolved, DEFINITIONS) == resolved  # idempotent


def test_unknown_platform_kind_is_rejected_at_definition_time():
    with pytest.raises(ValidationError):
        GroupDefinition(id="x", platform_ids={"gdirve": "x@harbor.example"})


def drive_doc(make_doc, *entries, classification=Classification.internal, grants=()):
    acl = [{"type": "group", "role": "reader", "email_or_domain": target} for target in entries]
    return make_doc(
        {"kind": "gdrive", "file_id": "f1", "acl": acl},
        classification=classification,
        grants=grants,
    )


def test_drive_group_address_matches_only_after_resolution(policy, people, make_doc, now):
    doc = drive_doc(make_doc, "finance-ops@harbor.example")
    member = people["alex"].model_copy(update={"groups": ["treasury"]})
    assert not policy.decide(member, doc, now=now).allowed  # unresolved: "treasury" only
    assert policy.decide(resolve_groups(member, DEFINITIONS), doc, now=now).allowed


def test_a_bound_group_no_longer_matches_by_its_local_name(policy, people, make_doc, now):
    """Drive names Leadership by its address, so a Drive entry that merely says "leadership"
    (another domain's group, or a typo) must not let local Leadership members in."""
    john = resolve_groups(people["john"], DEFINITIONS)
    assert not policy.decide(john, drive_doc(make_doc, "leadership"), now=now).allowed
    assert policy.decide(john, drive_doc(make_doc, "leadership@harbor.example"), now=now).allowed


def test_confluence_matches_the_bound_group_id(policy, people, make_doc, seed_blocks, now):
    block = {**seed_blocks["confluence"], "space_view_groups": ["conf-finance"]}
    doc = make_doc(block)
    jordan = people["jordan"]  # direct member of finance-ops
    assert not policy.decide(jordan, doc, now=now).allowed
    assert policy.decide(resolve_groups(jordan, DEFINITIONS), doc, now=now).allowed


def test_a_grant_to_a_parent_group_reaches_nested_members(
    policy, people, make_doc, make_grant, now
):
    grant = make_grant(SubjectType.group, "finance-ops")
    doc = drive_doc(
        make_doc,
        "treasury",  # unbound on Drive: the local id still matches
        classification=Classification.confidential,
        grants=[grant],
    )
    member = resolve_groups(people["alex"].model_copy(update={"groups": ["treasury"]}), DEFINITIONS)
    decision = policy.decide(member, doc, now=now)
    assert (decision.matched_rule, decision.grant_ids) == ("R5:explicit_grant", [grant.id])


async def test_service_resolves_groups_from_the_group_directory(people, make_doc, now):
    alex = people["alex"].model_copy(update={"groups": ["treasury"]})
    groups = InMemoryGroupDirectory()
    service = AccessControlService(
        directory=InMemoryPrincipalDirectory([alex]),
        grants=InMemoryGrantStore(),
        snapshots=InMemoryPermissionSnapshotStore(),
        groups=groups,
    )
    doc = drive_doc(make_doc, "finance-ops@harbor.example")
    await service.snapshots.put(doc.document_id, doc.source_permissions)
    assert (await service.filter(alex.id, [doc], now=now)).allowed_ids == []
    for definition in DEFINITIONS:
        await groups.put(definition)
    assert (await service.filter(alex.id, [doc], now=now)).allowed_ids == [doc.document_id]
