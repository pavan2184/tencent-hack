# Architecture

Last updated: 2026-10-13

## Overview

Brain Sauce is a governed knowledge layer over an "everything is a document" corporate
brain. Uploads, Slack conversation logs, emails, and Confluence, Jira and Google Drive content all
become **pages**: Markdown with YAML frontmatter, using GBrain's two-layer layout (compiled truth
above `---`, append-only timeline below) and GBrain's `(source_id, slug)` identity. Pages are
chunked, embedded and indexed in Postgres (tsvector + pgvector) for hybrid search.

Every question, whether it arrives through MCP, REST or the web UI, runs through one **governed
pipeline**: retrieve candidates, drop everything the asker may not see **before any LLM call**,
check freshness (live-verifying critical evidence), sanitize the evidence against prompt
injection, compose an answer whose every claim cites evidence, verify the support of each
claim, abstain rather than guess, and append a hash-chained audit event. The response is an
`AnswerEnvelope` carrying claim-level citations, a freshness receipt, a grounding report and an
access summary that never reveals what was denied.

The three hard problems are isolated in three pure-Python libraries owned by three developers:
`access_control` (Chai), `freshness` (Pavan) and `groundedness` (Raphael). The FastAPI app owns
I/O and composition: it implements the libraries' `*Store` Protocols against Postgres in
`app/adapters/`, and the libraries never import `app`. Model calls go through a provider
abstraction whose default is a deterministic mock, so the whole stack boots and tests offline;
Tencent Cloud ADP is the first real provider.

## Recommended Stack

| Layer         | Choice                                                                                                                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Backend       | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, `uv` workspace (`backend/` = app, `backend/libs/*` = members)                  |
| MCP           | `mcp>=2.0` `MCPServer("internal-brain")`, streamable HTTP mounted at `/mcp` (`json_response=True`)                                   |
| Libraries     | `groundedness`, `freshness`, `access_control`: pure Python, `pydantic>=2.9` only, hatchling `src/` layout                            |
| Database      | Postgres 16 + pgvector (`pgvector/pgvector:pg16`), `pg_trgm`, `pgcrypto`; single driver psycopg 3 (async app, sync migration runner) |
| Migrations    | Numbered SQL files in `infra/postgres/migrations/` with owner ranges, applied by `app/db/migrate.py` (no Alembic)                    |
| Cache / queue | Redis 7 (AOF) as Celery broker; Celery worker + beat; queues `q.ingest`, `q.sync`, `q.verify`, `q.maintenance`                       |
| Models        | Provider factory `PROVIDER_MODE=mock\|real`; real: OpenAI-compatible chat + embeddings, or the Tencent ADP app Chat API              |
| Frontend      | Next.js 15 App Router, React 19, TypeScript, Tailwind v4, Radix primitives, npm                                                      |
| Auth          | None: seeded personas selected by `X-Actor-Id` (MCP: header or `?actor=`), resolved by `app/core/auth.get_principal`                 |
| Deployment    | One `docker-compose.yml` at the root; single box on Tencent Cloud; optional Caddy edge (compose profile `edge`)                      |
| Observability | Structured JSON logs (`python-json-logger`) with `request_id`; `/healthz`; the audit log is the system of record                     |

## Folder Structure

