"""Permission drift: a document's source ACL changed between two captures.

The policy only sees the latest snapshot, so an ACL change is otherwise silent: nothing records
that the audience changed, and the freshness pipeline (which tracks content versions) never hears
about a share that was added or removed without an edit. ``detect_permission_drift`` compares two
captures by ``permission_fingerprint`` (the ACL itself, not capture time or run id), so the app can
record the change and tell freshness through one hook. A first capture is not drift.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from access_control.connectors import permission_fingerprint
from access_control.permissions import SourcePermissions


class PermissionDrift(BaseModel):
    """One observed change of a document's source permissions. Carries fingerprints and
    versions only, never ACL members, so it can be logged without disclosing who was added or
    removed."""

    document_id: str
    previous_fingerprint: str
    current_fingerprint: str
    previous_version: str | None
    current_version: str | None
    previous_captured_at: datetime
    observed_at: datetime


def detect_permission_drift(
    document_id: str, previous: SourcePermissions | None, current: SourcePermissions
) -> PermissionDrift | None:
    """The drift from ``previous`` to ``current``, or None when the ACL is unchanged."""
    if previous is None:
        return None
    before = permission_fingerprint(previous.raw)
    after = permission_fingerprint(current.raw)
    if before == after:
        return None
    return PermissionDrift(
        document_id=document_id,
        previous_fingerprint=before,
        current_fingerprint=after,
        previous_version=previous.permission_version,
        current_version=current.permission_version,
        previous_captured_at=previous.captured_at,
        observed_at=current.captured_at,
    )
