"""Permission drift is an ACL change between two captures, by fingerprint: capture time, run id
and a first capture are not drift, and a drift record never names ACL members."""

from __future__ import annotations

from datetime import timedelta

from access_control import PermissionDrift, SourcePermissions, detect_permission_drift


def snapshot(raw, *, at, version="pv-1", run="run-1"):
    return SourcePermissions.from_raw(
        raw, permission_version=version, captured_at=at, connector_run_id=run
    )


def test_first_capture_and_recapture_of_the_same_acl_are_not_drift(seed_blocks, now):
    first = snapshot(seed_blocks["gdrive"], at=now)
    assert detect_permission_drift("doc-1", None, first) is None
    later = snapshot(seed_blocks["gdrive"], at=now + timedelta(minutes=1), run="run-2")
    assert detect_permission_drift("doc-1", first, later) is None


def test_an_acl_change_is_drift_with_fingerprints_and_versions_only(seed_blocks, now):
    before = snapshot(seed_blocks["gdrive"], at=now)
    removed = {**seed_blocks["gdrive"], "acl": []}  # the leadership share is removed
    after = snapshot(removed, at=now + timedelta(minutes=1), version="pv-2")
    drift = detect_permission_drift("doc-1", before, after)
    assert isinstance(drift, PermissionDrift)
    assert drift.previous_fingerprint != drift.current_fingerprint
    assert drift.current_fingerprint.startswith("sha256:")
    assert (drift.previous_version, drift.current_version) == ("pv-1", "pv-2")
    assert (drift.previous_captured_at, drift.observed_at) == (now, after.captured_at)
    assert "leadership" not in drift.model_dump_json()
