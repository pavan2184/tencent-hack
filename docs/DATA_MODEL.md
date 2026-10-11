# Data Model

Last updated: 2026-10-12

## Overview

Postgres 16 with pgvector. UUID primary keys (`gen_random_uuid()`) except where an id is a
human-chosen string (principals, groups, sources, policies). All times are `timestamptz` in UTC.
Structured payloads are `jsonb`. The DDL lives in `infra/postgres/migrations/` and is the source
of truth; `app/db/models.py` mirrors it by hand (no autogenerate).

`pages` **is** the documents table: every upload, Slack daily log, email, Confluence page, Jira
issue and Drive file is a page. The model is a port of GBrain's (see
[GBrain mapping](GBRAIN_MAPPING.md)) plus governed columns, with each library's state in its own
migration range.

```text
principals ─< group_memberships >─ groups
    │
    ├─< uploads >── pages            sources ─< pages ─< content_chunks
    ├─< queries                                  │  ├─< links (from/to)
    └─< access_requests (document_id: soft ref)  │  ├─< tags, timeline_entries, raw_data, page_versions
                                                 │  ├── source_permissions (1:1)        [0200 access]
audit_events (append-only hash chain)            │  ├─< grants                          [0200 access]
ingest_log                                       │  └─< object_freshness.page_id        [0100 freshness]
                                       sources ─< connector_checkpoints, source_change_events,
                                                  sync_runs, object_freshness           [0100 freshness]
freshness_policies   freshness_receipts (queries.freshness_receipt_id: soft ref)        [0100 freshness]
```

## Vocabularies

| Concept                      | Values                                                                              | Used by                                                        |
| ---------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Source kind (access_control) | `confluence, jira, slack, gdrive, email, upload, gbrain_import, mcp_external`       | `sources.kind`, `pages.source_kind`, `source_permissions.kind` |
| Connector kind (freshness)   | `confluence, slack, jira, google_drive, email, upload, gbrain_import, mcp_external` | every freshness table, `policies.yaml`                         |
| Classification               | `public, internal, confidential, restricted`                                        | `pages.classification`                                         |
| Evidence class               | `critical, standard`                                                                | `pages.evidence_class`, `freshness_policies`                   |
| Freshness status             | `fresh, stale, unknown, not_searchable, deleted`                                    | `object_freshness.freshness_status`, receipt items             |
| Verification result          | `fresh, stale, unknown, not_required`                                               | `object_freshness.verification_result`                         |
| Sync path / trigger kind     | `webhook, delta, reconcile, live_verify`                                            | `object_freshness.sync_path`, `sync_runs.trigger_kind`         |
| Change kind                  | `upsert, delete, metadata_change`                                                   | `source_change_events.change_kind`                             |
| Event state                  | `accepted, processing, applied, parked`                                             | `source_change_events.state`                                   |
| Run status                   | `queued, running, completed, partial, failed, parked`                               | `sync_runs.status`                                             |
| Checkpoint status            | `ready, polling, degraded, paused`                                                  | `connector_checkpoints.status`                                 |
| Failure action               | `omit, abstain, allow_with_warning` (`allow_with_warning` only for `standard`)      | `freshness_policies.failure_action`                            |
| Policy status                | `draft, active, retired`                                                            | `freshness_policies.status`                                    |
| Overall receipt status       | `fresh, stale, unknown, not_required, mixed`                                        | `freshness_receipts.overall_status`                            |
| Grant subject / effect       | `principal, group, role` / `allow, deny`                                            | `grants`                                                       |
| Access request status        | `pending, approved, denied`                                                         | `access_requests.status`                                       |
| Ingest status (no CHECK)     | `pending, indexing, indexed, failed, budget_exceeded`                               | `pages.ingest_status`                                          |

Source kinds use the access-control vocabulary everywhere a source or page is described
(`gdrive`). The freshness `ConnectorKind` accepts `gdrive` as an input alias and always emits
`google_drive`, so freshness tables, policies and receipts store `google_drive`; the app can pass a
page's `source_kind` straight to the freshness lib. The superseded TypeScript spec's `searchable_current` and `pending` statuses are
`fresh` and `not_searchable` here.

## Core range (0001–0099), owner Raphael

