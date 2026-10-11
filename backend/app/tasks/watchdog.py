"""`tasks.watchdog_sweep` (q.maintenance, every WATCHDOG_INTERVAL_S): fail stuck sync runs.

A `sync_runs` row left `running` for more than 2x the sync task's hard time limit belongs to a
worker that died mid-run (OOM, SIGKILL, lost container). The sweep marks it `failed` with
`error_summary="watchdog_timeout"` so status pages stop reporting it as in progress; the next
delta/reconcile run resumes the work (the cursor only ever advanced past fully accounted pages).

TODO(Pavan): `freshness.FreshnessStore` has no list-runs method yet. The sweep calls
`store.list_runs(statuses=[RunStatus.running], limit=...)` only when the store provides it
(suggested SQL: `SELECT * FROM sync_runs WHERE status = ANY(:statuses) ORDER BY started_at
LIMIT :limit`, served by `idx_sync_runs_status_next`); otherwise it is a logged no-op.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from freshness import FreshnessStore, RunStatus

from app.celery_app import TASK_SYNC_SOURCE, TASK_WATCHDOG_SWEEP, TIME_LIMITS, celery_app
from app.tasks.common import run_async, services

logger = logging.getLogger(__name__)

STUCK_AFTER_S = 2 * TIME_LIMITS[TASK_SYNC_SOURCE][1]
SWEEP_LIMIT = 500


async def sweep_stuck_runs(
    store: FreshnessStore,
    *,
    now: datetime | None = None,
    stuck_after_s: int = STUCK_AFTER_S,
) -> dict[str, Any]:
    """Mark `running` runs older than `stuck_after_s` as `failed`. Safe no-op when unsupported."""
    list_runs = getattr(store, "list_runs", None)
    if list_runs is None:
        logger.info("watchdog: freshness store cannot list runs; sweep skipped (TODO Pavan)")
        return {"supported": False, "checked": 0, "failed_run_ids": []}
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=stuck_after_s)
    runs = await list_runs(statuses=[RunStatus.running], limit=SWEEP_LIMIT)
    failed: list[str] = []
    for run in runs:
        if run.status is not RunStatus.running or run.started_at >= cutoff:
            continue
        await store.update_run(
            run.evolve(status=RunStatus.failed, completed_at=now, error_summary="watchdog_timeout")
        )
        failed.append(run.id)
    if failed:
        logger.warning("watchdog: failed stuck sync runs", extra={"run_ids": failed})
    return {"supported": True, "checked": len(runs), "failed_run_ids": failed}


@celery_app.task(name=TASK_WATCHDOG_SWEEP)
def watchdog_sweep_task() -> dict[str, Any]:
    return run_async(sweep_stuck_runs(services().freshness_store))
