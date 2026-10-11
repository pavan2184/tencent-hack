"""Freshness receipts: order, retention, canonical hashing, persistence (hard gate
receipt_field_accuracy = 1.0)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from freshness import (
    ChangeKind,
    ChangePage,
    ConnectorKind,
    EvidenceClass,
    EvidenceRef,
    FreshnessStatus,
    ListChangeSource,
    OverallStatus,
    ProviderHead,
    ReceiptConflict,
    ReceiptRequest,
    ScriptedProbe,
    canonical_json,
    compute_receipt_hash,
    verify_receipt_hash,
)
from freshness.receipt import build_receipt, overall_status


def _ref(object_id: str, evidence_class: EvidenceClass = EvidenceClass.standard) -> EvidenceRef:
    return EvidenceRef(
        source_id="confluence-ops",
        external_object_id=object_id,
        connector_kind=ConnectorKind.confluence,
        evidence_class=evidence_class,
    )


@pytest.fixture
async def corpus(service, make_change, make_sync, apply) -> None:
    """fresh-1 and fresh-2 indexed at v1; gone-1 indexed then deleted; runbook at v7."""
    changes = [
        make_change("fresh-1", "1"),
        make_change("fresh-2", "1"),
        make_change("gone-1", "1"),
        make_change("runbook", "7"),
    ]
    await service.connector_sync(
        make_sync(), change_source=ListChangeSource([ChangePage(changes=changes)]), apply=apply
    )
    delete = make_change("gone-1", "2", kind=ChangeKind.delete)
    await service.connector_sync(
        make_sync(), change_source=ListChangeSource([ChangePage(changes=[delete])]), apply=apply
    )


async def test_items_keep_input_order_and_retain_unknown_and_deleted(service, corpus) -> None:
    request = ReceiptRequest(
        request_key="q-1",
        evidence=[_ref("missing-1"), _ref("fresh-1"), _ref("gone-1"), _ref("fresh-1")],
    )

    receipt = await service.freshness_receipt(request)

    assert [i.external_object_id for i in receipt.evidence_items] == [
        "missing-1",
        "fresh-1",
        "gone-1",
        "fresh-1",
    ]
    assert [i.freshness_status for i in receipt.evidence_items] == [
        FreshnessStatus.unknown,
        FreshnessStatus.fresh,
        FreshnessStatus.deleted,
        FreshnessStatus.fresh,
    ]
    assert receipt.evidence_items[0].reason == "object_not_found"
    assert receipt.evidence_items[2].tombstoned is True
    assert receipt.overall_status is OverallStatus.mixed
    assert receipt.oldest_evidence_age_seconds == 0
    assert verify_receipt_hash(receipt)


async def test_hash_is_deterministic_and_excludes_receipt_id_and_created_at(
    service, corpus
) -> None:
    request = ReceiptRequest(
        request_key="q-ephemeral", evidence=[_ref("fresh-1"), _ref("gone-1")], persist=False
    )

    first = await service.freshness_receipt(request)
    second = await service.freshness_receipt(request)
    restamped = first.evolve(receipt_id="other-id", created_at=datetime(2030, 1, 1, tzinfo=UTC))

    assert first.receipt_id != second.receipt_id
    assert first.receipt_hash == second.receipt_hash
    assert compute_receipt_hash(restamped) == first.receipt_hash


async def test_hash_changes_when_any_fact_changes(service, corpus, clock) -> None:
    request = ReceiptRequest(request_key="q-x", evidence=[_ref("fresh-1")], persist=False)
    before = await service.freshness_receipt(request)
    clock.advance(30)  # age is a receipt fact

    after = await service.freshness_receipt(request)

    assert after.receipt_hash != before.receipt_hash


def test_canonical_json_sorts_keys_and_uses_utc_iso_timestamps() -> None:
    from datetime import timedelta, timezone

    sgt = timezone(timedelta(hours=8))
    payload = {"b": 1, "a": datetime(2026, 10, 12, 17, 0, tzinfo=sgt), "c": FreshnessStatus.stale}

    assert canonical_json(payload) == '{"a":"2026-10-12T09:00:00+00:00","b":1,"c":"stale"}'
    assert canonical_json({"c": FreshnessStatus.stale, "b": 1, "a": payload["a"]}) == (
        canonical_json(payload)
    )


async def test_same_request_key_and_request_returns_existing_receipt(
    service, store, corpus, clock
) -> None:
    request = ReceiptRequest(request_key="q-audit", evidence=[_ref("fresh-1")])
    original = await service.freshness_receipt(request)
    clock.advance(10_000)  # provider/index state ages; the stored proof must not change

    replay = await service.freshness_receipt(request)

    assert replay == original
    assert len(store.receipts) == 1


async def test_same_request_key_different_request_conflicts(service, store, corpus) -> None:
    await service.freshness_receipt(ReceiptRequest(request_key="q-2", evidence=[_ref("fresh-1")]))

    with pytest.raises(ReceiptConflict):
        await service.freshness_receipt(
            ReceiptRequest(request_key="q-2", evidence=[_ref("fresh-2")])
        )
    assert len(store.receipts) == 1


async def test_store_save_receipt_replay_and_conflict(store, service, corpus) -> None:
    stored = await service.freshness_receipt(
        ReceiptRequest(request_key="q-3", evidence=[_ref("fresh-1")])
    )

    racing = stored.evolve(receipt_id="racer")  # same key, same request hash
    assert await store.save_receipt(racing) == stored
    other = stored.evolve(receipt_id="racer-2", request_payload_hash="0" * 64)
    with pytest.raises(ReceiptConflict):
        await store.save_receipt(other)


async def test_persist_false_writes_nothing(service, store, corpus) -> None:
    await service.freshness_receipt(
        ReceiptRequest(request_key="q-4", evidence=[_ref("fresh-1")], persist=False)
    )
    assert store.receipts == {}


async def test_probe_for_verifies_critical_items_before_snapshot(service, corpus) -> None:
    probe = ScriptedProbe(
        {
            "runbook": ProviderHead(provider_version="8"),  # provider moved on → stale
            "fresh-1": ProviderHead(provider_version="1"),
        }
    )

    def probe_for(ref: EvidenceRef):
        return probe if ref.evidence_class is EvidenceClass.critical else None

    receipt = await service.freshness_receipt(
        ReceiptRequest(
            request_key="q-5",
            evidence=[
                _ref("runbook", EvidenceClass.critical),
                _ref("fresh-1", EvidenceClass.critical),
                _ref("fresh-2"),
            ],
        ),
        probe_for=probe_for,
    )

    runbook, verified, standard = receipt.evidence_items
    assert probe.calls == ["runbook", "fresh-1"]
    assert (runbook.freshness_status, runbook.safe_to_use) == (FreshnessStatus.stale, False)
    assert runbook.fallback_action is not None
    assert (verified.freshness_status, verified.safe_to_use) == (FreshnessStatus.fresh, True)
    assert standard.freshness_status is FreshnessStatus.fresh
    assert receipt.policy_id is None  # critical + standard policies → per-item policy ids
    assert {runbook.policy_id, standard.policy_id} == {
        "confluence.critical",
        "confluence.standard",
    }


async def test_single_policy_receipt_names_the_policy(service, corpus) -> None:
    receipt = await service.freshness_receipt(
        ReceiptRequest(request_key="q-6", evidence=[_ref("fresh-1"), _ref("fresh-2")])
    )
    assert (receipt.policy_id, receipt.policy_schema_version) == ("confluence.standard", 1)
    assert receipt.overall_status is OverallStatus.fresh


async def test_unconfigured_connector_is_retained_as_unknown(service) -> None:
    ref = EvidenceRef(source_id="slack-ops", external_object_id="m1", connector_kind="slack")
    receipt = await service.freshness_receipt(ReceiptRequest(request_key="q-7", evidence=[ref]))

    (item,) = receipt.evidence_items
    assert item.freshness_status is FreshnessStatus.unknown
    assert item.reason == "policy_not_found"
    assert item.safe_to_use is False


async def test_explicit_empty_receipt(service) -> None:
    receipt = await service.freshness_receipt(
        ReceiptRequest(request_key="q-empty", allow_empty=True)
    )
    assert receipt.evidence_items == []
    assert receipt.overall_status is OverallStatus.not_required


def test_tampering_is_detected(make_object, standard_policy, t0) -> None:
    from freshness import evaluate

    item = evaluate(make_object(), standard_policy, t0)
    request = ReceiptRequest(request_key="k", evidence=[_ref("page-1")])
    receipt = build_receipt(
        request=request, request_hash="h", items=[item], receipt_id="r", created_at=t0
    )
    forged = receipt.evolve(evidence_items=[item.evolve(freshness_status=FreshnessStatus.stale)])

    assert verify_receipt_hash(receipt)
    assert not verify_receipt_hash(forged)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([FreshnessStatus.fresh, FreshnessStatus.fresh], OverallStatus.fresh),
        ([FreshnessStatus.stale, FreshnessStatus.deleted], OverallStatus.stale),
        ([FreshnessStatus.unknown, FreshnessStatus.not_searchable], OverallStatus.unknown),
        ([FreshnessStatus.fresh, FreshnessStatus.stale], OverallStatus.mixed),
    ],
)
def test_overall_status_rollup(make_object, standard_policy, t0, statuses, expected) -> None:
    from freshness import evaluate

    base = evaluate(make_object(), standard_policy, t0)
    items = [base.evolve(freshness_status=s) for s in statuses]
    assert overall_status(items) is expected