```text
tencent-hack/
├── docker-compose.yml  Makefile  .env.example  README.md  CLAUDE.md  AGENTS.md  .github/workflows/ci.yml
├── scripts/            run_tests.sh (→ make test)  run_checks.sh (→ make lint)  validate_env.sh  smoke.sh
├── docs/               PROJECT_BRIEF  ARCHITECTURE  DATA_MODEL  API_CONTRACT  TESTING  SECURITY_REVIEW
│                       DECISIONS  PROJECT_STATUS  GBRAIN_MAPPING  HACKATHON_REQUIREMENTS  superpowers/ (superseded TS design)
├── infra/
│   ├── postgres/init/01_extensions.sql          vector, pg_trgm, pgcrypto (first volume init only)
│   ├── postgres/migrations/                     0001_core_init  0002_core_gbrain_pages  0100_freshness_init
│   │                                            0200_access_init  0300_groundedness_init (placeholder)
│   ├── redis/redis.conf                         appendonly yes, appendfsync everysec
│   └── caddy/Caddyfile                          /api/*, /mcp*, /healthz → api:8000; else → frontend:3000
├── backend/
│   ├── pyproject.toml  uv.lock  Dockerfile  entrypoint.sh (ROLE=api|worker|beat|migrate|seed)
│   ├── seed/           principals.yaml  policies.yaml  corpus/<source>/source.yaml + *.md
│   ├── app/
│   │   ├── main.py  config.py  celery_app.py  seed.py
│   │   ├── core/       auth.py (get_principal, require_roles)  context.py  errors.py  logging.py  redis.py  hashing.py
│   │   ├── db/         session.py  models.py  migrate.py  repo.py  repo_sql.py  repo_memory.py
│   │   ├── schemas/    common.py  documents.py  ask.py (AnswerEnvelope)  access.py  audit.py  sources.py
│   │   ├── api/routers/  health  principals  documents  sources  access  ask  audit  webhooks
│   │   ├── mcp/server.py
│   │   ├── services/   wiring.py  documents.py  ingestion.py  retrieval.py (governed pipeline)  audit.py  sources.py
│   │   │               compose.py (ModelComposer: generate with deadline, then ground)
│   │   ├── providers/  base.py  mock.py  factory.py  real/openai_compatible.py  real/tencent_adp_app.py
│   │   ├── connectors/ base.py  upload.py  gbrain_import.py  stubs.py  registry.py
│   │   ├── adapters/   freshness_store.py (Pavan)  access_stores.py (Chai)
│   │   ├── tasks/      common.py (run_async)  ingest.py  sync.py  verify.py  watchdog.py
│   │   └── tests/      conftest.py + test_* (five scenarios in test_ask_pipeline.py)
│   └── libs/
│       ├── groundedness/    src/groundedness/{models,protocols,sanitize,compose,ground,numeric,verify,abstain}.py  tests/
│       ├── freshness/       src/freshness/{enums,models,protocols,service,policy,versioning,receipt,memory}.py  tests/
│       └── access_control/  src/access_control/{models,permissions,protocols,policy,memory}.py  tests/
└── frontend/
    ├── app/        layout.tsx (nav + PersonaSwitcher)  ask/  documents/  documents/[id]/  sources/  access/  audit/
    ├── components/ PersonaSwitcher  AnswerCard  CitationList  FreshnessReceiptCard  AccessSummaryBadge  DocumentTable
    │               UploadForm  GrantEditor  AuditEventTable  ui/
    └── lib/        apiClient.ts  api.ts  types.ts  persona.ts
```

## Service Boundaries

- **Libraries (`backend/libs/*`) are pure.** No I/O, no `app` imports (each lib has a test that
  fails if `src/` mentions `import app`/`from app`), dependency `pydantic>=2.9` only. Each
  exposes models, `@runtime_checkable` Protocols with documented invariants, stub
  implementations, and (`freshness`, `access_control`) `memory.py` in-memory stores used by the
  lib's own tests **and** by the app's test fixtures. `SCHEMA_VERSION = 1` is re-exported from
  each `__init__.py`.
- **App adapters implement the lib Protocols.** `app/adapters/freshness_store.py`
  (`FreshnessStore`) and `app/adapters/access_stores.py` (`GrantStore`, `PermissionSnapshotStore`,
  `PrincipalDirectory`, `AccessRequestStore`) are each owned by the matching library owner. The
  `groundedness` lib is model-free (D-013), so it has no port for the app to implement; generation
  lives in `app/services/compose.py`, owned with core.
- **Thin API, heavy workers.** Routers and MCP tools validate input, resolve the principal and call
  one service. Ingestion, sync, live verification and watchdog sweeps run in Celery.
  `tasks/common.run_async` is the only bridge from Celery into async services.
- **One repository interface.** `app/db/repo.py` defines the repo ABC; `repo_sql.py` (psycopg)
  and `repo_memory.py` (tests) implement it.
- **One `Settings`.** `app/config.py` is the only reader of the environment (`.env.example` is
  the full list). Production validation fails fast on missing provider keys or non-positive caps.
- **Providers behind a factory.** `providers/factory.py` builds mock or real chat and embedding
  providers. Real providers raise at construction when keys are blank.
- **Connectors behind one contract.** `connectors/base.Connector` (`list_changes`, `fetch`,
  `head`, `permissions`, `normalize_webhook`); `registry.py` maps a connector name to an instance.

## Trust boundaries

