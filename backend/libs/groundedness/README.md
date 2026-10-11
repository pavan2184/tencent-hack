# groundedness

Owner: **Raphael**. Pure Python 3.12 + Pydantic v2. **Never imports `app`.**

Turns access-checked, freshness-checked evidence into an answer where every sentence is a claim with
a citation, checks each citation against the evidence it points at, and decides whether the answer
may be shown. It also screens retrieved text for prompt injection before any model sees it. This is
the hackathon's LLM-safety layer: hallucination mitigation, injection in retrieved content, and never
inventing information the asker was not given.

The library ships working, deterministic stubs (no model needed) so the app's five demo scenarios
pass in mock mode. The LLM-backed pieces are the parts to improve.

## Invariants

| #   | Invariant                                 | Enforced by                                                                                                                                                                                              | Tested in                                                           |
| --- | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| 1   | **No uncited claim.**                     | `GroundedAnswer` validation rejects a claim without a citation; composers drop uncited sentences.                                                                                                        | `test_models`, `test_compose`                                       |
| 2   | **No quarantined evidence in an answer.** | Quarantined evidence is never put in a prompt, never cited by a composer, and always `unsupported` with `quote=None` in a report.                                                                        | `test_compose`, `test_verify`                                       |
| 3   | **No `supported` without evidence text.** | Missing, empty or quarantined evidence → `unsupported`. A quote that does not occur in the evidence text is discarded and the best matching evidence sentence is used. Every reported quote is verbatim. | `test_verify`                                                       |
| 4   | **Deterministic in mock mode.**           | No randomness. Every sort has explicit tie-breakers. Verifiers take an injectable `clock`.                                                                                                               | `test_*::*deterministic*`, `test_report_hash_is_stable_across_runs` |
| 5   | **Abstain rather than guess.**            | No usable evidence → abstain. A model `ABSTAIN` reply is honoured. The policy abstains with no claims, any contradiction, zero coverage, or coverage below the minimum.                                  | `test_compose`, `test_abstain`, `test_verify::test_pipeline_*`      |

Abstained answers always use the same `ABSTAIN_ANSWER_TEXT`, and abstention reasons never quote
evidence. An abstention therefore says nothing about whether restricted documents exist. The composer
only ever receives evidence the asker may read.

## Call order in the app (`services/retrieval.py`)

The order is fixed: `sanitize → compose → verify → should_abstain`. It runs after access filtering
and freshness checks, so restricted evidence is gone before anything here runs.

```python
from groundedness import (
    DefaultAbstentionPolicy, EvidenceSpan, GroundedAnswer, LexicalOverlapVerifier,
    LLMComposer, RegexInjectionSanitizer,
)

sanitizer = RegexInjectionSanitizer()
composer = LLMComposer(llm_port)          # or ExtractiveComposer() in mock mode
verifier = LexicalOverlapVerifier()
policy = DefaultAbstentionPolicy()

spans = [EvidenceSpan(id=f"E{rank}", document_id=..., chunk_id=..., source_id=..., source_kind=...,
                      slug=..., title=..., text=..., provider_version=..., url=...)
         for rank, chunk in enumerate(allowed_fresh_chunks, start=1)]

sanitized = sanitizer.sanitize(spans)                                    # never drops, order kept
answer = await composer.compose(question, sanitized, max_claims=8)       # every claim cited
report = await verifier.verify(answer, sanitized)                        # GroundingReport + hash
abstain, reason = policy.should_abstain(report, min_coverage=settings.GROUNDING_MIN_COVERAGE)
if abstain and not answer.abstained:
    answer = GroundedAnswer.abstention(reason, composer=answer.composer)  # show nothing ungrounded
# store `report` (queries.grounding_report) for audit. It describes the candidate answer.
```

`LLMComposer` raises `GroundednessProviderError` on provider failure by default (map it to
`503 provider_unavailable`). Pass `on_provider_error="fallback"` to degrade to the extractive answer
instead. The `llm_port` adapter (`app/adapters/llm_port.py`) must raise `GroundednessProviderError`
for every provider failure.

**Evidence ids and markers.** `EvidenceSpan.id` is what citations and answer markers carry
(`"... approval. [E1]"`). Use rank-ordered `E1`, `E2`, … so markers read naturally. Ids must be
unique per call. Inside the LLM prompt, evidence is always labelled by position (`E1` = first
sanitized item). Quarantined items are skipped but still counted, and the composer maps labels back
to ids.

