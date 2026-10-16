"""Celery application: queues, routing, time limits, the beat schedule and worker signals.

One backend image runs as `ROLE=worker` (`celery -A app.celery_app.celery_app worker -Q ...`) or
`ROLE=beat`. Tasks live in `app.tasks.*` and reach the async service layer only through
`app.tasks.common.run_async`. Tests run with `CELERY_TASK_ALWAYS_EAGER=true` (no broker needed).

Task names (stable; `app.services.jobs` enqueues by these):

| name                   | queue           | soft / hard limit |
| ---------------------- | --------------- | ----------------- |
| `tasks.ingest_page`    | `q.ingest`      | 240 / 300 s       |
| `tasks.sync_source`    | `q.sync`        | 540 / 600 s       |
| `tasks.verify_object`  | `q.verify`      | 50 / 60 s         |
| `tasks.sync_delta_all` | `q.maintenance` | Celery default    |
| `tasks.reconcile_all`  | `q.maintenance` | Celery default    |
| `tasks.watchdog_sweep` | `q.maintenance` | Celery default    |
"""

from __future__ import annotations

import inspect
import logging
from contextvars import Token
from typing import Any

from celery import Celery
from celery.signals import task_postrun, task_prerun, worker_process_init

from app.config import settings
from app.core.context import job_id_var

logger = logging.getLogger(__name__)

QUEUE_INGEST = "q.ingest"
QUEUE_SYNC = "q.sync"
QUEUE_VERIFY = "q.verify"
QUEUE_MAINTENANCE = "q.maintenance"
QUEUES: tuple[str, ...] = (QUEUE_INGEST, QUEUE_SYNC, QUEUE_VERIFY, QUEUE_MAINTENANCE)

TASK_INGEST_PAGE = "tasks.ingest_page"
TASK_SYNC_SOURCE = "tasks.sync_source"
TASK_SYNC_DELTA_ALL = "tasks.sync_delta_all"
TASK_RECONCILE_ALL = "tasks.reconcile_all"
TASK_VERIFY_OBJECT = "tasks.verify_object"
TASK_WATCHDOG_SWEEP = "tasks.watchdog_sweep"

#: (soft, hard) time limits in seconds. The watchdog treats a run as stuck after 2x the hard limit.
TIME_LIMITS: dict[str, tuple[int, int]] = {
    TASK_INGEST_PAGE: (240, 300),
    TASK_SYNC_SOURCE: (540, 600),
    TASK_VERIFY_OBJECT: (50, 60),
}

TASK_ROUTES: dict[str, dict[str, str]] = {
    TASK_INGEST_PAGE: {"queue": QUEUE_INGEST},
    TASK_SYNC_SOURCE: {"queue": QUEUE_SYNC},
    TASK_VERIFY_OBJECT: {"queue": QUEUE_VERIFY},
    TASK_SYNC_DELTA_ALL: {"queue": QUEUE_MAINTENANCE},
    TASK_RECONCILE_ALL: {"queue": QUEUE_MAINTENANCE},
    TASK_WATCHDOG_SWEEP: {"queue": QUEUE_MAINTENANCE},
}

celery_app = Celery(
    "brain_sauce",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.ingest", "app.tasks.sync", "app.tasks.verify", "app.tasks.watchdog"],
)

celery_app.conf.update(
    task_default_queue=QUEUE_MAINTENANCE,
    task_routes=TASK_ROUTES,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    task_annotations={
        name: {"soft_time_limit": soft, "time_limit": hard}
        for name, (soft, hard) in TIME_LIMITS.items()
    },
    beat_schedule={
        "sync-delta-all": {
            "task": TASK_SYNC_DELTA_ALL,
            "schedule": float(settings.SYNC_DELTA_INTERVAL_S),
        },
        "reconcile-all": {
            "task": TASK_RECONCILE_ALL,
            "schedule": float(settings.SYNC_RECONCILE_INTERVAL_S),
        },
        "watchdog-sweep": {
            "task": TASK_WATCHDOG_SWEEP,
            "schedule": float(settings.WATCHDOG_INTERVAL_S),
        },
    },
    # Keep our JSON log handler (app.core.logging) instead of Celery's.
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
)


@worker_process_init.connect
def _init_worker_process(**_: Any) -> None:
    """Build the service graph once per worker child process (after fork; engine per process)."""
    from app.core.logging import configure_logging
    from app.services.wiring import build_services, set_services
    from app.tasks.common import run_async

    configure_logging(settings.LOG_LEVEL)
    built = build_services()
    if inspect.isawaitable(built):
        built = run_async(built)
    set_services(built)
    logger.info("worker process initialised", extra={"repo_backend": settings.REPO_BACKEND})


_job_tokens: dict[str, Token[str | None]] = {}


@task_prerun.connect
def _set_job_id(task_id: str | None = None, **_: Any) -> None:
    if task_id:
        _job_tokens[task_id] = job_id_var.set(task_id)


@task_postrun.connect
def _clear_job_id(task_id: str | None = None, **_: Any) -> None:
    token = _job_tokens.pop(task_id, None) if task_id else None
    if token is None:
        return
    try:
        job_id_var.reset(token)
    except ValueError:  # set in a different context (eager retries); just clear it
        job_id_var.set(None)