```text
  UNTRUSTED
  ┌──────────────────────────────┐        ┌──────────────────────────────────┐
  │ Browser: Next.js UI           │        │ Agent / MCP client               │
  │ persona switcher (X-Actor-Id) │        │ X-Actor-Id header or ?actor=     │
  └───────────────┬──────────────┘        └────────────────┬─────────────────┘
                  │ /api/* JSON                            │ /mcp streamable HTTP
 ═════════════════╪════ TB1  network edge (Caddy :80, profile "edge"; else :8000) ═══════════
                  ▼                                        ▼
  ┌──────────────────────────────── FastAPI  (ROLE=api) ─────────────────────────────────┐
  │  request id ─▶ get_principal ─▶ Principal (TB2 identity: persona header, spoofable)  │
  │  routers / MCP tools (thin) ─▶ services                                             │
  │  ┌──────────────── governed pipeline  services/retrieval.py ──────────────────────┐ │
  │  │ 1 hybrid search, over-fetch top_k × 4 (repo.search_chunks)                      │ │
  │  │ 2 access_control.filter(principal, contexts)  ── denied evidence dropped here  │ │
  │  │ ═══════════════ TB3  no LLM call and no evidence text above this line ═════════ │ │
  │  │ 3 freshness.evaluate / verify_freshness (critical) ─▶ drop unsafe ─▶ receipt   │ │
  │  │ 4 groundedness.sanitize ─▶ compose ─▶ verify ─▶ should_abstain                 │ │
  │  │ 5 audit.record("ask") hash chain   6 AnswerEnvelope (no denied counts)         │ │
  │  └─────────────────────────────────────────────────────────────────────────────────┘ │
  └────┬───────────────────┬─────────────────────┬──────────────────────┬────────────────┘
       │ psycopg           │ Celery via Redis    │ provider factory     │ connectors
       ▼                   ▼                     ▼                      ▼
  ┌──────────────┐  ┌─────────────────────┐  ┌───────────────────┐  ┌─────────────────────┐
  │ Postgres 16  │  │ worker + beat        │  │ mock (default)    │  │ gbrain_import dir    │
  │ + pgvector   │◀─│ ingest / sync /      │  │ real ═══ TB4 ═══▶ │  │ upload store         │
  │ pages, chunks│  │ verify / watchdog    │  │ Tencent ADP (LLM, │  │ stubs: confluence,   │
  │ grants, audit│  │ (same libs + repo)   │  │ embeddings)       │  │ jira, slack, gdrive, │
  └──────────────┘  └─────────────────────┘  └───────────────────┘  │ email, mcp_external  │
                                                                    └──────── TB5 ────────┘
```

- **TB1, network edge.** Everything outside is untrusted. CORS allows only `CORS_ORIGINS`.
- **TB2, identity.** The actor comes from a header. That is spoofable and accepted for a
  synthetic-data demo; `get_principal` is the single replacement point for real auth.
- **TB3, the authorization line.** Nothing a principal may not see crosses into freshness,
  sanitization, the LLM, the receipt, the envelope or the asker-visible logs. Denied decisions
  are kept only for the audit event.
- **TB4, external model.** Only ACL-filtered, freshness-checked, sanitized evidence text leaves the
  box, and only when `PROVIDER_MODE=real`.
- **TB5, providers of content.** Retrieved content is untrusted input: the sanitizer screens it for
  prompt injection before composition, and quarantined evidence can never support a claim.

## Core Flows

### 1. Governed ask (hard invariant: order is asserted by tests)

1. **Principal.** `get_principal` resolves `X-Actor-Id` to an active `access_control.Principal`
   (roles, groups, external identities) or fails with `401`.
2. **Retrieve.** `repo.search_chunks` runs hybrid search (chunk tsvector + HNSW cosine over
   embeddings), over-fetching `ASK_TOP_K × ASK_OVERFETCH_FACTOR` chunks so that filtering can still
   fill `top_k`. Deleted pages are excluded. No content leaves the repo yet.
3. **Access filter.** Build one `DocumentAccessContext` per candidate document (classification,
   owner, raw `SourcePermissions`, grants, permission version) and call
   `access_control.filter(principal, contexts)`. Denied documents are dropped here. Their
   decisions are retained only for the audit event. **No LLM call happens before this step.**
4. **Freshness.** For each allowed document, `freshness.evaluate(object, policy, now)`; for
   critical evidence (and `FRESHNESS_LIVE_VERIFY_CRITICAL=true`), `verify_freshness` probes the
   provider through the connector's `head()`. Unsafe evidence (critical and not fresh, or anything
   not fresh when `require_fresh=true`) is dropped. `freshness_receipt` records every evaluated
   item, safe or not, in input order.
