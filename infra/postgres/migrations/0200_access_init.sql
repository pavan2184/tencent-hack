-- 0200_access_init.sql
-- Owner: access_control (Chai) · range 0200-0299.
-- Raw per-platform permission snapshots (NOT flattened) and explicit grants. Decisions are made
-- in Python by access_control.DefaultAccessPolicy before any evidence reaches an LLM; these tables
-- only store the inputs. Rules: idempotent, one transaction, no psql meta-commands, no
-- CONCURRENTLY; may reference only 0200-0299 or lower ranges (pages from core). Never edit an
-- applied file.

-- ---------------------------------------------------------------------------------------------
-- source_permissions: one raw snapshot per document. raw holds the discriminated permissions
-- object exactly as captured (shape depends on kind; see docs/DATA_MODEL.md).
-- connector_run_id is a soft reference to sync_runs (uploads have no run).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_permissions (
    page_id            UUID        PRIMARY KEY REFERENCES pages (id) ON DELETE CASCADE,
    kind               TEXT        NOT NULL
                                   CHECK (kind IN ('confluence', 'jira', 'slack', 'gdrive',
                                                   'email', 'upload', 'gbrain_import',
                                                   'mcp_external')),
    raw                JSONB       NOT NULL,
    permission_version TEXT,
    captured_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    connector_run_id   UUID
);

-- ---------------------------------------------------------------------------------------------
-- grants: explicit allow/deny per document and subject. Revocation sets revoked_at + revoked_by
-- (rows are never deleted, so the audit trail can show what was revoked and when).
-- granted_by / revoked_by are principal ids or 'system:<component>' (e.g. 'system:seed').
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grants (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  UUID        NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    subject_type TEXT        NOT NULL CHECK (subject_type IN ('principal', 'group', 'role')),
    subject_id   TEXT        NOT NULL,
    effect       TEXT        NOT NULL CHECK (effect IN ('allow', 'deny')),
    scope        TEXT        NOT NULL DEFAULT 'read',
    granted_by   TEXT        NOT NULL,
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ,
    revoked_by   TEXT,
    reason       TEXT,
    CONSTRAINT grants_revocation_complete CHECK ((revoked_at IS NULL) = (revoked_by IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_grants_document_active
    ON grants (document_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_grants_subject ON grants (subject_type, subject_id);
-- At most one ACTIVE grant per (document, subject, effect, scope): makes `make seed` idempotent
-- and lets a re-seed restore a grant that was revoked during a demo.
CREATE UNIQUE INDEX IF NOT EXISTS uq_grants_active
    ON grants (document_id, subject_type, subject_id, effect, scope)
    WHERE revoked_at IS NULL;
