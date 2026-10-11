"""`tasks.verify_object`: live-check one provider object against its source (q.verify).

Delegates to `app.services.documents.verify_object` (the same function REST/MCP verification and
the inline job path use): the source's connector is the `ProviderProbe`, `connector_kind` comes
from the stored freshness object (else the source kind) and `evidence_class` from the page, and
`freshness.verify_freshness` records `last_verified_at`/`verification_result`. Not access-checked:
this is a system job, never called on behalf of a principal.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Task

from app.celery_app import TASK_VERIFY_OBJECT, celery_app
from app.config import settings
from app.tasks.common import RETRYABLE, backoff_seconds, run_async, services

logger = logging.getLogger(__name__)


@celery_app.task(name=TASK_VERIFY_OBJECT, bind=True, max_retries=settings.TASK_MAX_RETRIES)
def verify_object_task(self: Task, *, source_id: str, external_object_id: str) -> dict[str, Any]:
    """Live verification of one object; returns `freshness.VerifyResult` JSON."""
    from app.services.documents import verify_object

    try:
        result = run_async(verify_object(services(), source_id, external_object_id))
    except RETRYABLE as exc:
        logger.warning("verify retry", extra={"source_id": source_id, "error": type(exc).__name__})
        raise self.retry(exc=exc, countdown=backoff_seconds(self.request.retries)) from exc
    return result.model_dump(mode="json")
