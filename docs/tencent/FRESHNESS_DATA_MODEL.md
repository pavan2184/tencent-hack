# Freshness Data Model

Last updated: 2026-09-24 · Contract version 1

These are approved future production contracts. No freshness migration or table exists in this phase. GBrain's existing sources, pages, chunks, embeddings, locks, and status remain canonical. Every `source_id` below references an existing GBrain source within the selected brain. An object reference is `(source_id, external_object_id)`; a page reference is `(source_id, gbrain_page_slug)` or an equivalent source-scoped page ID. Never identify a page by slug alone. Times are UTC instants; nullable times mean the transition has not happened, not an inferred success.

## `connector_checkpoints`

One durable cursor per connector scope. Primary identifier and unique key: `(source_id, scope_key)`.

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `source_id` | text, required | Existing GBrain source; part of primary key. |
| `scope_key` | text, required | Provider collection, channel, space, or equivalent cursor scope. |
| `connector_kind` | enum, required | `confluence`, `slack`, `jira`, `google_drive`. |
| `cursor_value` | opaque text, nullable | Last safely accounted provider page or watermark. |
| `cursor_version` | integer, required | Compare-and-swap generation, initially zero. |
| `last_polled_at`, `last_reconciled_at` | timestamp, nullable | Last completed attempt of each path. |
| `last_successful_run_id` | ID, nullable | Completed `sync_runs.id`, never a partial/failed run. |
| `status` | enum, required | `ready`, `polling`, `degraded`, or `paused`. |
| `created_at`, `updated_at` | timestamp, required | Row creation and last durable transition. |

The cursor advances with a compare-and-swap on `cursor_version` only after each change in the preceding page is applied or durably parked with its object marked non-current. A failed page leaves the cursor unchanged. Reconciliation does not overwrite the delta cursor. Deleting a source retires its checkpoint with the source lifecycle; a provider object deletion never deletes this row.

## `source_change_events`

Append-oriented acceptance and retry ledger. Primary key: `id` (stable UUID). Unique `(source_id, provider_event_id)` for provider events; synthesized delta/reconcile changes receive a deterministic source-scoped event ID from provider object, version, and change kind.

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `id` | UUID, required | Durable event identity. |
| `source_id`, `scope_key`, `connector_kind` | text, required | GBrain source, cursor scope, provider kind. |
| `provider_event_id`, `external_object_id` | text, required | Deduplication key and provider object identity. |
| `change_kind` | enum, required | `upsert`, `delete`, or `metadata_change`. |
| `provider_version` | opaque text, nullable | Provider revision, possibly unavailable until fetch. |
| `observed_at`, `accepted_at` | timestamp, required | Adapter observation and durable commit time. |
| `state` | enum, required | `accepted`, `processing`, `applied`, or `parked`. |
| `attempt_count` | integer, required | Nonnegative processing attempts. |
| `next_attempt_at` | timestamp, nullable | Durable backoff wake-up for retryable/parked work. |
| `last_error_code` | text, nullable | Stable classified failure; required when parked. |
| `payload_hash` | SHA-256 hex, required | Fingerprint of normalized minimal envelope, not raw secrets. |
| `applied_at`, `parked_at` | timestamp, nullable | Mutually exclusive terminal accounting times. |

`accepted -> processing -> applied` or `accepted/processing -> parked`; a parked event can retry through `processing` without losing its prior receipt. A duplicate returns the existing acceptance and does not increment a content mutation count. `parked` is durable accounting, never successful indexing. A delete event remains in the ledger; it creates a tombstone in `object_freshness` and cannot erase history. Payloads exclude credentials and unrestricted provider bodies.

## `object_freshness`

One current record per provider object. Primary and unique key: `(source_id, external_object_id)`.

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `source_id`, `external_object_id` | text, required | GBrain source and stable provider object identity. |
| `connector_kind` | enum, required | Provider matching the source. |
| `gbrain_page_slug` | text, nullable | Linked source-scoped GBrain page; null before first successful index or after full removal. |
| `provider_version` | opaque text, nullable | Latest accepted comparable revision. |
| `content_hash` | SHA-256 hex, nullable | Indexed content fingerprint; null for unindexed/deleted objects. |
| `provider_modified_at` | timestamp, nullable | Provider time when available. |
| `observed_at` | timestamp, required | Local observation time. |
| `accepted_at`, `indexed_at`, `searchable_at` | timestamp, nullable | Durable event acceptance, page write, and matching searchable representation. |
| `last_verified_at` | timestamp, nullable | Last live provider check. |
| `verification_result` | enum, nullable | `fresh`, `stale`, `unknown`, `not_required`. |
| `sync_path` | enum, required | `webhook`, `delta`, `reconcile`, `live_verify`. |
| `deleted_at`, `tombstone_version` | timestamp/text, nullable | Confirmed provider deletion and deletion revision. |
| `freshness_status` | enum, required | `pending`, `searchable_current`, `stale`, `unknown`, `deleted`. |
| `last_run_id` | ID, nullable | Producing `sync_runs.id`. |
| `created_at`, `updated_at` | timestamp, required | Record lifecycle. |

An older comparable version cannot replace a newer version. Deletion retains the comparable version high-water; a live comparable revision must be strictly higher to clear its tombstone. An incomparable revision cannot restore content by arrival alone: a later same-object provider verification must be fresh and match that revision. `searchable_at >= indexed_at`, and `searchable_current` requires matching page/chunk/embedding/search state and provider version. A content write with failed embedding remains `pending` or `unknown`. A tombstoned object is `deleted`, has no searchable content, and cannot be `searchable_current`; failed removal leaves `stale`/`unknown` with retry work, never a clean delete. Provider object deletion retains this row as proof.