### 0001 `schema_migrations`

| Column       | Type        | Null | Notes                              |
| ------------ | ----------- | ---- | ---------------------------------- |
| `filename`   | text        | no   | PK, e.g. `0100_freshness_init.sql` |
| `applied_at` | timestamptz | no   | default `now()`                    |
| `checksum`   | text        | no   | sha256 of the substituted SQL      |

### 0001 `principals`, `groups`, `group_memberships`

| Table               | Column                     | Type        | Null | Notes                                                              |
| ------------------- | -------------------------- | ----------- | ---- | ------------------------------------------------------------------ |
| `principals`        | `id`                       | text        | no   | PK, e.g. `priya.nair`                                              |
|                     | `display_name`             | text        | no   |                                                                    |
|                     | `email`                    | text        | yes  |                                                                    |
|                     | `roles`                    | text[]      | no   | default `{}`; `employee, manager, auditor, admin, contractor`      |
|                     | `external_identities`      | jsonb       | no   | default `{}`; `{slack, jira, confluence, gdrive, email}` → id      |
|                     | `is_active`                | boolean     | no   | default `true`; inactive ⇒ `401 unknown_actor`                     |
|                     | `created_at`, `updated_at` | timestamptz | no   | default `now()`                                                    |
| `groups`            | `id`, `name`               | text        | no   | PK `id`                                                            |
|                     | `created_at`               | timestamptz | no   |                                                                    |
| `group_memberships` | `principal_id`             | text        | no   | FK `principals` ON DELETE CASCADE; PK (`principal_id`, `group_id`) |
|                     | `group_id`                 | text        | no   | FK `groups` ON DELETE CASCADE; index `idx_group_memberships_group` |

### 0001 `uploads`, `usage_counters`

| Table            | Column         | Type        | Null | Notes                                                                                           |
| ---------------- | -------------- | ----------- | ---- | ----------------------------------------------------------------------------------------------- |
| `uploads`        | `id`           | uuid        | no   | PK                                                                                              |
|                  | `actor_id`     | text        | no   | FK `principals`                                                                                 |
|                  | `page_id`      | uuid        | yes  | FK `pages` ON DELETE SET NULL (added in 0002)                                                   |
|                  | `filename`     | text        | no   | original name; stored name is server-generated                                                  |
|                  | `bytes`        | bigint      | no   | `>= 0`                                                                                          |
|                  | `content_type` | text        | no   |                                                                                                 |
|                  | `created_at`   | timestamptz | no   | index (`actor_id`, `created_at DESC`)                                                           |
| `usage_counters` | `day`          | date        | no   | PK (`day`, `key`); all-time counters use the sentinel day `1970-01-01`                          |
|                  | `key`          | text        | no   | `uploads_total` (all-time), `uploads:<actor_id>` (per UTC day), `embedding_calls` (per UTC day) |
|                  | `count`        | bigint      | no   | default 0, `>= 0`                                                                               |
|                  | `updated_at`   | timestamptz | no   |                                                                                                 |

Cap check and increment in one statement (no row returned ⇒ cap hit ⇒ `429 cap_exceeded`):

```sql
INSERT INTO usage_counters (day, key, count) VALUES ($1, $2, 1)
ON CONFLICT (day, key) DO UPDATE SET count = usage_counters.count + 1, updated_at = now()
WHERE usage_counters.count < $3
RETURNING count;
```

### 0001 `queries`

| Column                 | Type        | Null | Notes                                                        |
| ---------------------- | ----------- | ---- | ------------------------------------------------------------ |
| `id`                   | uuid        | no   | PK = `AnswerEnvelope.query_id`                               |
| `actor_id`             | text        | no   | FK `principals`; index (`actor_id`, `created_at DESC`)       |
| `request_id`           | text        | yes  |                                                              |
| `question`             | text        | no   |                                                              |
| `status`               | text        | no   | `answered`, `abstained` or `failed`                          |
| `answer_text`          | text        | yes  |                                                              |
| `citations`            | jsonb       | no   | default `[]`; the envelope's citations                       |
| `grounding_report`     | jsonb       | yes  | `GroundingReport`                                            |
| `freshness_receipt_id` | uuid        | yes  | soft reference to `freshness_receipts` (higher range, no FK) |
| `access_summary`       | jsonb       | yes  | `AccessSummary` (no denied count)                            |
| `audit_event_id`       | uuid        | yes  | soft reference to `audit_events`                             |
| `latency_ms`           | integer     | yes  | `>= 0`                                                       |
| `created_at`           | timestamptz | no   |                                                              |

