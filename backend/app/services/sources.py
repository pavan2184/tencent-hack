"""Sources: registry (gbrain `sources_*` mirrors) and connector syncs through the freshness lib."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from access_control import SourceKind
from freshness import ConnectorSyncRequest, ConnectorSyncResult, SyncPath

from app.connectors.base import Connector, freshness_kind
from app.connectors.registry import connector_name, get_connector, is_stub
from app.core.errors import Conflict, NotFound, NotImplementedFeature, ValidationFailed
from app.schemas.domain import IngestLogEntry, Page, Source
from app.services import jobs
from app.services.ingestion import make_apply

if TYPE_CHECKING:
    from app.services.wiring import Services

logger = logging.getLogger(__name__)

UPLOADS_SOURCE_ID = "uploads"


async def list_sources(services: Services, *, include_archived: bool = False) -> list[Source]:
    return await services.repo.list_sources(include_archived=include_archived)


async def get_source(services: Services, source_id: str) -> Source:
    source = await services.repo.get_source(source_id)
    if source is None:
        raise NotFound("Source not found.")
    return source


async def add_source(
    services: Services,
    *,
    id: str,  # noqa: A002 - mirrors gbrain `sources_add`
    name: str,
    kind: str,
    local_path: str | None = None,
    config: dict[str, Any] | None = None,
    description: str = "",
    replace: bool = True,
) -> Source:
    """Register (or, with `replace`, update) a source. Name must be unique across sources."""
    try:
        source_kind = SourceKind(kind)
    except ValueError as exc:
        raise ValidationFailed(
            "Unknown source kind.", details={"errors": [{"loc": ["kind"], "input": kind}]}
        ) from exc
    config = dict(config or {})
    local_path = local_path or config.get("local_path")
    existing = await services.repo.get_source(id)
    if existing is not None and not replace:
        raise Conflict("Source already exists.")
    for other in await services.repo.list_sources(include_archived=True):
        if other.name == name and other.id != id:
            raise Conflict("Source name already in use.")
    source = Source(
        id=id,
        name=name,
        kind=source_kind,
        description=description,
        local_path=local_path,
        config=config,
    )
    return await services.repo.upsert_source(source)


async def ensure_uploads_source(services: Services) -> Source:
    source = await services.repo.get_source(UPLOADS_SOURCE_ID)
    if source is not None:
        return source
    return await add_source(
        services,
        id=UPLOADS_SOURCE_ID,
        name="Uploads",
        kind="upload",
        config={"connector": "upload"},
        description="Documents uploaded through the web UI, REST or MCP.",
    )


async def source_status(services: Services, source_id: str, *, admin: bool = False) -> dict:
    """Freshness status report for a source (checkpoint, last run, event and object counts).
    `objects_by_status` is included only for admins (counts cover invisible documents)."""
    from freshness import FreshnessStatusRequest

    source = await get_source(services, source_id)
    report = await services.freshness.freshness_status(FreshnessStatusRequest(source_id=source.id))
    last_run = None
    checkpoint = report.checkpoint
    if checkpoint is not None and checkpoint.last_successful_run_id:
        run = await services.freshness_store.get_run(checkpoint.last_successful_run_id)
        if run is not None:
            last_run = run.model_dump(
                mode="json",
                include={
                    "id",
                    "trigger_kind",
                    "status",
                    "started_at",
                    "completed_at",
                    "observed_count",
                    "applied_count",
                    "tombstoned_count",
                    "failed_count",
                },
            )
    body: dict[str, Any] = {
        "schema_version": report.schema_version,
        "source_id": source.id,
        "connector_kind": freshness_kind(source).value,
        "connector": connector_name(source),
        "generated_at": report.generated_at.isoformat(),
        "checkpoints": [
            checkpoint.model_dump(
                mode="json",
                include={
                    "scope_key",
                    "cursor_value",
                    "cursor_version",
                    "status",
                    "last_polled_at",
                    "last_reconciled_at",
                    "last_successful_run_id",
                },
            )
        ]
        if checkpoint is not None
        else [],
        "last_run": last_run,
        "last_successful_run_at": report.last_successful_run_at.isoformat()
        if report.last_successful_run_at
        else None,
        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
        "pending_events": report.pending_event_count,
        "parked_events": report.parked_event_count,
    }
    if admin:
        body["objects_by_status"] = {
            str(status): count for status, count in report.object_counts.items() if count
        }
    return body


def _sync_request(source: Source, trigger_kind: str, idempotency_key: str) -> ConnectorSyncRequest:
    trigger = SyncPath(str(trigger_kind))
    return ConnectorSyncRequest(
        source_id=source.id,
        connector_kind=freshness_kind(source),
        trigger_kind=trigger,
        idempotency_key=idempotency_key,
    )


async def run_sync(
    services: Services,
    source_id: str,
    trigger_kind: str,
    idempotency_key: str,
    *,
    granted_by: str = "system:sync",
) -> ConnectorSyncResult:
    """One webhook/delta/reconcile sync: the connector is the change source, ingestion applies.

    Raises `NotFound` for an unknown source and `NotImplementedError` for stub connectors.
    """
    source = await services.repo.get_source(source_id)
    if source is None:
        raise NotFound("Source not found.")
    if is_stub(source):
        raise NotImplementedError(f"{connector_name(source)} connector is a stub — owner: Pavan")
    connector = get_connector(source, services)
    result = await services.freshness.connector_sync(
        _sync_request(source, trigger_kind, idempotency_key),
        change_source=connector,
        apply=make_apply(services, source, connector, granted_by=granted_by),
    )
    pages = await services.repo.list_pages(source_ids=[source.id], limit=10_000)
    await refresh_permission_snapshots(services, source, connector, pages)
    newest = max(
        (p.provider_modified_at for p in pages if p.provider_modified_at is not None),
        default=None,
    )
    await services.repo.touch_source_sync(source.id, services.clock.now(), newest)
    if not result.replayed:
        await services.repo.log_ingest(
            IngestLogEntry(
                source_id=source.id,
                source_type=connector_name(source),
                source_ref=f"sync:{trigger_kind}:{idempotency_key}",
                pages_updated=[],
                summary=(
                    f"{result.status}: observed {result.observed_count}, applied "
                    f"{result.applied_count}, tombstoned {result.tombstoned_count}, parked "
                    f"{result.parked_count}"
                ),
            )
        )
    return result


async def refresh_permission_snapshots(
    services: Services, source: Source, connector: Connector, pages: list[Page]
) -> int:
    """Re-read every live page's source permissions so snapshots stay within the policy's maximum
    age (`access_control.DEFAULT_MAX_PERMISSION_AGE`), even when content did not change.

    Uploads are skipped: their permissions are managed locally. A page whose permissions cannot
    be read keeps its old snapshot, which then ages out and is denied (fail closed)."""
    if source.kind == SourceKind.upload:
        return 0
    refreshed = 0
    for page in pages:
        if page.deleted_at is not None or not page.external_object_id:
            continue
        try:
            perms = await connector.permissions(page.external_object_id)
        except Exception:
            logger.warning(
                "permission refresh failed",
                extra={"source_id": source.id, "page_id": page.id},
            )
            continue
        await services.permission_store.put(page.id, perms)
        refreshed += 1
    return refreshed


async def queue_sync(services: Services, source_id: str, trigger_kind: str) -> str:
    """Create the `queued` run (for the 202 `run_id`) and enqueue the worker sync."""
    source = await get_source(services, source_id)
    if is_stub(source):
        raise NotImplementedFeature(f"{connector_name(source)} connector is a stub — owner: Pavan")
    if str(trigger_kind) not in (SyncPath.delta, SyncPath.reconcile):
        raise ValidationFailed(
            "trigger_kind must be 'delta' or 'reconcile'.",
            details={"errors": [{"loc": ["trigger_kind"], "input": str(trigger_kind)}]},
        )
    key = f"manual:{source.id}:{uuid4()}"
    run = await services.freshness.queue_sync(_sync_request(source, trigger_kind, key))
    jobs.enqueue_sync(source.id, str(trigger_kind), key)
    return run.id