## `sync_runs`

Durable run receipt. Primary key: `id` (UUID); unique `(source_id, scope_key, idempotency_key)` so replay finds the same run.

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `id`, `idempotency_key` | UUID/text, required | Run and replay identity. |
| `source_id`, `scope_key`, `connector_kind` | text, required | GBrain source and provider scope. |
| `trigger_kind` | enum, required | `webhook`, `delta`, `reconcile`, `live_verify`. |
| `cursor_before`, `cursor_after` | opaque text, nullable | Provider cursor around the run; after stays null until safe advancement. |
| `started_at` | timestamp, required | Worker start. |
| `completed_at` | timestamp, nullable | Terminal finish only. |
| `status` | enum, required | `queued`, `running`, `completed`, `partial`, `failed`, `parked`. |
| `observed_count`, `applied_count`, `tombstoned_count`, `retry_count`, `failed_count` | integer, required | Nonnegative accounting. |
| `next_attempt_at` | timestamp, nullable | Retry schedule for nonterminal work. |
| `error_summary` | redacted text, nullable | Stable failure summary without provider secrets. |
| `created_at`, `updated_at` | timestamp, required | Durable lifecycle. |

`queued -> running -> completed/partial/failed/parked`; replay may resume partial, failed, or parked work with the same key. Only `completed` with all changes accounted can become `last_successful_run_id`. Counts and cursor must agree with ledger rows. A delete is counted in `tombstoned_count`, not physically erased from run history.

## `freshness_policies`

Immutable versioned policy rows. Primary key: `(policy_id, schema_version)`; unique active combination `(connector_kind, evidence_class, schema_version)`.

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `policy_id` | text, required | Stable policy family. |
| `schema_version` | integer, required | Contract/policy revision. |
| `connector_kind` | enum, required | One of four providers. |
| `evidence_class` | enum, required | `critical` or `standard`. |
| `max_index_age_seconds`, `max_verification_age_seconds` | integer, required | Nonnegative budgets. |
| `require_live_verification` | boolean, required | Query-time check requirement. |
| `failure_action` | enum, required | `omit`, `abstain`, or explicitly marked standard-evidence treatment. |
| `status` | enum, required | `draft`, `active`, or `retired`. |
| `effective_at`, `retired_at` | timestamp, nullable | Policy activation interval; `effective_at` is required when active or retired. |
| `created_at`, `updated_at` | timestamp, required | Audit timestamps; published versions are immutable. |

Policy publication goes `draft -> active -> retired` as metadata; revisions create rows rather than mutating an active budget. Critical stale/unknown evidence always uses safe fallback. Deletions and tombstones are object state, never policy deletion. Policy rows have no retry/parking state; a failed rollout leaves the previous active version and a failed run receipt.

## `freshness_receipts`

Immutable persisted snapshots for selected evidence, especially demo and audit reconstruction. Primary key: `receipt_id` (UUID). `request_key` is globally unique across all persisted `freshness_receipts`, including requests whose evidence spans sources; it is never scoped to one source or connector. `receipt_hash` is an integrity fingerprint of the canonical receipt payload and schema version, not the idempotency key.

| Field | Type / nullability | Meaning |
| --- | --- | --- |
| `receipt_id`, `schema_version` | UUID/integer, required | Snapshot identity and version. |
| `request_key` | text, required | Globally unique persisted request identity, independent of source scope. |
| `request_payload_hash` | SHA-256 hex, required | Canonical request hash for replay/conflict comparison. |
| `created_at` | timestamp, required | Snapshot creation. |
| `policy_id`, `policy_schema_version` | text/integer, required | Exact policy revision used. |
| `evidence_items` | structured array, required | Every requested `(source_id, external_object_id, gbrain_page_slug?)`, connector kind, provider version/hash, provider modification/observation/acceptance/index/search/verification times, verification result, sync path, age, budget, status, and tombstone marker. |
| `oldest_evidence_age_seconds` | integer, nullable | Null only when no item has a measurable age. |
| `overall_status` | enum, required | `fresh`, `stale`, `unknown`, `not_required`, or `mixed`. |
| `receipt_hash` | SHA-256 hex, required | Canonical snapshot integrity hash. |

For `persist: true`, compute `request_payload_hash` from contract version, ordered source-scoped evidence identifiers, policy ID/version, and the explicit empty-set declaration before reading mutable freshness state. Atomically reserve the globally unique `request_key` and commit its hash with the complete immutable receipt in one transaction. On a key collision, the same key plus the same canonical request hash returns the existing receipt, even if provider state changed later; the same key plus a different hash returns `receipt_conflict`. Concurrent attempts wait for the winner's committed result or receive a retryable in-progress outcome, never a second receipt. A failed transaction rolls back its reservation and receipt together.

Receipts are append-only. A later provider update or deletion does not rewrite old proof; a new request key produces a new receipt reflecting the new status. Unknown/deleted/mismatched items remain in `evidence_items`, preserving input order and source scope. There is no receipt parking state because no partial receipt is published. `persist: false` produces an ephemeral snapshot and no table row or durable idempotency reservation. Ordinary query storage is optional, but demo and audit reconstruction require persistence.

## Integrity and implementation boundary

All future writes must use source-scoped keys and PGLite/Postgres parity. Foreign links from events/runs/objects to GBrain sources and pages must reject cross-source reuse. The event ledger, checkpoint generation, object mutation, and run accounting must be recoverable after interruption. The receipt schema is about freshness facts only; it carries neither an authorization decision nor a groundedness score. Migrations, engine methods, and actual storage will be designed and tested in the production phase, after the eval contract and corpus are approved.