### 0001 `audit_events` (append-only, hash-chained)

| Column         | Type        | Null | Notes                                                                                    |
| -------------- | ----------- | ---- | ---------------------------------------------------------------------------------------- |
| `id`           | uuid        | no   | PK = `AnswerEnvelope.audit_id`                                                           |
| `seq`          | bigserial   | no   | UNIQUE; chain order                                                                      |
| `occurred_at`  | timestamptz | no   | default `now()`                                                                          |
| `actor_id`     | text        | yes  | principal id or `system:<component>` (no FK)                                             |
| `action`       | text        | no   | `ask`, `mcp.<tool>`, `document.upload`, `grant.create`, `grant.revoke`, `seed.loaded`, … |
| `request_id`   | text        | yes  |                                                                                          |
| `subject_type` | text        | yes  | `query`, `document`, `grant`, `source`, …                                                |
| `subject_id`   | text        | yes  |                                                                                          |
| `payload`      | jsonb       | no   | the full event body (see below); GIN `jsonb_path_ops` index                              |
| `prev_hash`    | text        | yes  | previous event's `hash`; `NULL` only for the genesis event                               |
| `hash`         | text        | no   | UNIQUE                                                                                   |

Indexes: (`actor_id`, `occurred_at DESC`), (`action`, `occurred_at DESC`), (`subject_type`,
`subject_id`), GIN on `payload`. A `BEFORE UPDATE OR DELETE` trigger raises
`audit_events is append-only` (SQLSTATE `42501`).

**Hash formula.**

```text
hash = sha256( prev_hash || seq || canonical_json(payload) )
```

- Implemented by `app/core/hashing.chain_hash`: the three parts are joined with a literal `|`
  and hashed as UTF-8, `sha256_hex(f"{prev_hash or ''}|{seq}|{canonical_json(payload)}")`;
  `seq` is its decimal string; the digest is lowercase hex. The genesis event has
  `prev_hash = NULL` (hashed as the empty string).
- `canonical_json` = `json.dumps(payload, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)`; datetimes via `isoformat()`, UUIDs and decimals as strings, enums as
  their values, Pydantic models via `model_dump(mode="json")` (`app/core/hashing.py`).
- The payload **includes** `actor_id`, `action`, `occurred_at`, `request_id`, `subject_type` and
  `subject_id` (mirroring the columns), so the hash covers them; verification also checks that the
  columns equal the payload copies.
- Appends serialise on `pg_advisory_xact_lock(hashtext('audit_events'))`, read the head hash, take
  `seq` from `nextval(pg_get_serial_sequence('audit_events','seq'))`, compute the hash, then insert
  with that explicit `seq`. Sequence gaps (rolled-back appends) are harmless: verification follows
  `seq` order and checks each `prev_hash` against the previous row's `hash`.
- `GET /api/audit/verify` → `{ok, length, head_hash, first_broken_seq}`.

The `ask` event (`action` exactly `ask`; MCP `query` writes `mcp.query` with the same payload)
has this payload, which the audit UI (`frontend/lib/auditPayload.ts`) reads:

| Key                                          | Content                                                                                   |
| -------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `question`, `query_id`                       | the question and `queries.id`                                                             |
| `retrieved_document_ids`                     | every candidate document id from retrieval, **including denied ones** (auditor-only view) |
| `access_decisions[]`                         | one per candidate: `{document_id, decision, reason, matched_rule, permission_version}`    |
| `freshness_receipt`                          | `{receipt_id, overall_status, receipt_hash, evidence_items[]}` (allowed evidence only)    |
| `answer_text`, `abstained`, `abstain_reason` | the answer as returned                                                                    |
| `cited_document_ids`                         | documents cited by at least one claim                                                     |
| `grounding`                                  | `{verdict, coverage_ratio}`                                                               |
| `started_at`, `completed_at`                 | pipeline timestamps                                                                       |

