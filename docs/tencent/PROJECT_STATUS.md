# Tencent Freshness Project Status

Last updated: 2026-09-24

## Completed

- Approved design for the contract-first freshness extension.
- Pinned upstream GBrain `v0.54.1.0` at `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29` integrated with both histories and MIT license retained.
- Tencent freshness docs complete: baseline, requirements mapping, architecture, future data and operation contracts, eval specification, and dated decisions.
- Receipt contract review resolved: persisted requests have a globally unique key and atomic request-hash replay/conflict rule; ephemeral snapshots carry no cross-call or restart idempotency promise.
- Structural documentation contract test added and observed red before the docs were completed, then green after completion.
- Strict synthetic freshness fixture and sealed-gold types, validator, public sanitizer, and complete gate/holdout/gold corpus loader are implemented. The contract tests observed a missing-module RED and then passed all 21 cases; the loader hash covers exact bytes in all three directories.

## In progress

- Freshness eval corpus: committed synthetic fixtures, gold files, JSON schemas, and a `contract_only` baseline remain to be built. The loader and validation contract are complete.
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

For the freshness loader task, `bun test test/freshness-eval-contract.test.ts` passed (21 tests). Default-heap typecheck again aborted at roughly 2 GiB; `NODE_OPTIONS=--max-old-space-size=6144 bun run typecheck` passed. The first full `bun run test` attempt could not find `bun` in child-shell `PATH`; it was rerun with `/Users/pavan/.bun/bin` on `PATH`. That run reproduced the inherited `test/skillpack-scaffold-harness.test.ts` failure and was interrupted before the 1,916-file shard completed, so it has no full-suite pass result. No local server is running.
