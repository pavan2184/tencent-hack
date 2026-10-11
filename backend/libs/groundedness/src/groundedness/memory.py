"""In-memory test doubles, used by this library's tests and by the app's conftest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LLMCall:
    """One recorded ``FakeLLM.complete`` call."""

    system: str
    user: str
    temperature: float
    max_tokens: int


class FakeLLM:
    """Scripted ``LLMPort``.

    ``complete`` returns the reply of the first ``script`` key (insertion order) that is a
    substring of the user prompt, else ``default``. Every call is appended to ``calls``. If
    ``error`` is set, it is raised after the call is recorded (to simulate provider failures).
    """

    def __init__(
        self,
        script: Mapping[str, str] | None = None,
        default: str = "ABSTAIN",
        *,
        error: Exception | None = None,
    ) -> None:
        self.script: dict[str, str] = dict(script or {})
        self.default = default
        self.error = error
        self.calls: list[LLMCall] = []

    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(
            LLMCall(system=system, user=user, temperature=temperature, max_tokens=max_tokens)
        )
        if self.error is not None:
            raise self.error
        for key, reply in self.script.items():
            if key in user:
                return reply
        return self.default
