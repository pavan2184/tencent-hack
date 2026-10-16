"""Answer generation for the ask path: one model call, then deterministic grounding.

`ModelComposer` implements `groundedness.AnswerComposer`. It is the only place on the ask path
that calls a model, and it runs strictly after `access_control.filter`, freshness and the
sanitizer (the caller only hands it allowed, sanitized evidence; `build_composer_prompt` never
lists quarantined items). The reply is attached to evidence by `groundedness.ground`, which is
pure Python, so the verifier and abstention policy see the same shape whatever the model wrote.

The model call has a total wall-clock deadline (`ASK_GENERATION_DEADLINE_S`). On timeout or any
provider failure the extractive composer answers instead; the composer id records it
(`model-v1->extractive-v1`) and the reason is logged with the request id, never audited
verbatim.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from groundedness import (
    REASON_NO_USABLE_EVIDENCE,
    ExtractiveComposer,
    GroundedAnswer,
    SanitizedEvidence,
    build_composer_prompt,
    evidence_labels,
    ground,
)

from app.core.context import get_request_id
from app.providers.base import ChatProvider, ProviderError

logger = logging.getLogger(__name__)

MODEL_COMPOSER_ID = "model-v1"
_MAX_REASON_CHARS = 300


class ModelComposer:
    """`groundedness.AnswerComposer` that generates with the app's ChatProvider, then grounds
    deterministically."""

    composer_id = MODEL_COMPOSER_ID

    def __init__(
        self,
        chat: ChatProvider,
        *,
        deadline_s: float,
        fallback: ExtractiveComposer | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> None:
        if deadline_s <= 0:
            raise ValueError("deadline_s must be > 0")
        self.chat = chat
        self.deadline_s = deadline_s
        self.fallback = fallback or ExtractiveComposer()
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def compose(
        self,
        question: str,
        evidence: Sequence[SanitizedEvidence],
        *,
        max_claims: int = 8,
    ) -> GroundedAnswer:
        if not evidence_labels(evidence):
            return GroundedAnswer.abstention(REASON_NO_USABLE_EVIDENCE, composer=MODEL_COMPOSER_ID)
        system, user = build_composer_prompt(question, evidence, max_claims=max_claims)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            async with asyncio.timeout(self.deadline_s):
                result = await self.chat.complete(
                    messages, temperature=self.temperature, max_tokens=self.max_tokens
                )
        except Exception as exc:  # noqa: BLE001 - any generation failure -> extractive answer
            return self._fall_back(question, evidence, max_claims, _reason(exc, self.deadline_s))
        return ground(
            result.text or "", evidence, max_claims=max_claims, generator=MODEL_COMPOSER_ID
        )

    def _fall_back(
        self,
        question: str,
        evidence: Sequence[SanitizedEvidence],
        max_claims: int,
        reason: str,
    ) -> GroundedAnswer:
        answer = self.fallback.compose_sync(question, evidence, max_claims=max_claims)
        composer = f"{MODEL_COMPOSER_ID}->{answer.composer}"
        logger.warning(
            "model generation failed; answered by %s (request_id=%s, reason=%s)",
            answer.composer,
            get_request_id(),
            reason,
            extra={"composer": composer, "fallback_reason": reason},
        )
        return answer.model_copy(update={"composer": composer})


def _reason(exc: Exception, deadline_s: float) -> str:
    if isinstance(exc, TimeoutError):
        return f"generation deadline of {deadline_s:g}s exceeded"
    kind = "provider error" if isinstance(exc, ProviderError) else "unexpected error"
    detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return f"{kind}: {detail}"[:_MAX_REASON_CHARS]
