# Project Status

Last updated: 2026-10-12

## Current phase

**Foundation (2026-10-12).** The project pivoted from a TypeScript fork of GBrain to a Python
monorepo (D-001, D-002). Today's goal is the skeleton every developer builds on: monorepo, the
three libraries with public interfaces, stubs and tests, the app core composing them into the
governed pipeline, compose and Makefile, the seeded demo corpus and personas, and the docs. It is
being built by parallel agents in waves and integrated by Raphael. Deadline: **16 October 2026**.

> **Eligibility reminder: CodeBuddy or WorkBuddy usage evidence is mandatory. Capture at least
> three screenshots or a screen recording of CodeBuddy/WorkBuddy conversation history while you
> build, every day until submission. Without it the project is not scored.**

## Completed

- Research and setup (September): track selected, handbook requirements captured in
  `docs/HACKATHON_REQUIREMENTS.md`, freshness design approved (now the reference for the
  `freshness` library).
- Pivot decisions recorded: D-001 to D-012 in `docs/DECISIONS.md`.
- Foundation docs: brief with team plan, architecture with trust-boundary diagram, data model,
  API contract, testing plan, security review, decisions, GBrain mapping, this status page.
- Infrastructure: `docker-compose.yml` (postgres, redis, migrate, api, worker, beat, frontend,
  caddy under profile `edge`), `infra/postgres` init + five migrations (validated against
  `pgvector/pgvector:pg16`, applied twice to prove idempotency), `infra/redis/redis.conf`,
  `infra/caddy/Caddyfile`, CI workflow, `scripts/smoke.sh`.
- Demo corpus: six personas, four groups, 16 freshness policies, six sources and eleven synthetic
  pages engineered for the five scenarios plus a prompt-injection fixture
  (`backend/seed/`).

## In progress (wave 1 → wave 2 → integration)

| Workstream                                                             | Owner                                    | State                                                                                                                         |
| ---------------------------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `groundedness` library                                                 | Raphael                                  | Public interfaces, stubs (regex sanitizer, extractive/LLM composer, lexical verifier, abstention) and tests landing in wave 1 |
| `freshness` library                                                    | Pavan                                    | Faithful port of the approved spec (enums, models, service, policy, versioning, receipts, in-memory stores) landing in wave 1 |
| `access_control` library                                               | Chai                                     | Principals, raw per-platform permissions, ordered policy R1–R10, stores, tests landing in wave 1                              |
| App core (config, core, db, services, routers, providers, seed loader) | Raphael                                  | Wave 2                                                                                                                        |
| Celery, connectors, MCP server, webhooks, Dockerfile                   | Raphael (foundation), Pavan (connectors) | Wave 2                                                                                                                        |
| Frontend (persona switcher, ask, documents, sources, access, audit)    | Raphael                                  | Wave 1                                                                                                                        |
| Integration (`make up`, `make seed`, smoke, CI green)                  | Raphael                                  | Wave 3                                                                                                                        |

## Next

- **Raphael (groundedness + foundation):** integrate waves 1–2; make `make test`, `make up`,
  `make seed`, `make smoke` and CI green; then the LLM composer prompt with `[E#]` markers, the
  entailment verifier, the injection-pattern corpus and groundedness evals; decide the upload cap
  numbers.
- **Pavan (freshness + ingestion + deploy):** delta and reconcile algorithms, backoff and parking,
  Confluence and Slack probes or simulations, port the TS eval fixtures to Python tests; own the
  Celery/connector pipeline; deploy the single box on Tencent Cloud; confirm the ADP embedding
  endpoint, model and dimension.
- **Chai (access control):** real platform-permission ingestion, group resolution, a
  permission-drift hook shared with freshness, final deny wording; review the corpus visibility
  matrix in `backend/seed/corpus/README.md`.
- **Everyone:** PR only `backend/libs/<your lib>`, `backend/app/adapters/<your file>` and
  `infra/postgres/migrations/<your range>`; capture CodeBuddy/WorkBuddy evidence daily.
- **14 Oct:** demo script on the real stack with `PROVIDER_MODE=real` against Tencent ADP.
- **15 Oct:** demo video, cover image (16:9, 380 × 216), project description with measurable
  impact, worked example for each scenario, architecture and trust-boundary diagram export.

## Known risks

- Four days to the deadline; the library stubs are the demo floor, so the five scenario tests must
  pass on stubs alone.
- Tencent ADP embedding endpoint and model are unconfirmed; `EMBEDDING_DIM` must match before the
  first real ingest (otherwise `make reset`).
- Critical evidence goes `stale` once its index age exceeds 3,600 s unless reconciliation or
  verification refreshes the age basis; the seeded KYC runbook could stop being "fresh" an hour
  after `make seed` (open question for Pavan).
- `mcp>=2.0` request access for the actor header inside tools is unverified (ContextVar fallback
  planned).
- The persona header is spoofable; never load real data.
- Upload cap numbers are placeholders (TBD).
- Missing CodeBuddy/WorkBuddy usage evidence makes the project ineligible for scoring.

## Verification

Results are pending integration (wave 3 fills this table).

| Check                              | Command                                                     | Result              |
| ---------------------------------- | ----------------------------------------------------------- | ------------------- |
| Env file matches the example       | `bash scripts/validate_env.sh`                              | pending integration |
| Compose file valid                 | `docker compose --env-file .env.example config -q`          | pending integration |
| Backend + library tests (offline)  | `make test`                                                 | pending integration |
| Lint                               | `make lint`                                                 | pending integration |
| Frontend typecheck and build       | `make typecheck` and `cd frontend && npm run build`         | pending integration |
| Stack up, migrations applied       | `cp .env.example .env && make up`                           | pending integration |
| Seed loaded                        | `make seed`                                                 | pending integration |
| Five scenarios end to end          | `make smoke`                                                | pending integration |
| MCP initialize, tools/list, whoami | `make mcp-smoke`                                            | pending integration |
| Integration tests against Postgres | `cd backend && DATABASE_URL=… uv run pytest -m integration` | pending integration |