## Public API

| Name                                                                                                           | Kind              | Notes                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `SupportLabel`, `Verdict`, `InjectionSeverity`                                                                 | `StrEnum`         | Members are UPPER_CASE, values are lower_case (`SupportLabel.NOT_CHECKED == "not_checked"`).                             |
| `EvidenceSpan`, `InjectionFlag`, `SanitizedEvidence`, `Claim`, `Citation`, `GroundedAnswer`                    | Pydantic models   | `extra="forbid"`. `SanitizedEvidence.id` and `.usable` are properties. `GroundedAnswer.abstention(reason, *, composer)`. |
| `GroundingReport`                                                                                              | frozen model      | `compute_hash()`, `hash_is_valid()`, `hash_payload()`. `report_hash` is filled automatically when left empty.            |
| `canonical_json`, `sha256_hex`, `report_hash`                                                                  | functions         | The hash definition is below.                                                                                            |
| `LLMPort`, `EvidenceSanitizer`, `AnswerComposer`, `SupportVerifier`, `AbstentionPolicy`                        | `Protocol`s       | `runtime_checkable`. Each docstring states its invariant.                                                                |
| `GroundednessError`, `GroundednessProviderError(message, *, retryable=False)`                                  | exceptions        |                                                                                                                          |
| `RegexInjectionSanitizer(patterns=DEFAULT_PATTERNS)`, `InjectionPattern`, `DEFAULT_PATTERNS`                   | sanitizer         | `.sanitize(spans)`, `.sanitize_one(span)`.                                                                               |
| `ExtractiveComposer(*, min_sentence_tokens=3, min_relative_score=0.5)`                                         | composer          | `extractive-v1`. Also `compose_sync`.                                                                                    |
| `LLMComposer(llm=None, *, fallback="extractive", on_provider_error="raise", temperature=0.0, max_tokens=1024)` | composer          | `llm-v1`. A fallback answer's composer reads `llm-v1->extractive-v1`.                                                    |
| `build_composer_prompt`, `parse_marked_answer`, `is_abstain_reply`, `evidence_labels`                          | functions         | The prompt to tune, the `[E#]` parser, and the `ABSTAIN` sentinel check.                                                 |
| `LexicalOverlapVerifier(*, supported_threshold=0.6, partial_threshold=0.3, clock=None)`                        | verifier          | `lexical-v1`. Also `verify_sync`, `check_citation`.                                                                      |
| `LLMEntailmentVerifier(llm=None, *, clock=None)`, `build_entailment_prompt`                                    | verifier skeleton | `verify` raises `NotImplementedError`.                                                                                   |
| `build_grounding_report(answer, evidence, citations, *, verifier, created_at)`, `claim_label`                  | functions         | Shared summarizer (counts, coverage, verdict, hash) for any verifier.                                                    |
| `DefaultAbstentionPolicy`, `DEFAULT_MIN_COVERAGE` (0.6)                                                        | policy            | `should_abstain(report, *, min_coverage=0.6) -> (bool, reason)`.                                                         |
| `FakeLLM(script=None, default="ABSTAIN", *, error=None)`, `LLMCall`                                            | test double       | Returns the reply for the first script key found in the user prompt. Records `.calls`. Raises `error` if set.            |
| `tokenize`, `content_tokens`, `split_sentences`, `jaccard`, `has_negation`, `best_matching_sentence`           | text toolkit      | Shared by the composers and the verifier.                                                                                |
| `SCHEMA_VERSION` (1), `ABSTAIN_ANSWER_TEXT`, `__version__`                                                     | constants         |                                                                                                                          |

## How the stubs decide

**Sanitizer.** It runs 13 named regexes over every title and body. Matching works on a copy of the
text with zero-width characters removed, so `ig​nore previous instructions` is still caught.
Offsets are mapped back to the original text, and title matches get the `@title` suffix.

