# Tencent Freshness Project Status

Last updated: 2026-09-24

## Foundation handoff

- Docs/eval foundation: complete. Contract gate: passing (`contract_only`, 12 synthetic fixtures: 10 gate and 2 holdout).
- Behavioral runner/baseline: not implemented; no behavioral claim. Production freshness implementation is ready for a separate plan.
- Live smoke execution: not run until adapters and disposable test tenants exist. No production latency or freshness SLA has been measured.
- Upstream pin: GBrain `v0.54.1.0` at `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29`. Complete corpus hash: `2a6c2245b4e0645274a04263c1a72b563ab80e163f80da52597b29a358f3a3ec`.

## Completed

- Approved design for the contract-first freshness extension.
- Pinned upstream GBrain `v0.54.1.0` at `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29` integrated with both histories and MIT license retained.
- Tencent freshness docs complete: baseline, requirements mapping, architecture, future data and operation contracts, eval specification, and dated decisions.
- Receipt contract review resolved: persisted requests have a globally unique key and atomic request-hash replay/conflict rule; ephemeral snapshots carry no cross-call or restart idempotency promise.
- Structural documentation contract test added and observed red before the docs were completed, then green after completion.
- Strict synthetic freshness fixture and sealed-gold types, validator, public sanitizer, and complete gate/holdout/gold corpus loader are implemented. The contract tests observed a missing-module RED and then passed all 26 cases; the loader hash covers exact bytes in all three directories. Review fixes require a real parked retry for advanced cursors, bind each delta event to its affected object, and preserve deletion tombstones in later checkpoints until a live provider mutation supersedes them.
- Published the draft 2020-12 freshness JSON Schemas and a deterministic synthetic corpus: ten gate fixtures, two holdouts, and twelve paired sealed gold files. The new committed-corpus tests observed an absent-directory RED before the files were added.
- Hardened sealed gold after review: every ratio with an empty fixture-specific denominator is declared explicitly and fixed at 1.0; live-verification receipts require a matching public verify step and result. The embedding-failure case now includes its unknown verification step.
- Added the committed `contract_only` baseline, strict hash/config/coverage/threshold validator, and hermetic `check:freshness-evals` verify gate. Its output is a contract summary, not a behavioral result.
- Added manual, non-CI Confluence and Slack live-smoke runbooks for disposable test tenants. They define evidence, lifecycle/recovery observations, and cleanup without asserting an implemented adapter or measured live result.

## In progress

- Freshness behavioral eval runner remains to be built. The contract baseline, loader, schemas, and initial corpus are complete.
- Team submission coordination: CodeBuddy or WorkBuddy usage evidence and combined demo artifacts.

## Not started

- Production freshness state machine, database migrations, and PGLite/Postgres methods.
- Live Confluence and Slack connectors and webhook routes; Jira and Google Drive remain planned simulations.
- Execution of the Confluence and Slack live-smoke runbooks; they require future provider adapters and controlled test-tenant access.
- Behavioral baseline, logical-time scoring, and manual provider latency evidence.

## Out of scope here

