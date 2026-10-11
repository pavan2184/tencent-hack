"""Data models for the groundedness library.

Everything the pipeline passes around is a Pydantic v2 model with ``extra="forbid"`` so a typo in
a field name fails loudly instead of being silently dropped.

Two invariants are enforced at the type level here (the rest live in the implementations):

* ``GroundedAnswer`` refuses a claim without at least one citation, and a citation that points at
  a claim that does not exist (invariant 1: no uncited claim).
* ``GroundingReport`` is frozen and carries ``report_hash``, a sha256 over the canonical JSON of
  every other field (see :func:`canonical_json` and :meth:`GroundingReport.compute_hash`).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
"""Version of the serialized ``GroundingReport`` shape. Bump on any field change."""

ABSTAIN_ANSWER_TEXT = "There is not enough evidence to answer this question."
"""User-facing text of every abstained answer.

It is deliberately identical whatever the cause, so an abstention never hints at whether
restricted documents exist (the composer only ever sees evidence the asker may read).
"""

HASH_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
"""``created_at`` is always rendered in UTC with microseconds in the hash payload."""


class SupportLabel(StrEnum):
    """How well one citation's evidence supports its claim."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    NOT_CHECKED = "not_checked"


class Verdict(StrEnum):
    """Overall grounding verdict for one answer."""

    GROUNDED = "grounded"
    PARTIALLY_GROUNDED = "partially_grounded"
    UNGROUNDED = "ungrounded"
    ABSTAINED = "abstained"


