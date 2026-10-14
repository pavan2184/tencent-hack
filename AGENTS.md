# AI Coding Instructions

Last updated: 2026-10-12

Before writing code, always read:

1. docs/PROJECT_BRIEF.md
2. docs/ARCHITECTURE.md
3. docs/DATA_MODEL.md
4. docs/API_CONTRACT.md
5. docs/TESTING.md
6. docs/DECISIONS.md
7. docs/PROJECT_STATUS.md

## Working Rules

- At the start of work in any project, check for a root `progress.md`. If it
  exists, read it before planning or editing.
- After meaningful work in any project, update the root `progress.md` when it
  exists. Record what changed, what verification ran, unresolved errors or
  skipped checks, known risks, and current local server URLs if servers are
  running.
- Do not start coding until the project brief, architecture, data model, API contract, and test plan exist.
- Prefer small, incremental changes over large rewrites.
- Never change protected files unless explicitly asked.
- Never invent environment variables. Check `.env.example`.
- Never remove tests to make a build pass.
- After every feature, update `docs/PROJECT_STATUS.md`.
- After every architectural decision, update `docs/DECISIONS.md`.
- For backend work, add tests.
- For auth, payments, legal, financial, health, or personal-data features, run a security review.
- For LLM features, consider prompt injection, data leakage, logging risk, and output unreliability.
- Use existing project patterns before adding new abstractions or dependencies.
- Keep changes scoped to the task unless the user explicitly asks for refactoring.

## Workstream boundaries

| Workstream     | Owner   | You may change                                                                                                | Entry points other code relies on                                                                                             |
| -------------- | ------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Groundedness   | Raphael | `backend/libs/groundedness/**`, `infra/postgres/migrations/03xx_*`                                            | `sanitize → ground → verify → should_abstain`; `ground` runs inside the composer called from `app/services/retrieval.py`      |
| Data freshness | Pavan   | `backend/libs/freshness/**`, `backend/app/adapters/freshness_store.py`, `infra/postgres/migrations/01xx_*`    | `FreshnessService` (`accept`, `connector_sync`, `freshness_status`, `evaluate`, `verify_freshness`, `freshness_receipt`)      |
| Access control | Chai    | `backend/libs/access_control/**`, `backend/app/adapters/access_stores.py`, `infra/postgres/migrations/02xx_*` | `DefaultAccessPolicy.decide/filter`, store Protocols, `Principal`                                                             |
| Foundation     | Raphael | everything else (`backend/app/**`, `frontend/**`, `infra/**`, docs, compose, CI, core migrations `00xx_*`)    | `get_principal`, the repo, the governed pipeline, `ModelComposer` (`app/services/compose.py`, generation), the error envelope |

Ownership rules:

- **Only touch your lib, your adapter, your migration range.** Changes elsewhere go through the
  foundation owner (Raphael) in a separate PR.
- **Libs never import `app`.** Libraries are pure Python with Pydantic as their only dependency;
  each has a test that fails if its `src/` imports the app. The app implements their `*Store`
  Protocols in `backend/app/adapters/`.
- **Pipeline order is an invariant.** Nothing may call an LLM, probe freshness, or put evidence in
  a response before `access_control.filter` has allowed it.
- **No existence leaks.** Denied documents get the same `404` as missing ones; no denied counts in
  any asker-visible payload.
- **Migrations** are idempotent numbered SQL files in your range, one transaction each, no psql
  meta-commands or `CONCURRENTLY`, and may reference only the same or lower ranges. Never edit an
  applied file; add a new one.
- **Tests stay offline** (`make test` must pass with no network, no Docker and no `.env`).
