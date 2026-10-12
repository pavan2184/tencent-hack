"""Model providers behind one abstraction: chat completion and embeddings (mock | real)."""

from app.providers.base import (
    ChatProvider,
    ChatResult,
    EmbeddingProvider,
    FatalError,
    ProviderError,
    RetryableError,
)
from app.providers.factory import get_chat_provider, get_embedding_provider

__all__ = [
    "ChatProvider",
    "ChatResult",
    "EmbeddingProvider",
    "FatalError",
    "ProviderError",
    "RetryableError",
    "get_chat_provider",
    "get_embedding_provider",
]
