"""Run accounting, success stamping, partial indexing, retry/parking, idempotent replay."""

from __future__ import annotations

from datetime import timedelta

from freshness import (
    DEFAULT_SCOPE,
    MAX_ATTEMPTS,
    RETRY_BASE_SECONDS,
    ChangeKind,
    ChangePage,
    CheckpointStatus,
    EventState,
    FreshnessStatus,
    FreshnessStatusRequest,
    ListChangeSource,
    RunStatus,
    evaluate,
)

SOURCE = "confluence-ops"


def _source(*changes, cursor: str = "c1", start: str | None = None) -> ListChangeSource:
    page = ChangePage(changes=list(changes), next_cursor=cursor)
    return ListChangeSource([page], start=start)


async def test_completed_run_counts_and_success_stamp(
    service, store, make_change, make_sync, apply, clock
) -> None:
    await service.connector_sync(
        make_sync(), change_source=_source(make_change("old", "1")), apply=apply
    )
    source = _source(
        make_change("a", "1"),
        make_change("b", "1"),
        make_change("old", "2", kind=ChangeKind.delete),
        make_change("a", "1", event_id="a-again"),  # same version, new id → no-op
        cursor="c2",
        start="c1",
    )

    result = await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert result.status is RunStatus.completed
    assert (result.observed_count, result.accepted_count) == (4, 4)
    assert (result.applied_count, result.tombstoned_count, result.noop_count) == (2, 1, 1)
    assert result.parked_count == 0
    run = store.runs[result.run_id]
    assert run.completed_at == clock.now()
    assert (run.applied_count, run.tombstoned_count, run.failed_count) == (2, 1, 0)
    checkpoint = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert checkpoint.last_successful_run_id == result.run_id
    assert checkpoint.last_polled_at == clock.now()
    assert checkpoint.status is CheckpointStatus.ready


async def test_partial_run_never_becomes_last_successful(
    service, store, make_change, make_sync, apply
) -> None:
    good = await service.connector_sync(
        make_sync(), change_source=_source(make_change("a", "1")), apply=apply
    )
    apply.fail.add("b")

    bad = await service.connector_sync(
        make_sync(),
        change_source=_source(make_change("b", "1"), cursor="c2", start="c1"),
        apply=apply,
    )

    assert bad.status is RunStatus.partial
    checkpoint = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert checkpoint.last_successful_run_id == good.run_id
    assert checkpoint.status is CheckpointStatus.degraded


async def test_failed_run_never_becomes_last_successful(service, store, make_sync, apply) -> None:
    broken = ListChangeSource([TimeoutError("provider timeout")])

    result = await service.connector_sync(make_sync(), change_source=broken, apply=apply)

    assert result.status is RunStatus.failed
    checkpoint = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert checkpoint.last_successful_run_id is None
    assert checkpoint.last_polled_at is None
    assert checkpoint.status is CheckpointStatus.degraded


async def test_content_written_but_not_searchable_is_not_searchable(
    service, store, make_change, make_sync, apply, standard_policy, clock
) -> None:
    apply.partial.add("a")

    result = await service.connector_sync(
        make_sync(), change_source=_source(make_change("a", "1")), apply=apply
    )

    assert result.status is RunStatus.partial
    obj = store.objects[(SOURCE, "a")]
    assert obj.freshness_status is FreshnessStatus.not_searchable
    assert obj.indexed_at is not None and obj.searchable_at is None
    event = next(iter(store.events.values()))
    assert (event.state, event.last_error_code) == (EventState.parked, "partial_index")
    item = evaluate(obj, standard_policy, clock.now())
    assert item.freshness_status is FreshnessStatus.not_searchable


async def test_retry_backoff_then_poison_parking(
    service, store, make_change, make_sync, apply, clock
) -> None:
    apply.fail.add("a")
    empty = ListChangeSource([])
    await service.connector_sync(
        make_sync(), change_source=_source(make_change("a", "1")), apply=apply
    )
    event = next(iter(store.events.values()))
    assert (event.state, event.attempt_count) == (EventState.parked, 1)
    assert event.next_attempt_at == clock.now() + timedelta(seconds=RETRY_BASE_SECONDS)

    clock.advance(RETRY_BASE_SECONDS - 1)  # not yet due: no tight retry loop
    await service.connector_sync(make_sync(), change_source=empty, apply=apply)
    assert apply.count("a") == 1

    clock.advance(1)
    await service.connector_sync(make_sync(), change_source=empty, apply=apply)
    event = store.events[event.id]
    assert (apply.count("a"), event.attempt_count) == (2, 2)
    assert event.next_attempt_at == clock.now() + timedelta(seconds=2 * RETRY_BASE_SECONDS)

    clock.advance(2 * RETRY_BASE_SECONDS)
    await service.connector_sync(make_sync(), change_source=empty, apply=apply)
    event = store.events[event.id]
    assert event.attempt_count == MAX_ATTEMPTS
    assert event.state is EventState.parked
    assert event.next_attempt_at is None  # poison: terminal, operator-visible

    apply.fail.clear()
    clock.advance(3600)
    await service.connector_sync(make_sync(), change_source=empty, apply=apply)
    assert apply.count("a") == MAX_ATTEMPTS  # never retried again
    assert store.objects[(SOURCE, "a")].freshness_status is FreshnessStatus.not_searchable


