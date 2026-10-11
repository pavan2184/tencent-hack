"""Canonical JSON, deterministic hashes, and receipt assembly.

Canonical JSON: keys sorted, compact separators, UTF-8, timestamps as UTC ISO-8601, enums as their
values, no NaN. ``receipt_hash`` covers the whole receipt except ``receipt_id``, ``created_at``
and itself, so two snapshots of the same facts hash identically regardless of when/where stored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Final

from pydantic import BaseModel

from freshness.enums import FreshnessStatus, OverallStatus
from freshness.models import SCHEMA_VERSION, FreshnessReceipt, ReceiptItem, ReceiptRequest
from freshness.protocols import ReceiptConflict

RECEIPT_HASH_EXCLUDED: Final = frozenset({"receipt_id", "created_at", "receipt_hash"})

_BUCKET: Final = {
    FreshnessStatus.fresh: OverallStatus.fresh,
    FreshnessStatus.stale: OverallStatus.stale,
    FreshnessStatus.deleted: OverallStatus.stale,  # provider reports deletion -> stale
    FreshnessStatus.unknown: OverallStatus.unknown,
    FreshnessStatus.not_searchable: OverallStatus.unknown,
}


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical JSON requires timezone-aware datetimes")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(_canonical(k)): _canonical(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_canonical(v) for v in value)
    return value


def canonical_json(value: Any, *, exclude: Collection[str] = ()) -> str:
    """Serialise ``value`` (model, mapping, list, scalar) to canonical JSON.

    ``exclude`` drops top-level keys when ``value`` is a model or mapping.
    """
    data = _canonical(value)
    if exclude and isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in exclude}
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def canonical_hash(value: Any, *, exclude: Collection[str] = ()) -> str:
    """SHA-256 hex digest of :func:`canonical_json`."""
    return hashlib.sha256(canonical_json(value, exclude=exclude).encode("utf-8")).hexdigest()


def compute_receipt_hash(receipt: FreshnessReceipt) -> str:
    """Integrity hash of a receipt (excludes ``receipt_id``, ``created_at``, ``receipt_hash``)."""
    return canonical_hash(receipt, exclude=RECEIPT_HASH_EXCLUDED)


def verify_receipt_hash(receipt: FreshnessReceipt) -> bool:
    """True when ``receipt.receipt_hash`` matches its content (audit reconstruction check)."""
    return receipt.receipt_hash == compute_receipt_hash(receipt)


def request_payload_hash(request: ReceiptRequest) -> str:
    """Hash of the request identity, computed before reading any mutable freshness state.

    Covers the contract version, the ordered source-scoped evidence identifiers, and the explicit
    empty-set declaration. ``persist`` is not part of the identity.
    """
    return canonical_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "evidence": [ref.model_dump(mode="python") for ref in request.evidence],
            "allow_empty": request.allow_empty,
        }
    )


def overall_status(items: Sequence[ReceiptItem]) -> OverallStatus:
    """Roll item statuses up: empty → not_required; one bucket → that bucket; else mixed.

    Buckets: fresh → fresh; stale/deleted → stale; unknown/not_searchable → unknown.
    """
    if not items:
        return OverallStatus.not_required
    buckets = {_BUCKET[item.freshness_status] for item in items}
    return buckets.pop() if len(buckets) == 1 else OverallStatus.mixed


def oldest_age_seconds(items: Sequence[ReceiptItem]) -> int | None:
    ages = [item.age_seconds for item in items if item.age_seconds is not None]
    return max(ages) if ages else None


def build_receipt(
    *,
    request: ReceiptRequest,
    request_hash: str,
    items: list[ReceiptItem],
    receipt_id: str,
    created_at: datetime,
) -> FreshnessReceipt:
    """Assemble a receipt; items are kept exactly as given (input order, nothing dropped)."""
    policies = {(item.policy_id, item.policy_schema_version) for item in items}
    single = len(policies) == 1 and None not in next(iter(policies))
    policy_id, policy_version = next(iter(policies)) if single else (None, None)
    draft = FreshnessReceipt(
        receipt_id=receipt_id,
        request_key=request.request_key,
        request_payload_hash=request_hash,
        created_at=created_at,
        policy_id=policy_id,
        policy_schema_version=policy_version,
        evidence_items=items,
        oldest_evidence_age_seconds=oldest_age_seconds(items),
        overall_status=overall_status(items),
        receipt_hash="",
    )
    return draft.evolve(receipt_hash=compute_receipt_hash(draft))


def check_replay(existing: FreshnessReceipt, request_hash: str) -> FreshnessReceipt:
    """Resolve a ``request_key`` collision: same request hash → existing; else ReceiptConflict."""
    if existing.request_payload_hash == request_hash:
        return existing
    raise ReceiptConflict(
        f"request_key {existing.request_key!r} was already used for a different evidence request"
    )
