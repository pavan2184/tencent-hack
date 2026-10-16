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

- **No-payment public demo (2026-10-13):** `EMBEDDING_PROVIDER=local_hash` permits real ADP answer
  generation with local deterministic retrieval vectors. The synthetic full stack runs on Pavan's
  Mac from an allowlisted staging copy outside the repository; Caddy, API, frontend, Postgres and
  Redis stay bound to loopback. The ADP agent is published on the $0 free plan, and a free
  Cloudflare Quick Tunnel exposes the demo at
  `https://grammar-adds-eau-classics.trycloudflare.com/ask` while this computer and tunnel remain
  running. No paid service was activated.
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

## Fixed 2026-10-13: query history bypassed revocation (Chai)

`GET /api/queries` and `GET /api/queries/{id}` returned stored answers without an access check,
so a revoked user could still read the board deck figures from history and the Ask page. Stored
answers are now re-authorised for the viewer on every read and withheld when any evidence
document is no longer readable (D-017). Regression tests: `app/tests/test_query_history_access.py`.

## Permission snapshot expiry (Chai, 2026-10-13, branch `feat/permission-max-age`)

Built on the access-control v2 work. Snapshots of source permissions now expire by
classification (confidential 5 min) and every delta sync refreshes them, so a revocation at the
source is enforced within 5 minutes for confidential documents (D-018). **The demo stack must run
the Celery worker and beat**, or confidential documents go dark after 5 minutes.

## Audit need-to-know and approval feedback (Chai, 2026-10-13, branch `feat/audit-need-to-know`)

Auditors see every decision but only the answer content they could read themselves; a recorded
"reveal with reason" shows the rest (D-019). Approving a request now tells the approver when the
source platform still withholds the document. **Demo scenario 5 now includes one reveal.**

## Architecture deck (Chai, 2026-10-13)

`docs/presentations/internal-brain-architecture.pptx`: case study, problem, four guarantees, the
end-to-end architecture with trust boundaries and the model-context boundary, native permission
handling per platform, the access-control demo, the five scenarios mapped to tests, answer
receipts, trade-offs and stack. Slides 6 and 10 assume the access-control v2 rules (native
permissions cap local grants), which still need team agreement.

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
  reworded model answer can fall below `GROUNDING_MIN_COVERAGE` and abstain, so the generation
  prompt must keep wording close to the evidence. Not yet measured on the demo questions.
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

## Chai's access-control delivery (12 October 2026)

Branch: `PinZheng/access-control`, integrated with latest `origin/main` at
`fc0bdf6c`. The new foundation merge was incorporated before final verification.

Delivered: ac-v2 source ceiling, query-time validated authority service, live-read
verifier seam, Slack/Drive capture helpers, permission fingerprints, corpus
visibility/revocation demo, primary-source research and security review. Updated
API expectations retain native restrictions after local grant approval and prove
local upload grants still work. Existing foundation docs, migrations and CI were
preserved. Merged via PR #9.

