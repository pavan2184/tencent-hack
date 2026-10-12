"""Async SQLAlchemy engine + session factory (psycopg v3 async driver).

One lazily created engine per process. FastAPI's lifespan calls `dispose_engine()` on shutdown;
Celery workers (`app/tasks/common.py`) call `dispose_engine()` after forking / per event loop,
because an async engine's pooled connections are bound to the loop that opened them.

`async_session_factory` is a zero-arg callable returning a new `AsyncSession` bound to the
CURRENT engine, so it can be handed to `SqlRepo` / the SQL stores and still follow an engine
that was disposed and recreated:

    async with async_session_factory() as session, session.begin():
        ...
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

__all__ = [
    "async_session_factory",
    "check_db",
    "dispose_engine",
    "get_engine",
    "get_session_factory",
    "json_dumps",
    "make_engine",
    "make_session_factory",
]

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, set | frozenset | tuple):
        return list(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def json_dumps(value: Any) -> str:
    """JSONB serializer: tolerates YAML frontmatter dates, UUIDs, enums and Pydantic models
    (stored as their JSON forms; they read back as strings)."""
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def make_engine(url: str | None = None, *, pool_size: int | None = None) -> AsyncEngine:
    """Build a new async engine (`postgresql+psycopg://…`). Never connects eagerly."""
    return create_async_engine(
        url or settings.DATABASE_URL,
        pool_size=pool_size if pool_size is not None else settings.DB_POOL_SIZE,
        pool_pre_ping=True,
        json_serializer=json_dumps,
        connect_args={"connect_timeout": 5},
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: rows read inside a transaction stay usable after it commits.
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def get_engine() -> AsyncEngine:
    """The process-wide engine (created on first use)."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = make_engine()
        _sessionmaker = make_session_factory(_engine)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """The `async_sessionmaker` bound to the process-wide engine."""
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def async_session_factory() -> AsyncSession:
    """A new `AsyncSession` on the current process-wide engine (use as `async with`)."""
    return get_session_factory()()


async def dispose_engine() -> None:
    """Close pooled connections and forget the engine; the next use creates a fresh one."""
    global _engine, _sessionmaker
    engine, _engine, _sessionmaker = _engine, None, None
    if engine is not None:
        await engine.dispose()


async def check_db(timeout_s: float = 3.0) -> bool:
    """`SELECT 1` against the database for `/healthz`. Never raises."""
    try:
        async with asyncio.timeout(timeout_s):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - health probes report, never raise
        log.warning("database health check failed: %s", exc.__class__.__name__)
        return False
