"""Pydantic v2 models: one per spec entity, plus the operation inputs/outputs.

Every datetime is timezone-aware and normalised to UTC on validation; naive datetimes are rejected.
Entity models are frozen — use :meth:`FreshnessModel.evolve` to get a re-validated copy, so the
cross-field invariants below are checked on every state transition, not only on construction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Final, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from freshness.enums import (
    ChangeKind,
    CheckpointStatus,
    ConnectorKind,
    EventState,
    EvidenceClass,
    FailureAction,
    FreshnessStatus,
    OverallStatus,
    PolicyStatus,
    RunStatus,
    SyncPath,
    VerificationResult,
)

SCHEMA_VERSION: Final = 1
DEFAULT_SCOPE: Final = "default"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetimes must be timezone-aware (UTC)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]
NonNegativeInt = Annotated[int, Field(ge=0)]


def synthetic_event_id(
    external_object_id: str,
    change_kind: ChangeKind | str,
    provider_version: str | None,
    content_hash: str | None = None,
) -> str:
    """Deterministic, source-scoped event id for delta/reconcile changes that carry none.

    Built from object id, change kind, and version (falling back to content hash). Two deliveries of
    the same object+version+kind therefore deduplicate in the ledger.
    """
    marker = provider_version if provider_version is not None else content_hash
    if marker is None:
        raise ValueError(
            "a change without provider_event_id needs provider_version or content_hash "
            "to synthesise a deterministic event id"
        )
    return f"synthetic:{ChangeKind(change_kind).value}:{external_object_id}:{marker}"


class FreshnessModel(BaseModel):
    """Base model: unknown fields are rejected and instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def evolve(self, **changes: Any) -> Self:
        """Return a copy with ``changes`` applied, re-running all validators."""
        return type(self).model_validate({**self.model_dump(), **changes})


# --------------------------------------------------------------------------------------------------
# Persisted entities (tables in infra/postgres/migrations/0100_freshness_init.sql)
# --------------------------------------------------------------------------------------------------


class ConnectorCheckpoint(FreshnessModel):
    """One durable cursor per connector scope. PK ``(source_id, scope_key)``; writes are CAS."""

    source_id: str
    scope_key: str = DEFAULT_SCOPE
    connector_kind: ConnectorKind
    cursor_value: str | None = None
    cursor_version: NonNegativeInt = 0
    last_polled_at: UtcDatetime | None = None
    last_reconciled_at: UtcDatetime | None = None
    last_successful_run_id: str | None = None
    status: CheckpointStatus = CheckpointStatus.ready
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None


class SourceChangeEvent(FreshnessModel):
    """Append-oriented acceptance/retry ledger row. Unique ``(source_id, provider_event_id)``."""

    id: str
    source_id: str
    scope_key: str = DEFAULT_SCOPE
    connector_kind: ConnectorKind
    provider_event_id: str
    external_object_id: str
    change_kind: ChangeKind
    provider_version: str | None = None
    version_order: int | None = None
    observed_at: UtcDatetime
    accepted_at: UtcDatetime
    state: EventState = EventState.accepted
    attempt_count: NonNegativeInt = 0
    next_attempt_at: UtcDatetime | None = None
    last_error_code: str | None = None
    payload_hash: str
    applied_at: UtcDatetime | None = None
    parked_at: UtcDatetime | None = None
    # Set when the event was accounted as applied without calling ``apply`` (e.g. older version).
    noop_reason: str | None = None

    @model_validator(mode="after")
    def _terminal_accounting(self) -> Self:
        if self.state is EventState.applied and (
            self.applied_at is None or self.parked_at is not None
        ):
            raise ValueError("an applied event needs applied_at and no parked_at")
        if self.state is EventState.parked:
            if self.parked_at is None or self.applied_at is not None:
                raise ValueError("a parked event needs parked_at and no applied_at")
            if not self.last_error_code:
                raise ValueError("a parked event needs a stable last_error_code")
        return self


