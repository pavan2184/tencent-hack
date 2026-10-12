from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from groundedness import (
    Citation,
    Claim,
    DefaultAbstentionPolicy,
    ExtractiveComposer,
    GroundedAnswer,
    LexicalOverlapVerifier,
    SanitizedEvidence,
    SupportLabel,
    Verdict,
    build_grounding_report,
    claim_label,
    unsupported_numeric_facts,
)

S = SupportLabel
CREATED_AT = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


def answer_for(*claims: tuple[str, list[tuple[str, str | None]]]) -> GroundedAnswer:
    """``answer_for(("claim text", [("E1", quote_or_None), ...]), ...)``."""
    claim_models: list[Claim] = []
    citations: list[Citation] = []
    for position, (text, cites) in enumerate(claims):
        claim = Claim(id=f"C{position + 1}", text=text, position=position)
        claim_models.append(claim)
        for evidence_id, quote in cites:
            citations.append(Citation(claim_id=claim.id, evidence_id=evidence_id, quote=quote))
    return GroundedAnswer(
        answer_text=" ".join(text for text, _ in claims),
        claims=claim_models,
        citations=citations,
        composer="test",
    )


async def verify_one(
    claim: str, evidence: list[SanitizedEvidence], *, evidence_id: str = "E1", quote=None
):
    answer = answer_for((claim, [(evidence_id, quote)]))
    report = await LexicalOverlapVerifier().verify(answer, evidence)
    (citation,) = report.per_claim
    return citation, report


# ---------------------------------------------------------------------------- thresholds


@pytest.mark.parametrize(
    ("claim", "evidence_text", "label", "score"),
    [
        ("alpha bravo charlie delta echo", "alpha bravo charlie delta echo", S.SUPPORTED, 1.0),
        ("alpha bravo charlie", "alpha bravo charlie delta echo", S.SUPPORTED, 0.6),
        (
            "alpha bravo charlie",
            "alpha bravo charlie delta echo foxtrot",
            S.PARTIALLY_SUPPORTED,
            0.5,
        ),
        (
            "alpha bravo charlie",
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet",
            S.PARTIALLY_SUPPORTED,
            0.3,
        ),
        ("alpha bravo", "alpha bravo charlie delta echo foxtrot golf", S.UNSUPPORTED, 0.2857),
        ("alpha", "bravo charlie", S.UNSUPPORTED, 0.0),
    ],
)
@pytest.mark.parametrize("with_quote", [True, False])
async def test_jaccard_thresholds(
    clean, claim: str, evidence_text: str, label: SupportLabel, score: float, with_quote: bool
) -> None:
    evidence = [clean(evidence_text, id="E1")]
    quote = evidence_text if with_quote else None
    citation, _ = await verify_one(claim, evidence, quote=quote)
    assert citation.support is label
    assert citation.score == score


async def test_custom_thresholds(clean) -> None:
    answer = answer_for(("alpha bravo charlie", [("E1", None)]))
    evidence = [clean("alpha bravo charlie delta echo", id="E1")]
    strict = LexicalOverlapVerifier(supported_threshold=0.9, partial_threshold=0.5)
    (citation,) = (await strict.verify(answer, evidence)).per_claim
    assert citation.support is S.PARTIALLY_SUPPORTED
    with pytest.raises(ValueError):
        LexicalOverlapVerifier(supported_threshold=0.5, partial_threshold=0.7)


# ---------------------------------------------------------------------------- safety rules


async def test_quarantined_evidence_is_never_supported(quarantined) -> None:
    text = "Payments above SGD 10,000 require CFO approval."
    citation, report = await verify_one(text, [quarantined(text, id="E1")], quote=text)
    assert citation.support is S.UNSUPPORTED
    assert citation.score == 0.0
    assert citation.quote is None
    assert report.quarantined_evidence_ids == ["E1"]
    assert report.verdict is Verdict.UNGROUNDED


