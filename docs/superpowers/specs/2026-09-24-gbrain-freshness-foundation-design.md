# GBrain Freshness Foundation Design

Date: 2026-09-24

Status: Approved in conversation; awaiting written-spec review

Owners: Pavan (data freshness), with separate team workstreams for access control and groundedness

## Summary

This project will become a full derived copy of GBrain and extend its existing
company-brain, synchronization, source, retrieval, monitoring, and evaluation
infrastructure with a proof-oriented data-freshness layer for the Tencent Cloud
AI CAN DO IT Hackathon Singapore 2026 FinTech challenge.

The freshness workstream will be contract-first. Documentation, deterministic
fixtures, sealed gold expectations, schemas, metrics, and regression gates will
exist before production connector or freshness implementation begins.

The project will represent Confluence, Slack, Jira, and Google Drive through one
connector contract. Confluence and Slack will be the live MVP connectors. Jira
and Google Drive will use realistic deterministic simulations that implement the
same contract.

## Source Baseline

The upstream foundation is:

- Repository: <https://github.com/garrytan/gbrain>
- Tutorial: <https://github.com/garrytan/gbrain/blob/master/docs/tutorials/company-brain.md>
- Pinned version: `v0.54.1.0`
- Pinned commit: `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29`
- License: MIT

The pin is intentional. Evaluation baselines must not drift because upstream
changes underneath them. Future upstream synchronization will be an explicit,
reviewed operation that reruns the full upstream and freshness gates.

## Goals

1. Preserve GBrain's source code, Git history, engineering invariants, tests,
   BrainBench fixtures, and evaluation infrastructure.
2. Reuse GBrain's Postgres/PGLite engine abstraction, sources, pages, chunks,
   embeddings, per-source locks, resumable sync behavior, status surfaces, MCP
   server, and contract-first operation registry.
3. Add deterministic freshness state for provider versions, content hashes,
   source timestamps, index timestamps, verification timestamps, cursors,
   tombstones, retries, and SLA decisions.
4. Prevent critical evidence from being silently presented as current when its
   freshness cannot be established.
5. Produce machine-readable freshness receipts for downstream retrieval and
   answer systems.
6. Prove expected behavior with hermetic, synthetic, reproducible evaluation
   fixtures before connector implementation.

## Non-Goals

This workstream will not research, design, or implement:

- RBAC, identity mapping, source permissions, authorization policy, or access
  control evaluations. Chai owns that workstream.
- Claim grounding, answer synthesis quality, citation entailment, or
  groundedness evaluations. Raphael owns that workstream.
- Four production-grade live connectors. Only Confluence and Slack are live MVP
  targets.
- Production-scale load testing or formal compliance certification.
- An LLM-controlled synchronization state machine.

The freshness layer will expose neutral identifiers and status metadata so the
other workstreams can integrate later without being designed here.

## Repository Integration

### History and upstream relationship

The current Tencent repository history will be retained. GBrain will be added as
an `upstream` remote and integrated non-destructively; no force-push or history
erasure is part of the design.

The integration must preserve:

- The upstream GBrain commit graph and release tag.
- The existing Tencent planning commits.
- Attribution and the upstream MIT license.
- An explicit record of the pinned upstream commit.

### Target documentation layout

GBrain remains at the repository root. Existing upstream documentation remains
intact. Tencent-specific material moves under `docs/tencent/`:

```text
docs/tencent/
├── PROJECT_BRIEF.md
├── HACKATHON_REQUIREMENTS.md
├── UPSTREAM_BASELINE.md
├── FRESHNESS_ARCHITECTURE.md
├── FRESHNESS_DATA_MODEL.md
├── FRESHNESS_API_CONTRACT.md
├── FRESHNESS_EVALS.md
├── DECISIONS.md
└── PROJECT_STATUS.md
```

`UPSTREAM_BASELINE.md` will record inherited capabilities, extension points,
known freshness gaps, licensing, the pin, and the upstream-update procedure.

The root README will retain the upstream documentation and add a concise section
identifying this repository as the Tencent FinTech freshness extension. Root
agent instructions will retain GBrain's engineering invariants and add the team
workstream boundary: this scope covers freshness, not access control or
groundedness.

### GBrain invariants retained

The derived project must continue to respect GBrain's existing rules:

