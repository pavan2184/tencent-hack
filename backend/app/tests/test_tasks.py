"""Celery tasks in eager mode over the in-memory, seeded service graph (no broker, no network)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freshness import InMemoryFreshnessStore, RunStatus, SyncRun

from app.celery_app import QUEUES, TASK_ROUTES, TIME_LIMITS, celery_app
from app.tasks import sync as sync_module
from app.tasks.common import run_async
from app.tasks.ingest import ingest_page_task
from app.tasks.sync import (
    reconcile_all_task,
    sync_delta_all_task,
    sync_idempotency_key,
    sync_source_task,
    time_bucket,
)
from app.tasks.verify import verify_object_task
from app.tasks.watchdog import STUCK_AFTER_S, sweep_stuck_runs, watchdog_sweep_task

RUNBOOK_SOURCE = "confluence-ops"
RUNBOOK_SLUG = "runbooks/payment-rail-failover"
RUNBOOK_OBJECT = "CONF-OPS-1042"


@pytest.fixture(autouse=True)
def _eager_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True)


def test_registered_tasks_routes_and_limits() -> None:
    celery_app.loader.import_default_modules()
    names = set(celery_app.tasks.keys())
    expected = {
        "tasks.ingest_page",
        "tasks.sync_source",
        "tasks.sync_delta_all",
        "tasks.reconcile_all",
        "tasks.verify_object",
        "tasks.watchdog_sweep",
    }
    assert expected <= names
    assert set(TASK_ROUTES) == expected
    assert {route["queue"] for route in TASK_ROUTES.values()} == set(QUEUES)
    assert TIME_LIMITS["tasks.sync_source"] == (540, 600)
    beat = celery_app.conf.beat_schedule
    assert {entry["task"] for entry in beat.values()} == {
        "tasks.sync_delta_all",
        "tasks.reconcile_all",
        "tasks.watchdog_sweep",
    }


def test_run_async_without_and_with_running_loop() -> None:
    async def answer() -> int:
        await asyncio.sleep(0)
        return 42

    assert run_async(answer()) == 42
    assert run_async(answer()) == 42  # the per-thread loop is reusable

    async def nested() -> int:  # eager task called from async code
        return run_async(answer())

    assert asyncio.run(nested()) == 42


async def test_ingest_page_task_returns_index_outcome(seeded: Any) -> None:
    page = await seeded.repo.get_page_by_slug(RUNBOOK_SOURCE, RUNBOOK_SLUG)
    assert page is not None
    outcome = ingest_page_task.delay(page_id=page.id).get()
    assert outcome["searchable"] is True
    assert outcome["page_id"] == page.id


def test_sync_source_task_runs_and_returns_counts(seeded: Any) -> None:
    result = sync_source_task.delay(
        source_id=RUNBOOK_SOURCE, trigger_kind="reconcile", idempotency_key="test:reconcile:1"
    ).get()
    assert result["status"] in {"completed", "partial"}
    assert result["observed_count"] >= 1
    for key in ("run_id", "applied_count", "noop_count", "duplicate_count", "parked_count"):
        assert key in result
    replay = sync_source_task.delay(
        source_id=RUNBOOK_SOURCE, trigger_kind="reconcile", idempotency_key="test:reconcile:1"
    ).get()
    assert replay["run_id"] == result["run_id"]


def test_verify_object_task_reports_failover_runbook_stale(seeded: Any) -> None:
    result = verify_object_task.delay(
        source_id=RUNBOOK_SOURCE, external_object_id=RUNBOOK_OBJECT
    ).get()
    assert result["verification_result"] == "stale"
    assert result["observed_provider_version"] == "8"
    assert result["safe_to_use"] is False


def test_sync_delta_all_enqueues_one_sync_per_active_source(
    seeded: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        sync_module.sync_source_task,
        "apply_async",
        lambda *args, **kwargs: calls.append(kwargs["kwargs"]),
    )
    sources = run_async(seeded.repo.list_sources(include_archived=False))
    result = sync_delta_all_task.delay().get()

    assert sorted(result["enqueued"]) == sorted(s.id for s in sources)
    assert sorted(c["source_id"] for c in calls) == sorted(s.id for s in sources)
    bucket = result["bucket"]
    for call in calls:
        assert call["trigger_kind"] == "delta"
        assert call["idempotency_key"] == f"delta:{call['source_id']}:{bucket}"

    calls.clear()
    reconcile = reconcile_all_task.delay().get()
    assert reconcile["trigger_kind"] == "reconcile"
    assert {c["trigger_kind"] for c in calls} == {"reconcile"}


def test_time_bucket_is_interval_aligned() -> None:
    assert time_bucket(60, now=125.0) == 120
    assert time_bucket(600, now=1_199.9) == 600
    assert sync_idempotency_key("delta", "slack-ops", 120) == "delta:slack-ops:120"


class _ListingStore(InMemoryFreshnessStore):
    """The in-memory store plus the list-runs method the watchdog uses when available."""

    async def list_runs(self, *, statuses: Any, limit: int = 500) -> list[SyncRun]:
        runs = [r for r in self.runs.values() if r.status in set(statuses)]
        return runs[:limit]


async def test_watchdog_fails_only_stuck_running_runs() -> None:
    store = _ListingStore()
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

    def run(run_id: str, age_s: int, status: RunStatus) -> SyncRun:
        return SyncRun(
            id=run_id,
            idempotency_key=f"k-{run_id}",
            source_id="confluence-ops",
            connector_kind="confluence",
            trigger_kind="delta",
            started_at=now - timedelta(seconds=age_s),
            status=status,
        )

    await store.create_run(run("stuck", STUCK_AFTER_S + 5, RunStatus.running))
    await store.create_run(run("young", 30, RunStatus.running))
    await store.create_run(run("done", STUCK_AFTER_S + 5, RunStatus.completed))

    report = await sweep_stuck_runs(store, now=now)
    assert report["supported"] is True
    assert report["failed_run_ids"] == ["stuck"]
    stuck = await store.get_run("stuck")
    assert stuck is not None and stuck.status is RunStatus.failed
    assert stuck.error_summary == "watchdog_timeout"
    young = await store.get_run("young")
    assert young is not None and young.status is RunStatus.running


def test_watchdog_task_is_a_safe_noop_without_list_runs(services: Any) -> None:
    report = watchdog_sweep_task.delay().get()
    if not hasattr(services.freshness_store, "list_runs"):
        assert report == {"supported": False, "checked": 0, "failed_run_ids": []}
    else:
        assert report["supported"] is True
