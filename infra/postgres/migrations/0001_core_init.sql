-- 0001_core_init.sql
-- Owner: core (Raphael) · range 0001-0099.
-- Rules: idempotent (IF NOT EXISTS / DO-guards), runnable top-to-bottom in ONE transaction by
-- psycopg (no psql meta-commands, no CONCURRENTLY). A file may reference only tables from its own
-- range or a LOWER range. Applied by app/db/migrate.py in filename order; recorded in
-- schema_migrations with a checksum. Never edit an applied file: add a new numbered file instead.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------------------------
-- schema_migrations: the runner's ledger (the runner also creates it before applying 0001).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum   TEXT        NOT NULL
);

-- ---------------------------------------------------------------------------------------------
-- Identity: seeded personas (no auth; actor resolved from X-Actor-Id). See docs/SECURITY_REVIEW.md.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS principals (
    id                  TEXT        PRIMARY KEY,
    display_name        TEXT        NOT NULL,
    email               TEXT,
    roles               TEXT[]      NOT NULL DEFAULT '{}',
    external_identities JSONB       NOT NULL DEFAULT '{}'::jsonb,
    is_active           BOOLEAN     NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS groups (
    id         TEXT        PRIMARY KEY,
    name       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS group_memberships (
    principal_id TEXT NOT NULL REFERENCES principals (id) ON DELETE CASCADE,
    group_id     TEXT NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    PRIMARY KEY (principal_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_group_memberships_group ON group_memberships (group_id);

-- ---------------------------------------------------------------------------------------------
-- Uploads + usage counters (caps keep the Tencent free trial safe; numbers TBD, see .env.example).
-- uploads.page_id -> pages(id) FK is added in 0002 once `pages` exists.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uploads (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id     TEXT        NOT NULL REFERENCES principals (id),
    page_id      UUID,
    filename     TEXT        NOT NULL,
    bytes        BIGINT      NOT NULL CHECK (bytes >= 0),
    content_type TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_uploads_actor_created ON uploads (actor_id, created_at DESC);

-- Keys: 'uploads_total' (all-time, stored on the sentinel day 1970-01-01), 'uploads:<actor_id>'
-- (per UTC day), 'embedding_calls' (per UTC day). Increment with
-- INSERT ... ON CONFLICT (day, key) DO UPDATE ... WHERE usage_counters.count < <limit> RETURNING count
-- (no row returned => cap hit => 429 cap_exceeded).
CREATE TABLE IF NOT EXISTS usage_counters (
    day        DATE        NOT NULL,
    key        TEXT        NOT NULL,
    count      BIGINT      NOT NULL DEFAULT 0 CHECK (count >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (day, key)
);

-- ---------------------------------------------------------------------------------------------
-- queries: one row per governed ask (REST /api/ask or MCP `query`).
-- freshness_receipt_id is a soft reference to freshness_receipts (range 0100 > 0001, so no FK).
-- audit_event_id is a soft reference to audit_events (written after the audit append).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS queries (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id             TEXT        NOT NULL REFERENCES principals (id),
    request_id           TEXT,
    question             TEXT        NOT NULL,
    status               TEXT        NOT NULL,
    answer_text          TEXT,
    citations            JSONB       NOT NULL DEFAULT '[]'::jsonb,
    grounding_report     JSONB,
    freshness_receipt_id UUID,
    access_summary       JSONB,
    audit_event_id       UUID,
    latency_ms           INTEGER     CHECK (latency_ms IS NULL OR latency_ms >= 0),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_queries_actor_created ON queries (actor_id, created_at DESC);

-- ---------------------------------------------------------------------------------------------
-- audit_events: append-only, hash-chained (app/core/hashing.chain_hash):
--   hash = sha256_hex( prev_hash || seq || canonical_json(payload) ), joined with '|' in UTF-8,
--   i.e. sha256(f"{prev_hash or ''}|{seq}|{canonical_json(payload)}"); the genesis event has
--   prev_hash NULL. Appends serialise on pg_advisory_xact_lock(hashtext('audit_events')) and
--   take seq from nextval() BEFORE hashing, then INSERT with that explicit seq.
-- UPDATE/DELETE are rejected by trigger; tampering beyond that is caught by GET /api/audit/verify.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_events (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    seq          BIGSERIAL   NOT NULL UNIQUE,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id     TEXT,
    action       TEXT        NOT NULL,
    request_id   TEXT,
    subject_type TEXT,
    subject_id   TEXT,
    payload      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    prev_hash    TEXT,
    hash         TEXT        NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor_time ON audit_events (actor_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_action_time ON audit_events (action, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_subject ON audit_events (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_payload ON audit_events USING GIN (payload jsonb_path_ops);

CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger
    LANGUAGE plpgsql AS
$fn$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only'
        USING ERRCODE = '42501', DETAIL = TG_OP;
END;
$fn$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_audit_events_append_only'
          AND tgrelid = 'audit_events'::regclass
    ) THEN
        CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
    END IF;
END
$$;

-- ---------------------------------------------------------------------------------------------
-- access_requests: "request access" inbox. POST always answers 202 whether or not the document
-- exists or is visible, so document_id deliberately has NO foreign key (a FK would make requests
-- for nonexistent ids behave differently from requests for denied ones).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS access_requests (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID        NOT NULL,
    principal_id TEXT        NOT NULL REFERENCES principals (id),
    reason       TEXT,
    status       TEXT        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'approved', 'denied')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at   TIMESTAMPTZ,
    decided_by   TEXT,
    CHECK ((status = 'pending') = (decided_at IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_access_requests_status ON access_requests (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_requests_document ON access_requests (document_id);
CREATE INDEX IF NOT EXISTS idx_access_requests_principal ON access_requests (principal_id);
