# Decisions

Last updated: 2026-10-12

Architectural and product decisions, newest last. Each entry is immutable once accepted; a change
of mind is a new entry that supersedes the old one.

## Decision Template

```markdown
### D-NNN — Title

Status: Proposed | Accepted | Rejected | Superseded by D-NNN
Date: 2026-10-12

Context: …
Decision: …
Consequences: positive, negative, follow-up.
```

## Log

### D-001 — Port GBrain's model to Python instead of running GBrain

Status: Accepted
Date: 2026-10-12

**Context.** GBrain (github.com/garrytan/gbrain, MIT, TypeScript/Bun, Postgres + pgvector) has the
knowledge model we want: Markdown pages with frontmatter, compiled truth plus an append-only
timeline, `(source_id, slug)` identity, sources as the scoping unit, hybrid search and an MCP
surface. It scopes reads per whole source, has no per-claim freshness, checks citation format
rather than truth, and records write attribution rather than an audit log. Running it would mean a
second runtime beside the Python stack the team knows, and the governed read path would have to
wrap code we do not control.

**Decision.** Port the model, not the code. Mirror GBrain's page layout and identity, its
`sources/pages/content_chunks/links/tags/timeline_entries/raw_data/page_versions/ingest_log`
tables, hybrid tsvector + HNSW search, its MCP tool names where they map, and its brain-directory
import (`gbrain_import` connector). Our three libraries fill the gaps.

**Consequences.** One Python stack and a read path we fully own. We give up GBrain's jobs, takes,
chronicle, schema packs and the rest of its ~150 tools, and must keep [GBrain mapping](GBRAIN_MAPPING.md)
current. A GBrain brain directory can still be imported as a source.

### D-002 — Supersede the TypeScript freshness spec and branch

Status: Accepted
Date: 2026-10-12

**Context.** On 2026-09-24 Pavan's design (`docs/superpowers/specs/2026-09-24-gbrain-freshness-foundation-design.md`,
plan `docs/superpowers/plans/2026-09-24-gbrain-freshness-foundation.md`, branch
`origin/codex/gbrain-freshness-foundation`) was approved for a full TypeScript/Bun derived copy of
GBrain. The project then pivoted to a Python monorepo (D-001).

**Decision.** The TS spec, plan and branch are superseded as the implementation plan but are
**retained untouched** as the freshness design reference: the two docs only gain a "Superseded
2026-10-12" banner, and the branch is not modified or deleted. The freshness entities
(`connector_checkpoints`, `source_change_events`, `object_freshness`, `sync_runs`,
`freshness_policies`, `freshness_receipts`), statuses and operations (`connector_sync`,
`freshness_status`, `verify_freshness`, `freshness_receipt`, durable webhook acceptance) are ported
verbatim into `backend/libs/freshness`, with only the status renames in D-004.

**Consequences.** Pavan's design work carries over intact; his eval fixtures can be ported as
Python tests. The spec's "Confluence and Slack live" connector target is replaced by
`gbrain_import` + `upload` real and typed stubs for the platforms.

### D-003 — Owner-scoped libraries with Protocol stores

Status: Accepted
Date: 2026-10-12

**Context.** Three developers, each with their own AI agent, build in parallel for four days.
Shared files are where parallel work collides.

**Decision.** Each workstream is a pure-Python library under `backend/libs/<lib>`
(`groundedness`, `freshness`, `access_control`) with models, `@runtime_checkable` Protocols that
state their invariants, stub implementations, in-memory stores in `memory.py`, tests and a README.
Libraries depend only on `pydantic>=2.9` and never import `app` (a test in each library enforces
it). The app implements the store Protocols in `app/adapters/` (one file per owner). Each owner's
PRs touch only their library, their adapter file and their migration range.

**Consequences.** Clean merges and independent test suites; the app composes the libraries in one
place (`services/retrieval.py`). Cross-library changes need a coordinated PR through Raphael.

### D-004 — Freshness vocabulary

Status: Accepted
Date: 2026-10-12

**Context.** The superseded spec used `searchable_current` and `pending`; the libraries need one
closed vocabulary shared by Python enums, SQL CHECK constraints and API payloads.

