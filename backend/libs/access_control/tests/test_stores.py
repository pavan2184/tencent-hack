"""In-memory stores satisfy the async Protocols and their documented invariants."""

from __future__ import annotations

from datetime import timedelta

import pytest
from access_control import (
    AccessControlError,
    AccessRequest,
    AccessRequestNotFound,
    AccessRequestStatus,
    AccessRequestStore,
    Classification,
    Effect,
    GrantNotFound,
    GrantStore,
    InMemoryAccessRequestStore,
    InMemoryGrantStore,
    InMemoryPermissionSnapshotStore,
    InMemoryPrincipalDirectory,
    PermissionSnapshotStore,
    PrincipalDirectory,
    SourcePermissions,
    SubjectType,
)

pytestmark = pytest.mark.asyncio


async def test_stores_satisfy_protocols():
    assert isinstance(InMemoryGrantStore(), GrantStore)
    assert isinstance(InMemoryPermissionSnapshotStore(), PermissionSnapshotStore)
    assert isinstance(InMemoryPrincipalDirectory(), PrincipalDirectory)
    assert isinstance(InMemoryAccessRequestStore(), AccessRequestStore)


# -- grants -------------------------------------------------------------------------------


async def test_grant_add_and_list_for_documents(make_grant):
    store = InMemoryGrantStore()
    g1 = await store.add(make_grant(SubjectType.group, "leadership", document_id="deck"))
    g2 = await store.add(make_grant(SubjectType.principal, "mei.chen", document_id="deck"))
    await store.add(make_grant(SubjectType.principal, "alex.tan", document_id="other"))
    listed = await store.list_for_documents(["deck", "missing"])
    assert set(listed) == {"deck", "missing"}  # a key for every requested id
    assert [g.id for g in listed["deck"]] == [g1.id, g2.id]
    assert listed["missing"] == []


async def test_grant_ids_default_unique_and_duplicates_rejected(make_grant):
    store = InMemoryGrantStore()
    a = make_grant(SubjectType.role, "auditor")
    b = make_grant(SubjectType.role, "auditor")
    assert a.id and a.id != b.id
    await store.add(a)
    with pytest.raises(AccessControlError):
        await store.add(a)


async def test_grant_revoke_is_soft_idempotent_and_visible(make_grant, now):
    store = InMemoryGrantStore([make_grant(SubjectType.group, "leadership", grant_id="g-1")])
    revoked = await store.revoke("g-1", by="root.admin", at=now)
    assert (revoked.revoked_at, revoked.revoked_by, revoked.is_revoked) == (
        now,
        "root.admin",
        True,
    )
    again = await store.revoke("g-1", by="someone.else", at=now + timedelta(hours=1))
    assert (again.revoked_at, again.revoked_by) == (now, "root.admin")  # first revocation wins
    listed = await store.list_for_documents(["doc-1"])
    assert listed["doc-1"][0].is_revoked  # still listed, for grant_revoked + audit
    with pytest.raises(GrantNotFound):
        await store.revoke("nope", by="root.admin", at=now)


async def test_grant_list_for_subject(make_grant, now):
    store = InMemoryGrantStore(
        [
            make_grant(SubjectType.group, "leadership", grant_id="a"),
            make_grant(SubjectType.group, "leadership", document_id="d2", grant_id="b"),
            make_grant(SubjectType.principal, "leadership", grant_id="c"),
        ]
    )
    await store.revoke("b", by="root.admin", at=now)
    got = await store.list_for_subject(SubjectType.group, "leadership")
    assert [g.id for g in got] == ["a", "b"]


async def test_grant_store_returns_copies(make_grant):
    store = InMemoryGrantStore([make_grant(SubjectType.group, "leadership", grant_id="g")])
    listed = await store.list_for_documents(["doc-1"])
    listed["doc-1"][0].subject_id = "everyone"
    again = await store.list_for_documents(["doc-1"])
    assert again["doc-1"][0].subject_id == "leadership"


async def test_revocation_through_store_flips_policy_decision(
    policy, people, make_doc, make_grant, seed_blocks, now
):
    """Demo scenario 4 end-to-end at the library level: revoke → re-evaluate → denied."""
    store = InMemoryGrantStore(
        [make_grant(SubjectType.group, "leadership", document_id="deck", grant_id="lead")]
    )

    async def decide():
        grants = (await store.list_for_documents(["deck"]))["deck"]
        doc = make_doc(
            seed_blocks["gdrive"],
            document_id="deck",
            classification=Classification.confidential,
            grants=grants,
        )
        return policy.decide(people["priya"], doc, now=now)

    assert (await decide()).decision == Effect.allow
    await store.revoke("lead", by="root.admin", at=now)
    after = await decide()
    assert (after.decision, after.reason) == (Effect.deny, "grant_revoked")


# -- permission snapshots -----------------------------------------------------------------


async def test_snapshot_put_and_get_many(seed_blocks, now):
    store = InMemoryPermissionSnapshotStore()
    v1 = SourcePermissions.from_raw(seed_blocks["slack"], permission_version="1", captured_at=now)
    v2 = SourcePermissions.from_raw(seed_blocks["slack"], permission_version="2", captured_at=now)
    await store.put("log", v1)
    await store.put("log", v2)  # replaces
    got = await store.get_many(["log", "missing"])
    assert set(got) == {"log"}  # missing ids are omitted, never defaulted
    assert got["log"].permission_version == "2"


# -- principals ---------------------------------------------------------------------------


async def test_principal_directory(people):
    inactive = people["mei"].model_copy(update={"is_active": False})
    directory = InMemoryPrincipalDirectory([*people.values()][:-1] + [inactive])
    assert (await directory.get("alex.tan")).groups == ["engineering"]
    assert (await directory.get("mei.chen")).is_active is False  # inactive still resolvable
    assert await directory.get("ghost") is None
    assert {p.id for p in await directory.list()} == {p.id for p in people.values()}
    assert await directory.groups_of("priya.nair") == ["finance-ops", "leadership"]
    assert await directory.groups_of("ghost") == []
    groups = await directory.groups_of("priya.nair")
    groups.append("root")
    assert await directory.groups_of("priya.nair") == ["finance-ops", "leadership"]


# -- access requests ----------------------------------------------------------------------


async def test_access_request_lifecycle(now):
    store = InMemoryAccessRequestStore()
    r1 = await store.create(
        AccessRequest(document_id="deck", principal_id="mei.chen", reason="audit", created_at=now)
    )
    r2 = await store.create(
        AccessRequest(document_id="log", principal_id="alex.tan", created_at=now)
    )
    assert r1.status == AccessRequestStatus.pending and r1.id != r2.id
    assert [r.id for r in await store.list_pending()] == [r1.id, r2.id]

    approved = await store.decide(r1.id, approved=True, by="root.admin", at=now)
    assert (approved.status, approved.decided_by, approved.decided_at) == (
        AccessRequestStatus.approved,
        "root.admin",
        now,
    )
    denied = await store.decide(r2.id, approved=False, by="priya.nair", at=now)
    assert denied.status == AccessRequestStatus.denied
    assert await store.list_pending() == []


async def test_access_request_errors(now):
    store = InMemoryAccessRequestStore()
    req = await store.create(AccessRequest(document_id="d", principal_id="p", created_at=now))
    with pytest.raises(AccessControlError):
        await store.create(req)
    with pytest.raises(AccessRequestNotFound):
        await store.decide("nope", approved=True, by="root.admin", at=now)
    await store.decide(req.id, approved=True, by="root.admin", at=now)
    with pytest.raises(AccessControlError):
        await store.decide(req.id, approved=False, by="root.admin", at=now)