5. **Groundedness.** `sanitize` (never drops; quarantines high-severity injection) → generate
   (app `ModelComposer`: one model call inside `ASK_GENERATION_DEADLINE_S`, extractive fallback on
   timeout or provider error; `ExtractiveComposer` alone in mock mode) → `ground` (deterministic
   claim/citation attachment; auto-cites unmarked sentences; every claim cites non-quarantined
   evidence; no usable evidence → abstained) → `verify` (`lexical-v2`: token overlap, negation
   cues, numeric/date gate; per-claim support labels, coverage, verdict, report hash; no model
   call, D-013) → `should_abstain` (`GROUNDING_MIN_COVERAGE`, contradictions). A model failure
   never fails the ask.
6. **Audit.** `audit.record("ask", …)` appends one hash-chained event with the question, every
   candidate's decision, the receipt id and hash, the cited evidence, the answer, the composer id
   and timings.
7. **Envelope.** `AnswerEnvelope` with `access_summary.allowed_count` only; there is no denied
   count anywhere in an asker-visible payload.

### 2. Upload

`POST /api/documents/upload` (or MCP `put_page` / `capture`) checks the extension allowlist and
the caps (`413` for size, `429 cap_exceeded` for counts and budget), stores the file under
`UPLOAD_DIR`, creates a page in source `uploads` owned by the actor with `UploadPermissions`,
enqueues `ingest_page`, and audits `document.upload`. The worker parses frontmatter, chunks,
embeds (budget-guarded: `ingest_status=budget_exceeded` when the daily embedding budget is
spent), writes chunks, timeline entries and tags, and reports an `IndexOutcome` so
`object_freshness` becomes `fresh`.

### 3. Sync (webhook, delta, reconcile)

Celery beat runs `sync_delta_all` every `SYNC_DELTA_INTERVAL_S` and `reconcile_all` every
`SYNC_RECONCILE_INTERVAL_S`. `sync_source(source_id, trigger_kind, idempotency_key)` calls
`freshness.connector_sync(apply=ingestion.apply_change)`: create run → per change accept →
version guard → apply → upsert object freshness → tombstone deletes → park failures with
`next_attempt_at` → advance the cursor by compare-and-swap only after the whole page of changes is
accounted for. Webhooks (`POST /api/webhooks/{connector_kind}/{source_id}`) only normalize and
`accept` the event durably, then enqueue work; a `202` means "durably accepted", not "indexed".

### 4. Live revocation

`DELETE /api/access/grants/{id}` sets `revoked_at`/`revoked_by` and audits `grant.revoke`. There
is no permission cache: the next ask builds fresh `DocumentAccessContext`s, so the revoked grant no
longer allows anything.

### 5. Audit reconstruction

`GET /api/audit/events/{id}` (auditor/admin) returns the event, including every candidate's
access decision, the receipt and the answer. `GET /api/audit/verify` recomputes the hash chain and
reports the first broken sequence number, if any.

## API Shape

- REST under `/api`, JSON, no versioned prefix in the MVP; payload types that are persisted or
  exchanged across components carry `schema_version` (currently `1`).
- Identity: `X-Actor-Id` header (or `?actor=`); `X-Request-Id` is honoured or generated and echoed.
- Errors: one envelope for every non-2xx response,
  `{"error": {"code", "message", "details", "request_id"}}`. A document the actor may not see
  returns the **same** `404` as a document that does not exist.
- MCP at `/mcp`: GBrain-named tools (`search`, `query`, `get_page`, `put_page`, …) plus our own
  (`freshness_status`, `verify_freshness`, `request_access`, `audit_lookup`). Every tool call is
  audited as `mcp.<tool>` and goes through the same services as REST.
- Full contract: [API contract](API_CONTRACT.md).

## Data Flow

1. **In.** Content enters through connectors (`gbrain_import` for the seeded corpus and any GBrain
   brain directory; `upload` for user files; typed stubs for the platforms) and through webhooks.
   Every change is durably accepted into `source_change_events` before it mutates anything.
2. **Index.** Ingestion turns a page's frontmatter and body into `pages`, `content_chunks`
   (tsvector + embedding), `timeline_entries`, `tags`, `source_permissions` (raw platform
   permissions) and `grants`, and records `object_freshness` from the `IndexOutcome`.