Recommended additional keys (so the hash covers the columns): `schema_version`, `actor_id`,
`action`, `occurred_at`, `request_id`, `subject_type` (`query`), `subject_id` (the query id).

### 0001 `access_requests`

| Column         | Type        | Null | Notes                                                                               |
| -------------- | ----------- | ---- | ----------------------------------------------------------------------------------- |
| `id`           | uuid        | no   | PK                                                                                  |
| `document_id`  | uuid        | no   | **no FK, deliberately**: requests for missing and denied ids are stored identically |
| `principal_id` | text        | no   | FK `principals`                                                                     |
| `reason`       | text        | yes  | `AccessRequest.reason` is optional                                                  |
| `status`       | text        | no   | `pending` (default), `approved`, `denied`                                           |
| `created_at`   | timestamptz | no   |                                                                                     |
| `decided_at`   | timestamptz | yes  | CHECK: null exactly when `pending`                                                  |
| `decided_by`   | text        | yes  |                                                                                     |

### 0002 `sources`

| Column                     | Type        | Null | Notes                                                                         |
| -------------------------- | ----------- | ---- | ----------------------------------------------------------------------------- |
| `id`                       | text        | no   | PK, e.g. `confluence-ops`                                                     |
| `name`                     | text        | no   | UNIQUE                                                                        |
| `kind`                     | text        | no   | source kind (access_control vocabulary)                                       |
| `description`              | text        | no   | default `''`                                                                  |
| `local_path`               | text        | yes  | brain directory for `gbrain_import`                                           |
| `config`                   | jsonb       | no   | `{connector: "gbrain_import"\|"upload"\|<stub>, webhook_secret?, scope_key?}` |
| `last_sync_at`             | timestamptz | yes  |                                                                               |
| `newest_content_at`        | timestamptz | yes  | newest `provider_modified_at` seen                                            |
| `archived`                 | boolean     | no   | default `false`                                                               |
| `archived_at`              | timestamptz | yes  |                                                                               |
| `created_at`, `updated_at` | timestamptz | no   |                                                                               |

### 0002 `pages` (documents)

| Column                     | Type        | Null | Notes                                                                           |
| -------------------------- | ----------- | ---- | ------------------------------------------------------------------------------- |
| `id`                       | uuid        | no   | PK = `document_id` everywhere                                                   |
| `source_id`                | text        | no   | FK `sources` ON DELETE CASCADE                                                  |
| `slug`                     | text        | no   | UNIQUE (`source_id`, `slug`)                                                    |
| `type`                     | text        | no   | default `note`; free text (`runbook`, `issue`, `daily_log`, `email`, …)         |
| `page_kind`                | text        | no   | `markdown` (default), `code`, `image`                                           |
| `title`                    | text        | no   |                                                                                 |
| `compiled_truth`           | text        | no   | body above the `---` separator                                                  |
| `timeline`                 | text        | no   | raw `## Timeline` section below the separator                                   |
| `frontmatter`              | jsonb       | no   | full parsed frontmatter; GIN `jsonb_path_ops`                                   |
| `content_hash`             | text        | yes  | sha256 of the normalized page                                                   |
| `created_at`, `updated_at` | timestamptz | no   | index on `updated_at DESC`                                                      |
| `deleted_at`               | timestamptz | yes  | soft delete / tombstone; excluded from search                                   |
| `effective_date`           | timestamptz | yes  |                                                                                 |
| `search_vector`            | tsvector    | yes  | trigger: title **A**, compiled_truth **B** (first 256 KiB), timeline **C**; GIN |
| `source_kind`              | text        | no   | ours; equals the source's kind                                                  |
| `external_object_id`       | text        | yes  | ours; UNIQUE (`source_id`, `external_object_id`) WHERE NOT NULL                 |
| `classification`           | text        | no   | ours; default `internal`                                                        |
| `owner_principal_id`       | text        | yes  | ours; soft reference (imported owners may be unknown); indexed                  |
| `permission_version`       | text        | yes  | ours                                                                            |
| `provider_version`         | text        | yes  | ours                                                                            |
| `provider_modified_at`     | timestamptz | yes  | ours                                                                            |
| `evidence_class`           | text        | no   | ours; default `standard`                                                        |
| `ingest_status`            | text        | no   | ours; default `pending`                                                         |

