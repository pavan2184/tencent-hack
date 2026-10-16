# freshness

Data-freshness state machine and freshness receipts for Brain Sauce.
**Owner: Pavan.** Pure Python 3.12 + pydantic v2. **Never imports `app`** (enforced by
`tests/test_models.py::test_no_app_import`). Postgres migration range: **0100–0199**.

```bash
cd backend && uv run --no-sync pytest -q libs/freshness/tests
uv run --no-sync ruff check libs/freshness && uv run --no-sync ruff format --check libs/freshness
```

## Lineage

This is a faithful Python port of the approved, now **superseded**, TypeScript/GBrain design:

- Spec: [`docs/superpowers/specs/2026-09-24-gbrain-freshness-foundation-design.md`](../../../docs/superpowers/specs/2026-09-24-gbrain-freshness-foundation-design.md)
  (Freshness Architecture, Data Model, Operation Contracts, Failure Semantics).
- Pavan's refined table/field contracts on branch `origin/codex/gbrain-freshness-foundation`
  (`docs/tencent/FRESHNESS_DATA_MODEL.md`, `docs/tencent/FRESHNESS_API_CONTRACT.md`). Read-only
  reference; the branch is not merged.

Where the branch and the foundation plan disagree on vocabulary, the plan wins:

| Branch / TS spec                     | This library                                      |
| ------------------------------------ | ------------------------------------------------- |
| `searchable_current`                 | `fresh`                                           |
| `pending`                            | `not_searchable`                                  |
| `stale` / `unknown` / `deleted`      | unchanged                                         |
| `safe_use`                           | `safe_to_use`                                     |
| `fallback_action: none`              | `fallback_action: None`                           |
| `gbrain_page_slug`                   | `page_slug` (+ `page_id`)                         |
| 4 connector kinds                    | 8: + `email, upload, gbrain_import, mcp_external` |
| `ConnectorKind` input `gdrive` alias | accepted, normalised to `google_drive`            |

## Entities (`models.py`, tables in `0100_freshness_init.sql`)

| Model                 | Table                   | Key                                                                                 | Purpose                                     |
| --------------------- | ----------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------- |
| `ConnectorCheckpoint` | `connector_checkpoints` | PK `(source_id, scope_key)`                                                         | Durable cursor; CAS on `cursor_version`     |
| `SourceChangeEvent`   | `source_change_events`  | UNIQUE `(source_id, provider_event_id)`                                             | Acceptance/retry ledger                     |
| `ObjectFreshness`     | `object_freshness`      | PK `(source_id, external_object_id)`                                                | Current state per provider object           |
| `SyncRun`             | `sync_runs`             | UNIQUE `(source_id, scope_key, idempotency_key)`                                    | Durable run receipt                         |
| `FreshnessPolicy`     | `freshness_policies`    | PK `(policy_id, schema_version)`; one active per `(connector_kind, evidence_class)` | Budgets                                     |
| `FreshnessReceipt`    | `freshness_receipts`    | PK `receipt_id`; UNIQUE `request_key`                                               | Immutable snapshot (`evidence_items` jsonb) |

Value types: `EvidenceRef`, `ReceiptItem` (= `EvidenceRef` + versions, timestamps, verification,
sync path, `age_seconds`, `budget_seconds`, `freshness_status`, `tombstoned`, `safe_to_use`,
`fallback_action`, `reason`, per-item `policy_id`/`policy_schema_version`), `NormalizedChange`,
`ChangePage`, `ProviderHead`, `IndexOutcome`. All datetimes are timezone-aware UTC (naive rejected).
Models are frozen; `model.evolve(**changes)` returns a re-validated copy.

## Operations (`FreshnessService(store, clock)`)

| Operation                                                     | Input                                                    | Output                                           | Writes                                            |
| ------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------- |
| `accept(change)`                                              | `NormalizedChange`                                       | `AcceptResult(event, duplicate)`                 | ledger row (dedup)                                |
| `queue_sync(req)`                                             | `ConnectorSyncRequest`                                   | `SyncRun` (`queued`)                             | run row (so a route can return `run_id`)          |
| `connector_sync(req, *, change_source, apply)`                | `ConnectorSyncRequest`, `ChangeSource`, `ApplyChange`    | `ConnectorSyncResult`                            | ledger, objects, run, checkpoint                  |
| `freshness_status(req)`                                       | `FreshnessStatusRequest`                                 | `FreshnessStatusReport`                          | nothing                                           |
| `evaluate(obj, policy, now, *, ref=None)` (pure, `policy.py`) | `ObjectFreshness`, `FreshnessPolicy`                     | `ReceiptItem`                                    | nothing                                           |
| `verify_freshness(req, probe)`                                | `VerifyRequest`, `ProviderProbe`                         | `VerifyResult` (+ `item`)                        | `last_verified_at`, `verification_result`, status |
| `freshness_receipt(req, *, probe_for=None)`                   | `ReceiptRequest`, `EvidenceRef -> ProviderProbe \| None` | `FreshnessReceipt`                               | receipt row when `persist=True`                   |
| `versioning.compare(a_v, a_o, b_v, b_o)`                      | versions + orders                                        | `"older" \| "same" \| "newer" \| "incomparable"` | —                                                 |
| `receipt.canonical_hash(value, *, exclude=())`                | model/mapping                                            | sha256 hex of canonical JSON                     | —                                                 |