3. **Ask.** Retrieval reads chunks; access control reads permissions and grants; freshness reads
   `object_freshness` and policies and may probe the provider; groundedness reads only the
   surviving evidence; the result is written to `queries`, `freshness_receipts` and `audit_events`.
4. **Out.** The `AnswerEnvelope` goes to the caller. With `PROVIDER_MODE=real`, sanitized
   allowed evidence text goes to the model provider. Nothing else leaves the box.

## Workers

| Task                                             | Queue           | Time limit (soft/hard) | Trigger                                      |
| ------------------------------------------------ | --------------- | ---------------------- | -------------------------------------------- |
| `ingest_page(page_id)`                           | `q.ingest`      | 240 / 300 s            | upload, sync apply, seed (inline)            |
| `sync_source(source_id, trigger_kind, idem_key)` | `q.sync`        | 540 / 600 s            | `POST /api/sources/{id}/sync`, beat, webhook |
| `sync_delta_all`                                 | `q.sync`        | 540 / 600 s            | beat, every `SYNC_DELTA_INTERVAL_S`          |
| `reconcile_all`                                  | `q.sync`        | 540 / 600 s            | beat, every `SYNC_RECONCILE_INTERVAL_S`      |
| `verify_object(source_id, external_object_id)`   | `q.verify`      | 50 / 60 s              | `POST /api/documents/{id}/verify`            |
| `watchdog_sweep`                                 | `q.maintenance` | default                | beat, every 60 s (`WATCHDOG_INTERVAL_S`)     |

Workers use `acks_late=True` and prefetch 1. The worker's compose `stop_grace_period` (660 s)
exceeds the longest hard limit, so a stop never kills a sync mid-page. Tests run Celery eagerly
(`CELERY_TASK_ALWAYS_EAGER=true`).

## Connector contract

`connectors/base.Connector`: `kind`; `list_changes(cursor, *, limit) -> ChangePage`;
`fetch(id) -> FetchedObject(markdown, provider_version, version_order, modified_at, content_hash,
permissions: SourcePermissions, evidence_class, classification, owner_principal_id, raw)`;
`head(id) -> ProviderHead`; `permissions(id) -> SourcePermissions`;
`normalize_webhook(body) -> NormalizedChange`.

- `gbrain_import` walks a brain directory of `*.md` files with `python-frontmatter`; frontmatter
  `permissions:` becomes `SourcePermissions`; the demo-only `simulate:` block
  (`live_version`, `deleted`, `indexed_at`) is honoured by `head()` and the importer. Schema:
  `backend/seed/corpus/README.md` and [Data model](DATA_MODEL.md).
- `upload` reads files stored under `UPLOAD_DIR`.
- `stubs.py` provides typed Confluence, Jira, Slack, Google Drive, email and `mcp_external`
  connectors that raise `NotImplementedError("<kind> connector is a stub — owner: Pavan")`.

## Model providers

`providers/base.py`: `ChatProvider.complete(messages, *, json_mode=False) -> ChatResult(text,
usage)`, `EmbeddingProvider.embed(texts) -> list[list[float]]`, errors `ProviderError`,
`RetryableError`, `FatalError`. `providers/factory.py` chooses by `PROVIDER_MODE` (`mock` default),
`LLM_PROVIDER` (`openai_compatible` | `tencent_adp_app`), and `EMBEDDING_PROVIDER`
(`openai_compatible` | `local_hash`).

- **Mock (default).** `MockChatProvider` returns a deterministic extractive stub;
  `MockEmbeddingProvider` returns seeded hash vectors of `EMBEDDING_DIM`. Mock vectors are
  noise, so mock-mode hybrid search is effectively keyword search.
- **`openai_compatible`.** httpx client for `/chat/completions` (`LLM_BASE_URL`, `LLM_API_KEY`,
  `LLM_MODEL`) and `/embeddings` (`EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`).
- **`tencent_adp_app`.** The ADP application Chat API over SSE (`TENCENT_ADP_APP_KEY`,
  `TENCENT_ADP_CHAT_URL`): concatenates `text.delta` events and surfaces `reference.added`.
- **`local_hash` embeddings.** Reuses the deterministic 1024-dimensional token-hash vectors with
  `PROVIDER_MODE=real`, so ADP can generate answers without a separately billable embedding API.
  Retrieval is primarily lexical; this is not a learned semantic embedding model.