class InjectionSeverity(StrEnum):
    """Severity of a prompt-injection pattern match. ``high`` quarantines the evidence."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceSpan(_Model):
    """One piece of retrieved, access-checked evidence (usually a chunk of a page).

    ``id`` is the handle used in citations and in ``[id]`` answer markers. The app should assign
    short rank-ordered ids (``"E1"``, ``"E2"``, ...) so the markers read naturally; any unique
    string works.
    """

    id: str
    document_id: str
    chunk_id: str | None = None
    source_id: str
    source_kind: str
    slug: str
    title: str
    text: str
    start_offset: int = Field(default=0, ge=0)
    end_offset: int | None = None
    provider_version: str | None = None
    content_hash: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InjectionFlag(_Model):
    """One prompt-injection pattern match.

    ``start``/``end`` index into the *original* (pre-sanitization) text, and
    ``matched_text == original[start:end]``. When the match is in the evidence title rather than
    the body, ``pattern_id`` ends with ``@title`` and the offsets index into the title.
    """

    pattern_id: str
    matched_text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    severity: InjectionSeverity


class SanitizedEvidence(_Model):
    """Evidence after injection screening.

    * ``quarantined`` -> a high-severity pattern matched; ``evidence`` is the original, untouched
      span and must never be shown to a model or cited.
    * ``was_modified`` -> low/medium matches were stripped; ``evidence.text`` is the cleaned text.
    * neither -> ``evidence`` is byte-identical to the input.
    """

    evidence: EvidenceSpan
    flags: list[InjectionFlag] = Field(default_factory=list)
    was_modified: bool = False
    quarantined: bool = False

    @property
    def id(self) -> str:
        return self.evidence.id

    @property
    def usable(self) -> bool:
        """True when this evidence may be shown to a model and cited."""
        return not self.quarantined and bool(self.evidence.text.strip())


class Claim(_Model):
    """One atomic statement in an answer. ``position`` is 0-based answer order."""

    id: str
    text: str
    position: int = Field(ge=0)
    kind: Literal["fact", "inference"] = "fact"


class Citation(_Model):
    """Links one claim to one evidence span.

    ``quote`` is a verbatim sentence of the evidence text (or ``None``). ``support`` and
    ``score`` are filled in by a ``SupportVerifier``; composers leave them ``not_checked``/0.0.
    """

    claim_id: str
    evidence_id: str
    quote: str | None = None
    support: SupportLabel = SupportLabel.NOT_CHECKED
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class GroundedAnswer(_Model):
    """A composed answer. Every claim has >= 1 citation (validated on construction)."""

    answer_text: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    abstain_reason: str | None = None
    composer: str

    @model_validator(mode="after")
    def _every_claim_cited(self) -> Self:
        claim_ids = [claim.id for claim in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim ids must be unique")
        known = set(claim_ids)
        cited: set[str] = set()
        for citation in self.citations:
            if citation.claim_id not in known:
                raise ValueError(f"citation references unknown claim {citation.claim_id!r}")
            cited.add(citation.claim_id)
        uncited = [claim_id for claim_id in claim_ids if claim_id not in cited]
        if uncited:
            raise ValueError(f"every claim needs at least one citation; uncited: {uncited}")
        return self

    @classmethod
    def abstention(cls, reason: str, *, composer: str) -> GroundedAnswer:
        """An abstained answer: no claims, no citations, the fixed abstention text."""
        return cls(
            answer_text=ABSTAIN_ANSWER_TEXT,
            abstained=True,
            abstain_reason=reason,
            composer=composer,
        )


class GroundingReport(BaseModel):
    """Verification result for one answer. Frozen; ``report_hash`` is tamper evidence.

    Counts are per claim and always sum to ``claims_total``. A claim's label is the strongest
    signal among its citations: ``contradicted`` if any citation is contradicted, else
    ``supported``, else ``partially_supported``, else ``unsupported``.

    ``report_hash`` definition (stable across runs, processes, and machines):

    1. ``payload = model_dump(mode="json", exclude={"report_hash"})``
    2. ``payload["created_at"]`` is replaced by ``created_at`` converted to UTC and formatted
       ``%Y-%m-%dT%H:%M:%S.%fZ`` (``created_at`` is normalized to UTC on construction, naive
       datetimes are taken as UTC), so equal instants hash equally whatever their offset.
    3. ``canonical_json(payload)``: keys sorted, ``(",", ":")`` separators, UTF-8, no NaN.
       List order (``per_claim``, ``quarantined_evidence_ids``) is significant.
    4. ``sha256`` hex digest of those bytes.

    Leave ``report_hash`` empty to have it computed; use :meth:`hash_is_valid` to detect edits
    (``model_copy(update=...)`` bypasses validation and leaves a stale hash).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SCHEMA_VERSION
    verifier: str
    created_at: datetime
    claims_total: int = Field(ge=0)
    supported: int = Field(ge=0)
    partially_supported: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    contradicted: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    verdict: Verdict
    injection_flags: int = Field(ge=0)
    quarantined_evidence_ids: list[str] = Field(default_factory=list)
    per_claim: list[Citation] = Field(default_factory=list)
    report_hash: str = ""

    @field_validator("created_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _check_counts_and_hash(self) -> Self:
        counted = self.supported + self.partially_supported + self.unsupported + self.contradicted
        if counted != self.claims_total:
            raise ValueError(
                f"label counts sum to {counted}, expected claims_total={self.claims_total}"
            )
        if not self.report_hash:
            # Frozen model: bypass __setattr__ exactly once, during construction.
            object.__setattr__(self, "report_hash", self.compute_hash())
        return self

    def hash_payload(self) -> dict[str, Any]:
        """The exact dict that is canonicalized and hashed (everything but ``report_hash``)."""
        payload = self.model_dump(mode="json", exclude={"report_hash"})
        payload["created_at"] = self.created_at.astimezone(UTC).strftime(HASH_TIME_FORMAT)
        return payload

    def compute_hash(self) -> str:
        """sha256 hex of ``canonical_json(self.hash_payload())``."""
        return sha256_hex(canonical_json(self.hash_payload()))

    def hash_is_valid(self) -> bool:
        """True when ``report_hash`` matches the current field values."""
        return self.report_hash == self.compute_hash()


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, non-ASCII kept, NaN rejected."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_hex(text: str) -> str:
    """sha256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def report_hash(report: GroundingReport) -> str:
    """Module-level alias for :meth:`GroundingReport.compute_hash`."""
    return report.compute_hash()
