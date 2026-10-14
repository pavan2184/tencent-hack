"""Conservative selection of verified claims from a low-coverage model answer."""

from __future__ import annotations

from datetime import UTC, datetime

from groundedness import (
    Citation,
    Claim,
    EvidenceSpan,
    GroundedAnswer,
    GroundingReport,
    LexicalOverlapVerifier,
    SanitizedEvidence,
    SupportLabel,
    Verdict,
    has_off_topic_claims,
    needs_partial_selection,
    procedure_requested,
    select_supported_relevant_claims,
)


def candidate(
    *,
    contradicted: bool = False,
    first_claim: str = "The sandbox settlement hold for Rail-B is 17 minutes.",
) -> tuple[GroundedAnswer, GroundingReport]:
    claims = [
        Claim(id="C1", text=first_claim, position=0),
        Claim(id="C2", text="The rehearsal begins on Thursday.", position=1),
        Claim(id="C3", text="The production cutover is Saturday.", position=2),
    ]
    citations = [
        Citation(claim_id="C1", evidence_id="E1"),
        Citation(claim_id="C1", evidence_id="E2"),
        Citation(claim_id="C2", evidence_id="E3"),
        Citation(claim_id="C3", evidence_id="E4"),
    ]
    answer = GroundedAnswer(
        answer_text="Generated answer with three claims.",
        claims=claims,
        citations=citations,
        composer="model-v1+ground-v1",
    )
    verified = [
        Citation(
            claim_id="C1",
            evidence_id="E1",
            quote="The sandbox settlement hold for Rail-B is 17 minutes.",
            support=SupportLabel.SUPPORTED,
            score=1,
        ),
        Citation(
            claim_id="C1",
            evidence_id="E2",
            quote="Sandbox hold timeline.",
            support=SupportLabel.PARTIALLY_SUPPORTED,
            score=0.4,
        ),
        Citation(
            claim_id="C2",
            evidence_id="E3",
            quote="Rehearsal.",
            support=SupportLabel.CONTRADICTED if contradicted else SupportLabel.UNSUPPORTED,
            score=0.2,
        ),
        Citation(
            claim_id="C3",
            evidence_id="E4",
            quote="Cutover.",
            support=SupportLabel.UNSUPPORTED,
            score=0.2,
        ),
    ]
    report = GroundingReport(
        verifier="lexical-v2",
        created_at=datetime(2026, 10, 14, tzinfo=UTC),
        claims_total=3,
        supported=1,
        partially_supported=0,
        unsupported=1 if contradicted else 2,
        contradicted=1 if contradicted else 0,
        coverage_ratio=0.3333,
        verdict=Verdict.PARTIALLY_GROUNDED,
        injection_flags=0,
        per_claim=verified,
    )
    return answer, report


def test_keeps_only_relevant_fully_supported_claim_and_citation() -> None:
    answer, report = candidate()
    original = answer.model_dump()

    selected = select_supported_relevant_claims("What's the settlement hold drill?", answer, report)

    assert selected is not None
    assert [claim.id for claim in selected.claims] == ["C1"]
    assert [(cite.claim_id, cite.evidence_id) for cite in selected.citations] == [("C1", "E1")]
    assert selected.answer_text == "The sandbox settlement hold for Rail-B is 17 minutes. [E1]"
    assert selected.composer == "model-v1+ground-v1"
    assert answer.model_dump() == original


def test_rejects_contradicted_candidate() -> None:
    answer, report = candidate(contradicted=True)
    assert (
        select_supported_relevant_claims("What's the settlement hold drill?", answer, report)
        is None
    )


def test_rejects_off_topic_supported_claim() -> None:
    answer, report = candidate(first_claim="The production cutover is Saturday.")
    assert (
        select_supported_relevant_claims("What's the settlement hold drill?", answer, report)
        is None
    )


def test_shared_rail_b_name_alone_does_not_make_claim_relevant() -> None:
    answer, report = candidate(first_claim="The Rail-B production cutover is Saturday.")
    assert (
        select_supported_relevant_claims(
            "How quickly must the Rail-B rollback complete?", answer, report
        )
        is None
    )


def test_rejects_model_abstention_and_empty_question_tokens() -> None:
    answer, report = candidate()
    abstained = GroundedAnswer.abstention("No evidence", composer="model-v1+ground-v1")
    assert select_supported_relevant_claims("Settlement hold", abstained, report) is None
    assert select_supported_relevant_claims("What is it?", answer, report) is None


def test_one_token_question_requires_one_matching_token() -> None:
    answer, report = candidate()
    selected = select_supported_relevant_claims("Hold?", answer, report)
    assert selected is not None
    assert len(selected.claims) == 1


def test_off_topic_detection_distinguishes_revenue_claims_from_cutover_extras() -> None:
    answer, _ = candidate()
    assert has_off_topic_claims("What's the settlement hold drill?", answer)
    relevant, _ = candidate()
    relevant.claims = [
        Claim(id="C1", text="The Q3 2026 revenue was SGD 48.6 million.", position=0),
        Claim(
            id="C2",
            text="Q3 2025 revenue was SGD 41.2 million.",
            position=1,
        ),
    ]
    relevant.citations = [
        Citation(claim_id="C1", evidence_id="E1"),
        Citation(claim_id="C2", evidence_id="E2"),
    ]
    assert not has_off_topic_claims("What were the Q3 board deck revenue figures?", relevant)


