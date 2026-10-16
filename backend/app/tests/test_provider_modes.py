"""Provider selection for a free local retrieval + ADP generation demo."""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.providers.factory import get_chat_provider, get_embedding_provider
from app.providers.mock import MockEmbeddingProvider
from app.providers.real.tencent_adp_app import TencentAdpAppChatProvider


def test_real_adp_can_use_local_vectors_without_remote_embedding_credentials() -> None:
    settings = Settings(
        _env_file=None,
        PROVIDER_MODE="real",
        LLM_PROVIDER="tencent_adp_app",
        TENCENT_ADP_APP_KEY="test-only-key",
        EMBEDDING_PROVIDER="local_hash",
        EMBEDDING_BASE_URL="",
        EMBEDDING_MODEL="",
        EMBEDDING_API_KEY="",
    )

    assert isinstance(get_chat_provider(settings), TencentAdpAppChatProvider)
    embedder = get_embedding_provider(settings)
    assert isinstance(embedder, MockEmbeddingProvider)
    vectors = asyncio.run(embedder.embed(["rail cutover", "rail schedule", "vendor contract"]))
    assert all(len(vector) == 1024 for vector in vectors)
    assert sum(a * b for a, b in zip(vectors[0], vectors[1], strict=True)) > sum(
        a * b for a, b in zip(vectors[0], vectors[2], strict=True)
    )


def test_real_remote_embeddings_still_require_endpoint_and_model() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_BASE_URL"):
        Settings(
            _env_file=None,
            PROVIDER_MODE="real",
            LLM_PROVIDER="tencent_adp_app",
            TENCENT_ADP_APP_KEY="test-only-key",
            EMBEDDING_PROVIDER="openai_compatible",
            EMBEDDING_BASE_URL="",
            EMBEDDING_MODEL="",
        )
