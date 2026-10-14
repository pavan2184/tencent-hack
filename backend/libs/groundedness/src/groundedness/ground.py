"""``ground(text, evidence)``: attach generated text to the evidence that supports it.

Deterministic and model-free. The app generates text however it likes (a model behind a
deadline, a template, a human); :func:`ground` turns it into a :class:`GroundedAnswer` whose every
sentence is a claim with at least one citation into usable evidence, ready for
:class:`groundedness.LexicalOverlapVerifier`:

1. no usable evidence -> abstention; blank text (or nothing but markers) -> abstention; text that
   starts with the ``ABSTAIN`` sentinel -> abstention;
2. the text is split into sentences (:func:`groundedness.parse_marked_answer` with
   ``keep_unmarked=True``); the first ``max_claims`` become claims ``C1..Cn``;
3. a sentence carrying ``[E#]`` markers is cited to each labelled evidence item, quoting that
   item's best-matching sentence;
4. an unmarked sentence is auto-cited to the usable evidence item whose best-matching sentence
   scores highest (ties -> earliest item); when no item shares a content token it is cited to the
   first usable item with ``quote=None``, and the verifier labels it ``unsupported``.

The text is never edited and no sentence is dropped: an ungroundable sentence lowers coverage
instead of being trimmed away, so the abstention policy decides on the whole answer.
"""

from __future__ import annotations

from collections.abc import Sequence

from groundedness.compose import (
    REASON_EMPTY_TEXT,
    REASON_MODEL_ABSTAINED,
    REASON_NO_USABLE_EVIDENCE,
    _answer_text,
    _require_max_claims,
    best_matching_sentence,
    evidence_labels,
    is_abstain_reply,
    parse_marked_answer,
    require_unique_ids,
)
from groundedness.models import Citation, Claim, GroundedAnswer, SanitizedEvidence

GROUND_ID = "ground-v1"


def ground(
    text: str,
    evidence: Sequence[SanitizedEvidence],
    *,
    max_claims: int = 8,
    generator: str = "external",
) -> GroundedAnswer:
    """Turn generated ``text`` into a cited answer over ``evidence`` (see the module docstring).

    ``evidence`` is the sanitized list the generation prompt was built from, in the same order
    (``E1`` = first item; quarantined items keep their position but are never cited).
    ``generator`` names the text's producer; the answer's ``composer`` reads
    ``"<generator>+ground-v1"`` so the audit shows both.
    """
    require_unique_ids(evidence)
    _require_max_claims(max_claims)
    composer = f"{generator}+{GROUND_ID}"
    labels = evidence_labels(evidence)
    if not labels:
        return GroundedAnswer.abstention(REASON_NO_USABLE_EVIDENCE, composer=composer)
    if not text.strip():
        return GroundedAnswer.abstention(REASON_EMPTY_TEXT, composer=composer)
    if is_abstain_reply(text):
        return GroundedAnswer.abstention(REASON_MODEL_ABSTAINED, composer=composer)
    sentences = parse_marked_answer(text, labels.keys(), keep_unmarked=True)[:max_claims]
    if not sentences:
        return GroundedAnswer.abstention(REASON_EMPTY_TEXT, composer=composer)

    usable = list(labels.values())
    claims: list[Claim] = []
    citations: list[Citation] = []
    for position, (sentence, sentence_labels) in enumerate(sentences):
        claim = Claim(id=f"C{position + 1}", text=sentence, position=position)
        claims.append(claim)
        if sentence_labels:
            for label in sentence_labels:
                cited = labels[label].evidence
                quote, _ = best_matching_sentence(sentence, cited.text)
                citations.append(Citation(claim_id=claim.id, evidence_id=cited.id, quote=quote))
        else:
            citations.append(_auto_cite(claim, usable))
    return GroundedAnswer(
        answer_text=_answer_text(claims, citations),
        claims=claims,
        citations=citations,
        composer=composer,
    )


def _auto_cite(claim: Claim, usable: Sequence[SanitizedEvidence]) -> Citation:
    """Cite the usable item whose best sentence overlaps ``claim`` most (ties -> earliest);
    with no overlap anywhere, the first usable item with no quote."""
    best_item = usable[0]
    best_quote: str | None = None
    best_score = 0.0
    for item in usable:
        quote, score = best_matching_sentence(claim.text, item.evidence.text)
        if score > best_score:
            best_item, best_quote, best_score = item, quote, score
    return Citation(claim_id=claim.id, evidence_id=best_item.id, quote=best_quote)
