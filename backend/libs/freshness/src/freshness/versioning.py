"""Provider-version comparison and the object write guard.

Provider revisions are opaque. They are comparable when both sides carry a ``version_order``
(an integer the connector derives, e.g. Confluence's version number) or when both version tokens
are plain decimal strings. Anything else is ``incomparable`` — which forces a provider read before
the object may be considered current (it is applied, but stays ``unknown`` until verified).
"""

from __future__ import annotations

from typing import Literal

from freshness.enums import FreshnessStatus
from freshness.models import ObjectFreshness
from freshness.protocols import VersionRegression

VersionComparison = Literal["older", "same", "newer", "incomparable"]


def _as_number(version: str) -> int | None:
    token = version.strip()
    if token.isascii() and token.isdigit():
        return int(token)
    return None


def compare(
    a_version: str | None,
    a_order: int | None,
    b_version: str | None,
    b_order: int | None,
) -> VersionComparison:
    """Compare revision ``a`` relative to revision ``b``.

    - Both orders present: the orders decide; equal orders with different non-null tokens are
      ``incomparable`` (the connector contradicted itself).
    - Otherwise equal non-null tokens are ``same``; two decimal tokens compare numerically.
    - Anything else (missing tokens, opaque tokens that differ) is ``incomparable``.
    """
    if a_order is not None and b_order is not None:
        if a_order < b_order:
            return "older"
        if a_order > b_order:
            return "newer"
        if a_version is not None and b_version is not None and a_version != b_version:
            return "incomparable"
        return "same"
    if a_version is None or b_version is None:
        return "incomparable"
    if a_version == b_version:
        return "same"
    a_num, b_num = _as_number(a_version), _as_number(b_version)
    if a_num is None or b_num is None:
        return "incomparable"
    if a_num < b_num:
        return "older"
    if a_num > b_num:
        return "newer"
    return "same"


def assert_can_replace(stored: ObjectFreshness | None, new: ObjectFreshness) -> None:
    """Raise :class:`VersionRegression` if ``new`` may not overwrite ``stored``.

    Store implementations call this against the locked current row before every object write.
    - An older comparable version never overwrites a newer one.
    - A tombstone (``deleted``) is cleared only by a strictly newer comparable version.
    """
    if stored is None:
        return
    relation = compare(
        new.provider_version, new.version_order, stored.provider_version, stored.version_order
    )
    if relation == "older":
        raise VersionRegression(
            f"{new.source_id}/{new.external_object_id}: version {new.provider_version!r} is older "
            f"than stored {stored.provider_version!r}"
        )
    if (
        stored.freshness_status is FreshnessStatus.deleted
        and new.freshness_status is not FreshnessStatus.deleted
        and relation != "newer"
    ):
        raise VersionRegression(
            f"{new.source_id}/{new.external_object_id}: a tombstone is cleared only by a strictly "
            "newer comparable version"
        )
