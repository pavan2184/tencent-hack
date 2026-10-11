"""Abstention policy: the last gate before an answer is shown."""

from __future__ import annotations

from groundedness.models import GroundingReport, Verdict

DEFAULT_MIN_COVERAGE = 0.6
"""Matches the app's ``GROUNDING_MIN_COVERAGE`` default."""


class DefaultAbstentionPolicy:
    """Abstain when there is nothing grounded to show (abstain over guess).

    Rules, first match wins (the reason never quotes evidence, so it cannot leak content):

    1. the answer abstained or has no claims;
    2. any claim is contradicted by its evidence;
    3. ``coverage_ratio`` is 0, or below ``min_coverage``.
    """

    def should_abstain(
        self, report: GroundingReport, *, min_coverage: float = DEFAULT_MIN_COVERAGE
    ) -> tuple[bool, str | None]:
        if not 0.0 <= min_coverage <= 1.0:
            raise ValueError("min_coverage must be within [0, 1]")
        if report.verdict is Verdict.ABSTAINED or report.claims_total == 0:
            return True, "no claims could be grounded in the available evidence"
        if report.contradicted > 0:
            return True, f"{report.contradicted} claim(s) contradicted by the cited evidence"
        if report.coverage_ratio == 0.0 or report.coverage_ratio < min_coverage:
            return True, (
                f"evidence supports {report.coverage_ratio:.0%} of claims; "
                f"{min_coverage:.0%} required"
            )
        return False, None
