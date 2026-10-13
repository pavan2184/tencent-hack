"""A complete reconciliation detects vanished provider objects without guessing on failure."""

from __future__ import annotations

from freshness import ChangeKind, ChangePage, FreshnessStatus, ListChangeSource, RunStatus, SyncPath


def _listing(*changes, has_more: bool = False) -> ListChangeSource:
    return ListChangeSource(
        [ChangePage(changes=list(changes), next_cursor="next", has_more=has_more)]
    )


async def test_complete_reconcile_tombstones_vanished_object(
    service, store, make_change, make_sync, apply
) -> None:
    await service.connector_sync(
        make_sync(),
        change_source=_listing(make_change("kept", "1"), make_change("gone", "1")),
        apply=apply,
    )

    result = await service.connector_sync(
        make_sync(SyncPath.reconcile),
        change_source=_listing(make_change("kept", "1")),
        apply=apply,
    )

    assert result.status is RunStatus.completed
    assert result.tombstoned_count == 1
    assert store.objects[("confluence-ops", "gone")].freshness_status is FreshnessStatus.deleted
    assert [
        change.change_kind for change in apply.calls if change.external_object_id == "gone"
    ] == [
        ChangeKind.upsert,
        ChangeKind.delete,
    ]


async def test_incomplete_reconcile_never_infers_deletion(
    service, store, make_change, make_sync, apply
) -> None:
    await service.connector_sync(
        make_sync(),
        change_source=_listing(make_change("kept", "1"), make_change("gone", "1")),
        apply=apply,
    )
    source = ListChangeSource(
        [
            ChangePage(changes=[make_change("kept", "1")], next_cursor="page-2", has_more=True),
            OSError("provider scan interrupted"),
        ]
    )

    result = await service.connector_sync(
        make_sync(SyncPath.reconcile), change_source=source, apply=apply
    )

    assert result.status is RunStatus.failed
    assert result.tombstoned_count == 0
    assert store.objects[("confluence-ops", "gone")].freshness_status is FreshnessStatus.fresh
    assert apply.count("gone") == 1


async def test_scoped_reconcile_does_not_delete_source_wide_objects(
    service, store, make_change, make_sync, apply
) -> None:
    await service.connector_sync(
        make_sync(), change_source=_listing(make_change("gone", "1")), apply=apply
    )

    result = await service.connector_sync(
        make_sync(SyncPath.reconcile, scope_key="partial-scope"),
        change_source=_listing(),
        apply=apply,
    )

    assert result.status is RunStatus.partial
    assert result.tombstoned_count == 0
    assert store.objects[("confluence-ops", "gone")].freshness_status is FreshnessStatus.fresh


async def test_repeated_reconcile_does_not_delete_twice(
    service, make_change, make_sync, apply
) -> None:
    await service.connector_sync(
        make_sync(), change_source=_listing(make_change("gone", "1")), apply=apply
    )
    first = await service.connector_sync(
        make_sync(SyncPath.reconcile), change_source=_listing(), apply=apply
    )
    second = await service.connector_sync(
        make_sync(SyncPath.reconcile), change_source=_listing(), apply=apply
    )

    assert first.tombstoned_count == 1
    assert second.tombstoned_count == 0
    assert [change.change_kind for change in apply.calls] == [ChangeKind.upsert, ChangeKind.delete]


async def test_newer_version_restores_reconciled_tombstone(
    service, store, make_change, make_sync, apply
) -> None:
    await service.connector_sync(
        make_sync(), change_source=_listing(make_change("gone", "1", order=1)), apply=apply
    )
    await service.connector_sync(
        make_sync(SyncPath.reconcile), change_source=_listing(), apply=apply
    )

    result = await service.connector_sync(
        make_sync(SyncPath.reconcile),
        change_source=_listing(make_change("gone", "2", order=2)),
        apply=apply,
    )

    assert result.status is RunStatus.completed
    assert result.applied_count == 1
    current = store.objects[("confluence-ops", "gone")]
    assert current.freshness_status is FreshnessStatus.fresh
    assert current.provider_version == "2"