`ApplyChange = Callable[[NormalizedChange], Awaitable[IndexOutcome]]` is the app's indexer. For an
upsert it fetches, writes the page, chunks and embeds, then returns
`IndexOutcome(content_written, searchable, embedded, indexed_at, searchable_at, page_id, page_slug,
provider_version?, version_order?, content_hash?, error_code?)`. The optional version/hash fields
report what was actually fetched. For a delete it removes the page from search and returns
`searchable=False`. Raising means failure (the event is parked and retried).

Ports (`protocols.py`, all `@runtime_checkable`): `Clock.now()` (sync), `FreshnessStore` (async,
below), `ProviderProbe.head(external_object_id) -> ProviderHead` (raise `ProbeUnavailable` on
transport failure), `ChangeSource.list_changes(cursor, *, limit) -> ChangePage`.
Errors (each has a stable `.code`): `FreshnessError`, `CursorConflict`, `VersionRegression`,
`ReceiptConflict`, `ProbeUnavailable` (`provider_unavailable`), `PolicyNotFound`.

## Invariants: the library must never

- apply a duplicate provider event id a second time (an `applied` event is terminal);
- let an older comparable version overwrite newer object state (store raises `VersionRegression`);
- report a tombstoned object as `fresh` or searchable, or clear a tombstone with anything but a
  strictly newer comparable version;
- record `searchable_at` earlier than `indexed_at`;
- report content that was written but not searchable/embedded as anything but `not_searchable`;
- upgrade `unknown` to `fresh` without a matching provider version. An unknown verification result
  never counts as fresh, and neither does re-arrival of the same version;
- turn a probe transport failure into anything but `unknown`;
- stamp a `failed`/`partial` run as `last_successful_run_id`;
- advance the cursor past a page before every change on it is applied or durably parked. A parked
  change leaves its object non-current (`stale`, or `not_searchable` if it was never indexed);
- move the delta cursor from a reconcile run;
- drop or reorder receipt items. Unknown, deleted and missing evidence stays, in input order;
- hash anything but canonical JSON (sorted keys, compact, UTC ISO timestamps) excluding
  `receipt_id`/`created_at`/`receipt_hash`;
- store a second receipt for a `request_key`. The same request returns the existing receipt;
  a different request raises `ReceiptConflict`;
- mark critical non-fresh evidence `safe_to_use`. It gets the policy's `fallback_action`
  (`omit`/`abstain`), and critical policies cannot be `allow_with_warning`;
- override a standard policy: standard evidence follows its `failure_action`
  (`allow_with_warning` gives `safe_to_use=True` and keeps the real status);
- default a missing object or missing policy to fresh. Both evaluate to `unknown`; a missing policy
  is unsafe (`omit`).

Evaluation (`policy.py`) uses age = `now − last_verified_at` when the last verification matched
(else `now − searchable_at`) against `max_index_age_seconds`. With `require_live_verification`, a
missing verification or one older than `max_verification_age_seconds` yields `unknown`.

Retry/backoff (deliberately simple): a failed or partial apply parks the event with
`next_attempt_at = now + 60s × attempt_count`. After 3 attempts it is parked terminally
(`next_attempt_at = None`), stays queryable, and is never retried automatically.
`# TODO(Pavan): backoff with jitter + provider retry hints` marks the spot in `service.py`.

## How the app calls it

- **`app/adapters/freshness_store.py`** implements `FreshnessStore` over the `0100_freshness_init.sql`
  tables (SQLAlchemy async). `freshness.memory.InMemoryFreshnessStore` is the executable reference:
  - `cas_checkpoint(cp, *, expected_version)`: `UPDATE … WHERE cursor_version = :expected` (or an
    insert when expected is 0); 0 rows → `CursorConflict`. Writes `cursor_version = expected + 1`.
    Reject a changed `last_successful_run_id` that isn't a `completed` run.
  - `accept_event` / `create_run`: `INSERT … ON CONFLICT DO NOTHING RETURNING *`, else select and
    return the existing row (the service detects duplicates/replays by id).
  - `update_event_state(event)`: writes `state, attempt_count, next_attempt_at, last_error_code,
applied_at, parked_at, noop_reason`; refuses to change an `applied` row.
  - `upsert_object(obj)`: `SELECT … FOR UPDATE`, then `freshness.assert_can_replace(stored, obj)`,
    then upsert.
  - `put_policy`: retire other active rows for the same `(connector_kind, evidence_class)`.
  - `save_receipt`: on a `request_key` collision use `freshness.receipt.check_replay`.
  - Also: `list_events(source_id, scope_key=None, *, states=None, limit=1000)` ordered by
    `(accepted_at, id)`, `get_run`, `get_receipt_by_request_key`, `list_objects(source_id, *, statuses=None)`.
  - Columns beyond the spec lists: `source_change_events.noop_reason text`, `connector_checkpoints`
    and `object_freshness` `created_at`/`updated_at` (nullable OK), `object_freshness.page_id`.
