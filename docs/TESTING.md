# Testing Plan

Last updated: 2026-10-12

## Testing Philosophy

- **Offline by default.** `make test` needs no network, no Docker, no `.env` and no API keys. The
  app's test fixtures force `PROVIDER_MODE=mock`, use in-memory stores (`app/db/repo_memory.py`
  and each library's `memory.py`), run Celery eagerly (`CELERY_TASK_ALWAYS_EAGER=true`) and use a
  fixed clock. A test that needs the network is a bug.
- **Stubs are the demo floor.** The five demo scenarios must pass on the libraries' stub
  implementations alone, so the demo works even if a library is not finished.
- **Invariants over coverage.** We test what must never happen: denied evidence reaching an LLM,
  a denied document answering differently from a missing one, stale critical evidence being used,
  an uncited claim, quarantined evidence supporting a claim, a wrong number, date or time counted
  as `supported`, an audit edit going undetected.
- **Each library tests itself.** Library tests use only the library and its `memory.py`; they never
  import `app`, and each has a test that fails if its `src/` does.
- **Do not overbuild.** No browser end-to-end suite; the frontend is checked by lint, typecheck and
  build, and the full stack by `scripts/smoke.sh`.

### Mock embeddings are noise

`MockEmbeddingProvider` returns seeded hash vectors. They are deterministic but carry no meaning,
so in mock mode the vector half of hybrid search contributes noise and **retrieval is effectively
keyword search** over the tsvector. Write scenario questions with words that appear in the target
pages (the corpus is built for this: "payment rail failover procedure", "Q3 board deck revenue").
Do not assert on vector-similarity ordering in mock mode.

## Test Commands

```bash
make test                         # backend app + the three libraries (cd backend && uv run pytest -q)
make test-app                     # backend/app/tests only
make test-lib LIB=freshness       # one library: groundedness | freshness | access_control
make lint                         # ruff check + ruff format --check (backend), npm run lint (frontend)
make typecheck                    # frontend tsc
make smoke                        # scripts/smoke.sh against a running stack (make up && make seed)
make mcp-smoke                    # scripts/smoke.sh mcp: initialize -> tools/list -> whoami

bash scripts/run_tests.sh         # = make test
bash scripts/run_checks.sh        # = make lint
```

Opt-in integration tests (need a live Postgres; the compose one is published on `127.0.0.1:5433`):

```bash
make up   # or: docker compose up -d postgres migrate
cd backend && DATABASE_URL=postgresql+psycopg://brain:brain@localhost:5433/brain \
  uv run pytest -q -m integration
```

Tests marked `@pytest.mark.integration` skip unless `DATABASE_URL` is set in the environment and
the marker is selected. The first one migrates an empty database and asserts that every table in
`app/db/models.py` exists.

## Fixtures

`backend/app/tests/conftest.py` (autouse unless stated):

| Fixture    | Provides                                                                                                                         |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------- |
| settings   | `Settings` with `PROVIDER_MODE=mock`, `CELERY_TASK_ALWAYS_EAGER=true`, small caps, `SEED_DIR=backend/seed`, a temp `UPLOAD_DIR`  |
| repo       | `repo_memory.MemoryRepo` installed through `repo.set_repo(...)`                                                                  |
| lib stores | `access_control.memory` stores, `freshness.memory.InMemoryFreshnessStore` + `FixedClock(2026-10-12T09:00:00Z)` + `ScriptedProbe` |
| providers  | `MockChatProvider`, `MockEmbeddingProvider` (dimension `EMBEDDING_DIM`)                                                          |
| `client`   | FastAPI `TestClient` with lifespan; default header `X-Actor-Id: alex.tan`; `client.as_actor("john.tan")` switches persona      |
| `seeded`   | Runs the real seed loader (`app/seed.py`) against `backend/seed/` into the in-memory stores; returns `{slug: document_id}`       |

Library tests build their own fixtures from their `memory.py` (`InMemoryFreshnessStore`,
`FixedClock`, `ScriptedProbe`, `ListChangeSource`, in-memory grant, snapshot, directory and
request stores). `groundedness` has no `memory.py`: it never calls a model (D-013), so its tests
feed literal evidence and generator text.

## Demo scenarios → tests

All five live in `backend/app/tests/test_ask_pipeline.py` and run on the seeded corpus.

