# Overview and Team Plan

Last updated: 2026-10-12

## What we are building

A permission-aware company brain exposed to AI agents through an **MCP layer** (plus REST and a
web UI). A mid/large corporate can upload documents, request documents, mark documents
confidential, and manage access control. Slack messages, emails, Confluence/Jira/Google Drive
content, and daily conversation logs all become **documents** ("everything is a document"), so one
set of machinery governs all of them. Every answer proves three things:

1. **Groundedness** — each claim cites evidence and is verified against it.
2. **Data freshness** — each piece of evidence carries a freshness receipt; stale critical
   evidence is never silently presented as current.
3. **Access control** — authorization is decided per document, before any LLM call, preserving
   each source platform's own permission semantics, with no existence leak.

Plus a tamper-evident audit trail (who asked, what was retrieved, per-document allow/deny, answer).

We port the model of [gbrain](https://github.com/garrytan/gbrain) (pages = markdown + frontmatter,
`(source, slug)` identity, sources as scoping unit, hybrid pgvector + tsvector search, gbrain-named
MCP tools) to Python rather than running the TypeScript gbrain. The three libraries fill gbrain's
documented gaps: per-document access control, per-claim freshness, and answer-support verification.

## Stack

| Layer | Choice |
| --- | --- |
| Frontend | Next.js 15 (App Router, TypeScript, Tailwind v4) in `frontend/` |
| Backend | FastAPI (Python 3.12, uv workspace, Pydantic v2, SQLAlchemy 2) in `backend/app/` |
| Database | PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`) |
| Jobs | Celery worker + beat on Redis (ingestion, connector sync, freshness verification) |
| Containers | `docker-compose.yml` at the root: postgres, redis, migrate, api, worker, beat, frontend |
| Models | Mock provider by default; first real adapter = Tencent Cloud ADP |
| Identity | Demo personas, no auth: `X-Actor-Id` header, persona switcher in the UI |

## The three Python libraries (what each dev builds)

All three live in `backend/libs/<name>/` as uv workspace members. Each is a pure-Python package
(Pydantic models + `Protocol` interfaces + a working stub + in-memory stores + tests + README).
Libraries **never import `app`**; where they need persistence they declare a `*Store` Protocol
that the app implements in `backend/app/adapters/`.

| Workstream | Owner | Package | Entry points the app calls | Migration range |
| --- | --- | --- | --- | --- |
| Groundedness | Raphael | `groundedness` | `sanitize → compose → verify → should_abstain` | 0300–0399 |
| Data freshness + ingestion pipeline + Tencent Cloud deploy | Pavan | `freshness` | `FreshnessService.connector_sync / evaluate / verify_freshness / freshness_receipt`; connectors + Celery tasks in `backend/app/connectors`, `backend/app/tasks` | 0100–0199 |
| Access control | Chai | `access_control` | `AccessPolicy.filter` (pre-LLM), `GrantStore`, `PermissionSnapshotStore`, `PrincipalDirectory` | 0200–0299 |

Each owner only touches: `backend/libs/<lib>/`, their `backend/app/adapters/<file>.py`, and SQL
migrations in their number range under `infra/postgres/migrations/`. The app core, docs and compose
are shared; coordinate changes there in the group chat.

## The governed query pipeline (`backend/app/services/retrieval.py`)

```
principal (X-Actor-Id) → hybrid search over-fetch → access_control.filter (drop denied BEFORE any LLM)
→ freshness.evaluate / verify (drop stale critical, build receipt) → groundedness.sanitize → compose
→ verify → abstain? → audit.record (hash chain) → AnswerEnvelope {answer, citations, freshness_receipt,
grounding, access_summary (no denied counts), audit_id}
```

The same pipeline backs `POST /api/ask` and the MCP `query` tool.

## Demo plan

- `make seed` loads six personas (employee, manager, auditor, admin, a finance-ops member, a
  contractor) and a synthetic "Example Harbor Finance" corpus across Confluence, Jira, Slack,
  Google Drive and email sources.
- The user plays different roles via the persona switcher.
- Uploads are open but capped (file size, total files, per-actor per day, embedding budget) to stay
  inside the Tencent free trial. **Cap numbers are TBD** (`UPLOAD_*` in `.env.example`).
- The five mandatory scenarios each map to a test in `backend/app/tests/test_ask_pipeline.py` and to
  a step in `scripts/smoke.sh`.

## Integration order

| Date | Milestone |
| --- | --- |
| 12 Oct | Skeleton on `main`: libs with stubs + tests, app core, compose, seed, docs |
| 13 Oct | Each owner replaces their stub behind the unchanged interface; PRs touch only their paths |
| 14 Oct | Demo script, real Tencent ADP provider, Tencent Cloud deployment (Pavan) |
| 15 Oct | Video, screenshots (CodeBuddy/WorkBuddy usage evidence is mandatory), submission package |
| 16 Oct | Official submission deadline |

## Getting started

```bash
cp .env.example .env
make up        # builds and starts the stack; waits for /healthz
make seed      # personas + corpus
make test      # backend app + all three libraries, offline, mock mode
make test-lib LIB=freshness
```

Read next: `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/API_CONTRACT.md`,
`docs/DECISIONS.md`, and the README inside your library.
