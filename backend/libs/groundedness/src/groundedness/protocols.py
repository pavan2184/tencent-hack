"""Ports of the groundedness library and its errors.

The app implements :class:`LLMPort` (``app/adapters/llm_port.py``); the library ships stub
implementations of the other four. Every Protocol is ``runtime_checkable`` so the app's wiring can
``assert isinstance(x, SupportVerifier)``. Each method docstring states the invariant an
implementation must guarantee; the stub tests check those invariants, and a replacement
implementation must pass the same tests.

Call order inside the app (``services/retrieval.py``) is fixed:
``sanitize -> compose -> verify -> should_abstain``.
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


class GroundednessProviderError(GroundednessError):
    """The model behind an ``LLMPort`` failed (transport, quota, timeout, bad response).

    ``LLMPort`` implementations raise this, and only this, for provider failures, so composers
    can decide between propagating (app maps it to ``503 provider_unavailable``) and falling back.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class LLMPort(Protocol):
    """Minimal chat-completion port the composers and verifiers depend on."""

    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        """Return the model's text reply to one system + user turn.

        Invariants: stateless (no conversation memory between calls); raises
        :class:`GroundednessProviderError` on any provider failure and never returns ``None``.
        """
        ...


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
        llm: LLMPort | None = None,
        max_claims: int = 8,
    ) -> GroundedAnswer:
        """Compose an answer of at most ``max_claims`` claims.

        Invariants: every claim has >= 1 citation, and every citation points at evidence in
        ``evidence`` that is not quarantined; quarantined evidence never reaches the model; no
        usable evidence -> ``abstained=True`` with a reason (never a guess); deterministic when
        ``llm`` is ``None`` or deterministic itself.
        """
        ...


@runtime_checkable
class SupportVerifier(Protocol):
    """Checks every citation of an answer against the evidence it points at."""

    async def verify(
        self,
        answer: GroundedAnswer,
        evidence: Sequence[SanitizedEvidence],
        *,
        llm: LLMPort | None = None,
    ) -> GroundingReport:
        """Label every citation and summarize the answer.

        Invariants: a citation into quarantined, missing, or empty evidence is never
        ``supported`` (it is ``unsupported``); ``supported`` is only given against text that is
        actually in the evidence; label counts sum to ``claims_total``; deterministic when
        ``llm`` is ``None`` (given the same clock).
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
