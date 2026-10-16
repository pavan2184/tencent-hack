from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import groundedness
import pytest
from groundedness import (
    ABSTAIN_ANSWER_TEXT,
    SCHEMA_VERSION,
    AbstentionPolicy,
    AnswerComposer,
    Citation,
    Claim,
    DefaultAbstentionPolicy,
    EvidenceSanitizer,
    EvidenceSpan,
    ExtractiveComposer,
    GroundedAnswer,
    GroundingReport,
    InjectionSeverity,
    LexicalOverlapVerifier,
    RegexInjectionSanitizer,
    SanitizedEvidence,
    SupportLabel,
    SupportVerifier,
    Verdict,
    canonical_json,
    report_hash,
)
from pydantic import ValidationError

SRC = Path(__file__).resolve().parents[1] / "src"
CREATED_AT = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
# Pinned so any change to the hash definition or serialization is caught (update deliberately).
GOLDEN_REPORT_HASH = "6bd442b3118336f5966621831d7f4d621ac041fc2bf1e0e303a251b84ac9a0e9"


def _citations() -> list[Citation]:
    return [
        Citation(
            claim_id="C1",
            evidence_id="E1",
            quote="Payments above SGD 10,000 require CFO approval.",
            support=SupportLabel.SUPPORTED,
            score=1.0,
        ),
        Citation(
            claim_id="C2",
            evidence_id="E3",
            quote="Approvals route through finance-ops.",
            support=SupportLabel.PARTIALLY_SUPPORTED,
            score=0.4,
        ),
    ]


def make_report(**overrides: Any) -> GroundingReport:
    fields: dict[str, Any] = {
        "verifier": "lexical-v1",
        "created_at": CREATED_AT,
        "claims_total": 2,
        "supported": 1,
        "partially_supported": 1,
        "unsupported": 0,
        "contradicted": 0,
        "coverage_ratio": 1.0,
        "verdict": Verdict.GROUNDED,
        "injection_flags": 1,
        "quarantined_evidence_ids": ["E2"],
        "per_claim": _citations(),
    }
    fields.update(overrides)
    return GroundingReport(**fields)


# ---------------------------------------------------------------------------- vocabularies


