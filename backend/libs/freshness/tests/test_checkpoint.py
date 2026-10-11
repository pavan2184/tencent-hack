"""Cursor safety (hard gate cursor_advanced_past_unaccounted_work = 0)."""

from __future__ import annotations

import pytest
from freshness import (
    DEFAULT_SCOPE,
    ChangePage,
    ConnectorCheckpoint,
    ConnectorKind,
    CursorConflict,
    EventState,
    FreshnessError,
    FreshnessService,
    FreshnessStatus,
    InMemoryFreshnessStore,
    ListChangeSource,
    RunStatus,
    SourceChangeEvent,
    SyncPath,
)

SOURCE = "confluence-ops"


def _checkpoint(cursor: str | None = None, **extra) -> ConnectorCheckpoint:
    return ConnectorCheckpoint(
        source_id=SOURCE, connector_kind=ConnectorKind.confluence, cursor_value=cursor, **extra
    )


async def test_cas_conflict_raises_and_writes_nothing(store) -> None:
    first = await store.cas_checkpoint(_checkpoint("c1"), expected_version=0)
    assert first.cursor_version == 1

    with pytest.raises(CursorConflict):
        await store.cas_checkpoint(_checkpoint("c-stale-writer"), expected_version=0)

    current = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert (current.cursor_value, current.cursor_version) == ("c1", 1)
    second = await store.cas_checkpoint(_checkpoint("c2"), expected_version=1)
    assert second.cursor_version == 2


async def test_store_rejects_success_stamp_from_non_completed_run(
    store, make_sync, service
) -> None:
    run = await service.queue_sync(make_sync())  # status queued
    with pytest.raises(FreshnessError, match="completed run"):
        await store.cas_checkpoint(_checkpoint(last_successful_run_id=run.id), expected_version=0)


async def test_cursor_advances_page_by_page_after_full_accounting(
    service, store, make_change, make_sync, apply
) -> None:
    source = ListChangeSource(
        [
            ChangePage(changes=[make_change("a", "1")], next_cursor="c1", has_more=True),
            ChangePage(changes=[make_change("b", "1")], next_cursor="c2", has_more=False),
        ]
    )

    result = await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert source.calls == [None, "c1"]
    assert (result.cursor_before, result.cursor_after) == (None, "c2")
    checkpoint = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert checkpoint.cursor_value == "c2"
    assert checkpoint.last_successful_run_id == result.run_id


async def test_cursor_does_not_pass_a_page_that_failed_to_list(
    service, store, make_change, make_sync, apply
) -> None:
    source = ListChangeSource(
        [
            ChangePage(changes=[make_change("a", "1")], next_cursor="c1", has_more=True),
            ConnectionError("provider 503"),
        ]
    )

    result = await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert result.status is RunStatus.failed
    assert result.error_summary == "change_source_error:ConnectionError"
    checkpoint = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert checkpoint.cursor_value == "c1"  # first page fully accounted, second never seen
    assert checkpoint.last_successful_run_id is None


class _ParkingOutage(InMemoryFreshnessStore):
    """Store that cannot durably record a parked event (e.g. the database went away)."""

    async def update_event_state(self, event: SourceChangeEvent) -> SourceChangeEvent:
        if event.state is EventState.parked:
            raise RuntimeError("database unavailable")
        return await super().update_event_state(event)


async def test_cursor_unchanged_when_a_failure_cannot_be_parked(
    clock, critical_policy, standard_policy, make_change, make_sync, apply
) -> None:
    store = _ParkingOutage(policies=[critical_policy, standard_policy])
    service = FreshnessService(store, clock)
    apply.fail.add("a")
    source = ListChangeSource(
        [ChangePage(changes=[make_change("a", "1")], next_cursor="c1", has_more=False)]
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert await store.get_checkpoint(SOURCE, DEFAULT_SCOPE) is None  # cursor never moved
    (run,) = store.runs.values()
    assert run.status is RunStatus.failed


async def test_cursor_advances_past_parked_change_which_leaves_object_non_current(
    service, store, make_change, make_sync, apply
) -> None:
    first = ListChangeSource([ChangePage(changes=[make_change("a", "1")], next_cursor="c1")])
    await service.connector_sync(make_sync(), change_source=first, apply=apply)
    apply.fail.add("a")
    second = ListChangeSource(
        [ChangePage(changes=[make_change("a", "2")], next_cursor="c2")], start="c1"
    )

    result = await service.connector_sync(make_sync(), change_source=second, apply=apply)

    assert result.status is RunStatus.partial
    assert result.parked_count == 1
    assert (await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)).cursor_value == "c2"
    obj = store.objects[(SOURCE, "a")]
    assert obj.freshness_status is FreshnessStatus.stale  # v1 still indexed, v2 parked
    assert obj.provider_version == "1"
    parked = next(e for e in store.events.values() if e.provider_version == "2")
    assert parked.state is EventState.parked
    assert parked.last_error_code == "apply_error:RuntimeError"


async def test_parked_new_object_gets_a_non_searchable_placeholder(
    service, store, make_change, make_sync, apply
) -> None:
    apply.fail.add("new")
    source = ListChangeSource([ChangePage(changes=[make_change("new", "1")], next_cursor="c1")])

    await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert store.objects[(SOURCE, "new")].freshness_status is FreshnessStatus.not_searchable


class _RacingSource:
    """Change source during whose listing another worker moves the cursor."""

    def __init__(self, store: InMemoryFreshnessStore, page: ChangePage) -> None:
        self.store = store
        self.page = page

    async def list_changes(self, cursor: str | None, *, limit: int) -> ChangePage:
        current = await self.store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
        await self.store.cas_checkpoint(
            _checkpoint("other-worker"),
            expected_version=current.cursor_version if current else 0,
        )
        return self.page


async def test_concurrent_cursor_move_is_a_cursor_conflict(
    service, store, make_change, make_sync, apply
) -> None:
    page = ChangePage(changes=[make_change("a", "1")], next_cursor="mine")

    with pytest.raises(CursorConflict):
        await service.connector_sync(
            make_sync(), change_source=_RacingSource(store, page), apply=apply
        )

    assert (await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)).cursor_value == "other-worker"
    (run,) = store.runs.values()
    assert run.status is RunStatus.failed
    assert run.error_summary == "cursor_conflict"


async def test_reconcile_scans_from_start_and_never_moves_delta_cursor(
    service, store, make_change, make_sync, apply
) -> None:
    delta = ListChangeSource([ChangePage(changes=[make_change("a", "1")], next_cursor="d1")])
    await service.connector_sync(make_sync(), change_source=delta, apply=apply)
    full_scan = ListChangeSource(
        [ChangePage(changes=[make_change("a", "1"), make_change("b", "1")], next_cursor="scan-1")]
    )

    result = await service.connector_sync(
        make_sync(SyncPath.reconcile), change_source=full_scan, apply=apply
    )

    assert full_scan.calls == [None]
    assert result.status is RunStatus.completed
    checkpoint = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert checkpoint.cursor_value == "d1"
    assert checkpoint.last_reconciled_at is not None
    assert store.objects[(SOURCE, "b")].sync_path is SyncPath.reconcile