- `app/services/compose.py` (`ModelComposer`) calls the `ChatProvider` directly, once per ask,
  inside `ASK_GENERATION_DEADLINE_S` (`LLM_TIMEOUT_S` stays the per-phase HTTP timeout). The
  groundedness lib never sees a model.

### Tencent Cloud ADP facts

Researched on 2026-10-12. "Verified" means read in Tencent's own documentation or Tencent's own
repository; nothing below has been exercised against our account yet.

| Item                     | Value                                                                                                                                                           | Status                                                                                                      |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| ADP app Chat API         | HTTP SSE `POST https://wss.lke.tencentcloud.com/adp/v2/chat`                                                                                                    | Verified (official docs)                                                                                    |
| Request body             | `AppKey`, `ConversationId` (32–64 chars), `VisitorId`, `Contents=[{"Type":"text","Text":…}]`, `Stream: "enable"\|"disable"`, optional `SystemRole`, `ModelName` | Verified (official docs)                                                                                    |
| Stream events            | `text.delta`, `message.done`, `reference.added`, `response.completed`, `error`                                                                                  | Verified (official docs)                                                                                    |
| Error codes              | `460011` QPM limit, `460031` QPS limit, `460032` insufficient balance                                                                                           | Verified (official docs); map 460011/460031 → `RetryableError`, 460032 → `FatalError`                       |
| OpenAI-compatible models | `base_url=https://api.lkeap.cloud.tencent.com/v1`, `model=deepseek-v3`, `chat.completions` format                                                               | Verified as used by Tencent's `TencentCloudADP/youtu-agent`; not yet called with our key                    |
| Alternative endpoint     | `https://api.adp.cloud.tencent.com/chat/completions`                                                                                                            | **Unverified** (third-party report only)                                                                    |
| Embeddings               | ADP custom vector models must be **1024-dim** → `EMBEDDING_DIM=1024`; adapter is OpenAI-compatible `/embeddings`                                                | Dimension verified; **no official embedding endpoint found** — URL and model to be confirmed in the console |
| Quotas for our account   | QPM/QPS, free-trial balance                                                                                                                                     | **Unknown**; caps in `.env.example` exist to stay inside the trial                                          |

`EMBEDDING_DIM` is baked into `content_chunks.embedding vector(__EMBEDDING_DIMS__)` at migration
time. If the real model's dimension differs, change `EMBEDDING_DIM` and `make reset` before the
first real ingest.

On 2026-10-13, Raphael's ADP console showed a $0 Free Edition Package valid through 2026-11-12,
10,000 credits available and no add-on packages. Tencent's subscription billing documentation
says plans and add-ons are prepaid, with no postpaid billing, and free-plan users cannot buy
credit top-ups. The ADP agent's own knowledge base remains empty; the backend supplies filtered
evidence. TokenHub activation requests payment-based billing, so it is excluded from the no-payment
demo.

## Deployment Assumptions

Owner: **Pavan**. Phased infrastructure: single box first. No payments or paid service activation
are allowed for this demo.

- The no-payment preview runs the whole `docker-compose.yml` on Pavan's Mac: `postgres`, `redis`,
  one-shot `migrate`, `api`, `worker`, `beat`, `frontend`, and `caddy`. A free Cloudflare Quick Tunnel
  can expose Caddy temporarily after the public-access check. Its URL changes when restarted and
  stops working when the Mac or tunnel stops. A paid Tencent VM is not part of this plan.
- Caddy serves one origin on `:80`: `/api/*`, `/mcp*` and `/healthz` go to `api:8000`; everything
  else goes to `frontend:3000`. Build the frontend for that origin
  (`NEXT_PUBLIC_API_BASE_URL=http://<host>/api`, `NEXT_PUBLIC_MCP_URL=http://<host>/mcp`). Add a
  domain and automatic TLS in the Caddyfile if a domain is available.
- Postgres and Redis publish only on `127.0.0.1` (`5433`, `6380`) and are never exposed publicly.
  Data lives in the `pgdata`, `redisdata` and `uploads` named volumes; back up with `pg_dump`.
- Secrets (`LLM_API_KEY`, `EMBEDDING_API_KEY`, `TENCENT_ADP_APP_KEY`) live only in `.env` on the box.
- `PROVIDER_MODE=real` requires the selected provider's key; the app refuses to start otherwise.
- Migrations run on every `up` through the `migrate` service; seeding is an explicit `make seed`.
- Scale-up path (not in the MVP): managed Postgres, separate worker hosts, Redis with replicas.

