# Tencent Freshness Project Status

Last updated: 2026-09-24

## Completed

- Approved design for the contract-first freshness extension.
- Pinned upstream GBrain `v0.54.1.0` at `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29` integrated with both histories and MIT license retained.
- Tencent freshness docs complete: baseline, requirements mapping, architecture, future data and operation contracts, eval specification, and dated decisions.
- Receipt contract review resolved: persisted requests have a globally unique key and atomic request-hash replay/conflict rule; ephemeral snapshots carry no cross-call or restart idempotency promise.
- Structural documentation contract test added and observed red before the docs were completed, then green after completion.
- Strict synthetic freshness fixture and sealed-gold types, validator, public sanitizer, and complete gate/holdout/gold corpus loader are implemented. The contract tests observed a missing-module RED and then passed all 26 cases; the loader hash covers exact bytes in all three directories. Review fixes require a real parked retry for advanced cursors, bind each delta event to its affected object, and preserve deletion tombstones in later checkpoints until a live provider mutation supersedes them.
- Published the draft 2020-12 freshness JSON Schemas and a deterministic synthetic corpus: ten gate fixtures, two holdouts, and twelve paired sealed gold files. The new committed-corpus tests observed an absent-directory RED before the files were added.
- Hardened sealed gold after review: every ratio with an empty fixture-specific denominator is declared explicitly and fixed at 1.0; live-verification receipts require a matching public verify step and result. The embedding-failure case now includes its unknown verification step.

## In progress

- Freshness eval runner and committed `contract_only` baseline remain to be built. The loader, schemas, and initial corpus are complete.
- Team submission coordination: CodeBuddy or WorkBuddy usage evidence and combined demo artifacts.

## Not started

- Production freshness state machine, database migrations, and PGLite/Postgres methods.
- Live Confluence and Slack connectors and webhook routes; Jira and Google Drive remain planned simulations.
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
