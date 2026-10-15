"""Conservatively retain verified, question-relevant facts from a model candidate."""

from __future__ import annotations

from groundedness.compose import content_tokens, tokenize
from groundedness.models import Citation, Claim, GroundedAnswer, GroundingReport, SupportLabel


def _terms(text: str) -> set[str]:
    return {token for token in content_tokens(text) if len(token) > 1}


def procedure_requested(question: str) -> bool:
    """Whether the question asks for a drill or procedure, rather than only a fact."""
    return bool(_terms(question) & {"drill", "procedure", "step"})


def _relevant(claim: Claim, question_terms: set[str]) -> bool:
    claim_terms = _terms(claim.text)
    if not question_terms or len(claim_terms & question_terms) < min(2, len(question_terms)):
        return False
    if question_terms & {"drill", "procedure", "step"}:
        # Shared subject words alone can describe an unrelated dashboard update.
        if claim_terms & {"drill", "procedure", "step"}:
            return True
        subjects = question_terms & {"hold", "rollback"}
        if not subjects or not claim_terms & subjects:
            return False
        if claim_terms & {"minute", "hour", "duration"} and "dashboard" not in claim_terms:
            return True
        words = tokenize(claim.text)
        return any(
            word in subjects and following in {"require", "requires", "need", "needs"}
            for word, following in zip(words, words[1:], strict=False)
        )
    return True


def has_off_topic_claims(question: str, answer: GroundedAnswer) -> bool:
    """Whether a candidate includes a claim lacking direct question overlap."""
    question_terms = _terms(question)
    return bool(question_terms) and any(
        not _relevant(claim, question_terms) for claim in answer.claims
    )


def needs_partial_selection(question: str, answer: GroundedAnswer, report: GroundingReport) -> bool:
    """Require claim pruning when a candidate contains unverified or irrelevant details."""
    return (
        report.unsupported > 0
        or has_off_topic_claims(question, answer)
        or (
            procedure_requested(question)
            and any(citation.support is not SupportLabel.SUPPORTED for citation in report.per_claim)
        )
    )


def select_supported_relevant_claims(
    question: str, answer: GroundedAnswer, report: GroundingReport
) -> GroundedAnswer | None:
    """Return a cited subset, or None when partial answering is unsafe.

    This selector runs only after the ordinary verifier. It never creates new claims, cites
    partially supported evidence, or recovers a contradicted or model-abstained answer.
    """
    if answer.abstained or report.contradicted:
        return None
    # A single-letter suffix in a name such as Rail-B is not a second subject match.
    question_tokens = _terms(question)
    if not question_tokens:
        return None

    supported_by_claim: dict[str, list[Citation]] = {}
    for citation in report.per_claim:
        if citation.support is SupportLabel.SUPPORTED:
            supported_by_claim.setdefault(citation.claim_id, []).append(citation)

    claims = [
        claim
        for claim in sorted(answer.claims, key=lambda item: item.position)
        if _relevant(claim, question_tokens) and claim.id in supported_by_claim
    ]
    if not claims:
        return None

    citations = [citation for claim in claims for citation in supported_by_claim[claim.id]]
    answer_text = " ".join(
        f"{claim.text} "
        + "".join(
            f"[{citation.evidence_id}]" for citation in citations if citation.claim_id == claim.id
        )
        for claim in claims
    )
    return GroundedAnswer(
        answer_text=answer_text,
        claims=claims,
        citations=citations,
        composer=answer.composer,
    )
