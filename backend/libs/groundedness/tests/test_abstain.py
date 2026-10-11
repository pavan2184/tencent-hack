from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from groundedness import (
    DEFAULT_MIN_COVERAGE,
    DefaultAbstentionPolicy,
    GroundingReport,
    Verdict,
)


def report(**overrides: Any) -> GroundingReport:
    fields: dict[str, Any] = {
        "verifier": "lexical-v1",
        "created_at": datetime(2026, 10, 12, tzinfo=UTC),
        "claims_total": 4,
        "supported": 4,
        "partially_supported": 0,
        "unsupported": 0,
        "contradicted": 0,
        "coverage_ratio": 1.0,
        "verdict": Verdict.GROUNDED,
        "injection_flags": 0,
    }
    fields.update(overrides)
    return GroundingReport(**fields)


POLICY = DefaultAbstentionPolicy()


def test_grounded_answer_is_shown() -> None:
    assert POLICY.should_abstain(report(), min_coverage=0.6) == (False, None)


def test_default_min_coverage_matches_app_setting() -> None:
    assert DEFAULT_MIN_COVERAGE == 0.6
    partial = report(supported=3, unsupported=1, coverage_ratio=0.75, verdict="partially_grounded")
    assert POLICY.should_abstain(partial) == (False, None)


def test_abstains_without_claims() -> None:
    empty = report(claims_total=0, supported=0, coverage_ratio=0.0, verdict=Verdict.UNGROUNDED)
    abstain, reason = POLICY.should_abstain(empty, min_coverage=0.0)
    assert abstain and reason


def test_abstains_when_answer_abstained() -> None:
    abstained = report(claims_total=0, supported=0, coverage_ratio=1.0, verdict=Verdict.ABSTAINED)
    abstain, reason = POLICY.should_abstain(abstained, min_coverage=0.6)
    assert abstain and reason


@pytest.mark.parametrize(
    ("coverage", "min_coverage", "expected"),
    [
        (0.5, 0.6, True),
        (0.5999, 0.6, True),
        (0.6, 0.6, False),
        (0.75, 0.6, False),
        (0.75, 1.0, True),
        (1.0, 1.0, False),
    ],
)
def test_coverage_threshold(coverage: float, min_coverage: float, expected: bool) -> None:
    candidate = report(
        claims_total=1, supported=1, coverage_ratio=coverage, verdict="partially_grounded"
    )
    abstain, reason = POLICY.should_abstain(candidate, min_coverage=min_coverage)
    assert abstain is expected
    assert (reason is not None) is expected


def test_zero_coverage_abstains_even_with_zero_minimum() -> None:
    ungrounded = report(supported=0, unsupported=4, coverage_ratio=0.0, verdict="ungrounded")
    abstain, reason = POLICY.should_abstain(ungrounded, min_coverage=0.0)
    assert abstain
    assert reason == "evidence supports 0% of claims; 0% required"


def test_any_contradiction_abstains() -> None:
    contradicted = report(
        supported=3, contradicted=1, coverage_ratio=1.0, verdict="partially_grounded"
    )
    abstain, reason = POLICY.should_abstain(contradicted, min_coverage=0.0)
    assert abstain
    assert reason == "1 claim(s) contradicted by the cited evidence"


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_min_coverage_must_be_a_ratio(bad: float) -> None:
    with pytest.raises(ValueError):
        POLICY.should_abstain(report(), min_coverage=bad)


def test_policy_is_pure() -> None:
    candidate = report(supported=2, unsupported=2, coverage_ratio=0.5, verdict="partially_grounded")
    before = candidate.model_dump()
    first = POLICY.should_abstain(candidate, min_coverage=0.6)
    second = DefaultAbstentionPolicy().should_abstain(candidate, min_coverage=0.6)
    assert first == second == (True, "evidence supports 50% of claims; 60% required")
    assert candidate.model_dump() == before
