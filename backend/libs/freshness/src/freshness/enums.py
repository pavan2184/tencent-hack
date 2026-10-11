"""Closed vocabularies for the freshness library.

Ported from the superseded TypeScript spec (``docs/superpowers/specs/2026-09-24-gbrain-freshness-
foundation-design.md``) and Pavan's branch data-model doc. Where the branch used
``searchable_current`` / ``pending`` this library uses ``fresh`` / ``not_searchable`` (see README).
Values are wire-stable: they are persisted in Postgres and emitted in receipts.
"""

from __future__ import annotations

from enum import StrEnum


class ConnectorKind(StrEnum):
    """Provider family a source/object/policy belongs to."""

    confluence = "confluence"
    slack = "slack"
    jira = "jira"
    google_drive = "google_drive"
    email = "email"
    upload = "upload"
    gbrain_import = "gbrain_import"
    mcp_external = "mcp_external"

    @classmethod
    def _missing_(cls, value: object) -> ConnectorKind | None:
        # ``access_control.SourceKind`` spells Google Drive as ``gdrive``; accept it on input so the
        # app can pass a page's ``source_kind`` straight through. Output is always ``google_drive``.
        if isinstance(value, str):
            alias = _CONNECTOR_ALIASES.get(value.strip().lower())
            if alias is not None:
                return cls(alias)
        return None


_CONNECTOR_ALIASES: dict[str, str] = {"gdrive": "google_drive"}


class FreshnessStatus(StrEnum):
    """Current freshness of one provider object.

    Branch vocabulary: ``searchable_current`` -> ``fresh``, ``pending`` -> ``not_searchable``.
    """

    fresh = "fresh"
    stale = "stale"
    unknown = "unknown"
    not_searchable = "not_searchable"
    deleted = "deleted"


class VerificationResult(StrEnum):
    """Outcome of a live provider check."""

    fresh = "fresh"
    stale = "stale"
    unknown = "unknown"
    not_required = "not_required"


class SyncPath(StrEnum):
    """Path that produced an object's state (also a run's ``trigger_kind``)."""

    webhook = "webhook"
    delta = "delta"
    reconcile = "reconcile"
    live_verify = "live_verify"


class ChangeKind(StrEnum):
    upsert = "upsert"
    delete = "delete"
    metadata_change = "metadata_change"


class EventState(StrEnum):
    """Ledger state: ``accepted -> processing -> applied`` or ``accepted/processing -> parked``."""

    accepted = "accepted"
    processing = "processing"
    applied = "applied"
    parked = "parked"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    partial = "partial"
    failed = "failed"
    parked = "parked"


class CheckpointStatus(StrEnum):
    ready = "ready"
    polling = "polling"
    degraded = "degraded"
    paused = "paused"


class EvidenceClass(StrEnum):
    critical = "critical"
    standard = "standard"


class FailureAction(StrEnum):
    """What a consumer must do with non-fresh evidence. ``allow_with_warning`` is standard-only."""

    omit = "omit"
    abstain = "abstain"
    allow_with_warning = "allow_with_warning"


class PolicyStatus(StrEnum):
    draft = "draft"
    active = "active"
    retired = "retired"


class OverallStatus(StrEnum):
    """Receipt-level roll-up of item statuses."""

    fresh = "fresh"
    stale = "stale"
    unknown = "unknown"
    not_required = "not_required"
    mixed = "mixed"
