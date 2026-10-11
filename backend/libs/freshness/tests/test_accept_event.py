"""Durable acceptance and duplicate delivery (spec "Duplicate delivery"; duplicate_mutations=0)."""

from __future__ import annotations

from freshness import (
    ChangePage,
    EventState,
    FreshnessStatus,
    ListChangeSource,
    SyncPath,
)


async def test_accept_is_durable_and_does_not_index(service, store, make_change, apply) -> None:
    result = await service.accept(make_change())

    assert result.duplicate is False
    assert result.event.state is EventState.accepted
    assert result.event.payload_hash
    assert store.events[result.event.id] == result.event
    assert apply.calls == []  # acceptance never mutates searchable content
    assert store.objects == {}


async def test_duplicate_event_id_returns_existing_event(
    service, store, make_change, clock
) -> None:
    first = await service.accept(make_change(event_id="wh-1"))
    clock.advance(5)
    again = await service.accept(make_change(event_id="wh-1"))

    assert again.duplicate is True
    assert again.event.id == first.event.id
    assert again.event.accepted_at == first.event.accepted_at
    assert len(store.events) == 1


async def test_duplicate_provider_event_id_never_produces_second_apply(
    service, store, make_change, make_sync, apply
) -> None:
    change = make_change("page-1", "1", event_id="evt-dup")
    source = ListChangeSource([ChangePage(changes=[change])])

    first = await service.connector_sync(make_sync(), change_source=source, apply=apply)
    second = await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert apply.count("page-1") == 1
    assert first.applied_count == 1
    assert second.duplicate_count == 1
    assert second.applied_count == 0
    assert len(store.events) == 1


async def test_duplicate_within_one_page_applies_once(
    service, make_change, make_sync, apply
) -> None:
    change = make_change("page-1", "1", event_id="evt-dup")
    source = ListChangeSource([ChangePage(changes=[change, change, change])])

    result = await service.connector_sync(make_sync(), change_source=source, apply=apply)

    assert apply.count("page-1") == 1
    assert result.accepted_count == 1
    assert result.applied_count == 1


async def test_webhook_accepted_event_is_applied_by_next_sync(
    service, store, make_change, make_sync, apply
) -> None:
    accepted = await service.accept(make_change("page-9", "3", event_id="wh-9"))
    empty = ListChangeSource([])

    result = await service.connector_sync(
        make_sync(SyncPath.webhook), change_source=empty, apply=apply
    )

    assert apply.count("page-9") == 1
    assert result.applied_count == 1
    assert store.events[accepted.event.id].state is EventState.applied
    obj = store.objects[("confluence-ops", "page-9")]
    assert obj.freshness_status is FreshnessStatus.fresh
    assert obj.sync_path is SyncPath.webhook
    assert obj.accepted_at == accepted.event.accepted_at


async def test_webhook_event_later_seen_in_delta_is_not_reapplied(
    service, make_change, make_sync, apply
) -> None:
    change = make_change("page-2", "4", event_id="wh-2")
    await service.accept(change)
    await service.connector_sync(
        make_sync(SyncPath.webhook), change_source=ListChangeSource([]), apply=apply
    )

    delta = ListChangeSource([ChangePage(changes=[change], next_cursor="c1")])
    result = await service.connector_sync(make_sync(), change_source=delta, apply=apply)

    assert apply.count("page-2") == 1
    assert result.duplicate_count == 1