Other indexes: `type`, trigram on `title`, partial on `deleted_at`.

### 0002 `content_chunks`

| Column          | Type                         | Null | Notes                                                                  |
| --------------- | ---------------------------- | ---- | ---------------------------------------------------------------------- |
| `id`            | uuid                         | no   | PK = `chunk_id`                                                        |
| `page_id`       | uuid                         | no   | FK `pages` ON DELETE CASCADE; UNIQUE (`page_id`, `chunk_index`)        |
| `chunk_index`   | integer                      | no   | `>= 0`                                                                 |
| `chunk_text`    | text                         | no   |                                                                        |
| `chunk_source`  | text                         | no   | `compiled_truth` (default) or `timeline`                               |
| `embedding`     | vector(`__EMBEDDING_DIMS__`) | yes  | HNSW `vector_cosine_ops`; null until embedded (partial index)          |
| `model`         | text                         | yes  | embedding model id                                                     |
| `token_count`   | integer                      | yes  |                                                                        |
| `embedded_at`   | timestamptz                  | yes  |                                                                        |
| `created_at`    | timestamptz                  | no   |                                                                        |
| `search_vector` | tsvector                     | —    | `GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED`; GIN |

### 0002 GBrain auxiliaries

| Table              | Columns                                                                                                                                        | Keys and indexes                                                                |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `links`            | `id`, `from_page_id`, `to_page_id` (FK pages CASCADE), `link_type` (`''`), `context` (`''`), `created_at`                                      | UNIQUE (`from_page_id`, `to_page_id`, `link_type`); index `to_page_id`          |
| `tags`             | `id`, `page_id` (FK CASCADE), `tag`                                                                                                            | UNIQUE (`page_id`, `tag`); index `tag`                                          |
| `timeline_entries` | `id`, `page_id` (FK CASCADE), `date` (date), `source` (`''`), `summary`, `detail` (`''`), `actor_id` (null for imported entries), `created_at` | index (`page_id`, `date`); UNIQUE (`page_id`, `date`, `md5(summary)`, `source`) |
| `raw_data`         | `id`, `page_id` (FK CASCADE), `source`, `data` (jsonb), `fetched_at`                                                                           | UNIQUE (`page_id`, `source`)                                                    |
| `page_versions`    | `id`, `page_id` (FK CASCADE), `compiled_truth`, `frontmatter`, `provider_version`, `snapshot_at`                                               | index (`page_id`, `snapshot_at DESC`)                                           |
| `ingest_log`       | `id`, `source_id`, `source_type`, `source_ref`, `pages_updated` (jsonb `[]`), `summary` (`''`), `actor_id`, `created_at`                       | index (`source_id`, `source_type`, `created_at DESC`)                           |

## Freshness range (0100–0199), owner Pavan

Ported from the approved spec and the branch data model, with the plan's status vocabulary. All
tables reference `sources` with ON DELETE CASCADE.