class ObjectFreshness(FreshnessModel):
    """Current freshness state of one provider object. PK ``(source_id, external_object_id)``."""

    source_id: str
    external_object_id: str
    connector_kind: ConnectorKind
    page_id: str | None = None
    page_slug: str | None = None
    provider_version: str | None = None
    version_order: int | None = None
    content_hash: str | None = None
    provider_modified_at: UtcDatetime | None = None
    observed_at: UtcDatetime
    accepted_at: UtcDatetime | None = None
    indexed_at: UtcDatetime | None = None
    searchable_at: UtcDatetime | None = None
    last_verified_at: UtcDatetime | None = None
    verification_result: VerificationResult | None = None
    sync_path: SyncPath
    deleted_at: UtcDatetime | None = None
    tombstone_version: str | None = None
    freshness_status: FreshnessStatus
    last_run_id: str | None = None
    created_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        if self.searchable_at is not None:
            if self.indexed_at is None:
                raise ValueError("searchable_at requires indexed_at")
            if self.searchable_at < self.indexed_at:
                raise ValueError("searchable_at cannot precede indexed_at")
        if self.freshness_status is FreshnessStatus.deleted:
            if self.deleted_at is None:
                raise ValueError("a deleted (tombstoned) object needs deleted_at")
            if self.searchable_at is not None:
                raise ValueError("a tombstoned object can never be searchable")
        if self.deleted_at is not None and self.freshness_status is FreshnessStatus.fresh:
            raise ValueError("a tombstoned object can never be fresh")
        if self.freshness_status is FreshnessStatus.fresh and self.searchable_at is None:
            raise ValueError("fresh requires a searchable representation (searchable_at)")
        return self


class SyncRun(FreshnessModel):
    """Durable run receipt. Unique ``(source_id, scope_key, idempotency_key)``."""

    id: str
    idempotency_key: str
    source_id: str
    scope_key: str = DEFAULT_SCOPE
    connector_kind: ConnectorKind
    trigger_kind: SyncPath
    cursor_before: str | None = None
    cursor_after: str | None = None
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    status: RunStatus = RunStatus.queued
    observed_count: NonNegativeInt = 0
    applied_count: NonNegativeInt = 0
    tombstoned_count: NonNegativeInt = 0
    retry_count: NonNegativeInt = 0
    failed_count: NonNegativeInt = 0
    next_attempt_at: UtcDatetime | None = None
    error_summary: str | None = None


class FreshnessPolicy(FreshnessModel):
    """Versioned budget. PK ``(policy_id, schema_version)``; one active per (kind, class)."""

    policy_id: str
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    connector_kind: ConnectorKind
    evidence_class: EvidenceClass
    max_index_age_seconds: NonNegativeInt
    max_verification_age_seconds: NonNegativeInt
    require_live_verification: bool = False
    failure_action: FailureAction
    status: PolicyStatus = PolicyStatus.active
    effective_at: UtcDatetime | None = None
    retired_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _critical_is_strict(self) -> Self:
        if self.status is not PolicyStatus.draft and self.effective_at is None:
            raise ValueError("an active or retired policy needs effective_at")
        if (
            self.evidence_class is EvidenceClass.critical
            and self.failure_action is FailureAction.allow_with_warning
        ):
            raise ValueError(
                "critical evidence always uses a safe fallback: failure_action must be "
                "'omit' or 'abstain'"
            )
        return self


class EvidenceRef(FreshnessModel):
    """Source-scoped evidence identity supplied by the caller (never a bare slug)."""

    source_id: str
    external_object_id: str
    connector_kind: ConnectorKind
    evidence_class: EvidenceClass = EvidenceClass.standard
    page_id: str | None = None
    page_slug: str | None = None


class ReceiptItem(EvidenceRef):
    """Freshness facts for one evidence item at evaluation time (no authz, no groundedness)."""

    policy_id: str | None = None
    policy_schema_version: int | None = None
    provider_version: str | None = None
    version_order: int | None = None
    content_hash: str | None = None
    provider_modified_at: UtcDatetime | None = None
    observed_at: UtcDatetime | None = None
    accepted_at: UtcDatetime | None = None
    indexed_at: UtcDatetime | None = None
    searchable_at: UtcDatetime | None = None
    last_verified_at: UtcDatetime | None = None
    verification_result: VerificationResult | None = None
    sync_path: SyncPath | None = None
    age_seconds: NonNegativeInt | None = None
    budget_seconds: NonNegativeInt | None = None
    freshness_status: FreshnessStatus
    tombstoned: bool = False
    safe_to_use: bool
    fallback_action: FailureAction | None = None
    # Stable machine-readable code explaining a non-fresh status (e.g. "index_age_exceeded").
    reason: str | None = None


