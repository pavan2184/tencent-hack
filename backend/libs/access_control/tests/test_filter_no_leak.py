"""``filter`` contract and the no-existence-leak shape of ``AccessSummary``."""

from __future__ import annotations

from typing import Any

import pytest
from access_control import (
    AccessSummary,
    Classification,
    Effect,
    FilterResult,
    SubjectType,
)


@pytest.fixture
def corpus(make_doc, make_grant, seed_blocks: dict[str, dict[str, Any]]):
    """Mixed candidates, as retrieval would over-fetch them."""

    return [
        make_doc(seed_blocks["confluence"], document_id="expense-policy"),
        make_doc(seed_blocks["slack"], document_id="treasury-ops-log"),
        make_doc(
            seed_blocks["gdrive"],
            document_id="board-deck-q3",
            classification=Classification.confidential,
            grants=[make_grant(SubjectType.group, "leadership", document_id="board-deck-q3")],
        ),
        make_doc(seed_blocks["jira"], document_id="PAY-142"),
        make_doc(None, document_id="no-snapshot"),
        make_doc(seed_blocks["email"], document_id="vendor-cutover"),
        make_doc(seed_blocks["upload"], document_id="alex-upload", owner="alex.tan"),
    ]


@pytest.mark.parametrize("who", ["alex", "priya", "sam", "root", "jordan", "mei"])
def test_one_decision_per_input_in_order_and_allowed_subset(policy, people, corpus, now, who):
    result = policy.filter(people[who], corpus, now=now)
    input_ids = [d.document_id for d in corpus]
    assert isinstance(result, FilterResult)
    assert len(result.decisions) == len(corpus)
    assert [d.document_id for d in result.decisions] == input_ids
    denied = {d.document_id for d in result.decisions if d.decision == Effect.deny}
    allowed = [d.document_id for d in result.decisions if d.decision == Effect.allow]
    assert result.allowed_ids == allowed  # same order as the input
    assert set(result.allowed_ids) <= set(input_ids)
    assert denied.isdisjoint(result.allowed_ids)
    assert all(d.evaluated_at == now and d.policy_version == "ac-v2" for d in result.decisions)


def test_expected_visibility_per_persona(policy, people, corpus, now):
    def visible(who: str) -> list[str]:
        return policy.filter(people[who], corpus, now=now).allowed_ids

    assert visible("alex") == ["expense-policy", "alex-upload"]
    finance = ["expense-policy", "treasury-ops-log", "PAY-142", "vendor-cutover"]
    assert visible("priya") == [*finance[:2], "board-deck-q3", *finance[2:]]
    assert visible("jordan") == ["expense-policy", "treasury-ops-log", "PAY-142", "vendor-cutover"]
    assert visible("mei") == []
    assert visible("root") == ["no-snapshot", "alex-upload"]


def test_live_revocation_drops_document(policy, people, corpus, make_grant, now):
    before = policy.filter(people["priya"], corpus, now=now)
    deck = corpus[2]
    revoked = deck.model_copy(
        update={
            "grants": [
                make_grant(
                    SubjectType.group, "leadership", document_id="board-deck-q3", revoked=True
                )
            ]
        }
    )
    after = policy.filter(people["priya"], [*corpus[:2], revoked, *corpus[3:]], now=now)
    assert "board-deck-q3" in before.allowed_ids
    assert "board-deck-q3" not in after.allowed_ids
    assert len(after.allowed_ids) == len(before.allowed_ids) - 1
    assert after.decisions[2].reason == "grant_revoked"


def test_duplicate_candidates_keep_one_decision_each_but_unique_allowed_ids(
    policy, people, corpus, now
):
    docs = [corpus[0], corpus[1], corpus[0]]
    result = policy.filter(people["alex"], docs, now=now)
    assert len(result.decisions) == 3
    assert result.allowed_ids == ["expense-policy"]


def test_empty_input(policy, people, now):
    result = policy.filter(people["alex"], [], now=now)
    assert result.allowed_ids == [] and result.decisions == []


def test_filter_accepts_any_iterable(policy, people, corpus, now):
    result = policy.filter(people["alex"], (d for d in corpus), now=now)
    assert len(result.decisions) == len(corpus)


def test_access_summary_has_no_denied_field(policy, people, corpus, now):
    assert not [name for name in AccessSummary.model_fields if "denied" in name.lower()]
    assert set(AccessSummary.model_fields) == {
        "principal_id",
        "policy_version",
        "allowed_count",
        "evaluated_at",
    }
    result = policy.filter(people["mei"], corpus, now=now)
    summary = AccessSummary.from_filter_result(
        result, principal_id="mei.chen", policy_version=policy.policy_version, evaluated_at=now
    )
    assert summary.allowed_count == 0
    assert "denied" not in summary.model_dump_json().lower()
    with pytest.raises(ValueError):
        AccessSummary(
            principal_id="x",
            policy_version="v",
            allowed_count=0,
            evaluated_at=now,
            denied_count=3,  # type: ignore[call-arg]
        )


def test_denied_decisions_reveal_nothing_beyond_ids_given(policy, people, corpus, now):
    """A denied decision only echoes the caller's own candidate id plus audit metadata."""
    result = policy.filter(people["mei"], corpus, now=now)
    for decision in result.decisions:
        assert set(decision.model_dump()) == {
            "document_id",
            "decision",
            "reason",
            "matched_rule",
            "permission_version",
            "policy_version",
            "evaluated_at",
        }