async def test_missing_or_empty_evidence_is_unsupported(clean) -> None:
    claim = "CFO approves payments."
    missing, _ = await verify_one(claim, [clean(claim, id="E1")], evidence_id="E404", quote=claim)
    empty, _ = await verify_one(claim, [clean("   ", id="E1")], quote=claim)
    for citation in (missing, empty):
        assert citation.support is S.UNSUPPORTED
        assert citation.quote is None


async def test_fabricated_quote_is_ignored(clean) -> None:
    claim = "The CFO approves all refunds."
    evidence = [clean("The office pantry is restocked on Mondays.", id="E1")]
    citation, _ = await verify_one(claim, evidence, quote=claim)
    assert citation.support is S.UNSUPPORTED
    assert citation.quote is None


async def test_missing_quote_uses_best_evidence_sentence(clean) -> None:
    text = "The pantry is restocked on Mondays. Payments above SGD 10,000 require CFO approval."
    claim = "Payments above SGD 10,000 require CFO approval."
    citation, _ = await verify_one(claim, [clean(text, id="E1")])
    assert citation.support is S.SUPPORTED
    assert citation.quote == "Payments above SGD 10,000 require CFO approval."


async def test_quote_match_ignores_case_and_whitespace(clean) -> None:
    text = "Payments above SGD 10,000\n  require CFO approval."
    claim = "Payments above SGD 10,000 require CFO approval."
    citation, _ = await verify_one(claim, [clean(text, id="E1")], quote=claim.upper())
    assert citation.support is S.SUPPORTED
    assert citation.quote == claim.upper()


# ---------------------------------------------------------------------------- contradiction


@pytest.mark.parametrize(
    ("claim", "evidence_text", "label"),
    [
        (
            "The vendor payment was not approved.",
            "The vendor payment was approved.",
            S.CONTRADICTED,
        ),
        (
            "The vendor payment wasn't approved by finance.",
            "The vendor payment was approved by finance.",
            S.CONTRADICTED,
        ),
        (
            "Refunds are approved by the CFO.",
            "Refunds are never approved by the CFO.",
            S.CONTRADICTED,
        ),
        ("The payment was not approved.", "The payment was not approved.", S.SUPPORTED),
        ("Never visit the golf club.", "alpha bravo charlie", S.UNSUPPORTED),
        (
            "None of the vendor payments were approved.",
            "The vendor payments were approved.",
            S.CONTRADICTED,
        ),
        (
            "Neither finance nor treasury approved the vendor payment.",
            "Finance and treasury approved the vendor payment.",
            S.CONTRADICTED,
        ),
        (
            "Refunds are issued without CFO approval.",
            "Refunds are issued with CFO approval.",
            S.CONTRADICTED,
        ),
        (
            "The vendor payment workflow no longer routes approvals through finance-ops.",
            "The vendor payment workflow routes approvals through finance-ops.",
            S.CONTRADICTED,
        ),
        (
            "Refunds are issued without CFO approval.",
            "Refunds are issued without CFO approval.",
            S.SUPPORTED,
        ),
    ],
)
async def test_negation_contradiction_heuristic(
    clean, claim: str, evidence_text: str, label: SupportLabel
) -> None:
    citation, _ = await verify_one(claim, [clean(evidence_text, id="E1")], quote=evidence_text)
    assert citation.support is label


# ---------------------------------------------------------------------------- numeric gate

POLICY_TEXT = "Payments above SGD 10,000 require CFO approval."


async def test_wrong_number_is_unsupported_despite_overlap(clean) -> None:
    claim = "Payments above SGD 20,000 require CFO approval."
    citation, report = await verify_one(claim, [clean(POLICY_TEXT, id="E1")], quote=POLICY_TEXT)
    assert citation.support is S.UNSUPPORTED
    assert citation.score == 0.75, "the overlap is kept for the audit"
    assert citation.quote == POLICY_TEXT, "the quote shows the evidence's real value"
    assert report.unsupported == 1
    assert report.verdict is Verdict.UNGROUNDED


