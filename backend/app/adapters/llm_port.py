"""Adapts an `app.providers.ChatProvider` to the groundedness library's `LLMPort`.

Provider errors become `GroundednessProviderError` (with `retryable`), which is the only error
the groundedness composers/verifiers expect from a port.
"""

from __future__ import annotations

from groundedness import GroundednessProviderError

from app.providers.base import ChatProvider, ProviderError


class ChatProviderLLMPort:
    """`groundedness.LLMPort` over a `ChatProvider` (one system + one user turn, stateless)."""

    def __init__(self, chat: ChatProvider) -> None:
        self.chat = chat

    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            result = await self.chat.complete(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        except ProviderError as exc:
            raise GroundednessProviderError(str(exc), retryable=exc.retryable) from exc
        except Exception as exc:  # any other provider bug is still a provider failure
            raise GroundednessProviderError(f"{type(exc).__name__}: {exc}") from exc
        return result.text or ""