- **`tasks/sync.py`** (`sync_source(source_id, trigger_kind, idempotency_key)`):
  `FreshnessService(store, SystemClock()).connector_sync(req, change_source=connector,
apply=ingestion.apply_change)`. The connector satisfies `ChangeSource`. `POST /api/sources/{id}/sync`
  can call `queue_sync(req)` for the 202 `run_id`; the worker's `connector_sync` with the same key
  resumes that run. Serialise one sync per `(source_id, scope_key)` (Celery lock); CAS turns a lost
  race into `CursorConflict`.
- **Webhooks** (`routers/webhooks.py`): normalise, `accept(change)`, return 202 with `event.id`,
  enqueue `sync_source(trigger_kind="webhook")`. The next `connector_sync` drains accepted ledger events.
- **Uploads / one-off ingests**: run `connector_sync` with a one-page
  `ListChangeSource([ChangePage(changes=[change])])` so every indexed page has an `object_freshness`
  row. Evidence without a row is `unknown`.
- **`services/retrieval.py`** (after access filtering, before any LLM): build one `EvidenceRef` per
  candidate (with `evidence_class` from `pages.evidence_class`), then call
  `freshness_receipt(ReceiptRequest(request_key=query_id, evidence=refs), probe_for=…)`.
  `probe_for` returns the connector (`ProviderProbe`) for critical refs when
  `FRESHNESS_LIVE_VERIFY_CRITICAL`, else `None`. Drop items with `safe_to_use=False`, keep the full
  receipt in the envelope, and zip items with candidates (same order). `evaluate` /
  `verify_freshness` are available for finer control. **Seed both a critical and a standard
  active policy for every connector kind in use**; a missing policy makes evidence unsafe.

## Deviations from the plan (and why)

- `FreshnessReceipt.policy_id`/`policy_schema_version` are optional: a cross-source receipt spans
  several (kind, class) policies, so each `ReceiptItem` carries its own; the receipt-level fields
  are set only when one policy covers every item.
- Receipt replay/conflict compares `request_payload_hash` (per the branch contract), not
  `receipt_hash`. A later replay of the same request returns the original proof even though ages
  have changed.
- Additive fields: `IndexOutcome.{page_id, page_slug, provider_version, version_order, content_hash,
provider_modified_at, error_code}`, `SourceChangeEvent.noop_reason`, `ReceiptItem.reason`,
  `ConnectorSyncResult.{replayed, duplicate_count, noop_count}`. Additive store methods:
  `list_events`, `get_run`, `get_receipt_by_request_key`. Additive service method: `queue_sync`.
- `FreshnessPolicy` defaults to `status=active` and then requires `effective_at` (branch rule,
  mirrored by the `0100` CHECK); critical policies cannot use `allow_with_warning`.
- `VerifyRequest` has no `idempotency_key`/expected-version fields yet. `VerifyResult` reports
  `indexed_provider_version` vs `observed_provider_version`.
- Incomplete or failed indexing parks the event (retryable) instead of marking it applied, so a
  partial index is recovered by retry (spec "Partial indexing"). `RunStatus.parked` is not produced
  yet.

## What Pavan builds next

1. Delta and reconcile algorithms: reconcile should diff the full listing against `list_objects` to
   synthesise deletes (`TODO(Pavan)` in `_drain_pages`; today a reconcile trusts the listing) and
   detect permission-version drift for Chai.
2. Backoff with jitter and provider retry hints (`Retry-After`, 429 windows); operator re-drive of
   poison events; deadline handling inside a page.
3. Live Confluence and Slack probes and change sources (or deterministic simulations implementing the
   same `ChangeSource`/`ProviderProbe`), plus Jira/Drive simulations.
4. Port the TypeScript eval corpus and hard gates from the branch (`stale_critical_exposures = 0`,
   `cursor_advanced_past_unaccounted_work = 0`, `duplicate_mutations = 0`, SLA pass rates at
   60 / 300 / 3,600 logical seconds) as hermetic logical-time tests using `FixedClock`.
5. Migrations `0101+` in the 0100–0199 range as the schema evolves.
