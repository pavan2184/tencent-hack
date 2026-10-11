"""Pipeline invariants named in docs/TESTING.md: access before any LLM; injection quarantine."""

from __future__ import annotations

from typing import Any

from groundedness import FakeLLM, LLMComposer

from app.services import retrieval
from app.tests.conftest import run

DECK = ("gdrive-finance", "files/board-deck-q3")
INJECTION = ("slack-ops", "channels/general/2026-10-11")


class RecordingSanitizer:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.seen: list[Any] = []

    def sanitize(self, evidence: Any) -> Any:
        self.seen.extend(evidence)
        return self.inner.sanitize(evidence)


def test_pipeline_order_access_before_llm(seeded: Any) -> None:
    deck = run(seeded.repo.get_page_by_slug(*DECK))
    fake = FakeLLM(default="ABSTAIN")
    seeded.llm_port = fake
    seeded.composer = LLMComposer(fake, fallback="extractive")
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
        assert "48.6" not in call.user
        assert deck.title not in call.user
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
