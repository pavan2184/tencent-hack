"""Provider ports: chat completion and embeddings, plus the provider error hierarchy.

Real providers live in `app/providers/real/` and are imported lazily by `factory.py`, so mock
mode never needs their dependencies or credentials. Callers map `RetryableError` to a retry
(Celery) or `503 provider_unavailable` (API) and `FatalError` to a hard failure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


class ProviderError(Exception):
    """Base error for every model-provider failure."""

    retryable: bool = False


class RetryableError(ProviderError):
    """Transient: rate limit, timeout, 5xx, transport failure. Safe to retry."""

    retryable = True


class FatalError(ProviderError):
    """Permanent: bad request, auth failure, exhausted balance. Retrying will not help."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class ChatProvider(ABC):
    """Chat completion over OpenAI-style messages (`[{"role": ..., "content": ...}]`)."""

    name: str = "chat"

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ChatResult:
        """One non-streaming completion. Raises `RetryableError` / `FatalError`."""


class EmbeddingProvider(ABC):
    """Text embeddings of a fixed dimension (`dim`, = `settings.EMBEDDING_DIM`)."""

    name: str = "embedding"

    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per input text, each of length `dim`. Raises `ProviderError`."""
