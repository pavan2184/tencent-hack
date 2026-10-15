"""groundedness: claims <-> evidence citations, support verification, abstention, and
prompt-injection screening for the Internal Brain.

Pure Python + Pydantic; never imports ``app`` and never calls a model: every step is
deterministic. Generation is the app's; the app calls, in this order::

    sanitized = sanitizer.sanitize(spans)                                # EvidenceSanitizer
    text = <the app's model call over build_composer_prompt(question, sanitized)>
    answer = ground(text, sanitized, generator="model-v1")               # or an AnswerComposer
    report = await verifier.verify(answer, sanitized)                    # SupportVerifier
    abstain, reason = policy.should_abstain(report, min_coverage=0.6)    # AbstentionPolicy

i.e. ``sanitize -> ground -> verify -> should_abstain``. Without a model the app composes with
``ExtractiveComposer`` instead of ``ground``.
"""

from __future__ import annotations

from groundedness.abstain import DEFAULT_MIN_COVERAGE, DefaultAbstentionPolicy
from groundedness.compose import (
    EXTRACTIVE_COMPOSER_ID,
    REASON_EMPTY_TEXT,
    REASON_MODEL_ABSTAINED,
    REASON_NO_USABLE_EVIDENCE,
    ExtractiveComposer,
    best_matching_sentence,
    build_composer_prompt,
    content_tokens,
    evidence_labels,
    has_negation,
    is_abstain_reply,
    jaccard,
    parse_marked_answer,
    split_sentences,
    tokenize,
)
from groundedness.ground import GROUND_ID, ground
from groundedness.models import (
    ABSTAIN_ANSWER_TEXT,
    SCHEMA_VERSION,
    Citation,
    Claim,
    EvidenceSpan,
    GroundedAnswer,
    GroundingReport,
    InjectionFlag,
    InjectionSeverity,
    SanitizedEvidence,
    SupportLabel,
    Verdict,
    canonical_json,
    report_hash,
    sha256_hex,
)
from groundedness.numeric import numeric_facts, unsupported_numeric_facts
from groundedness.partial import (
    has_off_topic_claims,
    needs_partial_selection,
    procedure_requested,
    select_supported_relevant_claims,
)
from groundedness.protocols import (
    AbstentionPolicy,
    AnswerComposer,
    EvidenceSanitizer,
    GroundednessError,
    SupportVerifier,
)
from groundedness.sanitize import DEFAULT_PATTERNS, InjectionPattern, RegexInjectionSanitizer
from groundedness.verify import (
    LEXICAL_VERIFIER_ID,
    LexicalOverlapVerifier,
    build_grounding_report,
    claim_label,
)

__version__ = "0.1.0"

__all__ = [
    "ABSTAIN_ANSWER_TEXT",
    "DEFAULT_MIN_COVERAGE",
    "DEFAULT_PATTERNS",
    "EXTRACTIVE_COMPOSER_ID",
    "GROUND_ID",
    "LEXICAL_VERIFIER_ID",
    "REASON_EMPTY_TEXT",
    "REASON_MODEL_ABSTAINED",
    "REASON_NO_USABLE_EVIDENCE",
    "SCHEMA_VERSION",
    "AbstentionPolicy",
    "AnswerComposer",
    "Citation",
    "Claim",
    "DefaultAbstentionPolicy",
    "EvidenceSanitizer",
    "EvidenceSpan",
    "ExtractiveComposer",
    "GroundedAnswer",
    "GroundednessError",
    "GroundingReport",
    "InjectionFlag",
    "InjectionPattern",
    "InjectionSeverity",
    "LexicalOverlapVerifier",
    "RegexInjectionSanitizer",
    "SanitizedEvidence",
    "SupportLabel",
    "SupportVerifier",
    "Verdict",
    "__version__",
    "best_matching_sentence",
    "build_composer_prompt",
    "build_grounding_report",
    "canonical_json",
    "claim_label",
    "content_tokens",
    "evidence_labels",
    "ground",
    "has_negation",
    "is_abstain_reply",
    "jaccard",
    "numeric_facts",
    "parse_marked_answer",
    "report_hash",
    "sha256_hex",
    "select_supported_relevant_claims",
    "has_off_topic_claims",
    "needs_partial_selection",
    "procedure_requested",
    "split_sentences",
    "tokenize",
    "unsupported_numeric_facts",
]
