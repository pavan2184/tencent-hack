"""groundedness: claims <-> evidence citations, support verification, abstention, and
prompt-injection screening for the Internal Brain.

Pure Python + Pydantic; never imports ``app``. The app calls, in this order::

    sanitized = sanitizer.sanitize(spans)                                   # EvidenceSanitizer
    answer = await composer.compose(question, sanitized, llm=llm_port)      # AnswerComposer
    report = await verifier.verify(answer, sanitized)                       # SupportVerifier
    abstain, reason = policy.should_abstain(report, min_coverage=0.6)       # AbstentionPolicy
"""

from __future__ import annotations

from groundedness.abstain import DEFAULT_MIN_COVERAGE, DefaultAbstentionPolicy
from groundedness.compose import (
    EXTRACTIVE_COMPOSER_ID,
    LLM_COMPOSER_ID,
    ExtractiveComposer,
    LLMComposer,
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
from groundedness.memory import FakeLLM, LLMCall
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
from groundedness.protocols import (
    AbstentionPolicy,
    AnswerComposer,
    EvidenceSanitizer,
    GroundednessError,
    GroundednessProviderError,
    LLMPort,
    SupportVerifier,
)
from groundedness.sanitize import DEFAULT_PATTERNS, InjectionPattern, RegexInjectionSanitizer
from groundedness.verify import (
    LEXICAL_VERIFIER_ID,
    LLM_ENTAILMENT_VERIFIER_ID,
    LexicalOverlapVerifier,
    LLMEntailmentVerifier,
    build_entailment_prompt,
    build_grounding_report,
    claim_label,
)

__version__ = "0.1.0"

__all__ = [
    "ABSTAIN_ANSWER_TEXT",
    "DEFAULT_MIN_COVERAGE",
    "DEFAULT_PATTERNS",
    "EXTRACTIVE_COMPOSER_ID",
    "LEXICAL_VERIFIER_ID",
    "LLM_COMPOSER_ID",
    "LLM_ENTAILMENT_VERIFIER_ID",
    "SCHEMA_VERSION",
    "AbstentionPolicy",
    "AnswerComposer",
    "Citation",
    "Claim",
    "DefaultAbstentionPolicy",
    "EvidenceSanitizer",
    "EvidenceSpan",
    "ExtractiveComposer",
    "FakeLLM",
    "GroundedAnswer",
    "GroundednessError",
    "GroundednessProviderError",
    "GroundingReport",
    "InjectionFlag",
    "InjectionPattern",
    "InjectionSeverity",
    "LLMCall",
    "LLMComposer",
    "LLMEntailmentVerifier",
    "LLMPort",
    "LexicalOverlapVerifier",
    "RegexInjectionSanitizer",
    "SanitizedEvidence",
    "SupportLabel",
    "SupportVerifier",
    "Verdict",
    "__version__",
    "best_matching_sentence",
    "build_composer_prompt",
    "build_entailment_prompt",
    "build_grounding_report",
    "canonical_json",
    "claim_label",
    "content_tokens",
    "evidence_labels",
    "has_negation",
    "is_abstain_reply",
    "jaccard",
    "parse_marked_answer",
    "report_hash",
    "sha256_hex",
    "split_sentences",
    "tokenize",
]
