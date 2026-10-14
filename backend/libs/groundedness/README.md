# groundedness

Owner: **Raphael**. Pure Python 3.12 + Pydantic v2. **Never imports `app`.**

Takes access-checked, freshness-checked evidence and the text a generator wrote from it, turns that
text into an answer where every sentence is a claim with a citation, checks each citation against
the evidence it points at, and decides whether the answer may be shown. It also screens retrieved
text for prompt injection before any model sees it. This is the hackathon's LLM-safety layer:
hallucination mitigation, injection in retrieved content, and never inventing information the asker
was not given.

The library is deterministic and model-free by decision D-013 (`docs/DECISIONS.md`): every step is
pure Python, makes no model call and returns the same output for the same input. Generation belongs
to the app (`app/services/compose.py`), and so does tuning the generation prompt. The lib supplies
the prompt helpers, grounds whatever text comes back, and verifies it. The app's five demo
scenarios pass in mock mode on the extractive composer alone.

## Invariants

| #   | Invariant                                 | Enforced by                                                                                                                                                                                                                                                                                                                              | Tested in                                                                     |
| --- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 1   | **No uncited claim.**                     | `GroundedAnswer` validation rejects a claim without a citation. The extractive composer cites every sentence it picks; `ground` cites every sentence it keeps (see invariant 6).                                                                                                                                                         | `test_models`, `test_compose`, `test_ground`                                  |
| 2   | **No quarantined evidence in an answer.** | Quarantined evidence is never put in a prompt, never cited by the extractive composer or by `ground` (neither its labels nor auto-citation include it), and always `unsupported` with `quote=None` in a report.                                                                                                                          | `test_compose`, `test_ground`, `test_verify`                                  |
| 3   | **No `supported` without evidence text.** | Missing, empty or quarantined evidence → `unsupported`. A quote that does not occur in the evidence text is discarded and the best matching evidence sentence is used. Every reported quote is verbatim. A claim that mentions a number, date or time the cited evidence does not mention is never `supported` or `partially_supported`. | `test_verify`, `test_numeric`                                                 |
| 4   | **Deterministic.**                        | The lib never calls a model (D-013). No randomness. Every sort has explicit tie-breakers (auto-citation ties go to the earliest evidence). Verifiers take an injectable `clock`.                                                                                                                                                         | `test_*::*deterministic*`, `test_report_hash_is_stable_across_runs`           |
| 5   | **Abstain rather than guess.**            | No usable evidence → abstain. A generator's `ABSTAIN` reply, or blank text, is honoured. The policy abstains with no claims, any contradiction, zero coverage, or coverage below the minimum.                                                                                                                                            | `test_compose`, `test_ground`, `test_abstain`, `test_verify::test_pipeline_*` |
| 6   | **Any generator's text can be grounded.** | `ground` keeps every sentence (up to `max_claims`) as a claim. `[E#]` markers are honoured; unmarked sentences are auto-cited to the best-matching usable evidence, never silently dropped. No sentence is rewritten, so an ungroundable sentence lowers coverage instead of disappearing.                                               | `test_ground`                                                                 |

Abstained answers always use the same `ABSTAIN_ANSWER_TEXT`, and abstention reasons never quote
evidence. An abstention therefore says nothing about whether restricted documents exist. The composer
only ever receives evidence the asker may read.

## Call order in the app (`services/retrieval.py`)

The lib's contract is `sanitize → ground → verify → should_abstain`. In the app, grounding happens
inside the composer: `ModelComposer` generates and then calls `ground`, and `ExtractiveComposer`
builds a cited answer directly from evidence sentences. The order runs after access filtering and
freshness checks, so restricted evidence is gone before anything here runs.

```python
from groundedness import (
    DefaultAbstentionPolicy, EvidenceSpan, ExtractiveComposer, GroundedAnswer,
    LexicalOverlapVerifier, RegexInjectionSanitizer, ground,
)
from app.services.compose import ModelComposer  # app side; the lib itself never imports `app`

sanitizer = RegexInjectionSanitizer()
composer = (ExtractiveComposer() if settings.is_mock    # mock mode: no model
            else ModelComposer(chat, deadline_s=settings.ASK_GENERATION_DEADLINE_S))
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

# A caller that already has generated text grounds it directly (ModelComposer does this):
answer = ground(text, sanitized, max_claims=8, generator="model-v1")     # composer "model-v1+ground-v1"
```

**Generation is the app's.** `ModelComposer` (`model-v1`) builds the prompt with
`build_composer_prompt`, calls the `ChatProvider` once within `ASK_GENERATION_DEADLINE_S` (default
20 s; `LLM_TIMEOUT_S` stays the per-phase HTTP timeout), and passes the reply to
`ground(..., generator="model-v1")`, so the answer's composer reads `model-v1+ground-v1`. On a
timeout or provider error it logs the reason and answers with `ExtractiveComposer` instead; the
composer then reads `model-v1->extractive-v1`. The ask never fails because the model did, and the
composer id is recorded in the audit `ask` payload.