class FreshnessReceipt(FreshnessModel):
    """Immutable snapshot for an ordered evidence set. Unique ``request_key``."""

    receipt_id: str
    schema_version: int = SCHEMA_VERSION
    request_key: str
    request_payload_hash: str
    created_at: UtcDatetime
    # Set when every item was evaluated under one policy revision; otherwise None and each item
    # carries its own ``policy_id``/``policy_schema_version``.
    policy_id: str | None = None
    policy_schema_version: int | None = None
    evidence_items: list[ReceiptItem] = Field(default_factory=list)
    oldest_evidence_age_seconds: NonNegativeInt | None = None
    overall_status: OverallStatus
    receipt_hash: str


# --------------------------------------------------------------------------------------------------
# Connector / indexing contract values
# --------------------------------------------------------------------------------------------------


class NormalizedChange(FreshnessModel):
    """A provider change in the shared contract (from a webhook, delta page, or reconcile scan).

    ``provider_event_id`` may be omitted; a deterministic id is synthesised from object id, change
    kind, and version (see :func:`synthetic_event_id`).
    """

    source_id: str
    scope_key: str = DEFAULT_SCOPE
    connector_kind: ConnectorKind
    provider_event_id: str
    external_object_id: str
    change_kind: ChangeKind
    provider_version: str | None = None
    version_order: int | None = None
    provider_modified_at: UtcDatetime | None = None
    observed_at: UtcDatetime
    content_hash: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _synthesise_event_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("provider_event_id"):
            data = {
                **data,
                "provider_event_id": synthetic_event_id(
                    data["external_object_id"],
                    data["change_kind"],
                    data.get("provider_version"),
                    data.get("content_hash"),
                ),
            }
        return data


class ChangePage(FreshnessModel):
    """One page of changes from a :class:`~freshness.protocols.ChangeSource`."""

    changes: list[NormalizedChange] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class ProviderHead(FreshnessModel):
    """Lightweight provider truth for one object (no content)."""

    provider_version: str | None = None
    version_order: int | None = None
    modified_at: UtcDatetime | None = None
    deleted: bool = False
    content_hash: str | None = None


class IndexOutcome(FreshnessModel):
    """What the app's ``apply`` callable reports after indexing (or removing) one change.

    Upsert/metadata: fully current only when ``content_written and searchable and embedded``.
    Delete: removal is confirmed when ``searchable`` is False.
    The optional version/hash fields report what was actually fetched and indexed (which can be
    newer than the change that triggered it); when omitted the change's values are used.
    """

    content_written: bool
    searchable: bool
    embedded: bool
    indexed_at: UtcDatetime | None = None
    searchable_at: UtcDatetime | None = None
    page_id: str | None = None
    page_slug: str | None = None
    provider_version: str | None = None
    version_order: int | None = None
    content_hash: str | None = None
    provider_modified_at: UtcDatetime | None = None
    # Stable code for a deliberately incomplete outcome (e.g. "budget_exceeded"); used when parking.
    error_code: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.searchable and not self.content_written:
            raise ValueError("searchable requires content_written")
        if self.searchable_at is not None:
            if not self.searchable:
                raise ValueError("searchable_at set but searchable is False")
            if self.indexed_at is not None and self.searchable_at < self.indexed_at:
                raise ValueError("searchable_at cannot precede indexed_at")
        return self


# --------------------------------------------------------------------------------------------------
# Operation inputs / outputs
# --------------------------------------------------------------------------------------------------


class AcceptResult(FreshnessModel):
    """Durable acceptance of one change. ``duplicate`` means the ledger already had this id."""

    schema_version: int = SCHEMA_VERSION
    event: SourceChangeEvent
    duplicate: bool