| #   | Scenario (handbook)                        | Test                                         | Asserts                                                                                                                                                                 |
| --- | ------------------------------------------ | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Unified natural-language query             | `test_unified_cited_query`                   | `john.tan` asks about the Rail-B cutover; answer not abstained; every claim has ≥ 1 citation; citations span ≥ 2 sources; envelope has receipt, grounding, `audit_id` |
| 2   | Bounded freshness                          | `test_bounded_freshness_stale_omitted`       | failover runbook (critical, indexed v7, live v8) is in the receipt as `stale`, `safe_to_use: false`, and is never cited; the fresh KYC runbook passes verification      |
| 3   | Negative permission without existence leak | `test_negative_permission_no_existence_leak` | `mei.chen` gets no citations and `GET` on the board deck returns a body identical to a random id's `404`; `alex.tan` never sees PAY-142; no denied count anywhere       |
| 4   | Live permission-change handling            | `test_live_revocation_changes_next_answer`   | board deck cited for `john.tan`; `root.admin` revokes the `leadership` grant; the next ask does not cite it and `allowed_count` drops                                 |
| 5   | Audit inquiry                              | `test_audit_reconstruction`                  | `sam.lee` reads the ask's audit event: question, every candidate's decision (incl. denied), receipt id/hash, answer, timestamps; `/api/audit/verify` is `ok`            |

`test_pipeline_invariants.py` asserts the pipeline order (`test_pipeline_order_access_before_llm`):
a recording fake `ChatProvider` wrapped in `ModelComposer`, and a recording sanitizer, prove that
no LLM call, sanitizer pass or freshness evaluation involves a document before
`access_control.filter` has allowed it. The same file covers the real-mode composer without a
network: `test_model_composer_timeout_falls_back` (the fake sleeps past `deadline_s` → the ask is
still answered, by the extractive composer, with `composer == "model-v1->extractive-v1"` in the
audit payload) and `test_model_composer_unmarked_reply_is_grounded` (a reply with no `[E#]`
marker is answered, its citation auto-attached and `supported`, composer `model-v1+ground-v1`).

## Unit Tests (libraries)

- **groundedness** (`libs/groundedness/tests`): `test_models` (report hash stable; no `app`
  import), `test_sanitize` (each pattern and severity; clean text untouched; order and length
  preserved), `test_compose` (every claim cited into non-quarantined evidence; empty → abstained;
  deterministic; negation cues), `test_ground` (`[E#]` marker parsing; unmarked sentences
  auto-cited to the best evidence; zero-overlap sentence cited with `quote=None` and verified
  `unsupported`; `ABSTAIN` and blank text abstain; `max_claims`; never cites quarantined evidence;
  a hallucinated number ends `ungrounded` and abstains), `test_numeric` (number, percentage, date
  and time keys; labels and versions are not facts; verbatim claims skip the gate), `test_verify`
  (thresholds; numeric/date gate; contradiction cues; quarantined never `supported`; coverage
  math), `test_abstain`.
- **freshness** (`libs/freshness/tests`): `test_models` (vocabulary exact; no `app` import),
  `test_accept_event` (duplicate → same id, no second apply), `test_versioning` (older cannot
  overwrite; incomparable → unknown), `test_tombstone`, `test_policy_evaluate` (budgets; unknown
  never fresh; critical non-fresh unsafe), `test_verify` (match, mismatch, probe failure),
  `test_receipt` (order retained; hash deterministic; conflict), `test_checkpoint` (CAS conflict;
  cursor unchanged after a failed page), `test_sync_run` (counts; a failed run is never
  `last_successful_run_id`).
- **access_control** (`libs/access_control/tests`): `test_models` (permission union round-trip per
  kind; no `app` import), `test_policy_rules` (deny beats allow; owner and admin allow; revoked
  allow falls through; restricted and confidential need grants; missing snapshot → deny),
  `test_platform_semantics` (one per platform), `test_filter_no_leak` (one decision per input;
  allowed ⊆ inputs; `AccessSummary` has no denied field), `test_stores`.

## API Tests (app)