**Evidence ids and markers.** `EvidenceSpan.id` is what citations and answer markers carry
(`"... approval. [E1]"`). Use rank-ordered `E1`, `E2`, … so markers read naturally. Ids must be
unique per call. Inside the generation prompt, evidence is always labelled by position (`E1` = first
sanitized item). Quarantined items are skipped but still counted, and `ground` maps labels back to
ids.

## Public API

| Name                                                                                                                              | Kind            | Notes                                                                                                                                                                                  |
| --------------------------------------------------------------------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SupportLabel`, `Verdict`, `InjectionSeverity`                                                                                    | `StrEnum`       | Members are UPPER_CASE, values are lower_case (`SupportLabel.NOT_CHECKED == "not_checked"`).                                                                                           |
| `EvidenceSpan`, `InjectionFlag`, `SanitizedEvidence`, `Claim`, `Citation`, `GroundedAnswer`                                       | Pydantic models | `extra="forbid"`. `SanitizedEvidence.id` and `.usable` are properties. `GroundedAnswer.abstention(reason, *, composer)`.                                                               |
| `GroundingReport`                                                                                                                 | frozen model    | `compute_hash()`, `hash_is_valid()`, `hash_payload()`. `report_hash` is filled automatically when left empty.                                                                          |
| `canonical_json`, `sha256_hex`, `report_hash`                                                                                     | functions       | The hash definition is below.                                                                                                                                                          |
| `EvidenceSanitizer`, `AnswerComposer`, `SupportVerifier`, `AbstentionPolicy`                                                      | `Protocol`s     | `runtime_checkable`. Each docstring states its invariant. `AnswerComposer.compose(question, evidence, *, max_claims)`; `SupportVerifier.verify(answer, evidence)`. Both deterministic. |
| `GroundednessError`                                                                                                               | exception       | Base class.                                                                                                                                                                            |
| `RegexInjectionSanitizer(patterns=DEFAULT_PATTERNS)`, `InjectionPattern`, `DEFAULT_PATTERNS`                                      | sanitizer       | `.sanitize(spans)`, `.sanitize_one(span)`.                                                                                                                                             |
| `ExtractiveComposer(*, min_sentence_tokens=3, min_relative_score=0.5)`                                                            | composer        | `extractive-v1`. Also `compose_sync`. The mock-mode answer source and the app's real-mode fallback.                                                                                    |
| `ground(text, evidence, *, max_claims=8, generator="external")`, `GROUND_ID`                                                      | grounding       | `ground-v1`. Returns a `GroundedAnswer` whose composer reads `<generator>+ground-v1`. `ABSTAIN` or blank text → abstained (`REASON_EMPTY_TEXT` for blank).                             |
| `build_composer_prompt`, `parse_marked_answer(text, valid_labels, *, keep_unmarked=False)`, `is_abstain_reply`, `evidence_labels` | prompt helpers  | Pure helpers for the app's generation prompt; prompt and parser agree on positional labels. `keep_unmarked=True` returns unmarked sentences with `[]` labels (what `ground` uses).     |
| `LexicalOverlapVerifier(*, supported_threshold=0.6, partial_threshold=0.3, clock=None)`                                           | verifier        | `lexical-v2`: token overlap, negation cues, numeric/date gate. Also `verify_sync`, `check_citation`.                                                                                   |
| `numeric_facts(text)`, `unsupported_numeric_facts(claim, evidence_text)`                                                          | functions       | Canonical number, percentage, date and time keys, and the claim's keys the evidence lacks (the verifier's gate).                                                                       |
| `build_grounding_report(answer, evidence, citations, *, verifier, created_at)`, `claim_label`                                     | functions       | Shared summarizer (counts, coverage, verdict, hash) for any verifier.                                                                                                                  |
| `DefaultAbstentionPolicy`, `DEFAULT_MIN_COVERAGE` (0.6)                                                                           | policy          | `should_abstain(report, *, min_coverage=0.6) -> (bool, reason)`.                                                                                                                       |
| `tokenize`, `content_tokens`, `split_sentences`, `jaccard`, `has_negation`, `best_matching_sentence`                              | text toolkit    | Shared by the extractive composer, `ground` and the verifier.                                                                                                                          |
| `SCHEMA_VERSION` (1), `ABSTAIN_ANSWER_TEXT`, `REASON_EMPTY_TEXT`, `__version__`                                                   | constants       |                                                                                                                                                                                        |

## How each piece decides

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

**Generation prompt.** `build_composer_prompt` sends `[E1] title — text` lines, one line per usable
evidence item, with any `[E9]` inside evidence defused to `(E9)`, and asks for at most `max_claims`
sentences, each ending in `[E#]` markers, or exactly `ABSTAIN`.

**Grounding (`ground`).** It splits the generator's text into sentences and keeps the first
`max_claims`; each becomes one claim, with marker text stripped. A sentence with valid `[E#]`
markers (before or after the full stop, `[E1][E3]` or `[E1, E3]`; invalid labels are ignored) gets
one citation per marker, quoting the cited evidence's best-matching sentence. An unmarked sentence
is auto-cited: the usable evidence whose best-matching sentence scores highest wins, ties go to the
earliest evidence, and that sentence becomes the quote. If no usable evidence shares a content token
with it, the sentence is cited to the first usable evidence with `quote=None`, so the verifier
labels it `unsupported` and the policy can withhold the answer. No sentence is dropped or rewritten;
the answer text is rebuilt from the claims with a marker on every sentence. An `ABSTAIN` reply (also
`**ABSTAIN**`), blank text, or no usable evidence produces an abstained answer.

**Lexical verifier (`lexical-v2`).** It computes the Jaccard similarity of content tokens between
the claim and its quote. A score of 0.6 or more is `supported`, 0.3 or more is
`partially_supported`, and anything lower is `unsupported`. When the overlap is 0.3 or more but only
one side contains a negation cue, the citation is `contradicted`. The cues are `not`, `no`, `never`,
`cannot`, `without`, `none`, `nor`, `neither` and any `n't` contraction (`NEGATION_CUES` in
`compose.py`); they decide contradiction only and never change the score.

Then the **numeric/date gate**: a `supported` or `partially_supported` citation whose claim mentions
a number, percentage, date or time that the whole cited evidence text does not mention is demoted to
`unsupported`. It keeps its score and quote, so the audit shows both the overlap and the evidence's
real value. A contradiction takes precedence over the gate, and a claim that occurs verbatim in the
evidence (ignoring case and whitespace) skips it, so extractive claims never pay for it.
`numeric_facts` reduces each mention to canonical keys:

| Mention                                            | Keys                                 |
| -------------------------------------------------- | ------------------------------------ |
| `10,000` / `10000` / `10k` / `10 thousand`         | `10000`                              |
| `SGD 2.5 million` / `2.5M` / `2,500,000`           | `2500000`                            |
| `18%` / `18 percent`                               | `18%`                                |
| `2026-10-01` / `1 October 2026` / `Oct 1st, 2026`  | `date:2026-10-01`, `md:10-1`, `2026` |
| `15 October` / `Oct 15`                            | `md:10-15`                           |
| `16:00` / `02:00`                                  | `time:16:00`, `time:02:00`           |
| `E1`, `[E3]`, `v2`, `FY2026`, `Q3`, `1.2.3`, `10x` | nothing (glued to a letter or a dot) |

Limits: word numbers (`one million`) are not parsed, so a claim saying `1 million` cited to evidence
that spells it out is demoted (the conservative direction); ranges are not expanded; slash dates are
read as plain numbers; a month and year yields only the year.

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

1. **Injection corpus.** Collect real indirect-injection samples (Slack, email, HTML, Unicode
   homoglyphs, base64) as regression tests. Tune severities to keep false positives low on the seed
   corpus.
2. **Evals.** Build a small labelled set of (question, evidence, expected verdict) and track
   precision and recall of `supported`, and the abstention rate, per composer and verifier. Include
   paraphrased generator replies, since lexical overlap bounds their recall (D-013).
3. **Word numbers and ranges in the numeric gate.** Parse `one million`-style numbers and expand
   ranges in `numeric_facts`, so they are checked rather than handled conservatively.
4. **Claim-level provenance.** Carry `provider_version`, `content_hash` and character offsets of the
   quote into each citation, so the audit can re-verify an old answer against the exact version it
   cited.

## Tests

```bash
cd backend && uv run --no-sync pytest -q libs/groundedness/tests
uv run --no-sync ruff check libs/groundedness && uv run --no-sync ruff format --check libs/groundedness
```

The tests are fast, offline and deterministic. `tests/conftest.py` contains fixtures only and is not
imported by the tests, so they run under pytest's `--import-mode=importlib`. The lib has no model
test double because it never calls a model; `test_ground.py` feeds `ground` literal text, and the
app's tests use a recording fake `ChatProvider`. `test_numeric.py` pins the extraction table above
and the gate rules.

## Rule: never import `app`

The app depends on this library, never the reverse. `test_models.py::test_no_app_import` walks `src/`
and fails on any `import app` or `from app …`. Implement new ports as Protocols here and adapt them
in `app/adapters/`.