| Table                   | Key / uniqueness                                                   | Columns (beyond the key)                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Constraints and indexes                                                                                                                                                                                                                                                                                                        |
| ----------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sync_runs`             | PK `id` uuid; UNIQUE (`source_id`, `scope_key`, `idempotency_key`) | `connector_kind`, `trigger_kind`, `cursor_before`, `cursor_after`, `started_at` (not null, `now()`), `completed_at`, `status` (`queued`), `observed_count`, `applied_count`, `tombstoned_count`, `retry_count`, `failed_count` (int ≥ 0, default 0), `next_attempt_at`, `error_summary`, `created_at`, `updated_at`                                                                                                                                                       | index (`source_id`, `started_at DESC`); partial index (`status`, `next_attempt_at`) on non-terminal statuses                                                                                                                                                                                                                   |
| `connector_checkpoints` | PK (`source_id`, `scope_key`)                                      | `connector_kind`, `cursor_value`, `cursor_version` (int ≥ 0, default 0, CAS generation), `last_polled_at`, `last_reconciled_at`, `last_successful_run_id` (FK `sync_runs` SET NULL), `status` (`ready`), `created_at`, `updated_at` (nullable, default `now()`, because the lib model's are optional)                                                                                                                                                                     | a failed or partial run never becomes `last_successful_run_id` (service rule)                                                                                                                                                                                                                                                  |
| `source_change_events`  | PK `id` uuid; UNIQUE (`source_id`, `provider_event_id`)            | `scope_key`, `connector_kind`, `external_object_id`, `change_kind`, `provider_version`, `version_order`, `observed_at` (not null), `accepted_at` (not null, `now()`), `state` (`accepted`), `attempt_count`, `next_attempt_at`, `last_error_code`, `payload_hash` (not null), `applied_at`, `parked_at`, `noop_reason` (set when accounted as applied without calling `apply`, e.g. `older_version`)                                                                      | CHECK `parked` ⇒ `last_error_code` not null; CHECK `applied` ⇒ `applied_at` set and `parked_at` null, `parked` ⇒ the reverse; index (`state`, `next_attempt_at`); index (`source_id`, `external_object_id`)                                                                                                                    |
| `object_freshness`      | PK (`source_id`, `external_object_id`)                             | `connector_kind`, `page_id` (FK `pages` SET NULL), `page_slug`, `provider_version`, `version_order`, `content_hash`, `provider_modified_at`, `observed_at` (not null), `accepted_at`, `indexed_at`, `searchable_at`, `last_verified_at`, `verification_result`, `sync_path` (not null), `deleted_at`, `tombstone_version`, `freshness_status` (default `not_searchable`), `last_run_id` (FK `sync_runs` SET NULL), `created_at`, `updated_at` (nullable, default `now()`) | CHECK `searchable_at` null or (`indexed_at` not null and `searchable_at >= indexed_at`); CHECK `deleted_at` not null ⇒ status ≠ `fresh`; CHECK `deleted` ⇒ `deleted_at` set and `searchable_at` null; CHECK `fresh` ⇒ `searchable_at` set; indexes `page_id`, `freshness_status`. `page_id` = `freshness.IndexOutcome.page_id` |
| `freshness_policies`    | PK (`policy_id`, `schema_version`)                                 | `connector_kind`, `evidence_class`, `max_index_age_seconds`, `max_verification_age_seconds` (int ≥ 0), `require_live_verification` (default false), `failure_action`, `status` (`draft`), `effective_at`, `retired_at`, `created_at`, `updated_at`                                                                                                                                                                                                                        | UNIQUE (`connector_kind`, `evidence_class`) WHERE `status = 'active'`; CHECK non-draft ⇒ `effective_at`; CHECK critical ⇒ `failure_action ≠ allow_with_warning`                                                                                                                                                                |
| `freshness_receipts`    | PK `receipt_id` uuid; UNIQUE (`request_key`)                       | `schema_version`, `request_payload_hash`, `created_at`, `policy_id`, `policy_schema_version` (**nullable**: set only when every item used one policy revision; otherwise each item carries its own; soft references), `evidence_items` (jsonb `[]`), `oldest_evidence_age_seconds`, `overall_status`, `receipt_hash`                                                                                                                                                      | index `created_at DESC`; append-only by service contract (same key + same hash → existing; different hash → `ReceiptConflict`)                                                                                                                                                                                                 |

Receipt `evidence_items[]` (one `ReceiptItem` per evaluated evidence object, input order, unsafe
items retained): `source_id, external_object_id, connector_kind, evidence_class, page_id,
page_slug, policy_id, policy_schema_version, provider_version, version_order, content_hash,
provider_modified_at, observed_at, accepted_at, indexed_at, searchable_at, last_verified_at,
verification_result, sync_path, age_seconds, budget_seconds, freshness_status, tombstoned,
safe_to_use, fallback_action, reason` (`reason` is a stable code for a non-fresh status, e.g.
`index_age_exceeded`; `fallback_action` is `null` for safe items). A receipt only ever contains evidence
that already passed the access filter.

Seeded policies (`backend/seed/policies.yaml`): one active `critical` and one active `standard`
policy per connector kind. Critical: index 3,600 s, verification 300 s, live verification
required, `omit`. Standard: 86,400 s, 3,600 s, no live check, `allow_with_warning`.

## Access-control range (0200–0299), owner Chai

### `source_permissions`

| Column               | Type        | Null | Notes                                                      |
| -------------------- | ----------- | ---- | ---------------------------------------------------------- |
| `page_id`            | uuid        | no   | PK, FK `pages` ON DELETE CASCADE                           |
| `kind`               | text        | no   | source kind; discriminator of `raw`                        |
| `raw`                | jsonb       | no   | the platform permission object exactly as captured (below) |
| `permission_version` | text        | yes  | stamped on every `AccessDecision`                          |
| `captured_at`        | timestamptz | no   | default `now()`                                            |
| `connector_run_id`   | uuid        | yes  | soft reference to `sync_runs` (uploads have no run)        |

### `grants`

| Column         | Type        | Null | Notes                                                         |
| -------------- | ----------- | ---- | ------------------------------------------------------------- |
| `id`           | uuid        | no   | PK                                                            |
| `document_id`  | uuid        | no   | FK `pages` ON DELETE CASCADE                                  |
| `subject_type` | text        | no   | `principal`, `group`, `role`                                  |
| `subject_id`   | text        | no   | index (`subject_type`, `subject_id`)                          |
| `effect`       | text        | no   | `allow`, `deny`                                               |
| `scope`        | text        | no   | default `read`                                                |
| `granted_by`   | text        | no   | principal id or `system:seed`                                 |
| `granted_at`   | timestamptz | no   |                                                               |
| `revoked_at`   | timestamptz | yes  | CHECK: set together with `revoked_by`; rows are never deleted |
| `revoked_by`   | text        | yes  |                                                               |
| `reason`       | text        | yes  |                                                               |

Indexes: partial (`document_id`) WHERE `revoked_at IS NULL`; UNIQUE (`document_id`,
`subject_type`, `subject_id`, `effect`, `scope`) WHERE `revoked_at IS NULL` (re-seeding restores a
grant revoked during a demo instead of duplicating an active one).

## Groundedness range (0300–0399), owner Raphael

`0300_groundedness_init.sql` is a comment-only placeholder. Grounding reports are stored in
`queries.grounding_report` and summarised (hash + verdict) in the `ask` audit payload.

## Imported page frontmatter

Pages (seeded corpus, any GBrain brain directory imported with `gbrain_import`, and uploads with
frontmatter) are Markdown with YAML frontmatter. The importer is implemented against this schema;
`backend/seed/corpus/README.md` holds the same table with the scenario map.

```yaml
title: Payment Rail Failover Runbook
type: runbook # free text page type (gbrain `type`)
slug: runbooks/payment-rail-failover # optional; default = relative path without .md
source_kind: confluence # must equal the source.yaml kind
external_object_id: "CONF-OPS-1042"
provider_version: "7"
version_order: 7 # optional int for comparable versions
provider_modified_at: "2026-10-01T09:30:00Z"
classification: internal # public|internal|confidential|restricted
owner: priya.nair # principal id or null
evidence_class: critical # critical|standard
permission_version: "pv-2026-10-01-1"
permissions: # raw per-platform semantics; shape depends on source_kind
  kind: confluence
  space_key: OPS
  page_id: "1042"
  space_view_users: []
  space_view_groups: [finance-ops, engineering]
  page_view_users: []
  page_view_groups: []
  ancestors: []
