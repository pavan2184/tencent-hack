"""Ports of the groundedness library and its base error.

The library ships a deterministic, model-free implementation of every port and never calls a
model. Every Protocol is ``runtime_checkable`` so the app's wiring can
``assert isinstance(x, SupportVerifier)``. Each method docstring states the invariant an
implementation must guarantee; the stub tests check those invariants, and a replacement
implementation must pass the same tests.

Call order inside the app (``services/retrieval.py``) is fixed:
``sanitize -> compose -> verify -> should_abstain``. An app composer that calls a model turns
the generated text into a cited answer with :func:`groundedness.ground`
(``sanitize -> ground -> verify -> should_abstain``); generation is the app's.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from groundedness.models import (
    EvidenceSpan,
    GroundedAnswer,
    GroundingReport,
    SanitizedEvidence,
)


class GroundednessError(Exception):
    """Base class for every error raised by the groundedness library."""


@runtime_checkable
class EvidenceSanitizer(Protocol):
    """Screens retrieved evidence for prompt injection before any model sees it."""

    def sanitize(self, evidence: Sequence[EvidenceSpan]) -> list[SanitizedEvidence]:
        """Screen every span.

        Invariants: never drops an item; output length and order equal the input's; a
        high-severity match sets ``quarantined=True`` and leaves the text intact; low/medium
        matches are removed and set ``was_modified=True``; text with no match is returned
        byte-identical; inputs are not mutated; deterministic.
        """
        ...


@runtime_checkable
class AnswerComposer(Protocol):
    """Turns a question plus sanitized evidence into a cited answer."""

    async def compose(
        self,
        question: str,
        evidence: Sequence[SanitizedEvidence],
        *,
        max_claims: int = 8,
    ) -> GroundedAnswer:
        """Compose an answer of at most ``max_claims`` claims.

        Invariants: every claim has >= 1 citation, and every citation points at evidence in
        ``evidence`` that is not quarantined; quarantined evidence never reaches a model; no
        usable evidence -> ``abstained=True`` with a reason (never a guess); the grounding of
        any generated text is deterministic.
        """
        ...


@runtime_checkable
class SupportVerifier(Protocol):
    """Checks every citation of an answer against the evidence it points at."""

    async def verify(
        self,
        answer: GroundedAnswer,
        evidence: Sequence[SanitizedEvidence],
    ) -> GroundingReport:
        """Label every citation and summarize the answer.

        Invariants: a citation into quarantined, missing, or empty evidence is never
        ``supported`` (it is ``unsupported``); ``supported`` is only given against text that is
        actually in the evidence; label counts sum to ``claims_total``; deterministic (given the
        same clock), with no model call.
        """
        ...


@runtime_checkable
class AbstentionPolicy(Protocol):
    """Final gate: decides whether a verified answer may be shown."""

    def should_abstain(
        self, report: GroundingReport, *, min_coverage: float
    ) -> tuple[bool, str | None]:
        """Return ``(True, reason)`` to withhold the answer, ``(False, None)`` to show it.

        Invariants: abstains when there are no claims, when any claim is contradicted, or when
        coverage is below ``min_coverage``; the reason never quotes evidence text; pure.
        """
        ...
