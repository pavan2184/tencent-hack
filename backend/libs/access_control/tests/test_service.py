"""Exercise revocation through live store reads and the pre-model evidence boundary."""

import pytest
from access_control import (
    AccessControlService,
    AccessSummary,
    Classification,
    DenyReason,
    InMemoryGrantStore,
    InMemoryPermissionSnapshotStore,
    InMemoryPrincipalDirectory,
    SourcePermissions,
    SubjectType,
)


@pytest.fixture
def authority(people):
    return (
        InMemoryPrincipalDirectory(people.values()),
        InMemoryGrantStore(),
        InMemoryPermissionSnapshotStore(),
    )


@pytest.fixture
def service(authority):
    directory, grants, snapshots = authority
    return AccessControlService(directory=directory, grants=grants, snapshots=snapshots)


async def test_local_grant_revocation_ignores_cached_candidate_grants(
    service, authority, people, make_doc, make_grant, seed_blocks, now
):
    _, grants, snapshots = authority
    grant = make_grant(SubjectType.group, "leadership")
    doc = make_doc(
        seed_blocks["gdrive"], classification=Classification.confidential, grants=[grant]
    )
    await grants.add(grant)
    await snapshots.put(doc.document_id, doc.source_permissions)
    assert (await service.filter(people["priya"].id, [doc], now=now)).allowed_ids == [
        doc.document_id
    ]
    await grants.revoke(grant.id, by="root.admin", at=now)
    after = await service.filter(people["priya"].id, [doc], now=now)
    assert after.allowed_ids == []
    assert after.decisions[0].reason == DenyReason.grant_revoked
    assert doc.grants[0].revoked_at is None  # stale candidate did not override the store


async def test_source_membership_revocation_without_content_change(
    service, authority, people, make_doc, seed_blocks, now
):
    _, _, snapshots = authority
    doc = make_doc(seed_blocks["slack"])
    await snapshots.put(doc.document_id, doc.source_permissions)
    assert (await service.filter(people["jordan"].id, [doc], now=now)).allowed_ids
    revoked = {**seed_blocks["slack"], "member_ids": ["U_PRIYA"]}
    await snapshots.put(
        doc.document_id,
        SourcePermissions.from_raw(revoked, permission_version="pv-1", captured_at=now),
    )
    after = await service.filter(people["jordan"].id, [doc], now=now)
    assert after.allowed_ids == []
    assert after.decisions[0].reason == DenyReason.no_source_membership


async def test_directory_group_revocation_is_visible_on_next_query(
    service, authority, people, make_doc, seed_blocks, now
):
    directory, _, snapshots = authority
    doc = make_doc(seed_blocks["confluence"])
    await snapshots.put(doc.document_id, doc.source_permissions)
    assert (await service.filter(people["alex"].id, [doc], now=now)).allowed_ids
    directory.upsert(people["alex"].model_copy(update={"groups": []}))
    assert (await service.filter(people["alex"].id, [doc], now=now)).allowed_ids == []


async def test_separate_group_directory_takes_precedence(
    service, authority, people, make_doc, seed_blocks, now, monkeypatch
):
    directory, _, snapshots = authority
    doc = make_doc(seed_blocks["confluence"])
    await snapshots.put(doc.document_id, doc.source_permissions)

    async def current_groups(_):
        return []

    monkeypatch.setattr(directory, "groups_of", current_groups)
    assert (await service.filter(people["alex"].id, [doc], now=now)).allowed_ids == []


@pytest.mark.parametrize("change", ["unknown", "inactive", "missing_snapshot", "stale_snapshot"])
async def test_unusable_authority_fails_closed(
    service, authority, people, make_doc, seed_blocks, now, change
):
    directory, _, snapshots = authority
    doc = make_doc(seed_blocks["confluence"])
    actor = people["alex"].id
    if change != "missing_snapshot":
        snapshot = doc.source_permissions
        if change == "stale_snapshot":
            snapshot = snapshot.model_copy(update={"permission_version": "new-version"})
        await snapshots.put(doc.document_id, snapshot)
    if change == "unknown":
        actor = "not-in-directory"
    if change == "inactive":
        directory.upsert(people["alex"].model_copy(update={"is_active": False}))
    result = await service.filter(actor, [doc], now=now)
    assert result.allowed_ids == [] and len(result.decisions) == 1