| Severity | Patterns                                                                                                                                                                      | Effect                                    |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| high     | `ignore_instructions`, `disregard_above`, `new_instructions`, `reveal_system_prompt`, `chat_template_tokens`, `html_comment_instruction`, `conceal_from_user`, `exfiltration` | `quarantined=True`, text unchanged        |
| medium   | `you_are_now`, `role_spoofing` (`^system:`/`assistant:`/`user:` label), `markdown_hidden_comment`                                                                             | matched span removed, `was_modified=True` |
| low      | `system_prompt_mention`, `zero_width_chars`                                                                                                                                   | matched span removed, `was_modified=True` |

**Extractive composer.** It splits usable evidence into sentences and scores each by how many
distinct content tokens it shares with the question (stopwords removed, plural `s` stripped). It
keeps sentences scoring at least half the best score, then takes them round-robin across
`document_id`s. Each picked sentence becomes one claim, quoted verbatim with one citation.

**LLM composer.** It sends `[E1] title — text` lines, one line per evidence item, with any `[E9]`
inside evidence defused to `(E9)`. It keeps only sentences carrying a valid marker and sets each
citation's `quote` to the cited evidence's best-matching sentence. An `ABSTAIN` reply produces an
abstained answer. An unparseable reply falls back to the extractive composer.

**Lexical verifier.** It computes the Jaccard similarity of content tokens between the claim and its
quote. A score of 0.6 or more is `supported`, 0.3 or more is `partially_supported`, and anything
lower is `unsupported`. When the overlap is 0.3 or more but only one side contains
`not/no/never/cannot/n't`, the citation is `contradicted`.

Each claim gets one claim-level label, and the label counts sum to `claims_total`:

- `contradicted` if any of its citations is contradicted;
- otherwise `supported` if any citation is supported;
- otherwise `partially_supported` if any citation is partially supported;
- otherwise `unsupported`.

`coverage_ratio` is the number of claims with at least one supported or partially supported
citation, divided by `claims_total`, rounded to 4 places. With zero claims it is 1.0 if the answer
abstained and 0.0 otherwise. The verdict is:

- `abstained` if the answer abstained;
- otherwise `grounded` when every claim is covered and none is contradicted;
- otherwise `partially_grounded` when coverage is above 0;
- otherwise `ungrounded`.

**`report_hash`.** It is the sha256 of `canonical_json(payload)`, where `payload` is
`model_dump(mode="json")` without `report_hash` and with `created_at` rendered as UTC
`%Y-%m-%dT%H:%M:%S.%fZ`. `created_at` is normalized to UTC on construction, and a naive datetime is
treated as UTC. `canonical_json` sorts keys, uses `(",", ":")` separators, encodes as UTF-8, and
rejects NaN. List order is significant. A golden hash is pinned in `test_models.py`.

## What Raphael builds next

1. **Tune the LLM composer prompt** (`build_composer_prompt`). Measure against the demo questions how
   often each model returns parseable replies, how dense the markers are, and how often it abstains.
2. **Entailment verifier** (`LLMEntailmentVerifier.verify`). Apply the same safety rules first, send
   one prompt per citation, map the reply to `SupportLabel` with unparseable replies counting as
   `unsupported`, then call `build_grounding_report`. Batch the citations to stay within the
   Tencent quota.
3. **Injection corpus.** Collect real indirect-injection samples (Slack, email, HTML, Unicode
   homoglyphs, base64) as regression tests. Tune severities to keep false positives low on the seed
   corpus.
4. **Evals.** Build a small labelled set of (question, evidence, expected verdict) and track
   precision and recall of `supported`, and the abstention rate, per composer and verifier.
5. **Claim-level provenance.** Carry `provider_version`, `content_hash` and character offsets of the
   quote into each citation, so the audit can re-verify an old answer against the exact version it
   cited.

## Tests

```bash
cd backend && uv run --no-sync pytest -q libs/groundedness/tests
uv run --no-sync ruff check libs/groundedness && uv run --no-sync ruff format --check libs/groundedness
```

The tests are fast, offline and deterministic. `tests/conftest.py` contains fixtures only and is not
imported by the tests, so they run under pytest's `--import-mode=importlib`. `memory.FakeLLM` is also
meant for the app's conftest.

## Rule: never import `app`

The app depends on this library, never the reverse. `test_models.py::test_no_app_import` walks `src/`
and fails on any `import app` or `from app …`. Implement new ports as Protocols here and adapt them
in `app/adapters/`.
