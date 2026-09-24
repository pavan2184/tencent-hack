# Slack Live Smoke Runbook

Status: manual, non-CI procedure for a future connector. No live result is claimed yet. The Slack adapter, webhook route, worker, and freshness operations are not implemented in this phase; executable commands are unavailable. The operation names below refer to the future [API contract](../FRESHNESS_API_CONTRACT.md), not current CLI commands.

## Prerequisites

- Test-tenant-only: use a disposable Slack test workspace and channel with synthetic messages. Do not use real conversations or a production channel.
- An operator with rights to create, edit, and delete test messages and manage event delivery; future connector API credentials and an event signing secret supplied through its approved secret store. These are provider credential concepts, not invented environment variable names. Do not place credential values in evidence.
- A dedicated GBrain source mapped to the test channel, isolated search state, and observable durable event ledger, checkpoint, worker run, and receipt views. Confirm the later adapter's message lifecycle and event contract before execution. This runbook asserts no support for threads, reactions, or files.
- UTC timestamp capture for provider mutation, webhook observation, durable acceptance, indexing, and searchability.

## Setup

1. Create the disposable workspace/channel and a unique synthetic marker. Record the test source ID, channel scope, initial cursor, and future adapter configuration identifier without recording secrets.
2. Configure future webhook validation and the channel scope. Concrete routes, commands, and credential names must come from the implemented adapter documentation.
3. Prepare operator access to future `connector_sync`, `freshness_status`, `verify_freshness`, and `freshness_receipt` observations. These are contract operation names; no executable commands are available now.

## Scenario

1. **Create and webhook fast path.** Post a synthetic message. Observe webhook receipt, durable acceptance ID/event, worker processing, and matching searchable representation. Record provider message identity and version or other adapter-defined comparable revision without assuming a specific Slack version field.
2. **Edit.** Change the message text. Observe another durable event and eventual searchable version/hash. Keep the acceptance and completed indexing timestamps distinct.
3. **Duplicate and reordered delivery.** In the controlled test delivery harness, replay the same event and deliver an older change after a newer edit. The duplicate should return the original acceptance and cause no second content mutation; an older comparable revision must not overwrite the current representation. If revisions cannot be compared, expect a provider read before mutation.
4. **Worker replay.** Interrupt the future worker after durable acceptance but before completed indexing, then resume the same run. Observe one eventual content mutation or durable parking with non-current status, stable event/run identity, and no lost accepted change.
5. **Missed webhook and cursor/delta/history recovery.** Withhold a synthetic edit event, then use the future delta/history recovery path for that channel. Observe the missing change, before/after cursor, page accounting, and final searchability. Cursor advancement requires every earlier change applied or durably parked with affected evidence non-current. Deliver the late webhook afterward and check deduplication.
6. **Delete.** Delete the synthetic message. Observe a durable delete event, search removal, retained tombstone, and deleted item in a future freshness receipt. Failed removal remains unsafe and retryable.

## Expected observation

- Webhook acknowledgement proves **durable acceptance**, not completed indexing. Completed indexing requires matching message content, searchable representation, and freshness metadata for the current provider observation.
- Duplicate/reordered delivery and worker replay must not create duplicate mutations or regress a newer comparable revision. A parked change is durable accounting, not a successful index. A failed history page leaves the safe cursor unchanged.
- Future `freshness_status` and `freshness_receipt` observations include `(source_id, external_object_id)`, channel scope, provider version/hash where available, provider modification/observation/acceptance/index/search/verification times, sync path, status, tombstone, policy revision, age/budget, safe-use/fallback, and receipt hash. Null or unavailable provider fields remain explicit; no synthetic version is invented.
- Record wall-clock intervals as observations only. The 60/300/3600-second targets in [evals](../FRESHNESS_EVALS.md) are logical-time design gates, not a live pass claim.

## Evidence capture

For each create, edit, delete, replay, and recovery step, record a redacted row with test run ID, source/channel, external message ID, adapter-reported provider revision/hash, mutation time, webhook receipt time, durable acceptance ID/time, event state, run ID/status, cursor before/after, indexed/searchable time, observed search result, receipt ID/hash/status, and wall-clock latency. Record stable failure code, retry or parking state, and affected non-current evidence for failures. Mark unavailable fields as unknown.

Redact secrets and private content from screenshots, traces, and logs. Never commit provider payloads or tokens, signing secrets, credentials, or unredacted test artifacts. Access-control evaluation and groundedness scoring are out of scope.

## Cleanup

Delete remaining synthetic messages and the disposable test channel/workspace through the provider's test-tenant process; confirm search removal or record pending retry. Revoke test credentials and event subscriptions through provider administration. Retain only redacted evidence and document any cleanup failure.