**Decision.** `ConnectorKind(confluence, slack, jira, google_drive, email, upload, gbrain_import,
mcp_external)`, `FreshnessStatus(fresh, stale, unknown, not_searchable, deleted)`,
`VerificationResult(fresh, stale, unknown, not_required)`, `SyncPath(webhook, delta, reconcile,
live_verify)`, `ChangeKind(upsert, delete, metadata_change)`, `EventState(accepted, processing,
applied, parked)`, `RunStatus(queued, running, completed, partial, failed, parked)`,
`CheckpointStatus(ready, polling, degraded, paused)`, `EvidenceClass(critical, standard)`,
`FailureAction(omit, abstain, allow_with_warning)`, `PolicyStatus(draft, active, retired)`,
`OverallStatus(fresh, stale, unknown, not_required, mixed)`. `searchable_current` → `fresh`,
`pending` → `not_searchable`.

**Consequences.** The access-control `SourceKind` says `gdrive` where freshness says
`google_drive`; `ConnectorKind` accepts `gdrive` as an input alias and always emits
`google_drive`, so source and page rows say `gdrive` and freshness rows say `google_drive`. `allow_with_warning` is
never valid for critical evidence (CHECK constraint).

### D-005 — SQL-file migrations with owner number ranges

Status: Accepted
Date: 2026-10-12

**Context.** Alembic revision chains conflict when three people add migrations concurrently, and
the repository hook blocks writes under `alembic/versions/`.

**Decision.** Numbered, idempotent SQL files in `infra/postgres/migrations/`, applied in filename
order by `app/db/migrate.py` (sync psycopg), one transaction per file, recorded with a checksum in
`schema_migrations`. Ranges: `0001–0099` core (Raphael), `0100–0199` freshness (Pavan),
`0200–0299` access_control (Chai), `0300–0399` groundedness (Raphael). A file may reference only
its own or lower ranges. `__EMBEDDING_DIMS__` is substituted from `EMBEDDING_DIM`.

**Consequences.** Parallel schema work merges cleanly. No autogenerate and no downgrades;
`app/db/models.py` mirrors the DDL by hand and an integration test checks every table exists.
Applied files are never edited.

### D-006 — Persona identity via `X-Actor-Id`

Status: Accepted
Date: 2026-10-12

**Context.** The demo needs to "play different roles" quickly; there is no time for an identity
provider, and all data is synthetic.

**Decision.** No authentication. Six seeded personas; the actor comes from the `X-Actor-Id`
header (MCP: the same header or `?actor=`), resolved by one dependency,
`app/core/auth.get_principal`, into an `access_control.Principal`. Missing → `401
unauthenticated`; unknown or inactive → `401 unknown_actor`.

**Consequences.** The header is spoofable; accepted for the demo and documented in the security
review, with `get_principal` as the single replacement point for real auth.

### D-007 — Pages are documents

Status: Accepted
Date: 2026-10-12

**Context.** Uploads, Slack messages, emails and platform objects need one governance model.

**Decision.** `pages` is the documents table. Everything ingested becomes a page with governed
columns (`source_kind`, `external_object_id`, `classification`, `owner_principal_id`,
`permission_version`, `provider_version`, `provider_modified_at`, `evidence_class`,
`ingest_status`). Slack is ingested as one daily conversation log page per channel per day.
`document_id` everywhere is `pages.id`.

**Consequences.** One retrieval, access, freshness and audit path for every content type. Slack
permissions are per channel-day page, which matches channel membership semantics.

### D-008 — Access control before any LLM; identical 404; no denied counts

Status: Accepted
Date: 2026-10-12

**Context.** The challenge requires filtering before the model and no confirmation that
restricted content exists.

**Decision.** In the governed pipeline, `access_control.filter` runs right after retrieval and
before freshness probing, sanitization, composition or any model call; denied decisions are kept
only for the audit event. A document the actor may not see returns a byte-identical `404` to a
nonexistent one. `AccessSummary` has `allowed_count` and no denied count; lists never count
invisible items; access requests always answer `202`.

**Consequences.** Answers can be thinner for restricted users, and abstention wording cannot
distinguish "denied" from "missing". The order is a tested invariant.