grants: [] # list of {subject_type: principal|group|role, subject_id, effect: allow|deny}
tags: [payments, runbook]
simulate: # OPTIONAL demo-only drift block honoured by the gbrain_import connector's head()
  live_version: "8" # provider now reports this version → verification says stale
  deleted: false
  indexed_at: "2026-10-01T10:00:00Z"
```

Body = compiled truth (Markdown), then a line that is exactly `---`, then `## Timeline` with
entries such as `- **2026-10-01** | Confluence — What happened.` (ISO date; regex
`^- \*\*(\d{4}-\d{2}-\d{2})\*\* \| (.+?) — (.+)$`). Quote timestamps and versions so YAML keeps
them as strings.

`permissions` shapes by kind (field names are exact):

| Kind         | Shape                                                                                                                                                                         |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `confluence` | `{kind, space_key, page_id, space_view_users[], space_view_groups[], page_view_users[], page_view_groups[], ancestors[]}`; empty page lists inherit the space                 |
| `jira`       | `{kind, project_key, issue_key, project_roles: {RoleName: [member ids]}, browse_roles: [RoleName], issue_security_level: str\|null, security_level_members: []}`              |
| `slack`      | `{kind, workspace_id, channel_id, channel_type: public\|private\|dm\|mpdm, member_ids: [], workspace_member_ids: [] \| null}`                                                 |
| `gdrive`     | `{kind, file_id, parent_ids: [], acl: [{type: user\|group\|domain\|anyone, role: owner\|organizer\|writer\|commenter\|reader, email_or_domain: str\|null, inherited: bool}]}` |
| `email`      | `{kind, message_id, from_, to: [], cc: [], bcc: []}`                                                                                                                          |
| `upload`     | `{kind, owner_principal_id, shared_with_principals: [], shared_with_groups: []}`                                                                                              |