def verified_pair(
    second_evidence: str, second_claim: str
) -> tuple[GroundedAnswer, GroundingReport]:
    first = "The sandbox settlement hold for Rail-B is 17 minutes."
    answer = GroundedAnswer(
        answer_text=f"{first} {second_claim}",
        claims=[
            Claim(id="C1", text=first, position=0),
            Claim(id="C2", text=second_claim, position=1),
        ],
        citations=[
            Citation(claim_id="C1", evidence_id="E1"),
            Citation(claim_id="C2", evidence_id="E2"),
        ],
        composer="model-v1+ground-v1",
    )
    evidence = [
        SanitizedEvidence(
            evidence=EvidenceSpan(
                id=evidence_id,
                document_id=evidence_id,
                source_id="synthetic",
                source_kind="confluence",
                slug=f"drills/{evidence_id}",
                title="Synthetic drill",
                text=text,
            )
        )
        for evidence_id, text in (("E1", first), ("E2", second_evidence))
    ]
    return answer, LexicalOverlapVerifier().verify_sync(answer, evidence)


def test_on_topic_partially_supported_procedure_claim_requires_selection() -> None:
    question = "What is the sandbox settlement hold drill procedure and how long is the hold?"
    answer, report = verified_pair(
        "The sandbox settlement hold requires manager review.",
        "The sandbox settlement hold requires manager review, operations authorization, "
        "treasury signoff, regulator notification, and ledger reconciliation.",
    )

    assert (report.supported, report.partially_supported, report.unsupported) == (1, 1, 0)
    assert report.coverage_ratio == 1.0
    assert not has_off_topic_claims(question, answer)
    assert procedure_requested(question)
    assert needs_partial_selection(question, answer, report)
    selected = select_supported_relevant_claims(question, answer, report)
    assert selected is not None
    assert [claim.id for claim in selected.claims] == ["C1"]


def test_supported_dashboard_fact_is_off_topic_for_drill() -> None:
    question = "What is the settlement hold drill procedure and how long does the hold last?"
    answer, report = verified_pair(
        "The settlement hold dashboard was updated yesterday.",
        "The settlement hold dashboard was updated yesterday.",
    )

    assert report.supported == 2
    assert has_off_topic_claims(question, answer)
    assert needs_partial_selection(question, answer, report)
    selected = select_supported_relevant_claims(question, answer, report)
    assert selected is not None
    assert [claim.id for claim in selected.claims] == ["C1"]


def test_supported_dashboard_requirement_is_off_topic_for_drill() -> None:
    question = "What is the sandbox settlement hold drill procedure and how long is the hold?"
    answer, report = verified_pair(
        "The settlement hold dashboard requires weekly review.",
        "The settlement hold dashboard requires weekly review.",
    )

    assert report.supported == 2
    assert has_off_topic_claims(question, answer)
    assert needs_partial_selection(question, answer, report)
    selected = select_supported_relevant_claims(question, answer, report)
    assert selected is not None
    assert [claim.id for claim in selected.claims] == ["C1"]


def test_hold_requirement_is_relevant_procedural_fact() -> None:
    question = "What is the settlement hold drill procedure?"
    answer, report = verified_pair(
        "The settlement hold requires two operators.",
        "The settlement hold requires two operators.",
    )

    assert report.supported == 2
    assert not has_off_topic_claims(question, answer)
    selected = select_supported_relevant_claims(question, answer, report)
    assert selected is not None
    assert [claim.id for claim in selected.claims] == ["C1", "C2"]


def test_weak_citation_on_supported_procedure_fact_is_removed() -> None:
    question = "What is the sandbox settlement hold drill procedure?"
    sentence = "The sandbox settlement hold for Rail-B is 17 minutes."
    answer = GroundedAnswer(
        answer_text=sentence,
        claims=[Claim(id="C1", text=sentence, position=0)],
        citations=[
            Citation(claim_id="C1", evidence_id="E1"),
            Citation(claim_id="C1", evidence_id="E2"),
        ],
        composer="model-v1+ground-v1",
    )
    evidence = [
        SanitizedEvidence(
            evidence=EvidenceSpan(
                id=evidence_id,
                document_id=evidence_id,
                source_id="synthetic",
                source_kind="confluence",
                slug=f"drills/{evidence_id}",
                title="Synthetic drill",
                text=text,
            )
        )
        for evidence_id, text in (
            ("E1", sentence),
            ("E2", "The sandbox settlement hold was scheduled for 17 minutes during rehearsal."),
        )
    ]
    report = LexicalOverlapVerifier().verify_sync(answer, evidence)

    assert report.supported == 1
    assert [citation.support for citation in report.per_claim] == [
        SupportLabel.SUPPORTED,
        SupportLabel.PARTIALLY_SUPPORTED,
    ]
    assert needs_partial_selection(question, answer, report)
    selected = select_supported_relevant_claims(question, answer, report)
    assert selected is not None
    assert [(citation.claim_id, citation.evidence_id) for citation in selected.citations] == [
        ("C1", "E1")
    ]


def test_two_token_minimum_excludes_concise_one_overlap_claim() -> None:
    answer, report = candidate(first_claim="The hold lasts 17 minutes.")
    assert (
        select_supported_relevant_claims("What's the settlement hold drill?", answer, report)
        is None
    )
