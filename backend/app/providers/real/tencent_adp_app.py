"""Tencent Cloud ADP application Chat API (HTTP, non-streaming or SSE).

POST `TENCENT_ADP_CHAT_URL` with `{AppKey, ConversationId (32-64 chars), VisitorId,
Contents: [{Type: "text", Text}], Stream: "disable"}`. The response is either one JSON document
or an SSE stream of events (`text.delta`, `message.done`, `reference.added`,
`response.completed`, `error`); both are parsed. Error codes 460011 (QPM) / 460031 (QPS) ->
`RetryableError`; 460032 (balance) -> `FatalError`. ADP apps carry their own system prompt, so
the system message is prepended to the user text.

TODO(integration): confirm the exact non-streaming response shape against the ADP console; the
parser accepts the documented SSE event payloads and a few plausible JSON envelopes.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import ChatProvider, ChatResult, FatalError, RetryableError

RETRYABLE_CODES = {460011, 460031}
FATAL_CODES = {460032}


def _flatten(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        content = str(message.get("content", ""))
        role = message.get("role", "user")
        parts.append(content if role == "user" else f"[{role}]\n{content}")
    return "\n\n".join(parts)


def _error_from(payload: dict[str, Any]) -> Exception | None:
    error = payload.get("error") or payload.get("Error")
    if not error:
        return None
    if isinstance(error, dict):
        code = error.get("code") or error.get("Code")
        message = error.get("message") or error.get("Message") or "ADP error"
    else:
        code, message = None, str(error)
    try:
        numeric = int(code) if code is not None else None
    except (TypeError, ValueError):
        numeric = None
    if numeric in RETRYABLE_CODES:
        return RetryableError(f"ADP {numeric}: {message}")
    return FatalError(f"ADP {code}: {message}")


def _text_of(payload: dict[str, Any]) -> str | None:
    for key in ("text", "Text", "content", "Content", "reply", "Reply"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    for key in (
        "payload",
        "Payload",
        "data",
        "Data",
        "message",
        "Message",
        "Response",
        "contents",
        "Contents",
        "messages",
        "Messages",
    ):
        inner = payload.get(key)
        if isinstance(inner, dict):
            if key in ("message", "Message") and inner.get("Type", inner.get("type")) not in (
                None,
                "reply",
            ):
                continue
            found = _text_of(inner)
            if found is not None:
                return found
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    if (
                        key in ("messages", "Messages")
                        and item.get("Type", item.get("type")) != "reply"
                    ):
                        continue
                    found = _text_of(item)
                    if found is not None:
                        return found
    return None


def parse_sse(body: str) -> tuple[str, list[dict[str, Any]], Exception | None]:
    """Concatenate `text.delta`s (or take `message.done`'s full text); collect references."""
    deltas: list[str] = []
    final: str | None = None
    references: list[dict[str, Any]] = []
    event_name: str | None = None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
            continue
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        kind = str(payload.get("type") or payload.get("Type") or event_name or "")
        if kind == "error":
            return "", references, _error_from(payload) or FatalError("ADP error event")
        if kind == "text.delta":
            deltas.append(_text_of(payload) or "")
        elif kind == "message.done":
            final = _text_of(payload) or final
        elif kind == "response.completed":
            final = _text_of(payload) or final
        elif kind == "reference.added":
            references.append(payload)
    text = final if final is not None else "".join(deltas)
    return text, references, None


class TencentAdpAppChatProvider(ChatProvider):
    name = "tencent-adp-app"

    def __init__(self, settings: Settings) -> None:
        if not settings.TENCENT_ADP_APP_KEY:
            raise FatalError("TENCENT_ADP_APP_KEY is blank; set it or use PROVIDER_MODE=mock")
        self.url = settings.TENCENT_ADP_CHAT_URL
        self.app_key = settings.TENCENT_ADP_APP_KEY
        self.timeout_s = settings.LLM_TIMEOUT_S
        self.visitor_id = "brain-sauce"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ChatResult:
        body = {
            "AppKey": self.app_key,
            "ConversationId": uuid.uuid4().hex,  # 32 chars: one stateless turn per call
            "VisitorId": self.visitor_id,
            "Contents": [{"Type": "text", "Text": _flatten(messages)}],
            "Stream": "disable",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(self.url, json=body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError(f"ADP: transport error: {type(exc).__name__}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableError(f"ADP: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise FatalError(f"ADP: HTTP {response.status_code}: {response.text[:300]}")
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type or response.text.lstrip().startswith(
            ("event:", "data:")
        ):
            text, references, error = parse_sse(response.text)
            if error is not None:
                raise error
            return ChatResult(text=text, raw={"references": references})
        try:
            data = response.json()
        except ValueError as exc:
            raise FatalError("ADP: response is neither SSE nor JSON") from exc
        if not isinstance(data, dict):
            raise FatalError("ADP: unexpected response shape")
        error = _error_from(data) or _error_from(data.get("Response") or {})
        if error is not None:
            raise error
        text = _text_of(data)
        if text is None:
            raise FatalError("ADP: no reply text in response")
        return ChatResult(text=text, raw=data)