@pytest.mark.parametrize(
    "store,method", [(0, "get"), (0, "groups_of"), (1, "list_for_documents"), (2, "get_many")]
)
async def test_store_errors_deny_even_admin_and_owner(
    service, authority, people, make_doc, now, monkeypatch, store, method
):
    async def unavailable(*args, **kwargs):
        raise TimeoutError("store unavailable")

    monkeypatch.setattr(authority[store], method, unavailable)
    doc = make_doc(None, owner=people["root"].id)
    result = await service.filter(people["root"].id, [doc], now=now)
    assert result.allowed_ids == []
    assert result.decisions[0].reason == DenyReason.unknown_permissions


@pytest.mark.parametrize("reply", [False, None, "error", 1, "true"])
async def test_live_check_failure_cannot_expose_model_evidence(
    service, authority, people, make_doc, seed_blocks, now, reply
):
    _, _, snapshots = authority
    doc = make_doc(seed_blocks["confluence"])
    await snapshots.put(doc.document_id, doc.source_permissions)

    class Verifier:
        async def verify(self, principal, candidate, *, now):
            assert principal.id == people["alex"].id
            assert candidate.document_id == doc.document_id
            if reply == "error":
                raise TimeoutError("provider unavailable")
            return reply

    service.verifier = Verifier()
    result = await service.filter(people["alex"].id, [doc], now=now)
    content = {doc.document_id: "SECRET SENTINEL"}
    model_context = [content[doc_id] for doc_id in result.allowed_ids]
    assert model_context == []
    summary = AccessSummary.from_filter_result(
        result,
        principal_id=people["alex"].id,
        policy_version=service.policy.policy_version,
        evaluated_at=now,
    ).model_dump_json()
    assert "SECRET" not in summary and doc.document_id not in summary and "denied" not in summary


async def test_live_confirmation_cannot_widen_local_policy(
    service, authority, people, make_doc, seed_blocks, now
):
    _, _, snapshots = authority
    doc = make_doc(seed_blocks["confluence"])
    await snapshots.put(doc.document_id, doc.source_permissions)
    calls = []

    class Verifier:
        async def verify(self, principal, candidate, *, now):
            calls.append(principal.id)
            return True

    service.verifier = Verifier()
    assert (await service.filter(people["mei"].id, [doc], now=now)).allowed_ids == []
    assert calls == []
    assert (await service.filter(people["alex"].id, [doc], now=now)).allowed_ids == [
        doc.document_id
    ]
    assert calls == [people["alex"].id]


async def test_empty_input_needs_no_authority(service, now):
    result = await service.filter("unknown", [], now=now)
    assert result.allowed_ids == result.decisions == []


async def test_live_revocation_is_visible_without_reindexing(
    service, authority, people, make_doc, seed_blocks, now
):
    _, _, snapshots = authority
    doc = make_doc(seed_blocks["confluence"])
    await snapshots.put(doc.document_id, doc.source_permissions)

    class Verifier:
        allowed = True

        async def verify(self, principal, candidate, *, now):
            return self.allowed

    verifier = Verifier()
    service.verifier = verifier
    assert (await service.filter(people["alex"].id, [doc], now=now)).allowed_ids
    verifier.allowed = False
    result = await service.filter(people["alex"].id, [doc], now=now)
    assert result.allowed_ids == []
    assert result.decisions[0].matched_rule == "LIVE:source_denied"


async def test_incomplete_grant_store_read_cannot_ignore_an_explicit_deny(
    service, authority, people, make_doc, now, monkeypatch
):
    async def incomplete(ids):
        return {}

    monkeypatch.setattr(authority[1], "list_for_documents", incomplete)
    result = await service.filter(people["root"].id, [make_doc(None)], now=now)
    assert result.allowed_ids == []
    assert result.decisions[0].reason == DenyReason.unknown_permissions


@pytest.mark.parametrize("malformed", ["groups", "grant", "snapshot"])
async def test_malformed_authority_is_revalidated_and_denied(
    service, authority, people, make_doc, make_grant, seed_blocks, now, monkeypatch, malformed
):
    directory, grants, snapshots = authority
    doc = make_doc(seed_blocks["confluence"])
    await snapshots.put(doc.document_id, doc.source_permissions)
    if malformed == "groups":

        async def wrong_groups(_):
            return "engineering"

        monkeypatch.setattr(directory, "groups_of", wrong_groups)
    elif malformed == "grant":
        invalid = make_grant(SubjectType.principal, people["alex"].id).model_copy(
            update={"effect": "unknown"}
        )
        await grants.add(invalid)
    else:
        invalid = doc.source_permissions.model_copy(update={"raw": {"kind": "unknown"}})
        await snapshots.put(doc.document_id, invalid)
    result = await service.filter(people["alex"].id, [doc], now=now)
    assert result.allowed_ids == []
    assert result.decisions[0].matched_rule == "SERVICE:authority_unavailable"
