# Freshness API and Operation Contract

Last updated: 2026-09-24 · Future JSON contract version 1

No operation or route in this document is implemented in the current phase. Each future operation is defined once in `src/core/operations.ts` (with implementation in `src/core/ops/`), including schema, `read`/`write` scope, handler, and CLI hints. GBrain derives CLI, MCP, and tools-json surfaces from that registry. The source resolver must preserve the selected brain and GBrain source scope; every object identifier is paired with `source_id`. This document does not define a new authorization policy.

The common response includes `schema_version: 1`. Failed calls use GBrain's operation error envelope with a stable `code`, safe `message`, and redacted `details`; errors never imply evidence is fresh. Provider payloads, tokens, and private content must not be logged in status or errors.

## `connector_sync`

Purpose: accept or execute work for one source and provider scope.

Input: required `source_id`, `scope_key`, `trigger_kind` (`webhook`, `delta`, `reconcile`), and `idempotency_key`; optional normalized `event_id` and bounded `deadline_at`. The connector kind resolves from the existing source and must match the event. A webhook invocation references an already durably accepted event.

Output: `schema_version`, `run_id`, `status` (`queued`, `running`, `completed`, `partial`, `failed`, `parked`), `accepted_count`, `applied_count`, `parked_count`, `cursor_before`, `cursor_after`, and `next_attempt_at` when retryable. Counts distinguish durable acceptance from completed indexing.

Errors: `invalid_source`, `invalid_scope`, `invalid_event`, `cursor_conflict`, `provider_unavailable`, `rate_limited`, `storage_unavailable`, `deadline_exceeded`. A duplicate `idempotency_key` returns the same run/acceptance result without a second content mutation. A failure leaves pending work durable and affected objects non-current; no failed or partial run stamps success or advances a cursor past unaccounted work. This is a write operation scoped to exactly one GBrain source.

## `freshness_status`

Purpose: read source, scope, or object freshness without changing state.

Input: required `source_id`; optional `scope_key` and `external_object_id`. An object lookup uses the composite `(source_id, external_object_id)`, never a global object ID.

Output: `schema_version`, source/scope/object identity, `freshness_status`, SLA class and budget, last successful webhook/delta/reconcile times when known, pending and parked failure counts, oldest non-current age, provider version, index/search timestamps, last verification result, and tombstone state when an object was requested. Unknown times are null with an explicit unknown status.

Errors: `invalid_source`, `invalid_scope`, `object_not_found`, `storage_unavailable`. The operation is read-only and idempotent. When status cannot be read, the safe fallback is `unknown`; a caller must not treat missing status as `fresh`.

## `verify_freshness`

Purpose: live-check source-scoped selected evidence immediately before critical use.

Input: required `source_id`, `external_object_id`, `evidence_class` (`critical` or `standard`), `policy_id`/version, and an `idempotency_key`; optional expected `provider_version`, `content_hash`, and bounded `deadline_at`. The linked GBrain page identity, if supplied, must match the same source.

Output: `schema_version`, source/object/page identity, expected and observed provider versions, `verified_at`, `verification_result` (`fresh`, `stale`, `unknown`, `not_required`), `freshness_status`, budget, `safe_use` boolean, and `fallback_action` (`none`, `omit`, `abstain`). A matching provider version and indexed/searchable state are required for `fresh`.

Errors: `invalid_source`, `object_not_found`, `policy_not_found`, `provider_unavailable`, `rate_limited`, `provider_malformed`, `deadline_exceeded`, `storage_unavailable`. Provider uncertainty is represented as `unknown` with a safe fallback for critical evidence; transport failure never upgrades state to `fresh`. Repeated verification with the same key and provider observation is idempotent, while a new observation can produce a new result. This is a scoped write because it records verification state; it does not perform authorization or claim scoring.

## `freshness_receipt`

Purpose: produce a stable, versioned snapshot for the exact selected evidence set.

Input: required ordered `evidence` array of `(source_id, external_object_id, gbrain_page_slug?)`, `policy_id`/version, and `request_key`; optional `persist` flag (default `true`). Every item must be checked in its own GBrain source. A zero-item set is valid only when the caller explicitly records that no evidence was selected.

Output: `schema_version`, `receipt_id`, `created_at`, policy revision, ordered `evidence_items`, `oldest_evidence_age_seconds`, `overall_status`, and `receipt_hash`. Each item includes source/connector/object/page identity, provider version and content hash, provider modification/observation/acceptance/index/search/live-verification times, verification result, sync path, computed age, budget, tombstone state, freshness status, and safe-use/fallback signal. Unknown, stale, deleted, or mismatched evidence remains in the receipt instead of disappearing from the input set.

Persistence modes:

- `persist: true`: `request_key` is globally unique across persisted receipts. The service computes `request_payload_hash` from the canonical contract version, ordered source-scoped evidence identifiers, policy ID/version, and explicit empty-set declaration. Atomic reservation and receipt commit ensure the same key plus the same hash returns the existing immutable receipt, while the same key plus a different hash returns `receipt_conflict`. A concurrent in-progress reservation is waited on or returned as retryable; no partial receipt is published.
- `persist: false`: returns an ephemeral snapshot with no persisted receipt or key reservation. `request_key` is for correlation and deterministic behavior within that request only; there is no cross-call or restart replay or conflict guarantee. A later call may observe changed freshness state and return a different snapshot.

Errors: `invalid_evidence`, `invalid_source`, `policy_not_found`, and `evidence_unavailable` apply to either mode. `receipt_conflict` and `storage_unavailable` apply only when persistence was requested. On failure no partial receipt is presented as fresh. A persisted receipt write that fails returns `storage_unavailable`, never an unauditable success. This operation reads scoped evidence and may write an immutable receipt, so its registry scope is statically `write` even when a caller chooses `persist: false`.

## Provider webhook transport

Future provider-specific HTTP webhook routes are thin adapters only: validate transport authenticity and envelope shape, normalize a provider event, deduplicate, call the shared durable-acceptance primitive, and return its stable acceptance ID. A successful `2xx` response means durable acceptance, never completed indexing. If durable storage fails, the route must fail for provider retry; it cannot acknowledge an in-memory-only event. Duplicate delivery returns the existing ID. Routes contain no cursor, indexing, policy, or query business logic. Their concrete paths and authentication mechanics are deferred to the live connector implementation.

## Compatibility and safety

Contract version changes are explicit and additive where possible; old receipt versions remain readable. Provider revisions are opaque until a connector can compare them; incomparable versions force a provider read. Source isolation, per-source locks, PGLite/Postgres parity, and GBrain's existing operation/error conventions remain binding. Freshness outputs carry neutral evidence identities, status, and safe-use signals. They contain no authorization decision and no groundedness score.
