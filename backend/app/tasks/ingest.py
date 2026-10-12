"""`tasks.ingest_page`: frontmatter -> chunk -> embed -> searchable, for one page (q.ingest)."""

from __future__ import annotations

import logging
from typing import Any

from celery import Task

from app.celery_app import TASK_INGEST_PAGE, celery_app
from app.config import settings
from app.tasks.common import RETRYABLE, backoff_seconds, run_async, services

logger = logging.getLogger(__name__)


@celery_app.task(name=TASK_INGEST_PAGE, bind=True, max_retries=settings.TASK_MAX_RETRIES)
def ingest_page_task(self: Task, *, page_id: str) -> dict[str, Any]:
    """Index one stored page and return its `freshness.IndexOutcome` as JSON."""
    from app.services.ingestion import ingest_page

    try:
        outcome = run_async(ingest_page(services(), page_id))
    except RETRYABLE as exc:
        logger.warning("ingest retry", extra={"page_id": page_id, "error": type(exc).__name__})
        raise self.retry(exc=exc, countdown=backoff_seconds(self.request.retries)) from exc
    return outcome.model_dump(mode="json")
