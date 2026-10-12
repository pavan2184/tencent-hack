-- 0002_core_gbrain_pages.sql
-- Owner: core (Raphael) · range 0001-0099. Port of gbrain's page model (github.com/garrytan/gbrain,
-- MIT): sources, pages, content_chunks, links, tags, timeline_entries, raw_data, page_versions,
-- ingest_log. Deviations from gbrain: UUID ids, extra governed columns on pages (marked "ours"),
-- compiled_truth indexed in pages.search_vector (truncated), chunk search_vector GENERATED.
-- `pages` IS the documents table: every upload, message, issue, file and log is a page.
-- Rules: idempotent, one transaction, no psql meta-commands, no CONCURRENTLY; references only this
-- range or lower. __EMBEDDING_DIMS__ is substituted by app/db/migrate.py from EMBEDDING_DIM.

-- ---------------------------------------------------------------------------------------------
-- sources: the scoping unit (gbrain). kind = platform permission semantics; config.connector =
-- the connector that syncs it ('gbrain_import' for the seeded corpus, 'upload' for uploads).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id                TEXT        PRIMARY KEY,
    name              TEXT        NOT NULL UNIQUE,
    kind              TEXT        NOT NULL
                                  CHECK (kind IN ('confluence', 'jira', 'slack', 'gdrive', 'email',
                                                  'upload', 'gbrain_import', 'mcp_external')),
    description       TEXT        NOT NULL DEFAULT '',
    local_path        TEXT,
    config            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    last_sync_at      TIMESTAMPTZ,
    newest_content_at TIMESTAMPTZ,
    archived          BOOLEAN     NOT NULL DEFAULT false,
    archived_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------------------------
-- pages: gbrain two-layer page (compiled truth above `---`, append-only timeline below).
-- Identity is (source_id, slug); external_object_id is the provider's id within the source.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pages (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id            TEXT        NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    slug                 TEXT        NOT NULL,
    type                 TEXT        NOT NULL DEFAULT 'note',
    page_kind            TEXT        NOT NULL DEFAULT 'markdown'
                                     CHECK (page_kind IN ('markdown', 'code', 'image')),
    title                TEXT        NOT NULL,
    compiled_truth       TEXT        NOT NULL DEFAULT '',
    timeline             TEXT        NOT NULL DEFAULT '',
    frontmatter          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    content_hash         TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at           TIMESTAMPTZ,
    effective_date       TIMESTAMPTZ,
    search_vector        TSVECTOR,
    -- ours: governed-document columns
    source_kind          TEXT        NOT NULL
                                     CHECK (source_kind IN ('confluence', 'jira', 'slack', 'gdrive',
                                                            'email', 'upload', 'gbrain_import',
                                                            'mcp_external')),
    external_object_id   TEXT,
    classification       TEXT        NOT NULL DEFAULT 'internal'
                                     CHECK (classification IN ('public', 'internal',
                                                               'confidential', 'restricted')),
    owner_principal_id   TEXT,
    permission_version   TEXT,
    provider_version     TEXT,
    provider_modified_at TIMESTAMPTZ,
    evidence_class       TEXT        NOT NULL DEFAULT 'standard'
                                     CHECK (evidence_class IN ('critical', 'standard')),
    ingest_status        TEXT        NOT NULL DEFAULT 'pending',
    CONSTRAINT pages_source_slug_key UNIQUE (source_id, slug)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pages_source_external_object
    ON pages (source_id, external_object_id)
    WHERE external_object_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pages_search ON pages USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_pages_type ON pages (type);
