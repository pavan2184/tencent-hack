# Project Status

Last updated: 2026-10-14

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

- **No-payment public demo (2026-10-13):** `EMBEDDING_PROVIDER=local_hash` permits real ADP answer
  generation with local deterministic retrieval vectors. The synthetic full stack runs on Pavan's
  Mac from an allowlisted staging copy outside the repository; Caddy, API, frontend, Postgres and
  Redis stay bound to loopback. The ADP agent is published on the $0 free plan, and a free
  Cloudflare Quick Tunnel exposes the demo while this computer and tunnel remain running. The
  temporary hostname changes on restart; the current verified link is maintained in PR #11's
  handoff. No paid service was activated.
- **Partial answer fix (draft, 2026-10-14):** A real-model candidate with unsupported or off-topic
  claims, or weak procedural claims or citations, can retain only directly relevant, fully
  supported claims and citations after a second deterministic verification. The 60% threshold is
  unchanged; no second model call is made. One public Jordan replay began at 33.33% coverage,
  dropped two claims, and returned only a cited 17-minute hold fact from source version 2 with a
  partial notice. After the final rebuild, another public replay returned only fully supported
  version-2 hold citations and the notice. Its audit confirmed real ADP composition and status
  `partial`. The five public REST scenarios passed, and the synthetic leadership grant was restored.
  The backend suite (587 passed, 11 skipped), frontend typecheck, lint, build, and Compose config
  check passed in the draft branch. Browser replay showed the notice with no console errors. ADP
  output and the free tunnel can vary between runs; a provider timeout still uses the existing
  extractive fallback.

## Temporary demo recovery

On Pavan's Mac, start Docker Desktop and run the existing `proof_demo` Compose project from
`/private/tmp/proof-knowledge-demo/docker-compose.yml`, preserving its named volumes and private
`.env`. Check `http://127.0.0.1:8080/api/healthz` for healthy database, Redis, and
`provider_mode=real`. Start a free `cloudflared` Quick Tunnel to `http://127.0.0.1:8080`,
keep the Mac awake while its process runs, and verify the new public `/ask` and `/api/healthz`
before sharing the new URL. Recheck it before the rehearsal and final submission. Never activate
a paid service or add a payment method.

```sh
docker compose -p proof_demo -f /private/tmp/proof-knowledge-demo/docker-compose.yml --profile edge up -d
curl -fsS http://127.0.0.1:8080/api/healthz
caffeinate -di &
cloudflared tunnel --url http://127.0.0.1:8080
# Use the new hostname printed by cloudflared:
curl -I https://NEW-HOST.trycloudflare.com/ask
curl -fsS https://NEW-HOST.trycloudflare.com/api/healthz
```

Keep the tunnel terminal and Mac running; the hostname changes if the tunnel restarts. Verify
`provider_mode=real` in the health response and record the new URL in the team handoff.
- Research and setup (September): track selected, handbook requirements captured in
  `docs/HACKATHON_REQUIREMENTS.md`, freshness design approved (now the reference for the
  `freshness` library).
- Decisions recorded in `docs/DECISIONS.md`: D-001 to D-012 (pivot), D-013 (deterministic
  grounding and verification, no LLM judge), and D-014 (free ADP chat with local vectors).
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

| Workstream                                                             | Owner                                    | State                                                                                                                                                                                               |
| ---------------------------------------------------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `groundedness` library                                                 | Raphael                                  | Done: interfaces, regex sanitizer, extractive composer, deterministic `ground`, lexical verifier v2 (numeric/date gate, negation cues), abstention policy; the lib is model-free (D-013), 274 tests |
| `freshness` library                                                    | Pavan                                    | Done: faithful port of the approved spec (enums, models, service, policy, versioning, receipts, in-memory stores), 121 tests                                                                        |
| `access_control` library                                               | Chai                                     | Done: principals, raw per-platform permissions, ordered policy R1–R10, stores, 100 tests                                                                                                            |
| App core (config, core, db, services, routers, providers, seed loader) | Raphael                                  | Done: governed pipeline, memory + SQL repos, providers (mock, OpenAI-compatible, Tencent ADP app), connectors, seed loader, 68 app tests                                                            |
| Celery, MCP server, webhooks, Dockerfile                               | Raphael (foundation), Pavan (connectors) | Done: six tasks + beat, 18 MCP tools over streamable HTTP, webhook acceptance route, one image with `ROLE` dispatch                                                                                 |
| Frontend (persona switcher, ask, documents, sources, access, audit)    | Raphael                                  | Done: all pages wired to the API contract; typecheck, lint, build and Docker image pass                                                                                                             |
| Integration (`make up`, `make seed`, smoke, CI green)                  | Raphael                                  | Done locally (see Verification); CI runs on the PR                                                                                                                                                  |

## Next

- **Raphael (groundedness + foundation):** integrate waves 1–2; make `make test`, `make up`,
  `make seed`, `make smoke` and CI green. Done on `feat/groundedness-deterministic`: verifier
  hardening (`lexical-v2`) and the model-free lib, with generation moved to the app's
  `ModelComposer` (D-013). Next: tune the app's generation prompt against the demo questions; the
  injection-pattern corpus; groundedness evals; decide the upload cap numbers.