| File                           | Covers                                                                                                                                              |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_health_and_errors.py`    | `/healthz`; `401 unauthenticated` / `unknown_actor`; 422 rewritten into the envelope; `X-Request-Id` echoed                                         |
| `test_documents_and_caps.py`   | ACL-filtered list; canonical `404`; upload `201`; extension `422`; size `413`; per-actor and total caps `429`; embedding budget → `budget_exceeded` |
| `test_ask_pipeline.py`         | the five scenarios above                                                                                                                            |
| `test_pipeline_invariants.py`  | access before any LLM; injection fixture quarantined; `ModelComposer` deadline fallback; unmarked model reply grounded                              |
| `test_audit_chain.py`          | append/verify; tampering with a payload, deleting a row, or reordering is detected at the right `seq`                                               |
| `test_seed.py`                 | seed is idempotent; 10 principals, 4 groups, 16 policies, 7 sources, 24 pages; grants restored on re-seed                                           |
| `test_seed_stories.py`         | the corpus access and freshness stories over REST: ethical wall, DM, bcc, inherited and restricted pages, Drive expiry and link-only, inactive actor |
| `test_connectors_and_tasks.py` | `gbrain_import` list/fetch/head (incl. `simulate`); stubs raise `NotImplementedError`; tasks registered; webhook `202`/duplicate/`501`              |
| `test_mcp.py`                  | lifespan `initialize` → `tools/list` → `tools/call whoami` (`X-Actor-Id: alex.tan`) → `tools/call query` → envelope keys                            |

## Frontend Tests

`npm run lint`, `npm run typecheck` and `npm run build` in CI. Manual check: the persona switcher
changes what `/documents` and `/ask` show; a denied document page shows the generic not-found view.

## End-to-End Tests

`scripts/smoke.sh` runs against a live stack (`make up && make seed`) with `curl` and `jq`:
healthz → principals → upload a temporary `.md` as `alex.tan` → ask the failover question as
`john.tan` (runbook not cited, receipt marks it unsafe) → find the board deck and list its grants
as `root.admin` (restoring the `leadership` grant if a previous run revoked it) → ask the Q3
question (deck cited) → revoke → re-ask (deck not cited, `allowed_count` lower) → `mei.chen`
existence probe (denied and nonexistent `404`s byte-identical) → audit lookup as `sam.lee` → audit
verify. It prints one line per step and exits non-zero on the first failure. `smoke.sh mcp`
initializes an MCP session, lists tools (must include `query`) and calls `whoami`.

## Regression Tests

- Every bug that leaked existence, used stale critical evidence or broke the audit chain gets a
  test in the matching file before the fix lands.
- The canonical `404` body is compared byte for byte, not by status code.

## Edge Cases

- Question with no matching evidence → abstained, empty citations, still audited.
- All candidates denied → abstained with the same wording as "no evidence" (no hint of denial).
- Probe failure on critical evidence → `unknown`, omitted, never `fresh`.
- Duplicate webhook delivery → same `event_id`, no second mutation.
- Re-seeding after a demo revocation restores the grant without duplicating active grants.
- Upload exactly at `UPLOAD_MAX_FILE_BYTES` succeeds; one byte more → `413`.
- `X-Actor-Id` of an inactive principal → `401 unknown_actor`.
- Prompt-injection fixture (`channels/general/2026-10-11`) is quarantined and never cited.
- Model timeout or provider error with `PROVIDER_MODE=real` → extractive answer, composer
  `model-v1->extractive-v1`, still audited; the ask never returns `503`.

## Manual Verification

1. `cp .env.example .env && make up` → all services healthy, `migrate` exited 0.
2. `curl localhost:8000/healthz` → `ok`, db `ok`, redis `ok`, `provider_mode` `mock`.
3. `make seed` → summary of principals, policies, sources, pages.
4. `http://localhost:3000` → switch personas; documents list changes.
5. `make smoke` and `make mcp-smoke` pass.

## CI

`.github/workflows/ci.yml`: `backend` matrix (`app/tests`, `libs/groundedness/tests`,
`libs/freshness/tests`, `libs/access_control/tests`; `uv sync --all-packages && uv run pytest -q
<path>`), `lint` (ruff check + format check), `frontend` (`npm ci`, lint, typecheck, build),
`compose` (`docker compose --env-file .env.example config -q`).

## Access-control verification (12 October 2026)

The library now has 174 tests, including source ceilings, stale/wrong-kind ACLs,
unknown Slack rosters, Drive expiry/deletion/discovery, malformed store responses,
query-time grant/group/source revocation and conflicting duplicate ids. The ten
real synthetic personas are checked against all 24 corpus documents (updated 16 October 2026),
and each access story in `backend/seed/corpus/README.md` is pinned to its rule.

The full offline backend suite passes 549 tests, with 11 database tests skipped
without `DATABASE_URL`. Core REST tests cover source restrictions after a local
grant, byte-identical missing/denied responses, upload grant/revoke, and all five
Tencent scenarios. The no-leak assertion checks answer text/claims/citations so
a timestamp containing `48.6` cannot cause an unrelated failure. All 135 backend
Python files pass Ruff lint/format checks. Existing CI already runs the library
and app suites, so no additional CI job is needed.

Run `uv run --frozen python libs/access_control/examples/revocation_demo.py` from
`backend` for the standalone corpus demo. The PPT is validated structurally and
rendered from the exported file for review. Live source tenants and Tencent model
responses are outside this offline verification.

### SQL verification follow-up

The 11 SQL integration tests passed against a disposable local Postgres 17
instance, including the access snapshot round-trip with Drive expiry, deleted
subjects and discovery fields. Combined with the 549 passing offline tests,
all 560 distinct backend tests passed. Postgres 17 was used because pulling the
configured Postgres 16 image was blocked by registry authentication. No shared
database or existing containers were modified. The temporary instance was
removed after the run. The configured Postgres 16 deployment and credentialed
source/Tencent calls were not tested by this work.
