from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import freshness
import pytest
from freshness import (
    ChangeKind,
    ChangeSource,
    CheckpointStatus,
    Clock,
    ConnectorKind,
    EventState,
    EvidenceClass,
    EvidenceRef,
    FailureAction,
    FixedClock,
    FreshnessPolicy,
    FreshnessStatus,
    FreshnessStore,
    IndexOutcome,
    InMemoryFreshnessStore,
    ListChangeSource,
    OverallStatus,
    PolicyStatus,
    ProviderProbe,
    ReceiptRequest,
    RunStatus,
    ScriptedProbe,
    SourceChangeEvent,
    SyncPath,
    VerificationResult,
    synthetic_event_id,
)
from pydantic import ValidationError

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (
            ConnectorKind,
            [
                "confluence",
                "slack",
                "jira",
                "google_drive",
                "email",
                "upload",
                "gbrain_import",
                "mcp_external",
            ],
        ),
        (FreshnessStatus, ["fresh", "stale", "unknown", "not_searchable", "deleted"]),
        (VerificationResult, ["fresh", "stale", "unknown", "not_required"]),
        (SyncPath, ["webhook", "delta", "reconcile", "live_verify"]),
        (ChangeKind, ["upsert", "delete", "metadata_change"]),
        (EventState, ["accepted", "processing", "applied", "parked"]),
        (RunStatus, ["queued", "running", "completed", "partial", "failed", "parked"]),
        (CheckpointStatus, ["ready", "polling", "degraded", "paused"]),
        (EvidenceClass, ["critical", "standard"]),
        (FailureAction, ["omit", "abstain", "allow_with_warning"]),
        (PolicyStatus, ["draft", "active", "retired"]),
        (OverallStatus, ["fresh", "stale", "unknown", "not_required", "mixed"]),
    ],
)
def test_vocabulary_is_exact(enum: type, values: list[str]) -> None:
    assert [member.value for member in enum] == values


def test_branch_vocabulary_is_not_accepted() -> None:
    for legacy in ("searchable_current", "pending"):
        with pytest.raises(ValueError):
            FreshnessStatus(legacy)


def test_connector_kind_accepts_gdrive_alias() -> None:
    assert ConnectorKind("gdrive") is ConnectorKind.google_drive
    ref = EvidenceRef(source_id="s", external_object_id="o", connector_kind="gdrive")
    assert ref.connector_kind is ConnectorKind.google_drive


def test_naive_datetimes_are_rejected(make_object) -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_object(observed_at=datetime(2026, 10, 12, 9, 0))


def test_datetimes_are_normalised_to_utc(make_object, t0) -> None:
    from datetime import timezone

    sgt = timezone(timedelta(hours=8))
    obj = make_object(observed_at=t0.astimezone(sgt))
    assert obj.observed_at.utcoffset() == timedelta(0)
    assert obj.observed_at == t0


def test_searchable_at_never_earlier_than_indexed_at(make_object, t0) -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        make_object(indexed_at=t0, searchable_at=t0 - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="requires indexed_at"):
        make_object(indexed_at=None, searchable_at=t0)
    with pytest.raises(ValidationError, match="cannot precede"):
        IndexOutcome(
            content_written=True,
            searchable=True,
            embedded=True,
            indexed_at=t0,
            searchable_at=t0 - timedelta(seconds=1),
        )


def test_tombstone_model_is_never_fresh_or_searchable(make_object, t0) -> None:
    with pytest.raises(ValidationError, match="never be fresh"):
        make_object(deleted_at=t0)  # status fresh + deleted_at
    with pytest.raises(ValidationError, match="never be searchable"):
        make_object(freshness_status=FreshnessStatus.deleted, deleted_at=t0)
    with pytest.raises(ValidationError, match="needs deleted_at"):
        make_object(freshness_status=FreshnessStatus.deleted, searchable_at=None)
    tombstone = make_object(
        freshness_status=FreshnessStatus.deleted, deleted_at=t0, searchable_at=None
    )
    assert tombstone.freshness_status is FreshnessStatus.deleted


