"""Pure query-time policy evaluation: object state + policy + now → :class:`ReceiptItem`.

No I/O and no clock: the same inputs always give the same item. Decision order (first match wins):

1. tombstoned (``deleted``)                                  → ``deleted``
2. no searchable representation / stored ``not_searchable``  → ``not_searchable``
3. stored ``stale`` or last verification ``stale``          → ``stale``
4. stored ``unknown`` or last verification ``unknown``      → ``unknown``
5. age > ``max_index_age_seconds``                           → ``stale``
6. ``require_live_verification`` and never verified, or verified longer ago than
   ``max_verification_age_seconds``                          → ``unknown``
7. otherwise                                                 → ``fresh``

Age is ``now − last_verified_at`` when the last verification matched the provider (``fresh``),
else ``now − searchable_at``. Nothing here can turn ``unknown`` into ``fresh``.
"""

from __future__ import annotations

from datetime import datetime

from freshness.enums import (
    EvidenceClass,
    FailureAction,
    FreshnessStatus,
    VerificationResult,
)
from freshness.models import EvidenceRef, FreshnessPolicy, ObjectFreshness, ReceiptItem


def _age_seconds(since: datetime | None, now: datetime) -> int | None:
    if since is None:
        return None
    return max(0, int((now - since).total_seconds()))


def safe_use(
    status: FreshnessStatus,
    evidence_class: EvidenceClass,
    policy: FreshnessPolicy | None,
) -> tuple[bool, FailureAction | None]:
    """Return ``(safe_to_use, fallback_action)`` for an evaluated status.

    - ``fresh`` → safe, no fallback.
    - ``deleted`` → never safe (a tombstone has no content to use); fallback ``omit`` unless the
      policy says ``abstain``.
    - critical non-fresh → never safe; the policy's ``failure_action`` (omit/abstain).
    - standard non-fresh → the policy decides: ``allow_with_warning`` is safe (status preserved),
      ``omit``/``abstain`` are not.
    - no policy → never safe, ``omit``: no policy defaults unknown state to fresh.
    """
    if status is FreshnessStatus.fresh:
        return True, None
    if policy is None:
        return False, FailureAction.omit
    action = policy.failure_action
    if status is FreshnessStatus.deleted:
        return False, (
            FailureAction.abstain if action is FailureAction.abstain else FailureAction.omit
        )
    if evidence_class is EvidenceClass.critical:
        strict = FailureAction.omit if action is FailureAction.allow_with_warning else action
        return False, strict
    return action is FailureAction.allow_with_warning, action


def _status(
    obj: ObjectFreshness, policy: FreshnessPolicy, now: datetime
) -> tuple[FreshnessStatus, str | None, int | None]:
    verified_fresh = (
        obj.verification_result is VerificationResult.fresh and obj.last_verified_at is not None
    )
    basis = obj.last_verified_at if verified_fresh else obj.searchable_at
    age = _age_seconds(basis, now)

    if obj.freshness_status is FreshnessStatus.deleted:
        return FreshnessStatus.deleted, "tombstoned", age
    if obj.searchable_at is None or obj.freshness_status is FreshnessStatus.not_searchable:
        return FreshnessStatus.not_searchable, "not_searchable", age
    if obj.freshness_status is FreshnessStatus.stale:
        return FreshnessStatus.stale, "stale_state", age
    if obj.verification_result is VerificationResult.stale:
        return FreshnessStatus.stale, "verification_stale", age
    if obj.freshness_status is FreshnessStatus.unknown:
        return FreshnessStatus.unknown, "unknown_state", age
    if obj.verification_result is VerificationResult.unknown:
        return FreshnessStatus.unknown, "verification_unknown", age
    if age is not None and age > policy.max_index_age_seconds:
        return FreshnessStatus.stale, "index_age_exceeded", age
    if policy.require_live_verification:
        if obj.last_verified_at is None or obj.verification_result is None:
            return FreshnessStatus.unknown, "verification_missing", age
        verification_age = _age_seconds(obj.last_verified_at, now)
        if verification_age is not None and verification_age > policy.max_verification_age_seconds:
            return FreshnessStatus.unknown, "verification_expired", age
    return FreshnessStatus.fresh, None, age


def evaluate(
    obj: ObjectFreshness,
    policy: FreshnessPolicy,
    now: datetime,
    *,
    ref: EvidenceRef | None = None,
) -> ReceiptItem:
    """Evaluate one object against ``policy`` at ``now`` (pure).

    ``ref`` supplies the caller's evidence identity (evidence class, page link); without it the
    identity is taken from ``obj`` and the evidence class from ``policy``.
    """
    status, reason, age = _status(obj, policy, now)
    evidence_class = ref.evidence_class if ref is not None else policy.evidence_class
    safe, fallback = safe_use(status, evidence_class, policy)
    verification = obj.verification_result
    if verification is None and not policy.require_live_verification:
        verification = VerificationResult.not_required
    return ReceiptItem(
        source_id=obj.source_id,
        external_object_id=obj.external_object_id,
        connector_kind=obj.connector_kind,
        evidence_class=evidence_class,
        page_id=(ref.page_id if ref is not None and ref.page_id else obj.page_id),
        page_slug=(ref.page_slug if ref is not None and ref.page_slug else obj.page_slug),
        policy_id=policy.policy_id,
        policy_schema_version=policy.schema_version,
        provider_version=obj.provider_version,
        version_order=obj.version_order,
        content_hash=obj.content_hash,
        provider_modified_at=obj.provider_modified_at,
        observed_at=obj.observed_at,
        accepted_at=obj.accepted_at,
        indexed_at=obj.indexed_at,
        searchable_at=obj.searchable_at,
        last_verified_at=obj.last_verified_at,
        verification_result=verification,
        sync_path=obj.sync_path,
        age_seconds=age,
        budget_seconds=policy.max_index_age_seconds,
        freshness_status=status,
        tombstoned=obj.deleted_at is not None or status is FreshnessStatus.deleted,
        safe_to_use=safe,
        fallback_action=fallback,
        reason=reason,
    )


def evaluate_missing(
    ref: EvidenceRef,
    policy: FreshnessPolicy | None,
    *,
    reason: str = "object_not_found",
) -> ReceiptItem:
    """Item for evidence with no freshness record (or no policy): ``unknown``, never fresh."""
    safe, fallback = safe_use(FreshnessStatus.unknown, ref.evidence_class, policy)
    return ReceiptItem(
        **ref.model_dump(),
        policy_id=policy.policy_id if policy is not None else None,
        policy_schema_version=policy.schema_version if policy is not None else None,
        budget_seconds=policy.max_index_age_seconds if policy is not None else None,
        freshness_status=FreshnessStatus.unknown,
        safe_to_use=safe,
        fallback_action=fallback,
        reason=reason,
    )
