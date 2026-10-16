"""FastAPI application factory.

`create_app()` wires CORS, the request-id middleware, the error envelope, the `/api` routers,
`/healthz`, and (when the MCP module is present) the MCP server at `/mcp`. The lifespan configures
logging and installs the `Services` container (building one from settings unless a test already
installed it); in `REPO_BACKEND=memory` with a freshly built container it auto-loads the seed so a
local run without Postgres has personas and documents, and runs a delta sync of every source each
`SYNC_DELTA_INTERVAL_S` so permission snapshots never age out (`app.services.memory_sync`).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app import __version__
from app.api.routers import access, ask, audit, documents, health, principals, sources
from app.config import get_settings
from app.core.context import new_request_id, request_id_var
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.services.wiring import build_services, current_services, set_services

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

try:  # owned by the MCP workstream; optional until it lands
    from app.mcp.server import mcp_lifespan, mount_mcp
except ImportError:  # pragma: no cover - depends on another agent's module
    mount_mcp = mcp_lifespan = None  # type: ignore[assignment]

try:  # owned by the sync workstream
    from app.api.routers import webhooks as _webhooks
except ImportError:  # pragma: no cover
    _webhooks = None  # type: ignore[assignment]


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and _REQUEST_ID_OK.match(incoming) else new_request_id()
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _default_seed_dir(configured: str) -> Path | None:
    for candidate in (Path(configured), Path(__file__).resolve().parents[1] / "seed"):
        if (candidate / "principals.yaml").is_file():
            return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    services = current_services()
    built_here = services is None
    if built_here:
        services = build_services(settings)
        set_services(services)
    sync_loop: asyncio.Task[None] | None = None
    if built_here and settings.REPO_BACKEND == "memory":
        seed_dir = _default_seed_dir(settings.SEED_DIR)
        if seed_dir is not None:
            from app.seed import load_seed

            summary = await load_seed(services, str(seed_dir))
            logger.info("memory backend auto-seeded", extra={"summary": summary.model_dump()})
        # No worker can reach in-process stores, so the API syncs them itself (D-022).
        from app.services.memory_sync import keep_permissions_fresh

        sync_loop = asyncio.create_task(
            keep_permissions_fresh(services, float(settings.SYNC_DELTA_INTERVAL_S))
        )
    async with AsyncExitStack() as stack:
        if mcp_lifespan is not None:
            await stack.enter_async_context(mcp_lifespan(app))
        yield
    if sync_loop is not None:
        sync_loop.cancel()
        with suppress(asyncio.CancelledError):
            await sync_loop
    if built_here and settings.REPO_BACKEND == "sql":
        try:
            from app.db.session import dispose_engine

            await dispose_engine()
        except Exception:  # noqa: BLE001
            logger.warning("engine dispose failed", exc_info=True)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Brain Sauce",
        version=__version__,
        description="Governed MCP + REST over an everything-is-a-document corporate brain.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["X-Actor-Id", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(health.router, prefix="/api")
    for module in (principals, documents, sources, access, ask, audit):
        app.include_router(module.router, prefix="/api")
    if _webhooks is not None:
        app.include_router(_webhooks.router, prefix="/api")
    if mount_mcp is not None:
        mount_mcp(app)
    return app


app = create_app()