async def test_right_number_in_another_format_keeps_its_label(clean) -> None:
    claim = "Payments above SGD 10k require CFO approval."
    citation, _ = await verify_one(claim, [clean(POLICY_TEXT, id="E1")])
    assert citation.support is S.SUPPORTED
    assert citation.score == 0.625


async def test_gate_checks_the_whole_evidence_text(clean) -> None:
    claim = "The CFO signs payment requests above 10,000."
    best = "The CFO signs every payment request."
    citation, _ = await verify_one(claim, [clean(f"{POLICY_TEXT} {best}", id="E1")])
    assert citation.support is S.PARTIALLY_SUPPORTED, "10,000 is elsewhere in the evidence"
    assert citation.score == 0.5714
    assert citation.quote == best

    other = "Payments above SGD 5,000 require CFO approval."
    citation, _ = await verify_one(claim, [clean(f"{other} {best}", id="E1")])
    assert citation.support is S.UNSUPPORTED, "10,000 is nowhere in the evidence"
    assert citation.score == 0.5714
    assert citation.quote == best


async def test_word_number_evidence_demotes_a_digit_claim(clean) -> None:
    evidence = [clean("The CFO limit is SGD one million.", id="E1")]
    citation, _ = await verify_one("The CFO limit is SGD 1 million.", evidence)
    assert citation.support is S.UNSUPPORTED
    assert citation.score == 0.6667


@pytest.mark.parametrize(
    ("claim", "label", "score"),
    [
        ("Revenue grew 21% year on year.", S.UNSUPPORTED, 0.6),
        ("Revenue grew 18% year on year.", S.SUPPORTED, 1.0),
    ],
)
async def test_percentage_gate(clean, claim: str, label: SupportLabel, score: float) -> None:
    citation, _ = await verify_one(claim, [clean("Revenue grew 18% year on year.", id="E1")])
    assert citation.support is label
    assert citation.score == score


@pytest.mark.parametrize(
    ("claim", "label", "score"),
    [
        ("The cutover is on 18 October at 02:00.", S.UNSUPPORTED, 0.4),
        ("The cutover is on 17 October at 03:00.", S.UNSUPPORTED, 0.4),
        ("The cutover is on 17 October at 02:00.", S.PARTIALLY_SUPPORTED, 0.5556),
    ],
)
async def test_date_and_time_gate(clean, claim: str, label: SupportLabel, score: float) -> None:
    evidence = [clean("The cutover runs on Saturday 17 October, 02:00 to 04:00 SGT.", id="E1")]
    citation, _ = await verify_one(claim, evidence)
    assert citation.support is label
    assert citation.score == score


async def test_negation_takes_precedence_over_the_gate(clean) -> None:
    claim = "Payments above SGD 10.000 do not require CFO approval."
    assert unsupported_numeric_facts(claim, POLICY_TEXT) == {"10"}, "the gate would fire"
    citation, _ = await verify_one(claim, [clean(POLICY_TEXT, id="E1")], quote=POLICY_TEXT)
    assert citation.support is S.CONTRADICTED
    assert citation.score == 1.0


BOARD_DECK = (
    "## Headline results\n\n"
    "- **Q3 2026 revenue: SGD 48.6 million**, up **18% year on year** "
    "(Q3 2025: SGD 41.2 million).\n"
    "- Operating expenses: SGD 38.8 million. **EBITDA: SGD 9.8 million**, a 20.2% margin.\n"
    "- Total payment volume: **SGD 12.4 billion** across 3.1 million transactions.\n"
    "- Active business accounts: 41,300, up 9% on the previous quarter."
)


async def test_extractive_claims_over_numeric_evidence_stay_grounded(clean, fixed_clock) -> None:
    evidence = [clean(BOARD_DECK, id="E1", document_id="doc-board-deck")]
    answer = await ExtractiveComposer().compose(
        "What were Q3 revenue, EBITDA, payment volume and active accounts?", evidence
    )
    assert len(answer.claims) >= 3
    report = await LexicalOverlapVerifier(clock=fixed_clock).verify(answer, evidence)
    assert [c.score for c in report.per_claim] == [1.0] * len(answer.claims)
    assert {c.support for c in report.per_claim} == {S.SUPPORTED}
    assert report.verdict is Verdict.GROUNDED


