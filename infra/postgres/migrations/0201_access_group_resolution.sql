-- 0201_access_group_resolution.sql
-- Owner: access_control (Chai) · range 0200-0299.
-- Group resolution inputs for access_control.resolve_groups: nested groups (a member of a child
-- group is a member of every ancestor) and each group's id on each source platform (Drive names
-- a group by its address, Confluence and Jira by their own group ids). Read by
-- app.adapters.access_stores.SqlGroupDirectory. Rules: idempotent, one transaction, no psql
-- meta-commands, no CONCURRENTLY; references only core tables (groups, 0001).

-- ---------------------------------------------------------------------------------------------
-- access_group_parents: group_id's members are also members of parent_group_id.
-- Cycles are allowed (resolution tolerates them); deleting either group removes the link, which
-- can only narrow access.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS access_group_parents (
    group_id        TEXT NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    parent_group_id TEXT NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, parent_group_id)
);
CREATE INDEX IF NOT EXISTS idx_access_group_parents_parent
    ON access_group_parents (parent_group_id);

-- ---------------------------------------------------------------------------------------------
-- access_group_platform_ids: the group's id on one platform. A bound id replaces the local
-- group id when matching that platform's group ACL entries (one id per group and platform).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS access_group_platform_ids (
    group_id          TEXT NOT NULL REFERENCES groups (id) ON DELETE CASCADE,
    source_kind       TEXT NOT NULL
                           CHECK (source_kind IN ('confluence', 'jira', 'slack', 'gdrive',
                                                  'email', 'upload', 'gbrain_import',
                                                  'mcp_external')),
    platform_group_id TEXT NOT NULL CHECK (platform_group_id <> ''),
    PRIMARY KEY (group_id, source_kind)
);
CREATE INDEX IF NOT EXISTS idx_access_group_platform_ids_lookup
    ON access_group_platform_ids (source_kind, platform_group_id);
