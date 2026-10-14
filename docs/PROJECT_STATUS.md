# Project Status

Last updated: 2026-10-13

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

## Skeleton delivered (PR #1, `feat/foundation-skeleton`, 2026-10-12)

| Workstream                                                             | Owner                                    | State                                                                                                                                    |
| ---------------------------------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `groundedness` library                                                 | Raphael                                  | Done: interfaces, regex sanitizer, extractive + LLM composer, lexical verifier, abstention policy, 185 tests                             |
| `freshness` library                                                    | Pavan                                    | Done: faithful port of the approved spec (enums, models, service, policy, versioning, receipts, in-memory stores), 121 tests             |
| `access_control` library                                               | Chai                                     | Done: principals, raw per-platform permissions, ordered policy R1–R10, stores, 100 tests                                                 |
| App core (config, core, db, services, routers, providers, seed loader) | Raphael                                  | Done: governed pipeline, memory + SQL repos, providers (mock, OpenAI-compatible, Tencent ADP app), connectors, seed loader, 68 app tests |
| Celery, MCP server, webhooks, Dockerfile                               | Raphael (foundation), Pavan (connectors) | Done: six tasks + beat, 18 MCP tools over streamable HTTP, webhook acceptance route, one image with `ROLE` dispatch                      |
| Frontend (persona switcher, ask, documents, sources, access, audit)    | Raphael                                  | Done: all pages wired to the API contract; typecheck, lint, build and Docker image pass                                                  |
| Integration (`make up`, `make seed`, smoke, CI green)                  | Raphael                                  | Done locally (see Verification); CI runs on the PR                                                                                       |

## Fixed 2026-10-13: query history bypassed revocation (Chai)

`GET /api/queries` and `GET /api/queries/{id}` returned stored answers without an access check,
so a revoked user could still read the board deck figures from history and the Ask page. Stored
answers are now re-authorised for the viewer on every read and withheld when any evidence
document is no longer readable (D-015). Regression tests: `app/tests/test_query_history_access.py`.

## Permission snapshot expiry (Chai, 2026-10-13, branch `feat/permission-max-age`)

Built on the access-control v2 work. Snapshots of source permissions now expire by
classification (confidential 5 min) and every delta sync refreshes them, so a revocation at the
source is enforced within 5 minutes for confidential documents (D-016). **The demo stack must run
the Celery worker and beat**, or confidential documents go dark after 5 minutes.

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
- Critical evidence goes `stale` once its index age exceeds 3,600 s. The seed loader live-verifies
  every object at seed time so the age basis is the seed time, but an hour later the KYC runbook
  ages out until reconciliation or verification runs (beat triggers delta/reconcile; Pavan owns
  the policy for refreshing the age basis).
- MCP actor identity reads `X-Actor-Id` from each JSON-RPC request (verified with `mcp` 2.3.0);
  the MCP mount disables the SDK's DNS-rebinding protection because it rejects any host that is
  not `127.0.0.1` (see `docs/SECURITY_REVIEW.md`).
- The persona header is spoofable; never load real data.
- Frontend `/queries` panel shows only the current actor's questions; the API enforces it.
- Upload cap numbers are placeholders (TBD).
- Missing CodeBuddy/WorkBuddy usage evidence makes the project ineligible for scoring.

## Verification

Run on 2026-10-12 (local, Docker 28, uv 0.11, Python 3.12.13, Node 25/npm 11; images use Node 22).

| Check                              | Command                                                     | Result                                                                                                                                                                        |
| ---------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Compose file valid                 | `docker compose --env-file .env.example config -q`          | pass                                                                                                                                                                          |
| Backend + library tests (offline)  | `make test`                                                 | 474 passed, 11 skipped (integration tests need `DATABASE_URL`)                                                                                                                |
| Lint                               | `make lint`                                                 | ruff clean (128 files), eslint clean                                                                                                                                          |
| Frontend typecheck and build       | `make typecheck` and `cd frontend && npm run build`         | pass                                                                                                                                                                          |
| Stack up, migrations applied       | `make up`                                                   | postgres, redis healthy; migrate applied 5 files; api `/healthz` `{db: ok, redis: ok, provider_mode: mock}`; worker registered 6 tasks; beat running                          |
| Seed loaded                        | `make seed`                                                 | 6 principals, 6 sources, 11 pages; verified 10 fresh, 1 stale (failover runbook)                                                                                              |
| Five scenarios end to end          | `make smoke`                                                | 12/12 steps: cited answer (7 citations); runbook stale and omitted; deck citations 8 → 0 and allowed 11 → 10 after revoke; byte-identical 404; audit reconstruction; chain ok |
| MCP initialize, tools/list, whoami | `make mcp-smoke`                                            | pass (18 tools)                                                                                                                                                               |
| Integration tests against Postgres | `cd backend && DATABASE_URL=… uv run pytest -m integration` | 11 passed against a throwaway `pgvector/pgvector:pg16`                                                                                                                        |

Open integration items: confirm the Tencent ADP non-streaming response shape against the console
(`backend/app/providers/real/tencent_adp_app.py`); unhandled 500s carry no `request_id` because
the generic handler runs outside the request-id middleware; upload cap numbers are still TBD.

## Chai's access-control delivery (12 October 2026)

Branch: `PinZheng/access-control`, integrated with latest `origin/main` at
`fc0bdf6c`. The new foundation merge was incorporated before final verification.

Delivered: ac-v2 source ceiling, query-time validated authority service, live-read
verifier seam, Slack/Drive capture helpers, permission fingerprints, corpus
visibility/revocation demo, primary-source research and security review. Updated
API expectations retain native restrictions after local grant approval and prove
local upload grants still work. Existing foundation docs, migrations and CI were
preserved. All changes remain local, with no push or PR.

Verification: 174 library tests; 549 offline backend tests passed, 11 database
tests skipped without a database; all 135 Python files pass Ruff lint/format.
The editable architecture deck contains five reviewed slides with native
connectors, an editable permissions table and source notes. File:
`output/presentations/tencent-internal-brain-architecture-delivery.pptx`.

See [handoff](ACCESS_CONTROL_HANDOFF.md). Native live-provider checks and verified
authentication still require integration. The existing pure-policy read paths
automatically use ac-v2 and passed the core REST scenario tests. Deployment and
credentialed enterprise/Tencent calls have not been verified by this work.

### SQL verification follow-up

The 11 SQL integration tests passed against a disposable local Postgres 17
instance, including the access snapshot round-trip with Drive expiry, deleted
subjects and discovery fields. Combined with the 549 passing offline tests,
all 560 distinct backend tests passed. Postgres 17 was used because pulling the
configured Postgres 16 image was blocked by registry authentication. No shared
database or existing containers were modified. The temporary instance was
removed after the run. The configured Postgres 16 deployment and credentialed
source/Tencent calls were not tested by this work.