- `src/core/operations.ts` is the central operation contract from which CLI and
  MCP surfaces derive.
- PGLite and Postgres implementations move in parity.
- Source identity is part of page identity.
- Per-source locks, checkpoints, and sync status remain authoritative.
- Tests and evals are hermetic by default and must not inspect a user's real
  brain.
- Public fixtures use fully synthetic people, companies, content, and events.
- Eval gold is sealed from the system being evaluated.

## Freshness Architecture

### 1. Webhook fast path

Provider webhook events enter through a thin adapter that:

1. validates the provider envelope and transport authenticity;
2. normalizes the event into the shared change contract;
3. deduplicates by provider event identity;
4. appends the event to durable change state; and
5. enqueues deterministic processing.

The webhook handler does not directly mutate searchable content. A successful
HTTP response means the event was durably accepted, not that indexing is
complete.

The fast path target is no more than one minute of logical propagation time for
providers that deliver a supported event.

### 2. Cursor/delta recovery

Every connector scope stores a durable provider cursor or equivalent watermark.
A periodic delta worker recovers missed, delayed, duplicated, and reordered
events.

The cursor does not advance past unaccounted work. It may advance after every
change in a delta page has either:

- been applied completely; or
- been durably parked for retry with its affected evidence marked non-current.

This avoids both indefinite poison-event blockage and silent change loss.

The recovery target is no more than five minutes of logical time.

### 3. Slim reconciliation

A periodic reconciliation pass compares lightweight provider state rather than
redownloading all content. The comparison uses, where available:

- stable external object ID;
- provider version or revision token;
- provider modification time;
- permission-version marker supplied by the future access-control workstream;
- deletion or trash state; and
- content checksum or metadata fingerprint.

Reconciliation repairs missed changes, detects deletes, and creates tombstones.
Its convergence target is no more than one hour of logical time.

### 4. Query-time verification

Evidence may be classified as `critical` or `standard` by deterministic policy.
Critical evidence is live-verified immediately before downstream use when its
policy requires verification or its last verification is too old.

Verification can produce:

- `fresh`: the provider version matches indexed state;
- `stale`: the provider reports a different version or deletion;
- `unknown`: verification could not establish provider truth; or
- `not_required`: the applicable policy does not require a live check.

Critical evidence in `stale` or `unknown` state is not silently used. The
freshness layer returns a safe omission/abstention signal to the downstream
consumer.

### 5. Freshness receipt

For each selected evidence object, the freshness layer can produce a versioned
receipt containing:

- source ID and connector kind;
- external object ID and linked GBrain page identity;
- provider version/revision;
- content hash;
- provider modification time;
- event observation time;
- durable acceptance time;
- indexed time;
- searchable/embedded time;
- last live-verification time and result;
- sync path (`webhook`, `delta`, `reconcile`, or `live_verify`);
- computed freshness age;
- applicable freshness budget;
- freshness status; and
- receipt schema version.

The receipt contains freshness facts, not an authorization decision or a claim
entailment score. Downstream workstreams may attach those separately.

### 6. Deterministic ownership

Deterministic code owns:

- timestamps and logical-clock comparisons;
- provider versions and content hashes;
- cursor movement;
- tombstones and deletion state;
- event deduplication and ordering;
- retries and backoff;
- freshness-policy evaluation;
- SLA breach classification; and
- safe fallback behavior.

Jev may classify semantic importance so important changes are processed first.
That classification cannot alter provider truth, cursor safety, freshness
status, or fallback decisions.

## Data Flow

```text
Provider webhook ─┐
                  ├─> normalize event ─> durable change ledger ─> sync worker
Delta poller ─────┘                                           │
                                                              v
Provider API <── fetch/verify ── object state ──> GBrain page/chunks/embed
     ^                                      │
     │                                      v
Reconciler ───────────── compare ───── freshness state and tombstones
                                             │
                                             v
Query consumer ── request verification ─> freshness receipt / safe fallback
```

Content becomes `searchable_current` only when the indexed page, chunks,
searchable representation, and freshness metadata agree on the same provider
version. A source-level success timestamp cannot advance from a partial or
unverifiable run.

## Data Model

Existing GBrain tables remain canonical for sources, pages, chunks, embeddings,
and locks. The freshness extension adds the following logical entities.

### `connector_checkpoints`

One row per connector scope.

Key fields:

- `source_id`
- `scope_key`
- `cursor_value`
- `cursor_version`
- `last_polled_at`
- `last_reconciled_at`
- `last_successful_run_id`
- `status`
- `updated_at`

Integrity rules:

- `(source_id, scope_key)` is unique.
- Cursor changes use compare-and-swap semantics.
- A failed run cannot stamp itself as the last successful run.

### `source_change_events`

Append-oriented normalized provider events.

Key fields:

- `id`
- `source_id`
- `provider_event_id`
- `external_object_id`
- `change_kind`
- `provider_version`
- `observed_at`
- `accepted_at`
- `state`
- `attempt_count`
- `next_attempt_at`
- `last_error_code`
- `payload_hash`

Integrity rules:

- Provider event identity is unique within a source.
- Raw secrets or unrestricted provider payloads are not required for the
  freshness ledger.
- Terminal failure remains queryable and cannot masquerade as success.

### `object_freshness`

Current freshness state per provider object.

Key fields:

- `source_id`
- `external_object_id`
- `gbrain_page_id` or source-scoped page identity
- `provider_version`
- `content_hash`
- `provider_modified_at`
- `observed_at`
- `indexed_at`
- `searchable_at`
- `last_verified_at`
- `verification_result`
- `sync_path`
- `deleted_at`
- `tombstone_version`
- `freshness_status`
- `last_run_id`

Integrity rules:

- `(source_id, external_object_id)` is unique.
- Older provider versions cannot overwrite newer versions.
- A tombstoned object cannot be `searchable_current`.
- `searchable_at` cannot precede `indexed_at`.

### `sync_runs`

Durable execution receipts for webhook, delta, reconciliation, and live
verification work.

Key fields:

- `id`
- `source_id`
- `scope_key`
- `trigger_kind`
- `cursor_before`
- `cursor_after`
- `started_at`
- `completed_at`
- `status`
- `observed_count`
- `applied_count`
- `tombstoned_count`
- `retry_count`
- `failed_count`
- `error_summary`

### `freshness_policies`

Versioned deterministic budgets by connector and evidence class.

Key fields:

- `policy_id`
- `schema_version`
- `connector_kind`
- `evidence_class`
- `max_index_age_seconds`
- `max_verification_age_seconds`
- `require_live_verification`
- `failure_action`

### `freshness_receipts`

Immutable receipt snapshots emitted for downstream use.

Key fields:

- `receipt_id`
- `schema_version`
- `created_at`
- `policy_id`
- `evidence_items`
- `oldest_evidence_age_seconds`
- `overall_status`
- `receipt_hash`

The stored receipt is optional for ordinary queries but required for demo and
audit reconstruction flows defined by the combined team architecture.

## Operation Contracts

Freshness operations are added to GBrain's central operation registry and use
the same versioned JSON contract across supported surfaces.

### `connector_sync`

Purpose: execute or enqueue webhook, delta, or reconciliation work for a named
source and scope.

Inputs:

- `source_id`
- `scope_key`
- `trigger_kind`
- optional normalized event reference
- optional bounded execution deadline

Outputs:

- `run_id`
- `status`
- `accepted_count`
- `applied_count`
- `parked_count`
- `cursor_before`
- `cursor_after`

### `freshness_status`

Purpose: report source, scope, or object freshness without changing state.

Outputs include SLA class, last successful event/delta/reconciliation time,
pending failures, oldest non-current object age, and object-specific state when
requested.

### `verify_freshness`

Purpose: live-check named evidence against its provider.

The operation never upgrades evidence to `fresh` without a matching provider
version. Transport failure returns `unknown`, not `fresh`.

### `freshness_receipt`

Purpose: produce a stable receipt for a supplied set of source-scoped evidence
identifiers.

Unknown, deleted, or mismatched evidence remains visible in the receipt as a
status; it is not dropped from the receipt input set.

### Webhook endpoints

Provider-specific HTTP handlers validate and normalize transport envelopes,
then call the shared durable-acceptance primitive. Business logic does not live
in the route layer.

## Failure Semantics

### Duplicate delivery

Duplicate provider event IDs return the existing durable acceptance result and
do not produce a second content mutation.

### Reordered delivery

Provider version comparison prevents an older event from overwriting newer
state. An incomparable version forces a provider read before mutation.

### Partial indexing

If content writes but chunks, embeddings, or freshness metadata fail, the object
is non-current and the run is partial. Recovery resumes from durable state.

### Deletion

A confirmed provider deletion creates a tombstone and removes the object from
searchability. Failure to complete removal leaves an explicit unsafe state and
an operator-visible retry; it does not report a clean sync.

### Rate limiting and transient errors

Retries use bounded exponential backoff with jitter and provider retry hints.
The next attempt time is durable. Work is not retried in a tight loop.

### Poison events

Malformed or repeatedly failing events receive durable failure receipts with a
stable error code. The delta cursor can progress only after the item is durably
parked and the affected evidence is marked non-current.

### Process interruption

Replaying a run after interruption must converge to the same final object
versions, hashes, tombstones, cursors, and receipts as an uninterrupted run.

### Live-verification failure

Critical evidence becomes `unknown` or `stale` and returns a safe fallback
signal. Standard evidence behavior follows its explicit policy; no policy
defaults unknown state to fresh.

## Evaluation Design

### Layout

```text
evals/freshness/
├── README.md
├── fixtures/
├── gold/
├── holdout/
├── schema/
│   ├── fixture.schema.json
│   ├── gold.schema.json
│   ├── result.schema.json
│   └── baseline.schema.json
└── baselines/
    └── main.json
```

Fixtures contain only adapter-visible provider state, events, and time steps.
Expected versions, hashes, cursor movement, tombstones, receipts, and verdicts
live in separate sealed gold files.

### Hermetic execution

CI uses:

- a deterministic fake provider;
- an injected logical clock;
- synthetic four-platform data;
- an isolated test database;
- no API keys;
- no network calls; and
- no LLM calls.

Logical time proves state-machine and SLA-policy behavior. It does not claim to
measure real provider latency.

### Suites

#### Fast path

Proves a webhook create or update becomes searchable at the expected version
within the logical one-minute budget.

#### Delta recovery

Proves a missed webhook is recovered within five logical minutes without loss,
duplication, or unsafe cursor movement.

#### Reconciliation

Proves drift, missed changes, deletion, and tombstone behavior converge within
one logical hour.

#### Critical verification

Proves version match, version drift, deletion, provider outage, timeout, and
malformed provider responses produce the correct verification and fallback
state.

#### Receipt integrity

Proves every receipt field and receipt hash matches the underlying durable
state and selected policy.

#### Failure recovery

Proves duplicate delivery, reorder, rate limiting, poison events, partial
indexing, worker interruption, and replay converge deterministically.

#### Cross-platform contract

Runs equivalent lifecycle cases through Confluence, Slack, Jira, and Google
Drive adapters. The adapter may vary provider semantics, but the normalized
freshness invariants do not.

### Initial fixture matrix

The initial committed corpus will include at least:

1. Confluence critical runbook update delivered by webhook.
2. Confluence provider version changes between retrieval and live verification.
3. Slack thread update with duplicate and reordered events.
4. Slack event accepted before a simulated worker crash and replay.
5. Jira issue update missed by webhook and recovered through delta polling.
6. Jira pagination or cursor page failure followed by retry.
7. Google Drive file deletion detected through reconciliation.
8. Google Drive modification-time change with unchanged content hash.
9. Poison event parked without a false success stamp.
10. Embedding/searchability failure after content indexing.
11. Rate-limit response with durable delayed retry.
12. Multi-source receipt containing mixed fresh, stale, deleted, and unknown
    evidence.

Approximately 15 percent of the expanded corpus will be held out from the
ordinary CI baseline and used for published/manual runs.

### Metrics and hard gates

Hard gates:

- `stale_critical_exposures = 0`
- `accepted_event_loss = 0`
- `cursor_advanced_past_unaccounted_work = 0`
- `duplicate_mutations = 0`
- `tombstone_accuracy = 1.0`
- `receipt_field_accuracy = 1.0`
- `safe_fallback_rate = 1.0`
- `eventual_convergence_rate = 1.0`
- `fast_path_sla_pass_rate = 1.0` at 60 logical seconds
- `delta_recovery_sla_pass_rate = 1.0` at 300 logical seconds
- `reconciliation_sla_pass_rate = 1.0` at 3,600 logical seconds

Diagnostics that are reported but not initially hard-gated:

- events processed per run;
- retry count;
- logical processing latency distribution;
- provider calls per changed object;
- reconciliation objects scanned per detected change; and
- receipt byte size.

### Baseline governance

The freshness gate follows BrainBench's governance model:

- compare a fresh HEAD run against the baseline from the protected main branch;
- bind results to a fixture hash and run configuration;
- require the committed baseline to match the actual run when fixtures change;
- require a written justification for any adverse metric movement;
- prohibit a pull request from self-approving by replacing its comparison
  baseline; and
- treat thrown or incomplete evaluation runs as failure, not as skipped success.

### Live smoke evaluations

Manual or scheduled live smokes use controlled Confluence and Slack test spaces.
They measure wall-clock propagation and provider behavior without contributing
to the hermetic CI baseline.

Each smoke records:

- provider mutation time;
- webhook receipt time when available;
- durable acceptance time;
- indexed/searchable time;
- observed propagation latency;
- provider version and content hash; and
- final freshness receipt.

Jira and Google Drive simulations remain contract tests for the MVP unless the
team later explicitly expands live scope.

## Documentation Deliverables

The docs/evals-first phase produces:

1. `docs/tencent/UPSTREAM_BASELINE.md`
2. `docs/tencent/FRESHNESS_ARCHITECTURE.md`
3. `docs/tencent/FRESHNESS_DATA_MODEL.md`
4. `docs/tencent/FRESHNESS_API_CONTRACT.md`
5. `docs/tencent/FRESHNESS_EVALS.md`
6. Updated Tencent project brief, decisions, and status documents
7. `evals/freshness/` schemas, fixtures, sealed gold files, baseline contract,
   and corpus documentation
8. Fixture-schema validation and deterministic eval-contract checks

The design documents describe intended behavior. Existing GBrain reference docs
continue to describe current upstream behavior until implementation lands.

## Phase Acceptance Criteria

The docs/evals-first phase is complete only when:

- GBrain is integrated at the pinned commit with both histories preserved.
- Upstream license and attribution remain intact.
- Tencent docs live under `docs/tencent/` and link correctly.
- Every added entity and operation has a versioned documented contract.
- Every hard metric has an exact formula and threshold.
- All four connectors have deterministic contract fixtures.
- Confluence and Slack have documented live-smoke procedures.
- Fixture/gold separation is validated automatically.
- The synthetic-corpus privacy rules pass.
- Existing upstream verification remains intact.
- No production connector or freshness implementation has begun.

## Trade-offs

### Full derived repository vs small overlay

A full derived repository increases merge and maintenance cost, but it allows
the project to extend GBrain's actual sync, storage, operations, and eval seams
without duplicating them or hiding core modifications in a wrapper.

### Two live connectors vs four

Two live connectors reduce integration risk during the three-day build window.
Using one normalized contract and four deterministic adapter suites preserves
coverage of the hackathon's four required platforms.

### Strict safe fallback

Omitting unverifiable critical evidence can reduce answer completeness. It is
preferable to silently presenting stale operational instructions as current.

### Durable event ledger

The ledger adds storage and operational complexity. It makes recovery,
deduplication, cursor safety, and evaluation reconstructable rather than
implicit.

### Hermetic logical-time evals

Logical-time tests are fast and deterministic but cannot prove provider service
latency. Live smokes supply that separate evidence without making CI flaky.

## Team Integration Boundaries

The freshness workstream emits:

- source-scoped evidence identifiers;
- provider versions and hashes;
- freshness status and verification result;
- tombstone state;
- freshness receipt; and
- safe-use or safe-fallback signal.

The access-control workstream may later filter which evidence identifiers reach
freshness verification and attach authorization decisions. The groundedness
workstream may later attach claim-to-evidence mappings and answer-level
citations. Neither contract is designed or evaluated in this specification.

## Next Step After Written Review

After Pavan reviews and approves this written specification, create a detailed
execution plan. The plan must keep repository integration, documentation,
freshness eval infrastructure, and production implementation as separate
phases. The first executable phase ends before production freshness code begins.