def test_fresh_requires_searchable_representation(make_object) -> None:
    with pytest.raises(ValidationError, match="fresh requires"):
        make_object(searchable_at=None)


def test_evolve_revalidates(make_object, t0) -> None:
    obj = make_object()
    with pytest.raises(ValidationError):
        obj.evolve(searchable_at=t0 - timedelta(hours=1))


def test_critical_policy_cannot_allow_with_warning(t0) -> None:
    with pytest.raises(ValidationError, match="critical"):
        FreshnessPolicy(
            policy_id="p",
            connector_kind=ConnectorKind.slack,
            evidence_class=EvidenceClass.critical,
            max_index_age_seconds=60,
            max_verification_age_seconds=60,
            failure_action=FailureAction.allow_with_warning,
            effective_at=t0,
        )


def test_published_policy_needs_effective_at() -> None:
    fields = {
        "policy_id": "p",
        "connector_kind": ConnectorKind.slack,
        "evidence_class": EvidenceClass.standard,
        "max_index_age_seconds": 60,
        "max_verification_age_seconds": 60,
        "failure_action": FailureAction.omit,
    }
    with pytest.raises(ValidationError, match="effective_at"):
        FreshnessPolicy(**fields)  # status defaults to active
    assert FreshnessPolicy(**fields, status=PolicyStatus.draft).effective_at is None


def test_parked_event_requires_stable_error_code(t0) -> None:
    base = {
        "id": "e1",
        "source_id": "s",
        "connector_kind": ConnectorKind.slack,
        "provider_event_id": "p1",
        "external_object_id": "o1",
        "change_kind": ChangeKind.upsert,
        "observed_at": t0,
        "accepted_at": t0,
        "payload_hash": "x",
    }
    with pytest.raises(ValidationError, match="last_error_code"):
        SourceChangeEvent(**base, state=EventState.parked, parked_at=t0)
    with pytest.raises(ValidationError, match="applied_at"):
        SourceChangeEvent(**base, state=EventState.applied)


def test_empty_receipt_request_requires_explicit_declaration() -> None:
    with pytest.raises(ValidationError, match="allow_empty"):
        ReceiptRequest(request_key="k")
    assert ReceiptRequest(request_key="k", allow_empty=True).evidence == []


def test_synthetic_event_id_is_deterministic() -> None:
    first = synthetic_event_id("page-1", ChangeKind.upsert, "7")
    assert first == synthetic_event_id("page-1", "upsert", "7")
    assert first != synthetic_event_id("page-1", ChangeKind.delete, "7")
    with pytest.raises(ValueError, match="provider_version or content_hash"):
        synthetic_event_id("page-1", ChangeKind.upsert, None)


def test_normalized_change_synthesises_missing_event_id(t0) -> None:
    from freshness import NormalizedChange

    change = NormalizedChange(
        source_id="s",
        connector_kind=ConnectorKind.jira,
        external_object_id="PAY-142",
        change_kind=ChangeKind.upsert,
        provider_version="12",
        observed_at=t0,
    )
    assert change.provider_event_id == "synthetic:upsert:PAY-142:12"


def test_in_memory_doubles_satisfy_protocols(t0) -> None:
    assert isinstance(InMemoryFreshnessStore(), FreshnessStore)
    assert isinstance(ScriptedProbe({}), ProviderProbe)
    assert isinstance(ListChangeSource([]), ChangeSource)
    assert isinstance(FixedClock(t0), Clock)


def test_public_api_surface() -> None:
    assert freshness.__version__ == "0.1.0"
    assert freshness.SCHEMA_VERSION == 1
    missing = [name for name in freshness.__all__ if not hasattr(freshness, name)]
    assert missing == []


def test_no_app_import() -> None:
    pattern = re.compile(r"^\s*(?:from\s+app(?:\.|\s)|import\s+app(?:\.|\s|,|$))", re.MULTILINE)
    offenders = [
        str(path.relative_to(SRC))
        for path in sorted(SRC.rglob("*.py"))
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"freshness must never import the app: {offenders}"