class ConnectorSyncRequest(FreshnessModel):
    source_id: str
    scope_key: str = DEFAULT_SCOPE
    connector_kind: ConnectorKind
    trigger_kind: SyncPath
    idempotency_key: str
    page_limit: int = Field(default=100, ge=1)
    max_pages: int = Field(default=50, ge=1)
    deadline_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _sync_trigger(self) -> Self:
        if self.trigger_kind is SyncPath.live_verify:
            raise ValueError("connector_sync runs webhook, delta, or reconcile work only")
        return self


class ConnectorSyncResult(FreshnessModel):
    """Outcome of one ``connector_sync`` call.

    ``accepted_count``/``duplicate_count``/``noop_count`` describe this invocation only; on a
    ``replayed`` result (idempotency key of an already-completed run) they are 0.
    ``parked_count`` is the number of observed changes left parked (== the run's ``failed_count``).
    """

    schema_version: int = SCHEMA_VERSION
    run_id: str
    status: RunStatus
    replayed: bool = False
    cursor_before: str | None = None
    cursor_after: str | None = None
    observed_count: NonNegativeInt = 0
    accepted_count: NonNegativeInt = 0
    duplicate_count: NonNegativeInt = 0
    applied_count: NonNegativeInt = 0
    noop_count: NonNegativeInt = 0
    tombstoned_count: NonNegativeInt = 0
    parked_count: NonNegativeInt = 0
    retry_count: NonNegativeInt = 0
    next_attempt_at: UtcDatetime | None = None
    error_summary: str | None = None


class FreshnessStatusRequest(FreshnessModel):
    source_id: str
    scope_key: str = DEFAULT_SCOPE
    external_object_id: str | None = None
    evidence_class: EvidenceClass = EvidenceClass.standard


class FreshnessStatusReport(FreshnessModel):
    """Read-only freshness view of a source scope (and optionally one object)."""

    schema_version: int = SCHEMA_VERSION
    source_id: str
    scope_key: str
    generated_at: UtcDatetime
    checkpoint: ConnectorCheckpoint | None = None
    last_successful_run_at: UtcDatetime | None = None
    object_counts: dict[FreshnessStatus, int] = Field(default_factory=dict)
    pending_event_count: NonNegativeInt = 0
    parked_event_count: NonNegativeInt = 0
    oldest_non_current_age_seconds: NonNegativeInt | None = None
    object: ObjectFreshness | None = None
    # The requested object evaluated against its active policy; None if no object or no policy.
    evaluation: ReceiptItem | None = None


class VerifyRequest(FreshnessModel):
    source_id: str
    external_object_id: str
    connector_kind: ConnectorKind
    evidence_class: EvidenceClass = EvidenceClass.standard

    @classmethod
    def from_ref(cls, ref: EvidenceRef) -> VerifyRequest:
        return cls(
            source_id=ref.source_id,
            external_object_id=ref.external_object_id,
            connector_kind=ref.connector_kind,
            evidence_class=ref.evidence_class,
        )


class VerifyResult(FreshnessModel):
    """Live-verification outcome. ``item`` is the post-verification evaluation."""

    schema_version: int = SCHEMA_VERSION
    source_id: str
    external_object_id: str
    connector_kind: ConnectorKind
    evidence_class: EvidenceClass
    page_id: str | None = None
    page_slug: str | None = None
    indexed_provider_version: str | None = None
    observed_provider_version: str | None = None
    verified_at: UtcDatetime
    verification_result: VerificationResult
    freshness_status: FreshnessStatus
    budget_seconds: NonNegativeInt | None = None
    safe_to_use: bool
    fallback_action: FailureAction | None = None
    reason: str | None = None
    item: ReceiptItem


class ReceiptRequest(FreshnessModel):
    """Ordered evidence set to snapshot. ``request_key`` is globally unique when persisted."""

    request_key: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    persist: bool = True
    # A zero-item receipt is valid only when the caller explicitly declares nothing was selected.
    allow_empty: bool = False

    @model_validator(mode="after")
    def _explicit_empty(self) -> Self:
        if not self.evidence and not self.allow_empty:
            raise ValueError("empty evidence set requires allow_empty=True")
        return self
