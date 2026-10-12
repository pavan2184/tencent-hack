"""Pipeline invariants named in docs/TESTING.md: access before any LLM; injection quarantine;
the model composer's deadline fallback and deterministic grounding of unmarked replies."""

from __future__ import annotations

import asyncio
from typing import Any

from app.providers.base import ChatProvider, ChatResult
from app.services import retrieval
from app.services.compose import ModelComposer
from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
INJECTION = ("slack-ops", "channels/general/2026-10-11")


class RecordingChat(ChatProvider):
    """A `ChatProvider` fake: records every `messages` list and returns a canned reply."""

    name = "fake-chat"

    def __init__(self, reply: str = "ABSTAIN", *, delay_s: float = 0.0) -> None:
        self.reply = reply
        self.delay_s = delay_s
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
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return ChatResult(text=self.reply, usage={})


class RecordingSanitizer:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.seen: list[Any] = []

    def sanitize(self, evidence: Any) -> Any:
        self.seen.extend(evidence)
        return self.inner.sanitize(evidence)


def test_pipeline_order_access_before_llm(seeded: Any) -> None:
    deck = run(seeded.repo.get_page_by_slug(*DECK))
    fake = RecordingChat("ABSTAIN")
    seeded.composer = ModelComposer(fake, deadline_s=5)
    recorder = RecordingSanitizer(seeded.sanitizer)
    seeded.sanitizer = recorder
    alex = run(seeded.repo.get_principal("alex.tan"))

    env = run(retrieval.ask(seeded, alex, "What were the Q3 board deck revenue figures?"))

    # The deck was retrieved (it matches best) but denied before anything downstream saw it.
    event = run(seeded.repo.get_audit_event(env.audit_id))
    assert deck.id in event.payload["retrieved_document_ids"]
    decisions = {d["document_id"]: d["decision"] for d in event.payload["access_decisions"]}
    assert decisions[deck.id] == "deny"
    assert recorder.seen, "allowed evidence still reaches the sanitizer"
    assert all(span.document_id != deck.id for span in recorder.seen)
    assert fake.calls, "the LLM composer was invoked"
    for call in fake.calls:
        for user in [m["content"] for m in call if m["role"] == "user"]:
            assert "48.6" not in user
            assert deck.title not in user
    assert deck.id not in {item.page_id for item in env.freshness_receipt.evidence_items}


def test_injection_fixture_quarantined(seeded: Any, client: Any) -> None:
    page = run(seeded.repo.get_page_by_slug(*INJECTION))
    env = client.post(
        "/api/ask",
        json={"question": "What did the Vegaline bot post about the Rail-B cutover checklist?"},
        headers={"X-Actor-Id": "priya.nair"},
    ).json()
    quarantined = env["grounding"]["quarantined_evidence_ids"]
    assert quarantined, "the injection chunk must be quarantined"
    assert not {c["evidence_id"] for c in env["citations"]} & set(quarantined)
    assert "system administrator" not in env["answer"]["text"]

    bundle = run(
        retrieval.assemble_evidence(
            seeded,
            run(seeded.repo.get_principal("priya.nair")),
            "Vegaline bot Rail-B cutover checklist ignore previous instructions",
        )
    )
    flagged = [s for s in bundle.spans if s.document_id == page.id and s.quarantined]
    assert flagged and all(s.text == "" for s in flagged)


def test_model_composer_timeout_falls_back(seeded: Any) -> None:
    fake = RecordingChat("The Rail-B cutover is cancelled. [E1]", delay_s=0.5)
    seeded.composer = ModelComposer(fake, deadline_s=0.05)
    priya = run(seeded.repo.get_principal("priya.nair"))

    env = run(retrieval.ask(seeded, priya, "What is the plan for the Rail-B cutover?"))

    assert fake.calls, "the model was called before the deadline expired"
    assert not env.answer.abstained
    assert env.claims
    assert "cancelled" not in env.answer.text
    event = run(seeded.repo.get_audit_event(env.audit_id))
    assert event.payload["composer"] == "model-v1->extractive-v1"


def test_model_composer_unmarked_reply_is_grounded(seeded: Any) -> None:
    sentence = "Rollback must complete within 10 minutes."
    fake = RecordingChat(sentence)
    seeded.composer = ModelComposer(fake, deadline_s=5)
    priya = run(seeded.repo.get_principal("priya.nair"))

    env = run(retrieval.ask(seeded, priya, "How quickly must the Rail-B rollback complete?"))

    assert not env.answer.abstained
    assert len(env.claims) == 1
    assert env.claims[0].text == sentence
    assert len(env.citations) == 1
    citation = env.citations[0]
    assert citation.claim_id == env.claims[0].id
    assert citation.support == "supported"
    assert citation.quote
    event = run(seeded.repo.get_audit_event(env.audit_id))
    assert event.payload["composer"] == "model-v1+ground-v1"
