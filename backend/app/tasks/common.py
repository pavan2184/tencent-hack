"""The single bridge between synchronous Celery tasks and the async service layer.

`run_async(coro)` is the only place a task enters asyncio:

* Normal worker execution (no loop running in this thread): the coroutine runs on this
  process+thread's own event loop, created on first use and reused for every later task. Async
  SQLAlchemy pooled connections are bound to the loop that opened them, so reusing one loop per
  worker process keeps the pool valid across tasks ("engine per worker process") with no
  reconnect per task. Whenever that loop has to be replaced (a fork, detected by pid, or a closed
  loop) and `REPO_BACKEND=sql`, `app.db.session.dispose_engine()` runs on the new loop first, so
  no connection from the old loop is reused.
* A loop is already running in this thread (eager mode called from async code: an async test, or
  an API handler with `CELERY_TASK_ALWAYS_EAGER=true`): the coroutine runs to completion on a
  fresh loop in a helper thread, with the caller's ContextVars (request/actor/job ids) copied in.
  With `REPO_BACKEND=sql` the engine is disposed before that temporary loop closes, as
  `app/db/session.py` requires.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import os
import random
import threading
from collections.abc import Coroutine, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from freshness import DEFAULT_SCOPE, CursorConflict, ProbeUnavailable

from app.config import settings
from app.core.errors import ProviderUnavailable

if TYPE_CHECKING:
    from app.services.wiring import Services

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """A transient failure: the task retries with exponential backoff (up to TASK_MAX_RETRIES)."""


#: Exceptions that make a task retry instead of failing outright.
RETRYABLE: tuple[type[BaseException], ...] = (
    RetryableError,
    ProviderUnavailable,
    ProbeUnavailable,
    CursorConflict,
    ConnectionError,
    TimeoutError,
)

_local = threading.local()


def _uses_sql() -> bool:
    return settings.REPO_BACKEND == "sql"


async def _dispose_engine() -> None:
    """Drop pooled DB connections (bound to another loop). Best effort: never masks a result."""
    from app.db.session import dispose_engine

    try:
        await dispose_engine()
    except Exception:
        logger.warning("engine dispose failed", exc_info=True)


def _thread_loop() -> asyncio.AbstractEventLoop:
    loop: asyncio.AbstractEventLoop | None = getattr(_local, "loop", None)
    if loop is not None and not loop.is_closed() and getattr(_local, "pid", None) == os.getpid():
        return loop
    replacing = loop is not None  # forked child (inherited thread-local) or a closed loop
    loop = asyncio.new_event_loop()
    _local.loop = loop
    _local.pid = os.getpid()
    if replacing and _uses_sql():
        loop.run_until_complete(_dispose_engine())
    return loop


async def _then_dispose[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        return await coro
    finally:
        if _uses_sql():
            await _dispose_engine()


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run `coro` to completion from synchronous (Celery) code and return its result."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _thread_loop().run_until_complete(coro)
    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="run_async") as pool:
        return pool.submit(ctx.run, asyncio.run, _then_dispose(coro)).result()


async def maybe_await(value: Any) -> Any:
    """Await `value` if it is awaitable (service helpers may be sync or async)."""
    if inspect.isawaitable(value):
        return await value
    return value


def services() -> Services:
    """The process-wide service graph (built in `worker_process_init`, or by the test conftest)."""
    from app.services.wiring import get_services

    return get_services()


def backoff_seconds(retries: int, *, base: int = 5, cap: int = 300) -> int:
    """Exponential backoff with jitter for `Task.retry(countdown=...)`."""
    delay = min(cap, base * (2**retries))
    return int(delay + random.uniform(0, delay / 2))


@contextmanager
def source_lock(source_id: str, scope_key: str = DEFAULT_SCOPE, *, ttl_s: int) -> Iterator[bool]:
    """Serialise `connector_sync` per `(source_id, scope_key)` across workers (Redis lock).

    Yields whether the lock is held. Eager mode (tests) has no broker, so it always yields True;
    the freshness checkpoint CAS still turns a lost race into `CursorConflict` (retried).
    """
    from app.celery_app import celery_app

    if celery_app.conf.task_always_eager:
        yield True
        return
    import redis

    lock = redis.Redis.from_url(settings.REDIS_URL).lock(
        f"lock:sync:{source_id}:{scope_key}", timeout=ttl_s, blocking=False
    )
    try:
        acquired = bool(lock.acquire(blocking=False))
    except redis.RedisError:
        logger.warning("sync lock unavailable; continuing without it", exc_info=True)
        yield True
        return
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except redis.RedisError:  # expired or Redis gone; the TTL cleans up
                logger.warning("sync lock release failed", exc_info=True)