async def test_wrong_number_answer_is_withheld_deterministically(clean, fixed_clock) -> None:
    evidence = [clean(POLICY_TEXT, id="E1")]
    answer = answer_for(("Payments above SGD 20,000 require CFO approval.", [("E1", None)]))
    first = await LexicalOverlapVerifier(clock=fixed_clock).verify(answer, evidence)
    second = await LexicalOverlapVerifier(clock=fixed_clock).verify(answer, evidence)
    assert first.model_dump() == second.model_dump()
    assert first.hash_is_valid()
    assert first.verifier == "lexical-v2"
    assert first.unsupported == 1
    assert first.verdict is Verdict.UNGROUNDED
    abstain, reason = DefaultAbstentionPolicy().should_abstain(first, min_coverage=0.6)
    assert abstain
    assert reason is not None and "20,000" not in reason and "10,000" not in reason


# ---------------------------------------------------------------------------- coverage & verdict


def _labelled(claim_id: str, support: SupportLabel, evidence_id: str = "E1") -> Citation:
    return Citation(claim_id=claim_id, evidence_id=evidence_id, support=support)


def _three_claims() -> GroundedAnswer:
    return answer_for(
        ("Claim one.", [("E1", None)]),
        ("Claim two.", [("E1", None)]),
        ("Claim three.", [("E1", None)]),
    )


@pytest.mark.parametrize(
    ("labels", "coverage", "verdict"),
    [
        ([S.SUPPORTED, S.SUPPORTED, S.SUPPORTED], 1.0, Verdict.GROUNDED),
        ([S.SUPPORTED, S.PARTIALLY_SUPPORTED, S.PARTIALLY_SUPPORTED], 1.0, Verdict.GROUNDED),
        ([S.SUPPORTED, S.PARTIALLY_SUPPORTED, S.UNSUPPORTED], 0.6667, Verdict.PARTIALLY_GROUNDED),
        ([S.SUPPORTED, S.SUPPORTED, S.CONTRADICTED], 0.6667, Verdict.PARTIALLY_GROUNDED),
        ([S.UNSUPPORTED, S.UNSUPPORTED, S.CONTRADICTED], 0.0, Verdict.UNGROUNDED),
        ([S.NOT_CHECKED, S.UNSUPPORTED, S.UNSUPPORTED], 0.0, Verdict.UNGROUNDED),
    ],
)
def test_coverage_and_verdict(
    labels: list[SupportLabel], coverage: float, verdict: Verdict
) -> None:
    answer = _three_claims()
    citations = [_labelled(f"C{i + 1}", label) for i, label in enumerate(labels)]
    report = build_grounding_report(answer, [], citations, verifier="test", created_at=CREATED_AT)
    assert report.coverage_ratio == coverage
    assert report.verdict is verdict
    assert report.claims_total == 3
    total = report.supported + report.partially_supported + report.unsupported + report.contradicted
    assert total == 3


def test_covered_but_contradicted_claim_blocks_grounded() -> None:
    answer = answer_for(("Claim one.", [("E1", None), ("E2", None)]))
    citations = [_labelled("C1", S.SUPPORTED, "E1"), _labelled("C1", S.CONTRADICTED, "E2")]
    report = build_grounding_report(answer, [], citations, verifier="t", created_at=CREATED_AT)
    assert report.coverage_ratio == 1.0
    assert report.contradicted == 1
    assert report.supported == 0
    assert report.verdict is Verdict.PARTIALLY_GROUNDED