- **Pavan (freshness + ingestion + deploy):** delta and reconcile algorithms, backoff and parking,
  Confluence and Slack probes or simulations, port the TS eval fixtures to Python tests; own the
  Celery/connector pipeline; rehearse the public ADP-backed demo and monitor its free credit
  balance. TokenHub activation and paid cloud hosting are excluded.
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
- Local hash vectors are deterministic and mostly lexical, so semantic retrieval quality is
  lower than a learned embedding model. The public URL is temporary and stops working when the
  tunnel or Pavan's Mac stops; it can change when restarted. The free ADP credit pool is finite.
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
- Lexical verification bounds paraphrase recall (D-013): with `PROVIDER_MODE=real`, a faithful but
  reworded model answer can fall below `GROUNDING_MIN_COVERAGE`. The broad settlement-drill question
  produced 33% candidate coverage on 14 October; the partial-answer fix retains only fully
  supported, question-relevant facts and still abstains when none can be verified.
- Missing CodeBuddy/WorkBuddy usage evidence makes the project ineligible for scoring.

## Verification

Run on 2026-10-12 (local, Docker 28, uv 0.11, Python 3.12.13, Node 25/npm 11; images use Node 22).

| Check                              | Command                                                     | Result                                                                                                                                                                        |
| ---------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Compose file valid                 | `docker compose --env-file .env.example config -q`          | pass                                                                                                                                                                          |
| Backend + library tests (offline)  | `make test`                                                 | 565 passed, 11 skipped (integration tests need `DATABASE_URL`)                                                                                                                |
| Deterministic groundedness (D-013) | `make test-lib LIB=groundedness` and `make test`            | lib 274 passed (58 in `test_numeric`, 30 in `test_ground`); app 70 passed, 11 skipped (timeout-fallback and unmarked-reply tests in `test_pipeline_invariants.py`)            |
| Lint                               | `make lint`                                                 | ruff clean (131 files), eslint clean                                                                                                                                          |
| Frontend typecheck and build       | `make typecheck` and `cd frontend && npm run build`         | pass                                                                                                                                                                          |
| Stack up, migrations applied       | `make up`                                                   | postgres, redis healthy; migrate applied 5 files; api `/healthz` `{db: ok, redis: ok, provider_mode: mock}`; worker registered 6 tasks; beat running                          |
| Seed loaded                        | `make seed`                                                 | 6 principals, 6 sources, 11 pages; verified 10 fresh, 1 stale (failover runbook)                                                                                              |
| Five scenarios end to end          | `make smoke`                                                | 12/12 steps: cited answer (7 citations); runbook stale and omitted; deck citations 8 → 0 and allowed 11 → 10 after revoke; byte-identical 404; audit reconstruction; chain ok |
| MCP initialize, tools/list, whoami | `make mcp-smoke`                                            | pass (18 tools)                                                                                                                                                               |
| Integration tests against Postgres | `cd backend && DATABASE_URL=… uv run pytest -m integration` | 11 passed against a throwaway `pgvector/pgvector:pg16`                                                                                                                        |

Open integration items: unhandled 500s carry no `request_id` because the generic handler runs
outside the request-id middleware; upload cap numbers are still TBD.

No-payment preview verification (2026-10-13, isolated staging copy): Docker build succeeded;
`/healthz` reported database and Redis healthy; the seeded synthetic corpus loaded; REST smoke
passed 12/12 steps; Chrome showed a cited answer and freshness receipt at
`http://127.0.0.1:8080/ask`. Provider-selection test: 2 passed; backend suite: 570 passed,
11 skipped; Ruff lint and format: pass; all seven checks on draft PR #8 passed. Current local
URLs: `http://127.0.0.1:8080` (Caddy), `http://127.0.0.1:8000` (API), and
`http://127.0.0.1:3000` (frontend). `npm audit --omit=dev` reported a high PostCSS advisory and a
moderate Next.js dependency advisory; these remain unresolved in the existing lockfile.

Real-model and public-link verification (2026-10-13): ADP reported the agent published
successfully. An existing enabled AppKey was placed only in the temporary runtime `.env`; it was
not added to the repository. The API health endpoint reports database and Redis healthy with
`provider_mode: real`. A local ask answered that the Singapore hotel cap is SGD 280, with one
supported citation to the synthetic Travel and Expense Policy; the audit event recorded
`model-v1+ground-v1`, confirming that generation used the model rather than the extractive
fallback. A more complex approval question abstained because lexical support was 50%, below the
60% threshold. The public `/ask` and `/api/healthz` returned HTTP 200, and Chrome showed the
same cited answer and freshness receipt through the tunnel with no console warnings or errors.
The first real-mode container start failed with an `AttributeError` for
`ASK_GENERATION_DEADLINE_S`: the temporary staging copy had an older config file than the source
branch. Refreshing that staged file and rebuilding the containers resolved the startup error;
the repository source was already correct. The tunnel and Docker services are running at handoff.
