-- 0100_freshness_init.sql
-- Owner: freshness (Pavan) · range 0100-0199. Initial version ported from the approved freshness
-- spec (docs/superpowers/specs/2026-09-24-gbrain-freshness-foundation-design.md) and the branch
-- data model (origin/codex/gbrain-freshness-foundation:docs/tencent/FRESHNESS_DATA_MODEL.md),
-- with the plan's vocabulary: searchable_current -> 'fresh', pending -> 'not_searchable', and
-- connector kinds widened to the eight ConnectorKind values of backend/libs/freshness.
-- Rules: idempotent, one transaction, no psql meta-commands, no CONCURRENTLY; may reference only
-- tables in 0100-0199 or the core range 0001-0099 (sources, pages). Never edit an applied file.

-- ---------------------------------------------------------------------------------------------
-- sync_runs: durable run receipts (created first so other tables can reference it).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_runs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key  TEXT        NOT NULL,
    source_id        TEXT        NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    scope_key        TEXT        NOT NULL,
    connector_kind   TEXT        NOT NULL
                                 CHECK (connector_kind IN ('confluence', 'slack', 'jira',
                                                           'google_drive', 'email', 'upload',
                                                           'gbrain_import', 'mcp_external')),
    trigger_kind     TEXT        NOT NULL
                                 CHECK (trigger_kind IN ('webhook', 'delta', 'reconcile',
                                                         'live_verify')),
    cursor_before    TEXT,
    cursor_after     TEXT,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    status           TEXT        NOT NULL DEFAULT 'queued'
                                 CHECK (status IN ('queued', 'running', 'completed', 'partial',
                                                   'failed', 'parked')),
    observed_count   INTEGER     NOT NULL DEFAULT 0 CHECK (observed_count >= 0),
    applied_count    INTEGER     NOT NULL DEFAULT 0 CHECK (applied_count >= 0),
    tombstoned_count INTEGER     NOT NULL DEFAULT 0 CHECK (tombstoned_count >= 0),
    retry_count      INTEGER     NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    failed_count     INTEGER     NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    next_attempt_at  TIMESTAMPTZ,
    error_summary    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sync_runs_source_scope_idem_key UNIQUE (source_id, scope_key, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_source_started ON sync_runs (source_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_runs_status_next
    ON sync_runs (status, next_attempt_at)
    WHERE status IN ('queued', 'running', 'partial', 'failed', 'parked');

-- ---------------------------------------------------------------------------------------------
-- connector_checkpoints: one durable cursor per connector scope; CAS on cursor_version.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS connector_checkpoints (
    source_id              TEXT        NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    scope_key              TEXT        NOT NULL,
    connector_kind         TEXT        NOT NULL
                                       CHECK (connector_kind IN ('confluence', 'slack', 'jira',
                                                                 'google_drive', 'email', 'upload',
                                                                 'gbrain_import', 'mcp_external')),
    cursor_value           TEXT,
    cursor_version         INTEGER     NOT NULL DEFAULT 0 CHECK (cursor_version >= 0),
    last_polled_at         TIMESTAMPTZ,
    last_reconciled_at     TIMESTAMPTZ,
    last_successful_run_id UUID        REFERENCES sync_runs (id) ON DELETE SET NULL,
    status                 TEXT        NOT NULL DEFAULT 'ready'
                                       CHECK (status IN ('ready', 'polling', 'degraded', 'paused')),
    -- nullable: freshness.ConnectorCheckpoint carries optional created_at/updated_at
    created_at             TIMESTAMPTZ DEFAULT now(),
    updated_at             TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (source_id, scope_key)
);

-- ---------------------------------------------------------------------------------------------
-- source_change_events: append-oriented acceptance + retry ledger. Duplicate provider events
-- (same source_id, provider_event_id) return the existing row and never mutate content twice.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_change_events (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id          TEXT        NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    scope_key          TEXT        NOT NULL,
    connector_kind     TEXT        NOT NULL
                                   CHECK (connector_kind IN ('confluence', 'slack', 'jira',
                                                             'google_drive', 'email', 'upload',
                                                             'gbrain_import', 'mcp_external')),
    provider_event_id  TEXT        NOT NULL,
    external_object_id TEXT        NOT NULL,
    change_kind        TEXT        NOT NULL
                                   CHECK (change_kind IN ('upsert', 'delete', 'metadata_change')),
    provider_version   TEXT,
    version_order      BIGINT,
    observed_at        TIMESTAMPTZ NOT NULL,
    accepted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    state              TEXT        NOT NULL DEFAULT 'accepted'
                                   CHECK (state IN ('accepted', 'processing', 'applied', 'parked')),
    attempt_count      INTEGER     NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at    TIMESTAMPTZ,
    last_error_code    TEXT,
    payload_hash       TEXT        NOT NULL,
    applied_at         TIMESTAMPTZ,
    parked_at          TIMESTAMPTZ,
    -- set when the event was accounted as applied without calling apply (e.g. 'older_version')
    noop_reason        TEXT,
    CONSTRAINT source_change_events_source_provider_event_key
        UNIQUE (source_id, provider_event_id),
    CONSTRAINT source_change_events_parked_has_error
        CHECK (state <> 'parked' OR last_error_code IS NOT NULL),
    CONSTRAINT source_change_events_terminal_accounting
        CHECK ((state <> 'applied' OR (applied_at IS NOT NULL AND parked_at IS NULL))
               AND (state <> 'parked' OR (parked_at IS NOT NULL AND applied_at IS NULL)))
);
CREATE INDEX IF NOT EXISTS idx_change_events_state_next
    ON source_change_events (state, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_change_events_object
    ON source_change_events (source_id, external_object_id);

-- ---------------------------------------------------------------------------------------------
-- object_freshness: current freshness state per provider object (one row per object, kept after
-- deletion as tombstone proof). page_id is freshness.IndexOutcome.page_id (nullable FK to pages).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS object_freshness (
    source_id            TEXT        NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    external_object_id   TEXT        NOT NULL,
    connector_kind       TEXT        NOT NULL
                                     CHECK (connector_kind IN ('confluence', 'slack', 'jira',
                                                               'google_drive', 'email', 'upload',
                                                               'gbrain_import', 'mcp_external')),
    page_id              UUID        REFERENCES pages (id) ON DELETE SET NULL,
    page_slug            TEXT,
    provider_version     TEXT,
    version_order        BIGINT,
    content_hash         TEXT,
    provider_modified_at TIMESTAMPTZ,
    observed_at          TIMESTAMPTZ NOT NULL,
    accepted_at          TIMESTAMPTZ,
    indexed_at           TIMESTAMPTZ,
    searchable_at        TIMESTAMPTZ,
    last_verified_at     TIMESTAMPTZ,
    verification_result  TEXT
                         CHECK (verification_result IS NULL
                                OR verification_result IN ('fresh', 'stale', 'unknown',
                                                           'not_required')),
    sync_path            TEXT        NOT NULL
                                     CHECK (sync_path IN ('webhook', 'delta', 'reconcile',
                                                          'live_verify')),
    deleted_at           TIMESTAMPTZ,
    tombstone_version    TEXT,
    freshness_status     TEXT        NOT NULL DEFAULT 'not_searchable'
                                     CHECK (freshness_status IN ('fresh', 'stale', 'unknown',
                                                                 'not_searchable', 'deleted')),
    last_run_id          UUID        REFERENCES sync_runs (id) ON DELETE SET NULL,
    -- nullable: freshness.ObjectFreshness carries optional created_at/updated_at
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (source_id, external_object_id),
    CONSTRAINT object_freshness_searchable_after_indexed
        CHECK (searchable_at IS NULL OR (indexed_at IS NOT NULL AND searchable_at >= indexed_at)),
    CONSTRAINT object_freshness_tombstone_never_fresh
        CHECK (deleted_at IS NULL OR freshness_status <> 'fresh'),
    CONSTRAINT object_freshness_deleted_is_tombstoned
        CHECK (freshness_status <> 'deleted' OR (deleted_at IS NOT NULL AND searchable_at IS NULL)),
    CONSTRAINT object_freshness_fresh_is_searchable
        CHECK (freshness_status <> 'fresh' OR searchable_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_object_freshness_page ON object_freshness (page_id);
CREATE INDEX IF NOT EXISTS idx_object_freshness_status ON object_freshness (freshness_status);

-- ---------------------------------------------------------------------------------------------
-- freshness_policies: immutable versioned budgets; at most one ACTIVE row per
-- (connector_kind, evidence_class).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS freshness_policies (
    policy_id                    TEXT        NOT NULL,
    schema_version               INTEGER     NOT NULL CHECK (schema_version >= 1),
    connector_kind               TEXT        NOT NULL
                                             CHECK (connector_kind IN ('confluence', 'slack',
                                                                       'jira', 'google_drive',
                                                                       'email', 'upload',
                                                                       'gbrain_import',
                                                                       'mcp_external')),
    evidence_class               TEXT        NOT NULL
                                             CHECK (evidence_class IN ('critical', 'standard')),
    max_index_age_seconds        INTEGER     NOT NULL CHECK (max_index_age_seconds >= 0),
    max_verification_age_seconds INTEGER     NOT NULL CHECK (max_verification_age_seconds >= 0),
    require_live_verification    BOOLEAN     NOT NULL DEFAULT false,
    failure_action               TEXT        NOT NULL
                                             CHECK (failure_action IN ('omit', 'abstain',
                                                                       'allow_with_warning')),
    status                       TEXT        NOT NULL DEFAULT 'draft'
                                             CHECK (status IN ('draft', 'active', 'retired')),
    effective_at                 TIMESTAMPTZ,
    retired_at                   TIMESTAMPTZ,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (policy_id, schema_version),
    CONSTRAINT freshness_policies_effective_when_published
        CHECK (status = 'draft' OR effective_at IS NOT NULL),
    CONSTRAINT freshness_policies_critical_never_warns
        CHECK (evidence_class <> 'critical' OR failure_action <> 'allow_with_warning')
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_freshness_policies_one_active
    ON freshness_policies (connector_kind, evidence_class)
    WHERE status = 'active';

-- ---------------------------------------------------------------------------------------------
-- freshness_receipts: immutable snapshots for demo + audit reconstruction. request_key is
-- globally unique: same key + same request_payload_hash => existing receipt; different hash =>
-- ReceiptConflict. policy_id/policy_schema_version are set only when every item was evaluated
-- under one policy revision; otherwise NULL and each evidence_items[] entry carries its own
-- policy_id/policy_schema_version (soft references, no FK).
-- evidence_items only ever contains evidence that already passed the access filter.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS freshness_receipts (
    receipt_id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_version              INTEGER     NOT NULL CHECK (schema_version >= 1),
    request_key                 TEXT        NOT NULL,
    request_payload_hash        TEXT        NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    policy_id                   TEXT,
    policy_schema_version       INTEGER,
    evidence_items              JSONB       NOT NULL DEFAULT '[]'::jsonb,
    oldest_evidence_age_seconds INTEGER
                                CHECK (oldest_evidence_age_seconds IS NULL
                                       OR oldest_evidence_age_seconds >= 0),
    overall_status              TEXT        NOT NULL
                                            CHECK (overall_status IN ('fresh', 'stale', 'unknown',
                                                                      'not_required', 'mixed')),
    receipt_hash                TEXT        NOT NULL,
    CONSTRAINT freshness_receipts_request_key_key UNIQUE (request_key)
);
CREATE INDEX IF NOT EXISTS idx_freshness_receipts_created ON freshness_receipts (created_at DESC);
