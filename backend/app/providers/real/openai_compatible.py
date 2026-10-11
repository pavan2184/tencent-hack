"""OpenAI-compatible chat + embeddings over httpx (Tencent LKEAP `deepseek-v3` by default).

POST `{LLM_BASE_URL}/chat/completions` and `{EMBEDDING_BASE_URL}/embeddings` with a Bearer key.
429/5xx/transport errors -> `RetryableError`; other 4xx and malformed bodies -> `FatalError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import (
    ChatProvider,
    ChatResult,
    EmbeddingProvider,
    FatalError,
    RetryableError,
)


def _raise_for_status(response: httpx.Response, what: str) -> None:
    status = response.status_code
    if status < 400:
        return
    snippet = response.text[:300]
    if status == 429 or status >= 500:
        raise RetryableError(f"{what}: HTTP {status}: {snippet}")
    raise FatalError(f"{what}: HTTP {status}: {snippet}")


async def _post_json(
    url: str, *, api_key: str, body: dict[str, Any], timeout_s: float, what: str
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url, json=body, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise RetryableError(f"{what}: transport error: {type(exc).__name__}") from exc
    _raise_for_status(response, what)
    try:
        data = response.json()
    except ValueError as exc:
        raise FatalError(f"{what}: response is not JSON") from exc
    if not isinstance(data, dict):
        raise FatalError(f"{what}: unexpected response shape")
    return data


class OpenAICompatibleChatProvider(ChatProvider):
    name = "openai-compatible-chat"

    def __init__(self, settings: Settings) -> None:
        if not settings.LLM_API_KEY:
            raise FatalError("LLM_API_KEY is blank; set it or use PROVIDER_MODE=mock")
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.timeout_s = settings.LLM_TIMEOUT_S

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = await _post_json(
            f"{self.base_url}/chat/completions",
            api_key=self.api_key,
            body=body,
            timeout_s=self.timeout_s,
            what="chat.completions",
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise FatalError("chat.completions: missing choices[0].message.content") from exc
        return ChatResult(text=str(text), usage=dict(data.get("usage") or {}), raw=data)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    name = "openai-compatible-embedding"

    def __init__(self, settings: Settings) -> None:
        if not settings.EMBEDDING_BASE_URL or not settings.EMBEDDING_MODEL:
            raise FatalError("EMBEDDING_BASE_URL/EMBEDDING_MODEL are blank")
        self.api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        if not self.api_key:
            raise FatalError("EMBEDDING_API_KEY (or LLM_API_KEY) is blank")
        self.base_url = settings.EMBEDDING_BASE_URL.rstrip("/")
        self.model = settings.EMBEDDING_MODEL
        self.timeout_s = settings.LLM_TIMEOUT_S
        self._dim = settings.EMBEDDING_DIM

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        data = await _post_json(
            f"{self.base_url}/embeddings",
            api_key=self.api_key,
            body={"model": self.model, "input": list(texts)},
            timeout_s=self.timeout_s,
            what="embeddings",
        )
        try:
            rows = sorted(data["data"], key=lambda row: row.get("index", 0))
            vectors = [list(map(float, row["embedding"])) for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise FatalError("embeddings: malformed data[]") from exc
        if len(vectors) != len(texts):
            raise FatalError(f"embeddings: expected {len(texts)} vectors, got {len(vectors)}")
        for vector in vectors:
            if len(vector) != self._dim:
                raise FatalError(
                    f"embeddings: got dimension {len(vector)}, EMBEDDING_DIM is {self._dim}"
                )
        return vectors