- Access control, identity/permission decisions, and permission evaluations (Chai's workstream).
- Groundedness, claim entailment, and answer-level scoring (Raphael's workstream).

## Verification and risk record

The documentation contract is structural only; it validates published markers, not behavioral freshness. The approved 60/300/3600-second targets have no measured result yet. Live API scopes and controlled provider spaces may take setup time. Missing CodeBuddy/WorkBuddy usage evidence would affect challenge eligibility. The combined submission still needs its demo walkthrough, architecture diagram, description, cover image, and worked examples.

The targeted documentation contract and generated structural inventory checks pass. An attempted full upstream unit run encountered a failure in `test/skillpack-scaffold-harness.test.ts`: its CLI init returned “A content-root component is not a real directory.” The same failure reproduced in an isolated run (21 pass, 1 fail). The full suite was stopped after that failure and is not reported as passing; this issue was not changed by the documentation task.

An additional `bun run typecheck` attempt aborted when Node 24.2.0 reached its roughly 2 GiB heap limit, before reporting TypeScript diagnostics. Typecheck therefore has no pass result for this task.

For the freshness loader task, `bun test test/freshness-eval-contract.test.ts` passed (26 tests). Default-heap typecheck again aborted at roughly 2 GiB; `NODE_OPTIONS=--max-old-space-size=6144 bun run typecheck` passed. The first full `bun run test` attempt could not find `bun` in child-shell `PATH`; it was rerun with `/Users/pavan/.bun/bin` on `PATH`. That run reproduced the inherited `test/skillpack-scaffold-harness.test.ts` failure and was interrupted before the 1,916-file shard completed, so it has no full-suite pass result. No local server is running.

For the committed freshness corpus task, the new tests first failed on absent
`evals/freshness` directories and schemas, then passed all 30 focused cases.
Both existing privacy guards include the freshness fixture, holdout, and gold
directories and passed; negative-path tests proved they reject injected
privacy violations. Draft 2020-12 schema compilation and validation passed
for all 24 corpus JSON documents. The 6 GiB typecheck passed. A full
`bun run test` attempt adapted to one shard and one file at a time because
only about 2 GiB was available; it was stopped with exit 130 after steady
progress, so there is no full-suite pass result. The isolated inherited
`test/skillpack-scaffold-harness.test.ts` failure reproduced (21 pass,
1 fail): CLI init returned “A content-root component is not a real
directory.” No local server is running.

Review fix round 1 used test-first checks for omitted, spurious, duplicate,
unknown, and non-1.0 empty-denominator declarations, plus live-verification
receipt provenance. The focused test first failed on the undeclared field
and missing provenance rule, then passed all 33 cases. All four JSON Schemas
compiled; Ajv validated all 24 fixture and gold documents. Both privacy
guards and the 6 GiB typecheck passed. The inherited full suite was not
rerun.

For the contract baseline task, the new test first failed on absent
`src/eval/freshness/baseline.ts`, then the combined corpus and baseline tests
passed all 66 cases. `bun run check:freshness-evals`, the generated structural
inventory check, baseline JSON Schema validation, and the 6 GiB typecheck
passed. The full `bun run test` attempt memory-adapted to one shard and one
file at a time with about 2 GiB available; it was interrupted with exit 130
after roughly four of 1,917 files in over two minutes, so it has no full-suite
pass result. The isolated inherited `test/skillpack-scaffold-harness.test.ts`
failure reproduced (21 pass, 1 fail): CLI init returned “A content-root
component is not a real directory.” No local server is running.

Contract-baseline review fix round 4 checks affirmative claims inside balanced
interruptions before checking the rejoined surrounding clause. Six new positive
regressions first failed; after the fix, all 61 baseline tests and all 94 combined
freshness tests passed, including cautionary comparisons and prior Markdown
regressions. The contract check, 6 GiB typecheck, and diff whitespace check passed.
The full suite was not rerun for this focused review fix. This remains a bounded
prose guard, with no behavioral runner or natural-language parser added.

For the manual live-smoke runbooks, the documentation contract first failed
because both provider runbooks were absent, then passed all 9 focused tests.
The structural inventory was regenerated for the two added cases and its
freshness check passed. `check:freshness-evals`, the 6 GiB typecheck, the
forbidden-marker/secret scan, and diff whitespace checks passed. The full
project suite was not rerun for this documentation-focused task. No live
provider smoke was executed, no latency was measured, and no local server is
running. Future execution requires implemented adapters and disposable test
tenants.

## Final foundation verification (2026-09-24)

Bun `1.4.2` (`744846f84`) was on `PATH`; TypeScript and full verify used `NODE_OPTIONS=--max-old-space-size=6144`. All commands below ran in this worktree. An exit 0 for a contract check proves only contract integrity.

| Command | Result |
| --- | --- |
| `LLMS_REPO_BASE=https://raw.githubusercontent.com/pavan2184/tencent-hack/main bun run build:llms` | Exit 0; fork index and full bundle generated. The final bundle is 489,493 bytes, below the 800,000-byte budget. Generated source links use the fork URL; upstream links inside inherited document bodies remain upstream references. |
| `bun scripts/classify-tests.ts`; `bun run check:structural-manifest` | Exit 0; 341 structural suites, 1,477 cases, 196 files, zero unknown; regeneration caused no TSV diff. |
| `bun test test/freshness-docs-contract.test.ts test/freshness-eval-contract.test.ts test/freshness-eval-baseline.test.ts` | Exit 0; 104 passed, zero failed. |
| `bun run check:freshness-evals`; `env -i PATH="/Users/pavan/.bun/bin:/usr/bin:/bin:/usr/sbin:/sbin" bun run check:freshness-evals` | Both exit 0 with the same `contract_only`, 12/10/2 count and corpus hash above; no provider or AI credentials required. |
| `bun run check:fixture-privacy`; `bun run check:synthetic-corpus-privacy` | Both exit 0; no banned fixture tokens or corpus privacy violations. |
| `bun test test/build-llms.test.ts`; `bun test test/scripts/check-key-files-current-state.test.ts` | Exit 0; 12 and 13 cases passed respectively. |
| `bun run typecheck`; `git diff --check` | Exit 0 with 6 GiB Node heap for typecheck; no whitespace errors. |
| `bun install --frozen-lockfile` | Exit 0; 290 installs checked, no dependency changes. |
| `bun run verify` | First attempt exited 1: 54/56 checks passed. The orphan guard counted 48 test-only modules against 46, including three intentionally test-only freshness eval modules; README was 45,503 bytes against its 45,000-byte cap. After the narrow guard assertion and README compression, the latest run exited 0: 56/56 passed. |
| `bun run test` | Exit 130 after an explicit interrupt at about 3 minutes 30 seconds: the memory-adapted runner used one shard and one file at a time, with 30 of 1,917 files complete and a several-hour projection. This is an incomplete full-suite result, not a pass. One inherited skillpack case had already failed. |
| `bun test test/skillpack-scaffold-harness.test.ts` | Default temp path exited 1 (21 pass, one fail): CLI init reported “A content-root component is not a real directory.” The test and product source are unchanged from the upstream pin. `TMPDIR=/private/tmp bun test test/skillpack-scaffold-harness.test.ts` exited 0 (22 pass), confirming the default macOS `/var` symlink path as the local cause. No product behavior was changed for this. |
| Pin, ancestry, scope, non-claim, and link audits | Exact `v0.54.1.0` tag and ancestor checks exited 0; no tracked `.codex` files; no unfinished markers, affirmative measured-behavior claims, or access-control implementation markers in the scoped freshness files; 55 fork links in `llms.txt` and 30 fork `Source:` links in `llms-full.txt`. |

Database E2E was not run: `DATABASE_URL` is unset and no disposable Postgres/PgBouncer environment was provisioned. No provider live smoke was run and no local server is running. The full unit suite remains unverified despite the clean isolated skillpack rerun.