Verification: 174 library tests; 549 offline backend tests passed, 11 database
tests skipped without a database; all 135 Python files pass Ruff lint/format.
The editable architecture deck contains five reviewed slides with native
connectors, an editable permissions table and source notes. File:
superseded by `docs/presentations/internal-brain-architecture.pptx` (PR #7).

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

## Web UI restyle (16 October 2026)

Applied the D-020 visual language across every page and shared component in
`frontend/`, with no API or data-flow changes. Ask now has a pill composer, numbered
pipeline steps as its empty state, coverage stat tiles and numbered claims.
`npm run typecheck` and `npm run lint` pass. All pages were checked visually against
the in-memory API at 1440px and 375px. `next build` (which fetches Inter Tight from
Google Fonts) was not run in this session.

## Access map (16 October 2026)

Added `GET /api/access/map` (managers and admins; D-021) and the `/access/map` page,
linked from Access. The page is an SVG map with this layout: group cards → people →
one line per allowed read → documents inside their source panels. Each line is styled
by its rule family (source ACL, owner, admin, explicit grant). Selecting a person,
group, source or document highlights its paths and labels each line with its policy
rule (`R8:slack`, `R5 · leadership`…). Grant-based access can be revoked from the
document panel (admin or owner), and the map refreshes at once. `.claude/launch.json`
gains an `api-memory` entry (in-memory API on port 8000) for browser checks.

Tests: `backend/app/tests/test_access_map.py` (7 tests: role gate, rules and grant
subjects, admin source ceiling with no title leaks, revocation).

## Extractive composer skips layout lines (Chai, 16 October 2026)

`ExtractiveComposer` no longer picks sentences on heading, table or message-header lines
(`From:`, `Subject:` ...). Before this, "What is the payment rail failover procedure?" in mock
mode answered with the whole vendor table as one claim, and the email header line showed up as a
claim too. `sentence_spans` and the verifier are unchanged, so verify scores do not move. The
composer id stays `extractive-v1` (Raphael to decide whether it should be bumped). Tests: three
new cases in `libs/groundedness/tests/test_compose.py`; full backend suite 686 passed, 11 skipped.
Timeline rows (`**2026-10-10** | Slack — ...`) can still be picked.

## Seed corpus expansion (Chai, 16 October 2026)

The demo corpus now covers each access rule and freshness branch the pipeline enforces, not just
the five scenarios. It grew from 6 personas, 6 sources and 11 pages to 10 personas (9 active),
7 sources (new `confluence-compliance`) and 24 pages. The five scenarios and their facts are
unchanged.

- New personas: `daniel.wong` (CFO, manager), `nora.ibrahim` (Head of Compliance, manager),
  `ravi.kumar` (payments SRE) and `lena.koh` (inactive leaver still on the `#treasury-ops` roster).
  `mei.chen` now has one live Drive share (the Rail-B test plan) and one expired share.
- New access stories, each pinned to its rule: an ethical-wall explicit deny beating a group grant
  (R2), a restricted STR register read through an `auditor` role grant (R5, R6 after revocation),
  an inherited Confluence restriction, an expired and a link-only Drive share, a DM, an email bcc,
  and an inactive account (R1).
- New freshness stories: standard evidence with a newer live version is used with a warning (the
  September incident review), and a critical page deleted upstream is omitted (2025 escalation
  contacts).
- The facts line up across sources (approval email, CFO DM, PAY-155, `#payments-eng`, the liquidity
  policy), so the unified cited query draws on more of them.
- `backend/seed/corpus/README.md` now has the persona table, story tables, the visibility matrix
  (generated from the real policy) and questions to ask. `make smoke` has three more steps
  (ethical wall, contractor scope, deleted page omitted).

Pages whose ACLs changed (PAY-142, PAY-150, both `#general` days, `#treasury-ops`) have bumped
provider versions, because a same-version re-sync is a no-op. A plain `make seed` therefore
upgrades an existing stack, and no `make reset` is needed.

Verification:

- Offline: 711 passed, 11 skipped after merging main (708 on the branch alone); Ruff check and
  format are clean.
- Access-control library: `test_seed_demo.py` now has 23 tests (persona matrix and 12 access
  stories). New `app/tests/test_seed_stories.py` has 9 REST tests.
- `make smoke` against the in-memory API: 15/15 steps pass.
- Throwaway `pgvector/pgvector:pg16` container: migrate and seed on the SQL repo gave
  10/7/24/5 grants (21 fresh, 3 stale), and a re-seed replayed. Seeding the old corpus first and
  then the new one re-applied the bumped pages, and the new ACLs took effect. The container was
  removed. The shared Docker stack on ports 5433/8000 was not touched.
- The access map rendered the new corpus in the browser: John sees 23 documents and 89 paths, and
  Ravi's panel omits the Orionix brief.

For Pavan (freshness): live verification of a provider-deleted object returns `stale`
(`provider_deleted`), not a tombstone. Standard evidence in that state is therefore allowed with a
warning, which is why the deleted seed page is critical. Should a provider deletion always
omit, whatever the class?
