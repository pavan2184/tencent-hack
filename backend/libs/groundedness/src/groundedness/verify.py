"""Support verification: label every citation, then summarize into a ``GroundingReport``.

* :class:`LexicalOverlapVerifier` (``lexical-v2``): deterministic, model-free token Jaccard with a
  negation heuristic for contradictions and a numeric/date gate (no LLM judge).
* :func:`build_grounding_report`: the shared summarizer (counts, coverage, verdict, hash) any
  verifier calls once its citations are labelled.

Safety rules applied before any scoring (invariant: no ``supported`` without evidence text):
a citation into missing, empty, or quarantined evidence is ``unsupported`` with ``quote=None``;
a quote that does not literally occur in the evidence text is ignored and replaced by the
evidence's best-matching sentence. Every ``quote`` in a report is therefore verbatim evidence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime

from groundedness.compose import (
    best_matching_sentence,
    content_tokens,
    has_negation,
    jaccard,
    require_unique_ids,
)
from groundedness.models import (
    Citation,
    Claim,
    GroundedAnswer,
    GroundingReport,
    SanitizedEvidence,
    SupportLabel,
    Verdict,
)
from groundedness.numeric import unsupported_numeric_facts

LEXICAL_VERIFIER_ID = "lexical-v2"

Clock = Callable[[], datetime]

_COVERING = frozenset({SupportLabel.SUPPORTED, SupportLabel.PARTIALLY_SUPPORTED})


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def quote_in_text(quote: str, text: str) -> bool:
    """True when ``quote`` occurs in ``text`` (case- and whitespace-insensitive)."""
    needle = _normalized(quote)
    return bool(needle) and needle in _normalized(text)


def claim_label(labels: Iterable[SupportLabel]) -> SupportLabel:
    """Claim-level label from its citations' labels.

    ``contradicted`` if any citation is contradicted, else ``supported`` if any is, else
    ``partially_supported`` if any is, else ``unsupported`` (also for no citations).
    """
    present = set(labels)
    for label in (
        SupportLabel.CONTRADICTED,
        SupportLabel.SUPPORTED,
        SupportLabel.PARTIALLY_SUPPORTED,
    ):
        if label in present:
            return label
    return SupportLabel.UNSUPPORTED


def build_grounding_report(
    answer: GroundedAnswer,
    evidence: Sequence[SanitizedEvidence],
    citations: Sequence[Citation],
    *,
    verifier: str,
    created_at: datetime,
) -> GroundingReport:
    """Summarize labelled ``citations`` for ``answer`` into a hashed ``GroundingReport``.

    * counts: one :func:`claim_label` per claim, so the four counts sum to ``claims_total``;
    * ``coverage_ratio`` = claims with >= 1 supported/partially_supported citation /
      ``claims_total``, rounded to 4 places; with zero claims it is 1.0 if the answer abstained,
      else 0.0;
    * verdict: ``abstained`` if the answer abstained; else ``grounded`` if every claim is covered
      and none is contradicted; else ``partially_grounded`` if any claim is covered; else
      ``ungrounded``;
    * ``per_claim``: the labelled citations ordered by claim position, then input order;
    * ``injection_flags`` / ``quarantined_evidence_ids`` summarize ``evidence`` in input order.
    """
    ordered_claims: list[Claim] = sorted(answer.claims, key=lambda claim: claim.position)
    by_claim: dict[str, list[Citation]] = {claim.id: [] for claim in ordered_claims}
    for citation in citations:
        if citation.claim_id in by_claim:
            by_claim[citation.claim_id].append(citation)

    counts: Counter[SupportLabel] = Counter()
    covered = 0
    for claim_citations in by_claim.values():
        labels = {citation.support for citation in claim_citations}
        counts[claim_label(labels)] += 1
        if labels & _COVERING:
            covered += 1

    total = len(ordered_claims)
    if total == 0:
        coverage = 1.0 if answer.abstained else 0.0
    else:
        coverage = round(covered / total, 4)

    if answer.abstained:
        verdict = Verdict.ABSTAINED
    elif total > 0 and covered == total and counts[SupportLabel.CONTRADICTED] == 0:
        verdict = Verdict.GROUNDED
    elif covered > 0:
        verdict = Verdict.PARTIALLY_GROUNDED
    else:
        verdict = Verdict.UNGROUNDED

    return GroundingReport(
        verifier=verifier,
        created_at=created_at,
        claims_total=total,
        supported=counts[SupportLabel.SUPPORTED],
        partially_supported=counts[SupportLabel.PARTIALLY_SUPPORTED],
        unsupported=counts[SupportLabel.UNSUPPORTED],
        contradicted=counts[SupportLabel.CONTRADICTED],
        coverage_ratio=coverage,
        verdict=verdict,
        injection_flags=sum(len(item.flags) for item in evidence),
        quarantined_evidence_ids=[item.id for item in evidence if item.quarantined],
        per_claim=[citation for group in by_claim.values() for citation in group],
    )


class LexicalOverlapVerifier:
    """Deterministic, model-free ``SupportVerifier`` using content-token Jaccard.

    Per citation, after the safety rules in the module docstring, ``score`` = Jaccard between the
    claim and the reference text (the quote if it occurs in the evidence, else the evidence's
    best-matching sentence). Then:

    * ``score >= partial_threshold`` and exactly one side contains a negation cue
      (not/no/never/cannot/without/none/nor/neither or an ``n't`` contraction) -> ``contradicted``;
    * ``score >= supported_threshold`` (0.6) -> ``supported``;
    * ``score >= partial_threshold`` (0.3) -> ``partially_supported``;
    * otherwise -> ``unsupported``.

    Numeric gate: a ``supported``/``partially_supported`` citation is demoted to ``unsupported``
    when the claim mentions a number, percentage, date or time that the *whole* cited evidence
    text does not (see :func:`groundedness.numeric.unsupported_numeric_facts`; a claim that occurs
    verbatim in the evidence always passes). ``score`` and ``quote`` are kept so the audit shows
    the overlap and the evidence's real value. A wrong number is never ``contradicted``: there is
    no unit or entity alignment lexically.

    Pass ``clock`` to pin ``created_at`` (and therefore ``report_hash``).
    """

    verifier_id = LEXICAL_VERIFIER_ID

    def __init__(
        self,
        *,
        supported_threshold: float = 0.6,
        partial_threshold: float = 0.3,
        clock: Clock | None = None,
    ) -> None:
        if not 0.0 < partial_threshold <= supported_threshold <= 1.0:
            raise ValueError("require 0 < partial_threshold <= supported_threshold <= 1")
        self.supported_threshold = supported_threshold
        self.partial_threshold = partial_threshold
        self.clock: Clock = clock or utc_now

    async def verify(
        self, answer: GroundedAnswer, evidence: Sequence[SanitizedEvidence]
    ) -> GroundingReport:
        return self.verify_sync(answer, evidence)

    def verify_sync(
        self, answer: GroundedAnswer, evidence: Sequence[SanitizedEvidence]
    ) -> GroundingReport:
        require_unique_ids(evidence)
        by_id = {item.id: item for item in evidence}
        claim_text = {claim.id: claim.text for claim in answer.claims}
        labelled = [
            self.check_citation(claim_text[citation.claim_id], citation, by_id)
            for citation in answer.citations
        ]
        return build_grounding_report(
            answer, evidence, labelled, verifier=self.verifier_id, created_at=self.clock()
        )

    def check_citation(
        self,
        claim: str,
        citation: Citation,
        evidence_by_id: dict[str, SanitizedEvidence],
    ) -> Citation:
        """Return a copy of ``citation`` with ``support``, ``score``, and a verbatim ``quote``."""
        item = evidence_by_id.get(citation.evidence_id)
        if item is None or not item.usable:
            return _labelled(citation, SupportLabel.UNSUPPORTED, 0.0, None)
        text = item.evidence.text
        reference: str | None
        if citation.quote and quote_in_text(citation.quote, text):
            reference = citation.quote
            score = jaccard(content_tokens(claim), content_tokens(reference))
        else:
            reference, score = best_matching_sentence(claim, text)
        if reference is None:
            return _labelled(citation, SupportLabel.UNSUPPORTED, 0.0, None)
        support = self.label(claim, reference, score)
        if support in _COVERING and unsupported_numeric_facts(claim, text):
            support = SupportLabel.UNSUPPORTED
        return _labelled(citation, support, score, reference)

    def label(self, claim: str, reference: str, score: float) -> SupportLabel:
        if score >= self.partial_threshold and has_negation(claim) != has_negation(reference):
            return SupportLabel.CONTRADICTED
        if score >= self.supported_threshold:
            return SupportLabel.SUPPORTED
        if score >= self.partial_threshold:
            return SupportLabel.PARTIALLY_SUPPORTED
        return SupportLabel.UNSUPPORTED


def _labelled(
    citation: Citation, support: SupportLabel, score: float, quote: str | None
) -> Citation:
    update = {"support": support, "score": round(score, 4), "quote": quote}
    return citation.model_copy(update=update)
