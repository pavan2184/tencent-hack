"""Seed loader: counts, policies for every connector kind, grants, freshness, idempotency."""

from __future__ import annotations

from typing import Any

from freshness import ConnectorKind, EvidenceClass, FreshnessStatus

from app.seed import load_seed
from app.tests.conftest import SEED_DIR, run


def test_seed_counts(seeded: Any) -> None:
    repo = seeded.repo
    assert len(run(repo.list_principals())) == 10
    assert len(run(repo.list_groups())) == 4
    sources = run(repo.list_sources())
    assert len(sources) == 7
    assert {s.id for s in sources} >= {
        "confluence-ops",
        "confluence-compliance",
        "gdrive-finance",
        "uploads",
    }
    pages = run(repo.list_pages(limit=1000))
    assert len(pages) == 24
    assert all(p.ingest_status == "indexed" for p in pages)
    assert all(p.permission_version for p in pages)
    snapshots = run(seeded.permission_store.get_many([p.id for p in pages]))
    assert set(snapshots) == {p.id for p in pages}
    for page in pages:
        assert snapshots[page.id].permission_version == page.permission_version
        assert run(repo.list_chunks(page.id))
    john = run(repo.get_principal("john.tan"))
    assert john.groups == ["finance-ops", "leadership"]


def test_seed_policies_for_every_kind(seeded: Any) -> None:
    for kind in ConnectorKind:
        for evidence_class in EvidenceClass:
            policy = run(seeded.freshness_store.get_active_policy(kind, evidence_class))
            assert policy is not None, (kind, evidence_class)


def test_seed_grants_and_freshness(seeded: Any) -> None:
    deck = run(seeded.repo.get_page_by_slug("gdrive-finance", "files/board-deck-q3"))
    grants = run(seeded.grant_store.list_for_documents([deck.id]))[deck.id]
    assert [(g.subject_type, g.subject_id, g.granted_by) for g in grants] == [
        ("group", "leadership", "system:seed")
    ]
    runbook = run(seeded.repo.get_page_by_slug("confluence-ops", "runbooks/payment-rail-failover"))
    obj = run(seeded.freshness_store.get_object("confluence-ops", runbook.external_object_id))
    assert obj.provider_version == "7"
    assert obj.indexed_at.isoformat().startswith("2026-10-01T10:00")
    assert obj.freshness_status == FreshnessStatus.stale
    kyc = run(seeded.repo.get_page_by_slug("confluence-ops", "runbooks/kyc-refresh"))
    kyc_obj = run(seeded.freshness_store.get_object("confluence-ops", kyc.external_object_id))
    assert kyc_obj.freshness_status == FreshnessStatus.fresh
    assert kyc_obj.last_verified_at is not None
    entries = run(seeded.repo.list_timeline(runbook.id))
    assert len(entries) == 3


def test_seed_is_idempotent(seeded: Any) -> None:
    repo = seeded.repo
    pages_before = {p.id: p.slug for p in run(repo.list_pages(limit=1000))}
    ids = list(pages_before)
    grants_before = run(seeded.grant_store.list_for_documents(ids))
    timeline_before = sum(len(run(repo.list_timeline(pid))) for pid in ids)

    summary = run(load_seed(seeded, str(SEED_DIR)))

    pages_after = {p.id: p.slug for p in run(repo.list_pages(limit=1000))}
    assert pages_after == pages_before
    grants_after = run(seeded.grant_store.list_for_documents(ids))
    assert {k: len(v) for k, v in grants_after.items()} == {
        k: len(v) for k, v in grants_before.items()
    }
    assert sum(len(run(repo.list_timeline(pid))) for pid in ids) == timeline_before
    assert len(run(repo.list_principals())) == 10
    assert all(r["replayed"] for r in summary.runs)
    assert len(run(repo.list_audit_events(action="seed.loaded"))) == 2
