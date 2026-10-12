"""Background job dispatch: the ONLY module on the service side that touches Celery.

- Celery mode (`CELERY_TASK_ALWAYS_EAGER=false` and `app.tasks` importable): `.delay(...)` the
  task, imported lazily (`app.tasks.ingest.ingest_page_task`, `app.tasks.sync.sync_source_task`,
  `app.tasks.verify.verify_object_task`).
- Inline mode (eager, or the task modules fail to import): run the service coroutine on the
  current event loop as a task (tracked; `await flush_inline()` waits for them) or, when no loop
  is running, synchronously with `asyncio.run`.

Services that need eager completion before responding (uploads, manual syncs) call
`await flush_inline()` right after enqueueing; in Celery mode it is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_inline_tasks: set[asyncio.Task[Any]] = set()


def runs_inline() -> bool:
    return bool(get_settings().CELERY_TASK_ALWAYS_EAGER)


def _run_inline(make_coro: Callable[[], Coroutine[Any, Any, Any]], what: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(make_coro())
        return
    task = loop.create_task(make_coro(), name=f"inline:{what}")
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)


async def flush_inline() -> None:
    """Wait for inline jobs scheduled on the current loop; re-raises the first failure."""
    loop = asyncio.get_running_loop()
    while True:
        pending = [t for t in list(_inline_tasks) if t.get_loop() is loop and not t.done()]
        done = [t for t in list(_inline_tasks) if t.get_loop() is loop and t.done()]
        for task in done:
            _inline_tasks.discard(task)
        if not pending:
            return
        results = await asyncio.gather(*pending, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("inline job failed: %r", result)


def _dispatch(
    task_path: tuple[str, str],
    kwargs: dict[str, Any],
    make_coro: Callable[[], Coroutine[Any, Any, Any]],
    what: str,
) -> None:
    if not runs_inline():
        try:
            module = __import__(task_path[0], fromlist=[task_path[1]])
            task = getattr(module, task_path[1])
        except Exception:  # noqa: BLE001 - any import failure falls back to inline
            logger.warning("task %s unavailable; running inline", task_path, exc_info=True)
        else:
            task.delay(**kwargs)
            return
    _run_inline(make_coro, what)


def enqueue_ingest(page_id: str) -> None:
    from app.services.ingestion import ingest_page
    from app.services.wiring import get_services

    _dispatch(
        ("app.tasks.ingest", "ingest_page_task"),
        {"page_id": page_id},
        lambda: ingest_page(get_services(), page_id),
        f"ingest:{page_id}",
    )


def enqueue_sync(source_id: str, trigger_kind: str, idempotency_key: str) -> None:
    from app.services.sources import run_sync
    from app.services.wiring import get_services

    _dispatch(
        ("app.tasks.sync", "sync_source_task"),
        {
            "source_id": source_id,
            "trigger_kind": str(trigger_kind),
            "idempotency_key": idempotency_key,
        },
        lambda: run_sync(get_services(), source_id, str(trigger_kind), idempotency_key),
        f"sync:{source_id}",
    )


def enqueue_verify(source_id: str, external_object_id: str) -> None:
    from app.services.documents import verify_object
    from app.services.wiring import get_services

    _dispatch(
        ("app.tasks.verify", "verify_object_task"),
        {"source_id": source_id, "external_object_id": external_object_id},
        lambda: verify_object(get_services(), source_id, external_object_id),
        f"verify:{source_id}:{external_object_id}",
    )
