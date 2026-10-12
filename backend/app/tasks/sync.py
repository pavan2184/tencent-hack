"""Connector sync tasks (q.sync) and their beat fan-outs (q.maintenance).

`tasks.sync_source` runs one `freshness.connector_sync` for a source through
`app.services.sources.run_sync` (connector = change source, ingestion = apply). The beat fan-outs
enqueue one `sync_source` per non-archived source with a time-bucketed idempotency key
`"<trigger>:<source_id>:<bucket>"`, so a duplicate beat tick inside one interval replays the same
run instead of starting a second one.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from celery import Task
from freshness import SyncPath

from app.celery_app import (
    TASK_RECONCILE_ALL,
    TASK_SYNC_DELTA_ALL,
    TASK_SYNC_SOURCE,
    TIME_LIMITS,
    celery_app,
)
from app.config import settings
from app.tasks.common import (
    RETRYABLE,
    backoff_seconds,
    maybe_await,
    run_async,
    services,
    source_lock,
)

logger = logging.getLogger(__name__)

SYNC_HARD_LIMIT_S = TIME_LIMITS[TASK_SYNC_SOURCE][1]


def time_bucket(interval_s: int, now: float | None = None) -> int:
    """Interval-aligned epoch seconds (`floor(now / interval) * interval`)."""
    interval_s = max(1, int(interval_s))
    now = time.time() if now is None else now
    return int(now // interval_s) * interval_s


def sync_idempotency_key(trigger_kind: str, source_id: str, bucket: int | str) -> str:
    return f"{trigger_kind}:{source_id}:{bucket}"


@celery_app.task(name=TASK_SYNC_SOURCE, bind=True, max_retries=settings.TASK_MAX_RETRIES)
def sync_source_task(
    self: Task, *, source_id: str, trigger_kind: str, idempotency_key: str
) -> dict[str, Any]:
    """Run one webhook/delta/reconcile sync for a source; returns `ConnectorSyncResult` JSON."""
    from app.services.sources import run_sync

    trigger = SyncPath(trigger_kind)
    with source_lock(source_id, ttl_s=SYNC_HARD_LIMIT_S) as held:
        if not held:
            if self.request.retries >= self.max_retries:
                logger.warning("sync skipped: source locked", extra={"source_id": source_id})
                return {"status": "skipped", "reason": "source_locked", "source_id": source_id}
            raise self.retry(countdown=backoff_seconds(self.request.retries))
        try:
            result = run_async(run_sync(services(), source_id, trigger, idempotency_key))
        except NotImplementedError as exc:
            # Stub connectors (owner: Pavan) cannot list changes yet; don't fail every beat tick.
            logger.info("sync skipped: %s", exc, extra={"source_id": source_id})
            return {"status": "skipped", "reason": "connector_stub", "source_id": source_id}
        except RETRYABLE as exc:
            logger.warning(
                "sync retry", extra={"source_id": source_id, "error": type(exc).__name__}
            )
            raise self.retry(exc=exc, countdown=backoff_seconds(self.request.retries)) from exc
    return result.model_dump(mode="json")


async def _syncable_source_ids() -> list[str]:
    from app.services.sources import list_sources

    sources = await maybe_await(list_sources(services()))
    if isinstance(sources, dict):  # tolerate a paged {"items": [...]} shape
        sources = sources.get("items", [])
    return [s.id for s in sources if not getattr(s, "archived", False)]


def _fan_out(trigger: SyncPath, interval_s: int) -> dict[str, Any]:
    bucket = time_bucket(interval_s)
    source_ids = run_async(_syncable_source_ids())
    for source_id in source_ids:
        sync_source_task.apply_async(
            kwargs={
                "source_id": source_id,
                "trigger_kind": trigger.value,
                "idempotency_key": sync_idempotency_key(trigger.value, source_id, bucket),
            }
        )
    logger.info("sync fan-out", extra={"trigger": trigger.value, "sources": len(source_ids)})
    return {"trigger_kind": trigger.value, "bucket": bucket, "enqueued": source_ids}


@celery_app.task(name=TASK_SYNC_DELTA_ALL)
def sync_delta_all_task() -> dict[str, Any]:
    """Beat (every SYNC_DELTA_INTERVAL_S): one delta sync per non-archived source."""
    return _fan_out(SyncPath.delta, settings.SYNC_DELTA_INTERVAL_S)


@celery_app.task(name=TASK_RECONCILE_ALL)
def reconcile_all_task() -> dict[str, Any]:
    """Beat (every SYNC_RECONCILE_INTERVAL_S): one full reconcile per non-archived source."""
    return _fan_out(SyncPath.reconcile, settings.SYNC_RECONCILE_INTERVAL_S)