async def test_zero_claims_abstained_answer(treasury_evidence) -> None:
    answer = GroundedAnswer.abstention("no usable evidence", composer="test")
    report = await LexicalOverlapVerifier().verify(answer, treasury_evidence)
    assert report.claims_total == 0
    assert report.coverage_ratio == 1.0
    assert report.verdict is Verdict.ABSTAINED
    assert report.per_claim == []


async def test_zero_claims_not_abstained_is_ungrounded() -> None:
    answer = GroundedAnswer(answer_text="Something with no claims.", composer="test")
    report = await LexicalOverlapVerifier().verify(answer, [])
    assert report.claims_total == 0
    assert report.coverage_ratio == 0.0
    assert report.verdict is Verdict.UNGROUNDED


def test_claim_label_precedence() -> None:
    assert claim_label([S.SUPPORTED, S.CONTRADICTED]) is S.CONTRADICTED
    assert claim_label([S.PARTIALLY_SUPPORTED, S.SUPPORTED]) is S.SUPPORTED
    assert claim_label([S.UNSUPPORTED, S.PARTIALLY_SUPPORTED]) is S.PARTIALLY_SUPPORTED
    assert claim_label([S.NOT_CHECKED]) is S.UNSUPPORTED
    assert claim_label([]) is S.UNSUPPORTED


def test_per_claim_follows_claim_position() -> None:
    answer = GroundedAnswer(
        answer_text="B. A.",
        claims=[Claim(id="CB", text="B.", position=1), Claim(id="CA", text="A.", position=0)],
        citations=[_labelled("CB", S.SUPPORTED), _labelled("CA", S.SUPPORTED)],
        composer="test",
    )
    report = build_grounding_report(
        answer, [], answer.citations, verifier="t", created_at=CREATED_AT
    )
    assert [c.claim_id for c in report.per_claim] == ["CA", "CB"]


# ---------------------------------------------------------------------------- report metadata


async def test_report_metadata_and_determinism(treasury_evidence, fixed_clock) -> None:
    answer = await ExtractiveComposer().compose("Who approves payments?", treasury_evidence)
    verifier = LexicalOverlapVerifier(clock=fixed_clock)
    first = await verifier.verify(answer, treasury_evidence)
    second = await LexicalOverlapVerifier(clock=fixed_clock).verify(answer, treasury_evidence)
    assert first.model_dump() == second.model_dump()
    assert first.verifier == "lexical-v2"
    assert first.created_at == fixed_clock()
    assert first.hash_is_valid()
    assert first.quarantined_evidence_ids == ["E2"]
    assert first.injection_flags == sum(len(item.flags) for item in treasury_evidence)
    assert all(c.support is not S.NOT_CHECKED for c in first.per_claim)

    later = await LexicalOverlapVerifier(clock=lambda: fixed_clock() + timedelta(seconds=1)).verify(
        answer, treasury_evidence
    )
    assert later.report_hash != first.report_hash
    assert later.model_dump(exclude={"created_at", "report_hash"}) == first.model_dump(
        exclude={"created_at", "report_hash"}
    )


async def test_verify_does_not_mutate_answer(treasury_evidence) -> None:
    answer = await ExtractiveComposer().compose("Who approves payments?", treasury_evidence)
    before = answer.model_dump()
    await LexicalOverlapVerifier().verify(answer, treasury_evidence)
    assert answer.model_dump() == before


# ---------------------------------------------------------------------------- end to end


async def test_pipeline_extractive_end_to_end(sanitizer, treasury_spans, fixed_clock) -> None:
    sanitized = sanitizer.sanitize(treasury_spans)
    answer = await ExtractiveComposer().compose(
        "Who must approve payments above SGD 10,000?", sanitized
    )
    report = await LexicalOverlapVerifier(clock=fixed_clock).verify(answer, sanitized)
    abstain, reason = DefaultAbstentionPolicy().should_abstain(report, min_coverage=0.6)
    assert report.verdict is Verdict.GROUNDED
    assert (abstain, reason) == (False, None)
    assert "E2" not in {c.evidence_id for c in answer.citations}
    assert "E2" in report.quarantined_evidence_ids