Membership is matched against the principal's `external_identities[kind]` (Slack member ids like
`U_PRIYA`; Jira and Confluence account ids equal principal ids; Drive and email use the mailbox
address, a Drive `domain` entry matching its domain) and against group ids (a Drive `group`
entry's `email_or_domain` is the group id). `mcp_external` permissions
(`{kind, app_name, allowed_principals, allowed_groups}`) exist in the library but no seeded page
uses them.

Ingestion maps frontmatter to rows: page columns from the scalar fields (`owner` →
`owner_principal_id`); `permissions` → `source_permissions.raw`; `grants` → `grants` rows with
`granted_by = system:seed` (or the importing actor) and `scope = read`; `tags` → `tags`; timeline
entries → `timeline_entries`; the whole frontmatter → `pages.frontmatter`.

## Data Integrity Rules

- A page is identified by (`source_id`, `slug`); a provider object by (`source_id`,
  `external_object_id`). Never identify a page by slug alone.
- Access decisions are computed in Python by `access_control` from `source_permissions` and
  `grants`; there is no flattened ACL column and no permission cache.
- Revocation updates `grants.revoked_at`; grant rows are never deleted.
- `audit_events` rows are never updated or deleted (trigger + hash chain).
- An older comparable provider version never overwrites a newer one; a tombstoned object is never
  `fresh`; `searchable_at >= indexed_at`.
- Asker-visible payloads never contain denied documents, denied counts or denied-document metadata.

## Migration Notes

- **Files.** `infra/postgres/migrations/NNNN_<owner>_<topic>.sql`, applied in filename order by
  `app/db/migrate.py` (sync psycopg): create `schema_migrations` if missing, skip applied files,
  substitute `__EMBEDDING_DIMS__` with `EMBEDDING_DIM`, run each file in **one transaction**, and
  record its checksum. In compose the directory is mounted read-only at `/app/migrations`
  (`MIGRATIONS_DIR`).
- **Owner ranges.** `0001–0099` core (Raphael), `0100–0199` freshness (Pavan), `0200–0299`
  access_control (Chai), `0300–0399` groundedness (Raphael). Each owner only adds files in their
  own range.
- **References only downward.** A file may reference tables from its own range or a lower range
  (0200 → `pages` is fine; 0001 → `freshness_receipts` is not, hence the soft references).
- **Idempotent.** `CREATE TABLE/INDEX IF NOT EXISTS`; triggers, constraints and types are created
  inside `DO $$ … $$` guards that check the catalog first. Every file must also run top-to-bottom
  inside one psycopg transaction: no `\` psql meta-commands and no `CREATE INDEX CONCURRENTLY`.
- **Never edit an applied file.** Add `0003_…`, `0101_…`, etc. The checksum makes edits visible.
- **Extensions.** `infra/postgres/init/01_extensions.sql` runs on first volume init; `0001`
  repeats `CREATE EXTENSION IF NOT EXISTS` for databases not created by compose.
- **Embedding dimension.** Changing `EMBEDDING_DIM` after the first migrate needs `make reset`.

## Open Data Questions

- Should critical-evidence index age be measured from the last confirming reconcile or
  verification rather than `indexed_at`? (Pavan; affects how long seeded critical pages stay fresh.)
- Do we persist a freshness receipt for every ask or only for demo/audit flows? The MVP persists
  every ask's receipt so audit reconstruction always has one.
- Final upload cap numbers (TBD by Raphael).
