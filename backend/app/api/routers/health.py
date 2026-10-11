"""Liveness + dependency checks (`GET /healthz`, `GET /api/healthz`; no actor)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import __version__
from app.config import get_settings

router = APIRouter(tags=["health"])


async def _check_db() -> str:
    try:
        from app.db.session import check_db
    except ImportError:
        return "unavailable"
    try:
        return "ok" if await check_db() else "error"
    except Exception:  # noqa: BLE001
        return "error"


async def _check_redis(url: str) -> str:
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return "unavailable"
    client = aioredis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
    try:
        ok = await asyncio.wait_for(client.ping(), timeout=3)
        return "ok" if ok else "error"
    except Exception:  # noqa: BLE001
        return "error"
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


async def health_body() -> tuple[int, dict[str, Any]]:
    settings = get_settings()
    if settings.REPO_BACKEND == "memory":
        db, redis_status = "memory", "skipped"
    else:
        db, redis_status = await asyncio.gather(_check_db(), _check_redis(settings.REDIS_URL))
    ok = db in ("ok", "memory") and redis_status in ("ok", "skipped")
    body = {
        "status": "ok" if ok else "degraded",
        "db": db,
        "redis": redis_status,
        "provider_mode": settings.PROVIDER_MODE,
        "version": __version__,
    }
    return (200 if ok else 503), body


@router.get("/healthz")
async def healthz() -> JSONResponse:
    status, body = await health_body()
    return JSONResponse(status_code=status, content=body)
