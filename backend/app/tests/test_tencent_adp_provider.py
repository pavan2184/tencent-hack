"""Tencent ADP chat responses follow the documented nested reply envelope."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers.real.tencent_adp_app import TencentAdpAppChatProvider, parse_sse


def test_completed_sse_reply_uses_nested_contents() -> None:
    body = (
        "event: message.done\n"
        'data: {"Type":"message.done","Message":{"Type":"reply",'
        '"Contents":[{"Type":"text","Text":"Hello! How can I help you?"}]}}\n\n'
        "event: response.completed\n"
        'data: {"Type":"response.completed","Response":{"Messages":['
        '{"Type":"reply","Contents":['
        '{"Type":"text","Text":"Hello! How can I help you?"}]}]}}\n\n'
    )

    text, references, error = parse_sse(body)

    assert text == "Hello! How can I help you?"
    assert references == []
    assert error is None


def test_completed_response_ignores_thought_message() -> None:
    body = (
        "event: response.completed\n"
        'data: {"Type":"response.completed","Response":{"Messages":['
        '{"Type":"thought","Contents":[{"Type":"text","Text":"private reasoning"}]},'
        '{"Type":"reply","Contents":[{"Type":"text","Text":"Cited answer"}]}]}}\n\n'
    )

    text, _, error = parse_sse(body)

    assert text == "Cited answer"
    assert error is None


@pytest.mark.asyncio
async def test_non_streaming_response_uses_reply_message(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "Response": {
            "Messages": [
                {"Type": "thought", "Contents": [{"Type": "text", "Text": "private reasoning"}]},
                {"Type": "reply", "Contents": [{"Type": "text", "Text": "Cited answer"}]},
            ]
        }
    }
    original_client = httpx.AsyncClient

    def client_factory(*, timeout: float) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
            timeout=timeout,
        )

    monkeypatch.setattr("app.providers.real.tencent_adp_app.httpx.AsyncClient", client_factory)
    provider = TencentAdpAppChatProvider(Settings(TENCENT_ADP_APP_KEY="test-key"))

    result = await provider.complete([{"role": "user", "content": "Question"}])

    assert result.text == "Cited answer"
