# Project Context for Claude

Last updated: 2026-10-12

## What this is

The Internal Brain: a governed MCP + REST + web layer over an "everything is a document"
corporate brain, for the Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 (FinTech track,
deadline 16 October 2026). GBrain's page model is ported to Python. Every question runs one
governed pipeline: hybrid search → `access_control.filter` (**no LLM call before this**) →
freshness evaluation and live verification → groundedness sanitize → compose → verify → abstain
→ hash-chained audit → `AnswerEnvelope`.

Stack: FastAPI + Pydantic v2 (Python 3.12, `uv` workspace in `backend/`), Postgres 16 + pgvector,
Redis + Celery, Next.js 15 + Tailwind v4 in `frontend/`, one `docker-compose.yml`.

## Read first

1. `docs/ARCHITECTURE.md` (pipeline order, trust boundaries, service boundaries)
2. `docs/PROJECT_STATUS.md` (what is done, what is next)
3. Then as needed: `docs/DATA_MODEL.md`, `docs/API_CONTRACT.md`, `docs/TESTING.md`,
   `docs/DECISIONS.md`, `docs/GBRAIN_MAPPING.md`, `backend/seed/corpus/README.md`.

Use a documentation-first workflow: understand the goal, read the architecture, check existing
patterns, plan, then implement.

## Make targets

`make up` · `make down` · `make reset` (drops volumes) · `make build` · `make logs` · `make ps` ·
`make migrate` · `make seed` · `make test` · `make test-app` · `make test-lib LIB=freshness` ·
`make lint` · `make fmt` · `make typecheck` · `make dev-api` · `make dev-web` · `make smoke` ·
`make mcp-smoke` · `make lock`.

Quickstart: `cp .env.example .env && make up && make seed`, then http://localhost:3000.

## Conventions

- **Thin API, heavy workers.** Routers and MCP tools validate, resolve the principal and call one
  service; ingestion, sync, verification and sweeps run in Celery. `tasks/common.run_async` is the
  only bridge from Celery into async code.
- **Provider abstraction with a mock|real factory.** `PROVIDER_MODE=mock` is the default and needs
  no secrets; real providers (OpenAI-compatible, Tencent ADP app API) raise at construction when
  keys are blank.
- **Repo pattern.** `app/db/repo.py` ABC with `repo_sql.py` (psycopg 3) and `repo_memory.py`.
- **One `Settings`** in `app/config.py`; never read the environment elsewhere; never invent
  environment variables (check `.env.example`).
- **No-network tests.** `make test` runs offline with mock providers, in-memory stores and eager
  Celery. Never remove a test to make a build pass.
- **Style.** Ruff, line length 100, target py312; every Python module starts with
  `from __future__ import annotations`; Pydantic v2 models; `StrEnum` vocabularies.
- **Errors.** Every non-2xx response is `{"error": {code, message, details, request_id}}`. A
  document the actor cannot see returns the same `404` as a missing one; never expose denied
  counts.

## Ownership

| Library (`backend/libs/…`) | Owner   | Adapter (`backend/app/adapters/…`) | Migration range |
| -------------------------- | ------- | ---------------------------------- | --------------- |
| `groundedness`             | Raphael | —                                  | 0300–0399       |
| `freshness`                | Pavan   | `freshness_store.py`               | 0100–0199       |
| `access_control`           | Chai    | `access_stores.py`                 | 0200–0299       |
| core (app, foundation)     | Raphael | —                                  | 0001–0099       |

The groundedness lib is model-free; generation lives in `app/services/compose.py`, owned with core.

- Only touch your lib, your adapter and your migration range unless asked otherwise.
- **Libs never import `app`.** They depend on Pydantic only; the app implements their Protocols.
- Migrations: numbered idempotent SQL in `infra/postgres/migrations/`, one transaction per file,
  no psql meta-commands or `CONCURRENTLY`, references only to the same or lower ranges, never edit
  an applied file. `__EMBEDDING_DIMS__` is substituted by `app/db/migrate.py`.

## Usual risks to watch

Docker path/import mistakes, port conflicts (Postgres is on host 5433, Redis on 6380), weak env
handling, missing tests, AI-generated code changing too many files, and LLM features without
safety boundaries (prompt injection, leakage, unsupported claims).

## Workflow

- Project agents live in `.claude/agents/`; hooks in `.claude/hooks/` protect `.env*`, lockfiles
  and migration folders of other tools, and format files after edits.
- Update `docs/PROJECT_STATUS.md` after every meaningful session, and `docs/DECISIONS.md` after
  every architectural decision.
- Capture CodeBuddy/WorkBuddy usage evidence; it is mandatory for eligibility.