CREATE INDEX IF NOT EXISTS idx_pages_frontmatter ON pages USING GIN (frontmatter jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_pages_title_trgm ON pages USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pages_updated_at_desc ON pages (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pages_owner ON pages (owner_principal_id);
CREATE INDEX IF NOT EXISTS idx_pages_deleted_at ON pages (deleted_at) WHERE deleted_at IS NOT NULL;

-- search_vector: title A, compiled_truth B, timeline C (english). compiled_truth is truncated to
-- 256 KiB so a maximum-size upload can never overflow Postgres's 1 MB tsvector limit.
CREATE OR REPLACE FUNCTION pages_search_vector_update() RETURNS trigger
    LANGUAGE plpgsql AS
$fn$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', left(coalesce(NEW.compiled_truth, ''), 262144)), 'B') ||
        setweight(to_tsvector('english', left(coalesce(NEW.timeline, ''), 262144)), 'C');
    RETURN NEW;
END;
$fn$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_pages_search_vector'
          AND tgrelid = 'pages'::regclass
    ) THEN
        CREATE TRIGGER trg_pages_search_vector
            BEFORE INSERT OR UPDATE OF title, compiled_truth, timeline ON pages
            FOR EACH ROW EXECUTE FUNCTION pages_search_vector_update();
    END IF;
END
$$;

-- ---------------------------------------------------------------------------------------------
-- content_chunks: retrieval units. Hybrid search = chunk tsvector (GIN) + embedding (HNSW cosine).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_chunks (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id       UUID        NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    chunk_index   INTEGER     NOT NULL CHECK (chunk_index >= 0),
    chunk_text    TEXT        NOT NULL,
    chunk_source  TEXT        NOT NULL DEFAULT 'compiled_truth'
                              CHECK (chunk_source IN ('compiled_truth', 'timeline')),
    embedding     vector(__EMBEDDING_DIMS__),
    model         TEXT,
    token_count   INTEGER     CHECK (token_count IS NULL OR token_count >= 0),
    embedded_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_vector TSVECTOR    GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED,
    CONSTRAINT content_chunks_page_index_key UNIQUE (page_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON content_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_search_vector ON content_chunks USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_chunks_unembedded
    ON content_chunks (page_id, chunk_index) WHERE embedding IS NULL;

-- ---------------------------------------------------------------------------------------------
-- links, tags, timeline_entries, raw_data, page_versions, ingest_log (gbrain auxiliaries).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS links (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    from_page_id UUID        NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    to_page_id   UUID        NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    link_type    TEXT        NOT NULL DEFAULT '',
    context      TEXT        NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT links_from_to_type_key UNIQUE (from_page_id, to_page_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_links_to ON links (to_page_id);

CREATE TABLE IF NOT EXISTS tags (
    id      UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id UUID NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    CONSTRAINT tags_page_tag_key UNIQUE (page_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags (tag);

CREATE TABLE IF NOT EXISTS timeline_entries (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id    UUID        NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    date       DATE        NOT NULL,
    source     TEXT        NOT NULL DEFAULT '',
    summary    TEXT        NOT NULL,
    detail     TEXT        NOT NULL DEFAULT '',
    actor_id   TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_timeline_page_date ON timeline_entries (page_id, date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_timeline_dedup
    ON timeline_entries (page_id, date, md5(summary), source);

CREATE TABLE IF NOT EXISTS raw_data (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id    UUID        NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    source     TEXT        NOT NULL,
    data       JSONB       NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT raw_data_page_source_key UNIQUE (page_id, source)
);

CREATE TABLE IF NOT EXISTS page_versions (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id          UUID        NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    compiled_truth   TEXT        NOT NULL,
    frontmatter      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    provider_version TEXT,
    snapshot_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_page_versions_page ON page_versions (page_id, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS ingest_log (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id     TEXT        NOT NULL,
    source_type   TEXT        NOT NULL,
    source_ref    TEXT        NOT NULL,
    pages_updated JSONB       NOT NULL DEFAULT '[]'::jsonb,
    summary       TEXT        NOT NULL DEFAULT '',
    actor_id      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ingest_log_source_created
    ON ingest_log (source_id, source_type, created_at DESC);

-- ---------------------------------------------------------------------------------------------
-- Deferred same-range FK: uploads.page_id -> pages(id).
-- ---------------------------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uploads_page_id_fkey'
          AND conrelid = 'uploads'::regclass
    ) THEN
        ALTER TABLE uploads
            ADD CONSTRAINT uploads_page_id_fkey
            FOREIGN KEY (page_id) REFERENCES pages (id) ON DELETE SET NULL;
    END IF;
END
$$;
