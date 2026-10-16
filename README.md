<a id="readme-top"></a>

<div align="center">
  <h1>Proof-Carrying Enterprise Knowledge</h1>
  <p><strong>Enterprise answers with evidence.</strong></p>
  <p>A permission-aware knowledge system for the Tencent Cloud AI CAN DO IT Hackathon Singapore 2026.</p>
  <p>
    <a href="docs/PROJECT_BRIEF.md"><strong>Explore the project brief »</strong></a>
    <br /><br />
    <a href="docs/HACKATHON_REQUIREMENTS.md">View requirements</a>
    &middot;
    <a href="https://github.com/pavan2184/tencent-hack/issues/new">Report a bug</a>
    &middot;
    <a href="https://github.com/pavan2184/tencent-hack/issues/new">Request a feature</a>
  </p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Tencent_Cloud-Hackathon-0052D9" alt="Tencent Cloud Hackathon" />
  <img src="https://img.shields.io/badge/Track-FinTech-1F6FEB" alt="FinTech" />
  <img src="https://img.shields.io/badge/Focus-Grounded_AI-7C3AED" alt="Grounded AI" />
  <img src="https://img.shields.io/badge/Status-In_Development-F59E0B" alt="In development" />
</p>

Last updated: 2026-10-12

An MCP layer, REST API and web UI over an "everything is a document" corporate brain for the
Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 (FinTech track, Aspire challenge **"The Internal
Brain"**). Confluence pages, Jira issues, Slack conversation logs, Google Drive files, emails and
uploads all become [GBrain](https://github.com/garrytan/gbrain)-style pages, and every question runs
through one governed pipeline: retrieve → **access control before any LLM call** → freshness
checks with live verification of critical evidence → prompt-injection screening → an answer whose
every claim cites evidence → a hash-chained audit event. Each answer carries claim-level citations,
a freshness receipt, a grounding report and an access summary that never reveals what was denied.
GBrain's page model is ported to Python (FastAPI + Postgres/pgvector + Celery + Next.js); the three
hard problems live in three team-owned libraries.

## Product thesis

Enterprise AI should not merely claim that an answer is current and authorized. It should prove:

- which sources and versions supported the answer;
- when each source was last synchronized or verified;
- which access-control decisions were applied before retrieval;
- which claims are grounded in which evidence; and
- how an auditor can reconstruct the result later.

## Quickstart

Requires Docker (with compose), and for local development `uv` and Node 22.

```bash
cp .env.example .env && make up && make seed
```

Open <http://localhost:3000> and switch personas in the header (`alex.tan`, `john.tan`,
`sam.lee`, `root.admin`, `jordan.lim`, `mei.chen`). The API is on <http://localhost:8000>
(OpenAPI at `/docs`), MCP on <http://localhost:8000/mcp>. Everything runs in mock mode with no keys;
set `PROVIDER_MODE=real` and the Tencent ADP values in `.env` for real models.

Try the demo scenarios: ask "What is the payment rail failover procedure?" as `john.tan` (the
stale critical runbook is omitted and shown in the receipt), ask "What were the Q3 board deck
revenue figures?" before and after `root.admin` revokes the `leadership` grant, open the board deck
as `mei.chen` (same "not found" as a random id), and read the audit trail as `sam.lee`.
`make smoke` runs all of this end to end.

## Make targets

| Target                  | What it does                                                            |
| ----------------------- | ----------------------------------------------------------------------- |
| `make up`               | Build and start the stack, wait for the API to be healthy               |
| `make down`             | Stop the stack                                                          |
| `make reset`            | Stop and delete volumes (database, redis, uploads)                      |
| `make build`            | Build images                                                            |
| `make logs` / `make ps` | Tail logs / service status                                              |
| `make migrate`          | Apply SQL migrations from `infra/postgres/migrations`                   |
| `make seed`             | Load personas, freshness policies and the synthetic corpus (idempotent) |
| `make test`             | Backend app + the three library suites, offline in mock mode            |
| `make test-app`         | Backend app tests only                                                  |
| `make test-lib LIB=…`   | One library: `groundedness`, `freshness` or `access_control`            |
| `make lint`             | Ruff (backend + libs) and the frontend linter                           |
| `make fmt`              | Auto-format the backend                                                 |
| `make typecheck`        | Frontend TypeScript check                                               |
| `make dev-api`          | API with reload on the host                                             |
| `make dev-web`          | Next.js dev server                                                      |
| `make smoke`            | End-to-end curl smoke test against a running stack (`scripts/smoke.sh`) |
| `make mcp-smoke`        | MCP `initialize` → `tools/list` → `whoami`                              |
| `make lock`             | Regenerate `uv.lock` and `package-lock.json`                            |

## Repository layout

```text
docker-compose.yml  Makefile  .env.example       one stack, mock-safe defaults
backend/
  app/                FastAPI app: core, db, schemas, api/routers, mcp, services, providers,
                      connectors, adapters (one file per lib owner), tasks, tests
  libs/groundedness   claims ↔ evidence, support verification, abstention, injection screening (Raphael)
  libs/freshness      webhook/delta/reconcile/verify state machine and receipts (Pavan)
  libs/access_control principals, raw per-platform permissions, grants, no existence leak (Chai)
  seed/               personas, freshness policies, synthetic corpus (Example Harbor Finance)
frontend/             Next.js 15 UI: ask, documents, sources, access, audit, persona switcher
infra/                postgres init + numbered migrations, redis.conf, Caddyfile
scripts/              run_tests.sh, run_checks.sh, validate_env.sh, smoke.sh
docs/                 brief, architecture, data model, API contract, testing, security, decisions
```

## Team workstreams

| Workstream     | Owner   | Library          | Also owns                                                    | Migrations |
| -------------- | ------- | ---------------- | ------------------------------------------------------------ | ---------- |
| Groundedness   | Raphael | `groundedness`   | the foundation (app core) and integration                    | 0300–0399  |
| Data freshness | Pavan   | `freshness`      | ingestion/sync pipeline (Celery, connectors), Tencent deploy | 0100–0199  |
| Access control | Chai    | `access_control` | —                                                            | 0200–0299  |

Core tables (`0001–0099`) belong to the foundation. Ownership rules:

- **Only touch your lib, your adapter, your migration range:** `backend/libs/<your lib>`,
  `backend/app/adapters/<your file>`, `infra/postgres/migrations/<your range>`. Everything else
  goes through Raphael.
- **Libs never import `app`.** Each library depends on Pydantic only and has a test that fails if
  its source imports the app. The app implements the libraries' store Protocols in
  `backend/app/adapters/`.
- Migrations are idempotent SQL files and may reference only their own or lower ranges.

## Project documents

- [Overview and team plan](docs/OVERVIEW.md)
- [Project brief](docs/PROJECT_BRIEF.md) (scope, team plan, integration order)
- [Hackathon requirements](docs/HACKATHON_REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md) (stack, trust boundaries, governed pipeline, Tencent ADP)
- [Data model](docs/DATA_MODEL.md) (tables, frontmatter schema, migration ranges, audit hash)
- [API contract](docs/API_CONTRACT.md) (REST, `AnswerEnvelope`, MCP tools, webhooks)
- [Testing](docs/TESTING.md)
- [Security review](docs/SECURITY_REVIEW.md)
- [Decisions](docs/DECISIONS.md)
- [GBrain mapping](docs/GBRAIN_MAPPING.md)
- [Project status](docs/PROJECT_STATUS.md)
- [Demo corpus](backend/seed/corpus/README.md)
- [Project workflow](PROJECT_STARTER_SYSTEM.md)

## Timeline

Internal milestones leading up to the organizer's deadline:

- 3 October 2026 — team check-in
- 10 October 2026 — research finalized
- 12 October 2026 — foundation skeleton merged (Python monorepo pivot)
- 13 October 2026 — libraries built behind the stubs
- 14 October 2026 — demo script on the real stack, Tencent ADP provider
- 15 October 2026 — video demo and submission package
- 16 October 2026 — submission deadline

The official handbook also lists finalist announcements on 23 October 2026 and the Singapore
Hackathon Demo Day on 3 November 2026 (TBC).

## Official requirements

The submission must use CodeBuddy or WorkBuddy and include proof of that usage (at least three
screenshots or a screen recording). For the FinTech track, the solution must demonstrate unified
querying, bounded data freshness, negative permission enforcement, live permission revocation, and
audit reconstruction. See the [hackathon requirements](docs/HACKATHON_REQUIREMENTS.md) for the
verified checklist, judging rubric, and organizer timeline.

## Credits

The page model and MCP tool names follow [GBrain](https://github.com/garrytan/gbrain) (MIT); see
[GBrain mapping](docs/GBRAIN_MAPPING.md). All demo data is synthetic.

<p align="right">(<a href="#readme-top">back to top</a>)</p>
