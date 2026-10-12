"""App test fixtures: offline, in-memory, mock providers, eager jobs, fixed clock.

The environment is forced BEFORE `app.config` is imported (it builds a module-level `settings`),
so no `.env`, Postgres, Redis or network is ever needed.

Fixtures (a contract shared by every app test file):
- `services`: a fresh in-memory `Services` (FixedClock at `FIXED_NOW`) installed with
  `set_services`;
- `seeded`: `services` after `load_seed(services, SEED_DIR)`;
- `client`: `TestClient(app)` used as a context manager (lifespan runs, reuses `services`), with
  the default header `X-Actor-Id: alex.tan`;
- `headers`: returns the helper `make_headers(actor_id) -> {"X-Actor-Id": actor_id}`.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Callable, Coroutine, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
SEED_DIR = BACKEND_DIR / "seed"
UPLOAD_DIR = tempfile.mkdtemp(prefix="brain-test-uploads-")
FIXED_NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
DEFAULT_ACTOR = "alex.tan"

os.environ.update(
    {
        "ENV": "test",
        "REPO_BACKEND": "memory",
        "PROVIDER_MODE": "mock",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "SEED_DIR": str(SEED_DIR),
        "UPLOAD_DIR": UPLOAD_DIR,
        "LOG_LEVEL": "warning",
    }
)

import app.config  # noqa: E402

app.config.get_settings.cache_clear()
app.config.settings = app.config.get_settings()

from fastapi.testclient import TestClient  # noqa: E402
from freshness import FixedClock  # noqa: E402

from app.db.repo import set_repo  # noqa: E402
from app.services.wiring import Services, build_services, set_services  # noqa: E402


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from sync test code (own loop, helper thread)."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def make_headers(actor_id: str) -> dict[str, str]:
    return {"X-Actor-Id": actor_id}


@pytest.fixture
def services() -> Iterator[Services]:
    svc = build_services(app.config.get_settings(), clock=FixedClock(FIXED_NOW))
    set_repo(None)
    set_services(svc)
    yield svc
    set_services(None)


@pytest.fixture
def seeded(services: Services) -> Services:
    from app.seed import load_seed

    run(load_seed(services, str(SEED_DIR)))
    return services


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    from app.main import app as fastapi_app

    with TestClient(fastapi_app, headers=make_headers(DEFAULT_ACTOR)) as test_client:
        yield test_client


@pytest.fixture(name="headers")
def headers_fixture() -> Callable[[str], dict[str, str]]:
    return make_headers
