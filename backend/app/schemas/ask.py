"""Ask / search / evidence schemas: the `AnswerEnvelope` and friends (docs/API_CONTRACT.md)."""

from __future__ import annotations

from typing import Any

from access_control import AccessSummary
from freshness import FreshnessReceipt
from groundedness import Claim, GroundingReport, SupportLabel
from pydantic import BaseModel, ConfigDict, Field

ENVELOPE_SCHEMA_VERSION = 1


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    require_fresh: bool = False


class AnswerOut(BaseModel):
    text: str
    abstained: bool
    abstain_reason: str | None = None
    partial_notice: str | None = None


class CitationOut(BaseModel):
    claim_id: str
    evidence_id: str
    document_id: str
    slug: str
    title: str
    source_id: str
    source_kind: str
    quote: str | None = None
    support: SupportLabel
    score: float
    provider_version: str | None = None
    url: str | None = None


class Timing(BaseModel):
    retrieval_ms: int = 0
    access_ms: int = 0
    freshness_ms: int = 0
    compose_ms: int = 0
    verify_ms: int = 0
    total_ms: int = 0


class AnswerEnvelope(BaseModel):
    schema_version: int = ENVELOPE_SCHEMA_VERSION
    query_id: str
    audit_id: str
    answer: AnswerOut
    claims: list[Claim] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    freshness_receipt: FreshnessReceipt | None = None
    grounding: GroundingReport
    access_summary: AccessSummary
    timing: Timing


class SearchHitOut(BaseModel):
    """An ACL-filtered search hit (MCP `search`); never includes denied documents."""

    document_id: str
    source_id: str
    source_kind: str
    slug: str
    title: str
    chunk_id: str
    snippet: str
    score: float
    freshness_status: str | None = None


class EvidenceSpanOut(BaseModel):
    id: str
    document_id: str
    chunk_id: str | None = None
    source_id: str
    source_kind: str
    slug: str
    title: str
    text: str
    provider_version: str | None = None
    url: str | None = None
    quarantined: bool = False
    was_modified: bool = False
    injection_flags: int = 0
    freshness_status: str | None = None


class EvidenceBundle(BaseModel):
    """ACL-filtered, freshness-checked, sanitized evidence (MCP `assemble_evidence`); no answer."""

    schema_version: int = ENVELOPE_SCHEMA_VERSION
    query: str
    spans: list[EvidenceSpanOut] = Field(default_factory=list)
    freshness_receipt: FreshnessReceipt | None = None
    access_summary: AccessSummary
    meta: dict[str, Any] = Field(default_factory=dict)