def test_vocabularies_are_exact() -> None:
    assert [m.value for m in SupportLabel] == [
        "supported",
        "partially_supported",
        "unsupported",
        "contradicted",
        "not_checked",
    ]
    assert [m.value for m in Verdict] == [
        "grounded",
        "partially_grounded",
        "ungrounded",
        "abstained",
    ]
    assert [m.value for m in InjectionSeverity] == ["low", "medium", "high"]


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EvidenceSpan(
            id="E1",
            document_id="d",
            source_id="s",
            source_kind="slack",
            slug="x",
            title="t",
            text="body",
            bogus=1,  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        Citation(claim_id="C1", evidence_id="E1", confidence=0.9)  # type: ignore[call-arg]


def test_evidence_span_defaults() -> None:
    span = EvidenceSpan(
        id="E1", document_id="d", source_id="s", source_kind="slack", slug="x", title="t", text="b"
    )
    assert span.chunk_id is None
    assert span.start_offset == 0
    assert span.end_offset is None
    assert span.metadata == {}


def test_citation_defaults_to_not_checked() -> None:
    citation = Citation(claim_id="C1", evidence_id="E1")
    assert citation.support is SupportLabel.NOT_CHECKED
    assert citation.score == 0.0
    assert citation.quote is None


def test_sanitized_evidence_usable(make_span) -> None:
    assert SanitizedEvidence(evidence=make_span("Some text.")).usable
    assert not SanitizedEvidence(evidence=make_span("Some text."), quarantined=True).usable
    assert not SanitizedEvidence(evidence=make_span("   \n")).usable
    assert SanitizedEvidence(evidence=make_span("x", id="E9")).id == "E9"


# ---------------------------------------------------------------------------- GroundedAnswer


def test_grounded_answer_rejects_uncited_claim() -> None:
    with pytest.raises(ValidationError, match="every claim needs at least one citation"):
        GroundedAnswer(
            answer_text="A.",
            claims=[Claim(id="C1", text="A.", position=0)],
            citations=[],
            composer="test",
        )


def test_grounded_answer_rejects_citation_to_unknown_claim() -> None:
    with pytest.raises(ValidationError, match="unknown claim"):
        GroundedAnswer(
            answer_text="A.",
            claims=[Claim(id="C1", text="A.", position=0)],
            citations=[
                Citation(claim_id="C1", evidence_id="E1"),
                Citation(claim_id="C9", evidence_id="E1"),
            ],
            composer="test",
        )


def test_grounded_answer_rejects_duplicate_claim_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        GroundedAnswer(
            answer_text="A. B.",
            claims=[Claim(id="C1", text="A.", position=0), Claim(id="C1", text="B.", position=1)],
            citations=[Citation(claim_id="C1", evidence_id="E1")],
            composer="test",
        )


def test_abstention_helper() -> None:
    answer = GroundedAnswer.abstention("no usable evidence", composer="extractive-v1")
    assert answer.abstained
    assert answer.abstain_reason == "no usable evidence"
    assert answer.answer_text == ABSTAIN_ANSWER_TEXT
    assert answer.claims == [] and answer.citations == []
    assert answer.composer == "extractive-v1"


# ---------------------------------------------------------------------------- report hash


def test_report_hash_is_filled_and_valid() -> None:
    report = make_report()
    assert re.fullmatch(r"[0-9a-f]{64}", report.report_hash)
    assert report.hash_is_valid()
    assert report.report_hash == report.compute_hash() == report_hash(report)


def test_report_hash_definition_is_reproducible_by_hand() -> None:
    report = make_report()
    payload = report.model_dump(mode="json", exclude={"report_hash"})
    payload["created_at"] = "2026-10-12T09:30:00.000000Z"
    assert payload == report.hash_payload()
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert report.report_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_report_hash_is_stable_across_runs() -> None:
    assert make_report().report_hash == make_report().report_hash == GOLDEN_REPORT_HASH


def test_report_hash_independent_of_created_at_representation() -> None:
    utc = make_report()
    singapore = make_report(
        created_at=datetime(2026, 10, 12, 17, 30, tzinfo=timezone(timedelta(hours=8)))
    )
    naive = make_report(created_at=datetime(2026, 10, 12, 9, 30))
    iso_string = make_report(created_at="2026-10-12T09:30:00+00:00")
    assert utc.report_hash == singapore.report_hash == naive.report_hash == iso_string.report_hash
    assert singapore.created_at == CREATED_AT
    assert singapore.created_at.tzinfo is UTC


@pytest.mark.parametrize(
    "overrides",
    [
        {"verifier": "lexical-v2"},
        {"created_at": CREATED_AT + timedelta(microseconds=1)},
        {"schema_version": 2},
        {"coverage_ratio": 0.5},
        {"verdict": Verdict.PARTIALLY_GROUNDED},
        {"supported": 2, "partially_supported": 0},
        {"injection_flags": 2},
        {"quarantined_evidence_ids": []},
        {"quarantined_evidence_ids": ["E2", "E4"]},
        {"per_claim": list(reversed(_citations()))},
        {"per_claim": [_citations()[0].model_copy(update={"score": 0.99}), _citations()[1]]},
        {"per_claim": [_citations()[0].model_copy(update={"quote": "x"}), _citations()[1]]},
    ],
)
def test_report_hash_changes_when_a_field_changes(overrides: dict[str, Any]) -> None:
    assert make_report(**overrides).report_hash != make_report().report_hash


def test_report_hash_survives_json_roundtrip() -> None:
    report = make_report()
    restored = GroundingReport.model_validate_json(report.model_dump_json())
    assert restored == report
    assert restored.report_hash == report.report_hash
    assert restored.hash_is_valid()


def test_report_is_frozen_and_tampering_is_detectable() -> None:
    report = make_report()
    with pytest.raises(ValidationError):
        report.verdict = Verdict.UNGROUNDED  # type: ignore[misc]
    tampered = report.model_copy(update={"verdict": Verdict.UNGROUNDED})
    assert tampered.report_hash == report.report_hash
    assert not tampered.hash_is_valid()


def test_report_keeps_an_explicit_hash() -> None:
    report = make_report(report_hash="0" * 64)
    assert report.report_hash == "0" * 64
    assert not report.hash_is_valid()


def test_report_rejects_counts_that_do_not_sum() -> None:
    with pytest.raises(ValidationError, match="claims_total"):
        make_report(supported=2)


def test_report_schema_version_default() -> None:
    assert make_report().schema_version == SCHEMA_VERSION == groundedness.SCHEMA_VERSION == 1


def test_canonical_json() -> None:
    assert canonical_json({"b": 1, "a": [2, 1], "c": "é"}) == '{"a":[2,1],"b":1,"c":"é"}'
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


# ---------------------------------------------------------------------------- public surface


def test_public_api_is_exported() -> None:
    assert groundedness.__version__ == "0.1.0"
    missing = [name for name in groundedness.__all__ if not hasattr(groundedness, name)]
    assert missing == []


def test_stubs_satisfy_protocols() -> None:
    assert isinstance(RegexInjectionSanitizer(), EvidenceSanitizer)
    assert isinstance(ExtractiveComposer(), AnswerComposer)
    assert isinstance(LexicalOverlapVerifier(), SupportVerifier)
    assert isinstance(DefaultAbstentionPolicy(), AbstentionPolicy)


_APP_IMPORT_LINE = re.compile(r"^\s*(?:import\s+app\b|from\s+app(?:\.|\s))", re.MULTILINE)


def test_no_app_import() -> None:
    """The library must never depend on the app (it is imported *by* the app)."""
    sources = sorted(SRC.rglob("*.py"))
    assert sources, f"no sources under {SRC}"
    offenders: list[str] = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if _APP_IMPORT_LINE.search(text):
            offenders.append(f"{path.relative_to(SRC)} (line match)")
        for node in ast.walk(ast.parse(text, filename=str(path))):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            else:
                continue
            if "app" in roots:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == []
