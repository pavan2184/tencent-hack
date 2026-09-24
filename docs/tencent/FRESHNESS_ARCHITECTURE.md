# Freshness Architecture

Last updated: 2026-09-24 · Approved future contract, not production behavior

## Boundary and six-layer flow

GBrain remains the root application. Its source-scoped pages, chunks, embeddings, search, source locks, and sync status are the substrate. The freshness extension will add durable provider-change accounting and evidence status before a consumer uses selected evidence.

```text
provider webhook -> durable event -> deterministic worker -> indexed/searchable state
provider delta cursor ------------------------------^
provider slim reconcile ----------------------------^
critical query -> live verify -> fresh | stale | unknown | not_required
selected evidence -> versioned freshness receipt
```

1. A thin provider webhook adapter authenticates and normalizes the envelope, deduplicates the provider event identity, commits durable acceptance, then schedules work. HTTP success means durable acceptance, not completed indexing. Supported webhook-path changes target `<=60` logical seconds from durable acceptance to searchability.
2. A delta poller tracks a per-source, per-scope provider cursor. A page cursor advances only when every preceding change is applied or durably parked for retry with affected evidence marked non-current. Delta-recovered changes target `<=300` logical seconds from provider change to searchability.
3. Slim reconciliation compares stable external object IDs, provider versions, modification times, deletion state, and available metadata fingerprints. It detects missed changes and tombstones without downloading every object. Reconcile-only changes target `<=3600` logical seconds from provider change to convergence.
4. The deterministic worker fetches current provider state, compares versions, updates GBrain's source-scoped page and derived chunks/embeddings, and records the matching freshness state. `searchable_current` requires the page, chunks, searchable representation, and freshness metadata to agree on the same provider version. Partial indexing remains non-current.
5. A critical query invokes live verification when policy requires it or the last verification is too old. The result is `fresh`, `stale`, `unknown`, or `not_required`. A version mismatch or deletion is stale; provider timeout, outage, malformed response, or incomparable version is unknown until resolved. Critical stale/unknown evidence produces a safe omission or abstention signal and is never silently exposed as current.
6. A selected evidence set produces a versioned freshness receipt with source and object identities, provider version and hash, observation/acceptance/index/search/verification times, sync path, age, budget, and status. Mixed, deleted, or unknown items stay visible in the receipt.

## Providers and deployment phases

One normalized connector contract covers Confluence, Slack, Jira, and Google Drive. Confluence and Slack are the live MVP integration targets, subject to controlled test spaces and credentials. Jira and Google Drive use deterministic simulations in this phase. All four must obey the same lifecycle and safety invariants. These docs define contracts only; there are no new webhook routes, workers, tables, or live connectors yet.

## Failure and recovery rules

Duplicate event IDs return the original durable acceptance and cannot cause duplicate content mutation. A lower comparable provider version cannot overwrite a higher one; an incomparable version requires a provider read. A confirmed deletion creates a tombstone and removes searchability. If removal fails, the object remains explicitly unsafe and retryable. Rate limits and transient errors use bounded backoff with durable next-attempt times. Poison events are parked with a stable error code; parking permits cursor movement only after the affected evidence is marked non-current. Interrupted runs replay idempotently. No partial or unverifiable run stamps a source or scope as successfully current.

Deterministic code owns clock comparisons, versions and hashes, deduplication, cursor movement, tombstones, retries, policy budgets, breach classification, and fallback. Jev may prioritize semantically important work, but cannot change provider truth, cursor safety, status, or fallback. The access-control and groundedness workstreams consume neutral identifiers and status later; this architecture does not make their decisions.

## GBrain seams

Future operations enter `src/core/operations.ts` and derive CLI/MCP surfaces. PGLite and Postgres changes must move together, with schema migration and bootstrap coverage. Every object lookup, page mutation, receipt item, and status read preserves GBrain source identity. Tests use isolated stores, an injected logical clock, synthetic data, and no live provider, network, key, or LLM in CI. [Data model](FRESHNESS_DATA_MODEL.md), [operations](FRESHNESS_API_CONTRACT.md), and [evals](FRESHNESS_EVALS.md) are the executable design references.
