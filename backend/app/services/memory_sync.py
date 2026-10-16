"""In-process delta syncs for `REPO_BACKEND=memory`, standing in for Celery beat.

Permission snapshots expire by classification (5 minutes for confidential documents, D-018) and
only a sync refreshes them. With the SQL backend the beat's delta fan-out does that from the
worker. An in-memory API keeps its stores inside the API process, where no worker can reach them,
so without this loop every confidential document goes dark 5 minutes after start-up (D-022).

Each tick runs the same `run_sync` the worker runs, once per non-archived source with a real
connector, with the beat's time-bucketed idempotency key. A failing source is logged and skipped;
the others still sync.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from freshness import SyncPath

from app.connectors.registry import is_stub

if TYPE_CHECKING:
    from app.services.wiring import Services

logger = logging.getLogger(__name__)


async def sync_all_sources(services: Services) -> list[str]:
    """One delta sync per syncable source; returns the ids that synced."""
    from app.services.sources import run_sync
    from app.tasks.sync import sync_idempotency_key, time_bucket

    interval_s = services.settings.SYNC_DELTA_INTERVAL_S
    bucket = time_bucket(interval_s)
    synced: list[str] = []
    for source in await services.repo.list_sources():
        if is_stub(source):
            continue
        key = sync_idempotency_key(SyncPath.delta.value, source.id, bucket)
        try:
            await run_sync(services, source.id, SyncPath.delta.value, key)
        except Exception:
            logger.warning("in-process sync failed", extra={"source_id": source.id}, exc_info=True)
            continue
        synced.append(source.id)
    return synced


async def keep_permissions_fresh(services: Services, interval_s: float) -> None:
    """Sync every source every `interval_s` seconds until cancelled (first run after one wait)."""
    while True:
        await asyncio.sleep(interval_s)
        synced = await sync_all_sources(services)
        logger.debug("in-process sync tick", extra={"sources": synced})
