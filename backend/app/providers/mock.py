"""Deterministic offline providers (the default, `PROVIDER_MODE=mock`).

`MockEmbeddingProvider` sums seeded per-token unit vectors and normalises the result, so texts
that share tokens have a higher cosine similarity than texts that do not; this keeps hybrid
search meaningful offline. `MockChatProvider` answers extractively: it echoes the first sentence
of the first `[E#]` evidence line in the prompt with its marker, or `ABSTAIN`.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.providers.base import ChatProvider, ChatResult, EmbeddingProvider

_TOKEN = re.compile(r"[a-z0-9]+")
_EVIDENCE_LINE = re.compile(r"^\[(E\d+)\]\s*(?:.*?\s—\s)?(.+)$", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@lru_cache(maxsize=50_000)
def _token_vector(token: str, dim: int) -> tuple[float, ...]:
    seed = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return tuple(v / norm for v in vec)


class MockEmbeddingProvider(EmbeddingProvider):
    name = "mock-embedding"

    def __init__(self, dim: int = 1024) -> None:
        if dim <= 0:
            raise ValueError("dim must be > 0")
        self._dim = dim
        self.calls = 0

    @property
    def dim(self) -> int:
        return self._dim

    def embed_one(self, text: str) -> list[float]:
        acc = [0.0] * self._dim
        for token in set(tokens(text)):
            for i, v in enumerate(_token_vector(token, self._dim)):
                acc[i] += v
        norm = math.sqrt(sum(v * v for v in acc))
        if norm == 0.0:
            return acc
        return [v / norm for v in acc]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [self.embed_one(t) for t in texts]


class MockChatProvider(ChatProvider):
    name = "mock-chat"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ChatResult:
        self.calls.append(messages)
        user = next(
            (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"), ""
        )
        match = _EVIDENCE_LINE.search(user)
        if match is None:
            text = "ABSTAIN"
        else:
            label, body = match.group(1), match.group(2).strip()
            sentence = _SENTENCE_END.split(body, maxsplit=1)[0].strip()
            text = f"{sentence} [{label}]" if sentence else "ABSTAIN"
        usage = {"prompt_tokens": len(tokens(user)), "completion_tokens": len(tokens(text))}
        return ChatResult(text=text, usage=usage)
