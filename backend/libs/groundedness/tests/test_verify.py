from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from groundedness import (
    Citation,
    Claim,
    DefaultAbstentionPolicy,
    ExtractiveComposer,
    FakeLLM,
    GroundedAnswer,
    LexicalOverlapVerifier,
    LLMComposer,
    LLMEntailmentVerifier,
    SanitizedEvidence,
    SupportLabel,
    Verdict,
    build_entailment_prompt,
    build_grounding_report,
    claim_label,
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
    ],
)
async def test_negation_contradiction_heuristic(
    clean, claim: str, evidence_text: str, label: SupportLabel
) -> None:
    citation, _ = await verify_one(claim, [clean(evidence_text, id="E1")], quote=evidence_text)
    assert citation.support is label


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
    assert first.verifier == "lexical-v1"
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


# ---------------------------------------------------------------------------- LLM entailment


async def test_llm_entailment_verifier_is_a_skeleton(treasury_evidence) -> None:
    answer = GroundedAnswer.abstention("x", composer="test")
    with pytest.raises(NotImplementedError, match="Raphael: implement the entailment judge"):
        await LLMEntailmentVerifier(FakeLLM()).verify(answer, treasury_evidence)


def test_entailment_prompt() -> None:
    system, user = build_entailment_prompt(
        "CFO approves  payments.", "Payments need CFO approval.", title="Treasury"
    )
    for label in ("SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "UNSUPPORTED"):
        assert label in system
    assert "untrusted" in system
    assert "CLAIM: CFO approves payments." in user
    assert "EVIDENCE (Treasury):\nPayments need CFO approval." in user


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


async def test_pipeline_hallucinated_llm_claim_is_withheld(
    sanitizer, treasury_spans, fixed_clock
) -> None:
    sanitized = sanitizer.sanitize(treasury_spans)
    llm = FakeLLM(default="The CFO limit is SGD 1 million [E1].")
    answer = await LLMComposer(llm).compose("What is the CFO limit?", sanitized)
    report = await LexicalOverlapVerifier(clock=fixed_clock).verify(answer, sanitized)
    abstain, reason = DefaultAbstentionPolicy().should_abstain(report, min_coverage=0.6)
    assert report.verdict is Verdict.UNGROUNDED
    assert abstain
    assert reason is not None and "1 million" not in reason