### D-009 — Hash-chained append-only audit log

Status: Accepted
Date: 2026-10-12

**Context.** The audit trail must be tamper-evident, complete and queryable.

**Decision.** `audit_events` with `seq` and
`hash = sha256(prev_hash || seq || canonical_json(payload))` (parts joined with `|`,
`app/core/hashing.chain_hash`), genesis `prev_hash` NULL; the payload should copy the event
columns so the hash covers them; appends serialise on an advisory
lock; a trigger rejects `UPDATE`/`DELETE`; `GET /api/audit/verify` recomputes the chain. Every
ask, MCP tool call, upload, grant change and seed load is audited.

**Consequences.** Modification, deletion and reordering are detectable. A database superuser can
still rewrite the whole chain; external anchoring is a follow-up.

### D-010 — Mock providers by default; Tencent ADP first real provider

Status: Accepted
Date: 2026-10-12

**Context.** Tests and `make up` must work offline with no keys; the hackathon is Tencent Cloud's.

**Decision.** House provider abstraction (`ChatProvider`, `EmbeddingProvider`, mock|real
factory). `PROVIDER_MODE=mock` is the default. Real providers: OpenAI-compatible chat and
embeddings (`LLM_BASE_URL=https://api.lkeap.cloud.tencent.com/v1`, `LLM_MODEL=deepseek-v3`) and
the ADP app Chat API over SSE (`https://wss.lke.tencentcloud.com/adp/v2/chat`).
`EMBEDDING_DIM=1024` (ADP custom vector models are 1024-dim). Real providers raise at
construction when keys are blank.

**Consequences.** Deterministic tests; mock-mode retrieval is effectively keyword search. The
embedding endpoint and model are still unconfirmed, and a dimension change needs `make reset`.

### D-011 — Upload and budget caps in Postgres counters; numbers TBD

Status: Accepted
Date: 2026-10-12

**Context.** Uploads are open to every persona, and the Tencent free trial must not be exhausted.

**Decision.** Caps on file size (`413`), total files, files per actor per day and daily embedding
calls (`429 cap_exceeded`, details `{cap, limit, window}`), enforced with one atomic
`INSERT … ON CONFLICT … WHERE count < limit RETURNING` on `usage_counters`. Values are Settings
with placeholder defaults (`UPLOAD_MAX_FILE_BYTES=1000000`, `UPLOAD_MAX_FILES_TOTAL=200`,
`UPLOAD_MAX_FILES_PER_ACTOR_PER_DAY=20`, `EMBEDDING_DAILY_CALL_BUDGET=2000`); the final numbers are
TBD by Raphael.

**Consequences.** Caps survive restarts and work across api and worker processes without Redis
coordination. Placeholder values must be confirmed before the public demo.

### D-012 — psycopg 3 as the single database driver

Status: Accepted
Date: 2026-10-12

**Context.** The app is async (FastAPI), the migration runner and Celery bridge are sync, and we
want one driver to debug.

**Decision.** psycopg 3 everywhere: async connections for the app (via SQLAlchemy's
`postgresql+psycopg` dialect and `pgvector`), sync connections for `app/db/migrate.py`. Multi-
statement migration files run through psycopg's simple query protocol in one transaction.

**Consequences.** One dependency (`psycopg[binary,pool]`), consistent type handling for `jsonb`,
`uuid` and `vector`. Celery tasks bridge into async services only through
`tasks/common.run_async`.

### D-013 - Native source permissions cap local application grants

Status: Accepted
Date: 2026-10-12

The challenge requires preserving source permissions. Policy `ac-v2` therefore
checks native read access before local owner/admin/grant allows for imported
content. App-managed uploads retain local sharing. Existing signatures and deny
reasons stay compatible. Calls that relied on bypassing a native ACL intentionally
stop allowing access. Local approval does not change a source platform's ACL.

A query-time service supplies current validated store reads and an optional live
verifier that can only tighten access. No cached allow exists. Native API transport
and complete source-scoped group resolution belong in app adapters. The diagram
marks live-provider/authentication boundaries separately from implemented code.