async def test_retry_success_applies_parked_event(
    service, store, make_change, make_sync, apply, clock
) -> None:
    apply.fail.add("a")
    await service.connector_sync(
        make_sync(), change_source=_source(make_change("a", "1")), apply=apply
    )
    apply.fail.clear()
    clock.advance(RETRY_BASE_SECONDS)

    result = await service.connector_sync(
        make_sync(), change_source=ListChangeSource([]), apply=apply
    )

    assert result.status is RunStatus.completed
    assert result.applied_count == 1
    event = next(iter(store.events.values()))
    assert event.state is EventState.applied
    assert event.last_error_code == "apply_error:RuntimeError"  # prior receipt retained
    assert store.objects[(SOURCE, "a")].freshness_status is FreshnessStatus.fresh


async def test_completed_run_replay_is_idempotent(
    service, store, make_change, make_sync, apply
) -> None:
    request = make_sync(key="nightly-2026-10-12")
    source = _source(make_change("a", "1"))

    first = await service.connector_sync(request, change_source=source, apply=apply)
    replay = await service.connector_sync(request, change_source=source, apply=apply)

    assert replay.replayed is True
    assert replay.run_id == first.run_id
    assert replay.status is RunStatus.completed
    assert replay.applied_count == first.applied_count
    assert apply.count("a") == 1
    assert len(store.runs) == 1


async def test_failed_run_resumes_under_same_run_id(
    service, store, make_change, make_sync, apply
) -> None:
    request = make_sync(key="retry-me")
    failed = await service.connector_sync(
        request, change_source=ListChangeSource([OSError("down")]), apply=apply
    )

    resumed = await service.connector_sync(
        request, change_source=_source(make_change("a", "1")), apply=apply
    )

    assert failed.status is RunStatus.failed
    assert resumed.run_id == failed.run_id
    assert resumed.status is RunStatus.completed
    checkpoint = await store.get_checkpoint(SOURCE, DEFAULT_SCOPE)
    assert checkpoint.last_successful_run_id == resumed.run_id


async def test_queued_run_is_picked_up_by_the_worker(
    service, store, make_change, make_sync, apply
) -> None:
    request = make_sync(key="api-202")
    queued = await service.queue_sync(request)
    assert queued.status is RunStatus.queued

    result = await service.connector_sync(
        request, change_source=_source(make_change("a", "1")), apply=apply
    )

    assert result.run_id == queued.id
    assert result.status is RunStatus.completed


async def test_deadline_stops_between_pages_without_unsafe_cursor_moves(
    service, store, make_change, make_sync, apply, clock
) -> None:
    request = make_sync(deadline_at=clock.now())

    result = await service.connector_sync(
        request, change_source=_source(make_change("a", "1")), apply=apply
    )

    assert result.status is RunStatus.partial
    assert result.error_summary == "deadline_exceeded"
    assert apply.calls == []


async def test_freshness_status_report_is_read_only(
    service, store, make_change, make_sync, apply, clock
) -> None:
    apply.fail.add("b")
    await service.connector_sync(
        make_sync(),
        change_source=_source(make_change("a", "1"), make_change("b", "1")),
        apply=apply,
    )
    clock.advance(42)
    before = (dict(store.objects), dict(store.events), dict(store.checkpoints))

    report = await service.freshness_status(
        FreshnessStatusRequest(source_id=SOURCE, external_object_id="a")
    )

    assert (dict(store.objects), dict(store.events), dict(store.checkpoints)) == before
    assert report.object_counts[FreshnessStatus.fresh] == 1
    assert report.object_counts[FreshnessStatus.not_searchable] == 1
    assert report.parked_event_count == 1
    assert report.pending_event_count == 0
    assert report.oldest_non_current_age_seconds == 42
    assert report.object is not None and report.object.external_object_id == "a"
    assert report.evaluation is not None
    assert report.evaluation.freshness_status is FreshnessStatus.fresh
    assert report.checkpoint is not None and report.checkpoint.cursor_value == "c1"
    assert report.last_successful_run_at is None  # the only run was partial