## Tradeoffs

- **Port GBrain's model vs run GBrain.** Running the TypeScript GBrain would give us its full
  feature set but a second runtime, and its read scoping is per whole source. Porting the model to
  Python keeps one stack and lets the three libraries sit in the read path. We give up GBrain's
  jobs, takes, chronicle, schema packs and most of its ~150 tools.
- **SQL migrations with owner ranges vs Alembic.** Three developers evolve the schema concurrently;
  idempotent numbered files in disjoint ranges merge without conflicts. We give up autogenerate
  and downgrades.
- **Persona header vs authentication.** Fast to demo and test; spoofable. Accepted for synthetic
  data only, with one replacement point (`get_principal`).
- **Over-fetch then filter in Python vs ACL in SQL.** Access decisions need raw per-platform
  semantics that do not reduce to a SQL predicate. Over-fetching by 4× usually still fills
  `top_k`; a heavily restricted asker may get fewer candidates, which is the safe failure mode.
- **Strict omission of stale critical evidence.** Answers can be less complete or abstain;
  preferable to presenting stale operational instructions as current.
- **Live verification on the ask path.** Adds latency (bounded by the verify time limit) for
  critical evidence; standard evidence relies on budgets instead.
- **Hash chain in the same database.** Detects modification and deletion of audit rows but not a
  wholesale rewrite by someone with full database control; external anchoring of the head hash is
  out of MVP scope.
- **Extractive composer.** Deterministic and offline, so tests are stable. It is the mock-mode
  answer source and the real-mode fallback when the model times out or fails; its answers read
  mechanically. The LLM composer is the app's `ModelComposer` (`PROVIDER_MODE=real`).
- **Lexical verification vs an LLM judge (D-013).** No extra model calls, so an ask stays at one
  call and every grounding report is reproducible; wrong numbers, dates and times cannot be
  `supported`. In exchange, paraphrase recall is bounded by lexical overlap, so the generation
  prompt must keep the model's wording close to the evidence.

## Open Architecture Questions

- Which Tencent ADP embedding endpoint and model do we use, and is it really 1024-dim for our
  account? (Blocks the first real ingest.)
- Final upload cap numbers (`UPLOAD_MAX_FILE_BYTES`, `UPLOAD_MAX_FILES_TOTAL`,
  `UPLOAD_MAX_FILES_PER_ACTOR_PER_DAY`, `EMBEDDING_DAILY_CALL_BUDGET`): TBD by Raphael.
- Does `mcp>=2.0` expose the HTTP request on `ctx.request_context.request`, or do we need the
  ContextVar-setting ASGI wrapper to read `X-Actor-Id` in MCP tools?
- Lighthouse or CVM for the demo box, and is a domain available for TLS?
- Should index age for critical evidence be measured from the last successful reconcile or
  verification rather than from `indexed_at`, so unchanged critical pages do not go stale an hour
  after seeding? (Freshness lib decision, Pavan.)

## Access-control update (12 October 2026)

Latest integrated baseline: `fc0bdf6c`. The app now supplies REST/MCP, SQL adapters,
Celery and a governed retrieval pipeline. Its `filter_pages`/`visible_page` calls
use the pure library policy and reload grants/snapshots per read. `ac-v2` enforces
native source permissions before local owner/admin/grant allows. Upload sharing
remains local. Denied duplicate ids, wrong-kind/stale snapshots and uncaptured
Confluence ancestor restrictions fail closed.

The library also supplies `AccessControlService`, which reloads and validates
principal/groups/grants/snapshots, and an optional `SourcePermissionVerifier`.
This is an available orchestration seam, not a claim that a live provider check
is already wired into the app. Slack/Drive normalisers preserve guest, expiry
and discovery restrictions; deterministic fingerprints track ACL-only changes.

The editable architecture deck is
[`docs/presentations/internal-brain-architecture.pptx`](presentations/internal-brain-architecture.pptx)
(15 slides; the submission copy without the internal status slide is
`internal-brain-architecture-submission.pptx`). It shows the implemented pipeline,
trust boundaries and native permission handling, and marks the remaining live
platform/authentication boundaries. See [handoff](ACCESS_CONTROL_HANDOFF.md) and
[research](ACCESS_CONTROL_RESEARCH.md).
