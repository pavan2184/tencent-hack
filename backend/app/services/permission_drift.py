"""The single write path for imported permission snapshots, and the permission-drift hook that
access control shares with freshness (D-024).

Every connector snapshot goes through `store_permissions`. When the ACL differs from the stored
one (`access_control.detect_permission_drift`, by fingerprint):

1. a hash-chained `access.permission_drift` audit event records which document's audience
   changed, by fingerprint and version only (never the members added or removed);
2. when the change was seen by a permission refresh rather than a content sync, a freshness
   `metadata_change` event is accepted for the object, so the next sync re-applies it. Freshness
   then knows the object changed although its content did not, and re-ingesting it brings the
   page's own `permission_version` into line with the new snapshot.

Until that re-apply, a page whose expected `permission_version` no longer matches the new
snapshot is denied to everyone (`R9:permission_version_mismatch`): the gap fails closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from access_control import PermissionDrift, SourcePermissions, detect_permission_drift
from freshness import ChangeKind, NormalizedChange

from app.connectors.base import freshness_kind
from app.schemas.domain import Page, Source
from app.services import audit

if TYPE_CHECKING:
    from app.services.wiring import Services

DRIFT_ACTION = "access.permission_drift"


def _version_order(page: Page) -> int | None:
    value = (page.frontmatter or {}).get("version_order")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def store_permissions(
    services: Services,
    page: Page,
    perms: SourcePermissions,
    *,
    observed_via: str,
    source: Source | None = None,
) -> PermissionDrift | None:
    """Replace the page's snapshot with `perms`; on drift, audit it and (with `source`, i.e. from
    a permission refresh) tell freshness. Returns the drift, or None when the ACL is unchanged."""
    previous = (await services.permission_store.get_many([page.id])).get(page.id)
    await services.permission_store.put(page.id, perms)
    drift = detect_permission_drift(page.id, previous, perms)
    if drift is None:
        return None
    payload: dict[str, Any] = {
        **drift.model_dump(mode="json"),
        "source_id": page.source_id,
        "observed_via": observed_via,
        "freshness_notified": False,
    }
    if source is not None and page.external_object_id:
        accepted = await services.freshness.accept(
            NormalizedChange(
                source_id=source.id,
                connector_kind=freshness_kind(source),
                # One event per ACL state: a later, different change is never a duplicate.
                provider_event_id=(
                    f"permission-drift:{page.external_object_id}:{drift.current_fingerprint}"
                ),
                external_object_id=page.external_object_id,
                change_kind=ChangeKind.metadata_change,
                provider_version=page.provider_version,
                version_order=_version_order(page),
                provider_modified_at=page.provider_modified_at,
                observed_at=drift.observed_at,
            )
        )
        payload["freshness_notified"] = True
        payload["freshness_event_id"] = accepted.event.id
    await audit.record(
        services,
        actor_id=None,
        action=DRIFT_ACTION,
        subject_type="document",
        subject_id=page.id,
        payload=payload,
    )
    return drift
