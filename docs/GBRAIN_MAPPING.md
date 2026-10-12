# GBrain Mapping

Last updated: 2026-10-12

[GBrain](https://github.com/garrytan/gbrain) is an MIT-licensed, TypeScript/Bun knowledge brain
on Postgres + pgvector (with a PGLite engine for local use). We **port its model to Python**
rather than running it (decision D-001). This page records what we took, what we left, which
GBrain gaps our three libraries fill, and where we deviate. Facts about GBrain below were checked
against its `master` branch (`src/schema.sql`, `docs/TOOL_CATALOG.md`, `README.md`) on 2026-10-12.

## What we port

- **Two-layer page.** A page is Markdown with YAML frontmatter. The body is the **compiled truth**
  (the current best statement) above a `---` line and an append-only **timeline** below it
  (`pages.compiled_truth`, `pages.timeline`, plus structured `timeline_entries`).
- **Identity `(source_id, slug)`.** Slugs are unique per source, not globally
  (`pages_source_slug_key`). We never identify a page by slug alone.
- **Sources as the scoping unit.** `sources(id, name UNIQUE, local_path, config jsonb,
last_sync_at, newest_content_at, archived…)`; every page belongs to exactly one source.
- **Tables.** `sources`, `pages`, `content_chunks`, `links`, `tags`, `timeline_entries`,
  `raw_data`, `page_versions`, `ingest_log` (in `0002_core_gbrain_pages.sql`).
- **Hybrid search.** Chunk-grain full-text search (tsvector, GIN) combined with vector search over
  `content_chunks.embedding` (HNSW, `vector_cosine_ops`), and a weighted page-level tsvector
  (title A, …, timeline C) maintained by a trigger.
- **Folder layout.** A brain is a directory of Markdown files; the slug is the relative path
  without `.md` (GBrain suggests type-named folders such as `people/` and `meetings/` but does not
  enforce a fixed layout). Our corpus uses `<source-id>/<area>/<name>.md`.
- **Brain-directory import.** The `gbrain_import` connector walks a GBrain-style directory, parses
  frontmatter with `python-frontmatter`, and syncs it as one source. The seeded corpus is imported
  this way.
- **Tool names.** Where a GBrain MCP tool maps onto our model we keep its name (table below).

## What we skip

- **PGLite** and engine parity: Postgres only.
- **Jobs / minions**, subagents, the dream cycle and the autopilot: Celery replaces background work.
- **Takes, facts, the ontology, the life chronicle**, emotional weight and salience scoring,
  query caching and contextual-retrieval generations.
- **The OAuth client model** (clients, tokens, grants, bound-client slug fences): we use persona
  identity (D-006).
- **Schema packs** (type taxonomies such as `gbrain-base-v2`): page `type` is free text.
- **The other tools.** GBrain's generated tool catalog lists 149 MCP tools; we mirror 14 and add
  4 of our own. The rest (admin dashboards, code intelligence, image search, files, skills,
  calibration, loops, …) are out of scope.

## Gaps our libraries fill

| GBrain behaviour                                                                                                                                                                                                                                                                                                       | Gap for the challenge                                                                                                                                        | Filled by                                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Reads are scoped per **whole source**: remote clients are confined by source and operation grants plus visibility filters, and the only finer switch is `visibility: private\|world` on saved facts. GBrain's README says its authorization tests "exercise specific access paths, not a universal no-leak guarantee". | No per-document platform permissions (Confluence space/page, Jira role and security level, Slack channel, Drive ACL) and no "deny without an existence leak" | `access_control`: raw per-platform permission snapshots, grants, classification rules, one decision per document before any LLM |
| Evidence-change tracking ("stale" sentence flags) exists for **pinned questions** (`questions_pin`); other freshness signals are per source sync or health dashboards                                                                                                                                                  | No per-object provider version, no query-time verification of critical evidence, no receipt                                                                  | `freshness`: event ledger, cursors, object freshness, policies, live verification, hashed receipts                              |
| Citations are generated and repaired by LLM passes; the checks we found confirm that citations are present and well-formed, not that the cited text entails each claim (team review, 2026-10-12)                                                                                                                       | Claims can cite pages that do not support them; injected instructions in retrieved content are not screened                                                  | `groundedness`: claim ↔ evidence citations, support verification, abstention, injection quarantine                              |
| **Write attribution** (`get_write_attribution`) records who created or last changed a page or fact                                                                                                                                                                                                                     | Not an audit log: no record of who _asked_ what, what was retrieved, or each allow/deny decision; not tamper-evident                                         | App core: hash-chained `audit_events` with per-document decisions, receipts and answers                                         |

## Tool mirror

| Tool                 | Mirrors GBrain `master`               | Notes                                                                                                                    |
| -------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `whoami`             | yes                                   | returns the resolved persona instead of an OAuth client                                                                  |
| `search`             | yes                                   | ACL-filtered hybrid search, no LLM                                                                                       |
| `query`              | yes (name)                            | runs our governed pipeline and returns an `AnswerEnvelope`; GBrain's `query` returns search results with query expansion |
| `get_page`           | yes                                   | visible pages only; denied = same `not_found` as missing                                                                 |
| `put_page`           | yes                                   | writes only into the `uploads` source, owned by the actor, caps apply                                                    |
| `list_pages`         | yes                                   | ACL-filtered                                                                                                             |
| `capture`            | yes                                   | quick note into `uploads` under `inbox/`, idempotent on content                                                          |
| `add_timeline_entry` | yes                                   |                                                                                                                          |
| `get_timeline`       | yes                                   |                                                                                                                          |
| `log_ingest`         | yes                                   | `manager`/`admin`                                                                                                        |
| `sources_list`       | yes                                   | no page counts (they would count invisible pages)                                                                        |
| `sources_status`     | yes                                   | returns the freshness status report                                                                                      |
| `sources_add`        | yes                                   | `admin`                                                                                                                  |
| `assemble_evidence`  | yes (GBrain master tool of that name) | returns ACL-filtered, freshness-checked, sanitized evidence + receipt; no answer                                         |
| `freshness_status`   | ours                                  | object freshness without side effects                                                                                    |
| `verify_freshness`   | ours                                  | live verification (`manager`/`admin`)                                                                                    |
| `request_access`     | ours                                  | always `{"status": "received"}`                                                                                          |
| `audit_lookup`       | ours                                  | `auditor`/`admin`                                                                                                        |

Parameters and payloads: [API contract → MCP tools](API_CONTRACT.md#mcp-tools).

## Deviations from GBrain

- **UUID ids.** GBrain uses `SERIAL` integer ids for pages, chunks, links, tags and timeline
  entries; we use UUIDs (`gen_random_uuid()`) so ids are safe to expose and do not leak counts.
- **Extra page columns.** `source_kind`, `external_object_id` (unique per source),
  `classification`, `owner_principal_id`, `permission_version`, `provider_version`,
  `provider_modified_at`, `evidence_class`, `ingest_status`.
- **Page search vector includes compiled truth** (weight B, first 256 KiB). GBrain dropped
  compiled truth from the page vector because whole-page bodies can exceed Postgres's 1 MB
  tsvector limit; our pages are small and capped, and the truncation keeps us under the limit.
- **Chunk search vector is a generated column** (`to_tsvector('english', chunk_text)`) instead of
  GBrain's trigger over code-symbol columns; we index Markdown only.
- **Persona identity** instead of OAuth clients and source grants.
- **Frontmatter carries governance fields** (`classification`, `owner`, `evidence_class`,
  `permissions`, `grants`, `permission_version`, optional demo-only `simulate`). See
  [Data model → Imported page frontmatter](DATA_MODEL.md#imported-page-frontmatter).
- **No `default` source.** Every source is explicit; uploads go to the `uploads` source.
- **Links** are unique per (`from_page_id`, `to_page_id`, `link_type`); GBrain also keys on link
  source and origin page.

## License

GBrain is MIT-licensed. We reuse its data model and tool names, not its source code; credit is
given here and in the README.
