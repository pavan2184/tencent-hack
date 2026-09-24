# Confluence Live Smoke Runbook

Status: manual, non-CI procedure for a future connector. No live result is claimed yet. The Confluence adapter, webhook route, worker, and freshness operations are not implemented in this phase; executable commands are unavailable. The operation names below refer to the future [API contract](../FRESHNESS_API_CONTRACT.md), not current CLI commands.

## Prerequisites

- Test-tenant-only: use a disposable Confluence test space and synthetic page content. Do not run against a production space or real policy material.
- An operator with test-space page create, edit, delete, and webhook administration rights; a future connector with provider API credentials and a webhook signing secret supplied through its approved secret store. These are provider credential concepts, not configuration variable names. Do not place credentials in this runbook or evidence.
- A dedicated GBrain source mapped to that test space, an isolated index, observable durable event ledger, checkpoint, worker run, search, and freshness receipt views. Confirm the future connector's supported page lifecycle and authentication contract before executing.
- A clock source for UTC provider mutation, webhook observation, durable acceptance, indexing, and searchability timestamps. Keep evidence in a restricted test artifact location.

## Setup

1. Create the disposable space and one synthetic runbook page with an unmistakable unique marker and harmless version-one text. Record the test space, source ID, stable external page ID, and provider version without copying the page body.
2. Configure the future connector for the test space and record the initial scope cursor. Confirm that webhook authenticity validation and durable storage are enabled. The concrete route, setup commands, and credential names must come from the implemented adapter documentation.
3. Prepare operator access to future `connector_sync`, `freshness_status`, `verify_freshness`, and `freshness_receipt` observations. These are contract operation names; no executable commands are available now.

## Scenario

1. **Create and webhook fast path.** Create the synthetic page in the provider. Observe webhook receipt, stable acceptance ID, durable `source_change_events` entry, worker application, and the matching source-scoped page becoming searchable. Record each time separately.
2. **Update.** Change the page text and provider version. Check that the webhook is durably accepted, then independently wait for matching indexed and searchable state. An accepted response alone does not pass the update.
3. **Missed or delayed webhook and cursor/delta recovery.** In the controlled test setup, withhold or delay delivery for another synthetic update. Run the future delta sync for the same source and scope. Observe the changed page recovered from provider history, the before/after cursor, and whether every preceding change was applied or durably parked with affected evidence non-current before cursor advancement. Then deliver the delayed webhook and check deduplication.
4. **Version drift live verification.** Change the provider page again before its indexed representation catches up. Request future `verify_freshness` for critical selected evidence using its source-scoped identity and expected version. Observe `stale` on comparable version drift, or `unknown` when comparison/provider access is unavailable, with safe omit or abstain. Recheck only after searchable state matches the current provider version.
5. **Delete.** Delete the test page. Observe a durable delete event, worker removal of searchable content, a retained tombstone with deletion version/time, and a receipt that still exposes the deleted evidence item. If removal fails, record non-current retry state rather than declaring a clean delete.

## Expected observation

- Webhook acknowledgement proves **durable acceptance**, not completed indexing. Completed indexing requires the page, chunks, searchable representation, and freshness metadata to match the provider version; `searchable_at` is recorded only then.
- A duplicate or delayed event cannot mutate content twice or replace a newer comparable provider version. A failed delta page cannot advance the cursor past unaccounted work. A parked event is durable accounting, not searchability.
- The future `freshness_status` and `freshness_receipt` views show `(source_id, external_object_id)`, connector kind, provider version and content hash where available, provider modification/observation/acceptance/index/search/verification times, sync path, status, tombstone, policy revision, age/budget, safe-use/fallback, and receipt hash. Record nulls explicitly when a transition has not occurred.
- Record wall-clock intervals as observations only. The 60/300/3600-second targets in [evals](../FRESHNESS_EVALS.md) are logical-time design gates, not a live pass claim.

## Evidence capture

For each mutation, record a small redacted evidence row: test run ID, source and scope, external page ID, provider version/hash, provider mutation time, webhook receipt time, durable acceptance ID/time, event state, run ID/status, cursor before/after, indexed/searchable time, search result version, verification result/time, receipt ID/hash/status, and observed wall-clock latency. Capture classified failure code, retry/parking state, and relevant timestamps if any check fails. Mark missing data unknown; do not infer success from an absent log.

Redact secrets and private content from screenshots, traces, and logs. Never commit provider payloads or tokens, webhook secrets, credentials, or unredacted test artifacts. Access-control evaluation and groundedness scoring are out of scope.

## Cleanup

Delete remaining synthetic pages and the disposable test space through the provider's test-tenant process; confirm tombstone/search removal before removing connector configuration. Revoke test credentials and webhook subscriptions using the provider administration process. Retain only redacted evidence and note any cleanup failure or pending retry explicitly.
