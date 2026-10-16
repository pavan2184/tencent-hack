"""Provider factory: `PROVIDER_MODE=mock|real`, `LLM_PROVIDER=openai_compatible|tencent_adp_app`.

Real implementations are imported lazily and raise at construction when credentials are blank.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.providers.base import ChatProvider, EmbeddingProvider
from app.providers.mock import MockChatProvider, MockEmbeddingProvider


def get_chat_provider(settings: Settings | None = None) -> ChatProvider:
    settings = settings or get_settings()
    if settings.PROVIDER_MODE == "mock":
        return MockChatProvider()
    if settings.LLM_PROVIDER == "tencent_adp_app":
        from app.providers.real.tencent_adp_app import TencentAdpAppChatProvider

        return TencentAdpAppChatProvider(settings)
    from app.providers.real.openai_compatible import OpenAICompatibleChatProvider

    return OpenAICompatibleChatProvider(settings)


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    if settings.PROVIDER_MODE == "mock" or settings.EMBEDDING_PROVIDER == "local_hash":
        return MockEmbeddingProvider(settings.EMBEDDING_DIM)
    from app.providers.real.openai_compatible import OpenAICompatibleEmbeddingProvider

    return OpenAICompatibleEmbeddingProvider(settings)
