# GBrain Freshness Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `pavan2184/tencent-hack` into a pinned, attributed GBrain-derived repository and land the Tencent FinTech data-freshness documentation plus a hermetic, sealed-gold freshness evaluation contract before any production freshness state machine or connector code is written.

**Architecture:** Preserve GBrain `v0.54.1.0` at commit `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29` as the root application, move Tencent-specific material under `docs/tencent/`, and add a standalone `src/eval/freshness/` contract layer. The eval layer loads deterministic gate and holdout fixtures, keeps expectations in a sealed gold directory, hashes the complete corpus, and validates a deliberately `contract_only` baseline. It does not call providers, databases, networks, LLMs, or claim production behavior has passed.

**Tech Stack:** Bun `>=1.3.11`, TypeScript, Bun test, JSON Schema 2020-12, Bash, Git/GitHub, GBrain's existing test and verification scripts.

**Spec:** `docs/superpowers/specs/2026-09-24-gbrain-freshness-foundation-design.md`

## Global Constraints

- Work from an isolated Git worktree on branch `codex/gbrain-freshness-foundation`; do not implement directly on `main`.
- Retain both histories. Do not force-push, squash away the upstream merge, or replace the repository contents by copying files from a tarball.
- Pin and verify upstream commit `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29` and release `v0.54.1.0` before merging.
- Preserve upstream `LICENSE`, attribution, root documentation, application code, tests, and Git history.
- Treat GBrain's root `CLAUDE.md`, `AGENTS.md`, `docs/TESTING.md`, and operation/source/engine invariants as authoritative after integration.
- Keep access control, RBAC, identity mapping, permission evaluation, and groundedness out of this workstream. Chai and Raphael own those separate concerns.
- Use Confluence and Slack as live-MVP provider identities in documentation; Jira and Google Drive are deterministic simulations in this phase.
- Keep all committed fixture content synthetic. Do not use Pavan's data, a real company, real credentials, or copied provider payloads.
- Keep gold sealed: fixture files may not contain expected outcomes, and production/eval adapters may never receive gold objects.
- Tests and checks are hermetic: no network, provider keys, database service, wall-clock sleeps, or LLM calls.
- The baseline status is exactly `contract_only`. It proves schema/corpus integrity only; it must not be presented as measured freshness performance.
- Do not edit `scripts/structural-suites.tsv` manually. Regenerate it with `bun scripts/classify-tests.ts` if the new suites change the generated inventory.
- Do not add a row to `scripts/guards-manifest.tsv`: the freshness check is a TypeScript contract check, not a shell scanner guard.
- Do not touch the untracked root `.codex/` directory.
- Use `apply_patch` for content edits. Use `git mv` only for path-preserving renames.
- After each task, run the named targeted checks and make the named commit. Stop on any unexpected failure instead of weakening a test.
- Update `docs/tencent/PROJECT_STATUS.md` after each meaningful task and record skipped checks or environmental blockers.
- Production tables, migrations, provider adapters, webhook routes, operations, live verification, and behavioral scoring are explicitly deferred to a later implementation plan.

## Review Focus

Reviewers must give special attention to these five failure modes, each of which has a named test below:

1. A reordered or lower provider version must never describe the expected current state after a higher comparable version has been accepted.
2. A cursor may advance after a poison event is durably parked only when the affected evidence is expected to be non-current; it must never advance past unaccounted work.
3. Content that was written but whose embeddings/searchability failed is not expected to be `fresh` or usable.
4. A provider deletion with a retained searchable object is a hard failure and must require a tombstone.
5. A `contract_only` baseline must never be accepted or described as a measured green behavioral baseline.

---

## Task 1: Create the isolated worktree and integrate pinned GBrain history

**Files:**

- Move: `docs/PROJECT_BRIEF.md` → `docs/tencent/PROJECT_BRIEF.md`
- Move: `docs/HACKATHON_REQUIREMENTS.md` → `docs/tencent/HACKATHON_REQUIREMENTS.md`
- Move: `docs/ARCHITECTURE.md` → `docs/tencent/FRESHNESS_ARCHITECTURE.md`
- Move: `docs/DATA_MODEL.md` → `docs/tencent/FRESHNESS_DATA_MODEL.md`
- Move: `docs/API_CONTRACT.md` → `docs/tencent/FRESHNESS_API_CONTRACT.md`
- Move: `docs/TESTING.md` → `docs/tencent/FRESHNESS_EVALS.md`
- Move: `docs/DECISIONS.md` → `docs/tencent/DECISIONS.md`
- Move: `docs/PROJECT_STATUS.md` → `docs/tencent/PROJECT_STATUS.md`
- Move: `docs/SECURITY_REVIEW.md` → `docs/tencent/SECURITY_REVIEW.md`
- Delete: `.env.example`
- Delete: `PROJECT_STARTER_SYSTEM.md`
- Delete: `scripts/bootstrap_project.sh`
- Delete: `scripts/run_checks.sh`
- Delete: `scripts/run_tests.sh`
- Delete: `scripts/validate_env.sh`
- Merge from upstream: all paths at GBrain commit `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29`
- Modify after merge: `AGENTS.md`
- Modify after merge: `README.md`

- [ ] **Step 1: Read the required project and skill instructions before changing state**

Read the approved spec, current project docs, and the complete skills required for isolated execution and plan execution:

```bash
sed -n '1,900p' docs/superpowers/specs/2026-09-24-gbrain-freshness-foundation-design.md
sed -n '1,240p' docs/PROJECT_BRIEF.md
sed -n '1,240p' docs/ARCHITECTURE.md
sed -n '1,240p' docs/DATA_MODEL.md
sed -n '1,240p' docs/API_CONTRACT.md
sed -n '1,240p' docs/TESTING.md
sed -n '1,240p' docs/DECISIONS.md
sed -n '1,240p' docs/PROJECT_STATUS.md
sed -n '1,260p' /Users/pavan/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.1/skills/using-git-worktrees/SKILL.md
sed -n '1,320p' /Users/pavan/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.1/skills/executing-plans/SKILL.md
```

Expected: every file exists and the execution skill selected by Pavan is followed. If subagent-driven execution was selected, read that skill instead of `executing-plans` and follow its review checkpoints.

- [ ] **Step 2: Confirm the starting repository is clean except for the known local `.codex/` directory**

```bash
git status --short --branch
git fetch origin
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
```

Expected: branch `main` matches `origin/main`; `.codex/` may appear as untracked and must remain untouched. Stop for any other tracked or untracked user work.

- [ ] **Step 3: Create the isolated worktree**

Follow `superpowers:using-git-worktrees` for directory selection and safety checks, then create:

```bash
git worktree add ../tencent-hack-gbrain-freshness -b codex/gbrain-freshness-foundation main
cd ../tencent-hack-gbrain-freshness
git status --short --branch
```

Expected: clean branch `codex/gbrain-freshness-foundation` in the new worktree.

- [ ] **Step 4: Rehome the Tencent docs and remove only obsolete starter scaffolding**

```bash
set -e
mkdir -p docs/tencent
git mv docs/PROJECT_BRIEF.md docs/tencent/PROJECT_BRIEF.md
git mv docs/HACKATHON_REQUIREMENTS.md docs/tencent/HACKATHON_REQUIREMENTS.md
git mv docs/ARCHITECTURE.md docs/tencent/FRESHNESS_ARCHITECTURE.md
git mv docs/DATA_MODEL.md docs/tencent/FRESHNESS_DATA_MODEL.md
git mv docs/API_CONTRACT.md docs/tencent/FRESHNESS_API_CONTRACT.md
git mv docs/TESTING.md docs/tencent/FRESHNESS_EVALS.md
git mv docs/DECISIONS.md docs/tencent/DECISIONS.md
git mv docs/PROJECT_STATUS.md docs/tencent/PROJECT_STATUS.md
git mv docs/SECURITY_REVIEW.md docs/tencent/SECURITY_REVIEW.md
git rm .env.example PROJECT_STARTER_SYSTEM.md \
  scripts/bootstrap_project.sh scripts/run_checks.sh scripts/run_tests.sh scripts/validate_env.sh
git status --short
```

Expected: only the listed renames/deletions are staged or unstaged; the approved spec remains under `docs/superpowers/specs/`.

- [ ] **Step 5: Commit the repository preparation**

```bash
git add docs/tencent docs/superpowers
git commit -m "chore: prepare repository for GBrain integration"
```

- [ ] **Step 6: Add and verify the upstream remote and immutable pin**

```bash
set -e
if git remote get-url upstream >/dev/null 2>&1; then
  test "$(git remote get-url upstream)" = "https://github.com/garrytan/gbrain.git"
else
  git remote add upstream https://github.com/garrytan/gbrain.git
fi
git fetch upstream master --tags
test "$(git rev-parse 'v0.54.1.0^{commit}')" = "6040075c6cb95be5881cc2e1b76ef7d71f4e5d29"
git show -s --format='%H %D %s' 6040075c6cb95be5881cc2e1b76ef7d71f4e5d29
```

Expected: the equality check succeeds and the shown commit is the GBrain `v0.54.1.0` commit. Do not merge if the tag resolves differently.

- [ ] **Step 7: Merge the exact upstream commit and resolve only the four known conflicts**

```bash
set -e
git merge --allow-unrelated-histories --no-commit 6040075c6cb95be5881cc2e1b76ef7d71f4e5d29
git diff --name-only --diff-filter=U | sort
```

Expected unresolved paths, exactly:

```text
AGENTS.md
CLAUDE.md
README.md
docs/TESTING.md
```

Resolve those four from upstream first:

```bash
git checkout --theirs AGENTS.md CLAUDE.md README.md docs/TESTING.md
git add AGENTS.md CLAUDE.md README.md docs/TESTING.md
test -z "$(git diff --name-only --diff-filter=U)"
```

If the conflict set differs, stop and inspect; do not use a blanket `--theirs` over the repository.

- [ ] **Step 8: Add the narrow Tencent amendments to upstream root instructions and README**

Append a `Tencent FinTech freshness extension` section to `AGENTS.md` that requires reading:

```text
docs/tencent/PROJECT_BRIEF.md
docs/tencent/HACKATHON_REQUIREMENTS.md
docs/tencent/UPSTREAM_BASELINE.md
docs/tencent/FRESHNESS_ARCHITECTURE.md
docs/tencent/FRESHNESS_DATA_MODEL.md
docs/tencent/FRESHNESS_API_CONTRACT.md
docs/tencent/FRESHNESS_EVALS.md
docs/tencent/DECISIONS.md
docs/tencent/PROJECT_STATUS.md
```

The section must say this branch owns data freshness only, must preserve GBrain invariants, must keep evals hermetic and synthetic, and must not implement access control or groundedness.

Add a concise README section immediately after the upstream introduction containing:

```markdown
## Tencent FinTech freshness extension

This repository derives from GBrain v0.54.1.0 and adds a contract-first data-freshness layer for the Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 FinTech track. The pinned upstream baseline, architecture, API contracts, and hermetic evaluation design live in [`docs/tencent/`](docs/tencent/UPSTREAM_BASELINE.md).

The current phase contains documentation and evaluation contracts only. It does not yet claim measured production freshness behavior, and access control and answer groundedness are separate team workstreams.
```

- [ ] **Step 9: Verify merge shape, attribution, and scope**

```bash
set -e
test -f LICENSE
test -f package.json
test -f src/core/operations.ts
test -f docs/tutorials/company-brain.md
test -f docs/tencent/PROJECT_BRIEF.md
grep -q '"version": "0.54.1.0"' package.json
test "$(git rev-parse MERGE_HEAD)" = "6040075c6cb95be5881cc2e1b76ef7d71f4e5d29"
git diff --cached --check
git status --short
```

The file, version, and merge-head checks are mandatory.

- [ ] **Step 10: Commit the upstream merge**

```bash
git add AGENTS.md README.md
git commit -m "chore: integrate pinned GBrain v0.54.1.0"
git merge-base --is-ancestor 6040075c6cb95be5881cc2e1b76ef7d71f4e5d29 HEAD
test "$(git rev-list --parents -n 1 HEAD | wc -w | tr -d ' ')" = "3"
```

Expected: a merge commit with two parents, one descending from the Tencent history and one equal to or descending from the pinned GBrain commit.

---

## Task 2: Replace placeholders with the complete Tencent freshness documentation set

**Files:**

- Create: `docs/tencent/UPSTREAM_BASELINE.md`
- Rewrite: `docs/tencent/PROJECT_BRIEF.md`
- Rewrite: `docs/tencent/HACKATHON_REQUIREMENTS.md`
- Rewrite: `docs/tencent/FRESHNESS_ARCHITECTURE.md`
- Rewrite: `docs/tencent/FRESHNESS_DATA_MODEL.md`
- Rewrite: `docs/tencent/FRESHNESS_API_CONTRACT.md`
- Rewrite: `docs/tencent/FRESHNESS_EVALS.md`
- Rewrite: `docs/tencent/DECISIONS.md`
- Rewrite: `docs/tencent/PROJECT_STATUS.md`
- Preserve with scope note only: `docs/tencent/SECURITY_REVIEW.md`
- Modify: `README.md`

- [ ] **Step 1: Install/check the execution prerequisites without adding project dependencies**

```bash
command -v git
command -v docker
command -v bun
bun --version
node --version || true
```

Expected: Bun `>=1.3.11`. If Bun is missing, install it using Bun's official installer outside the repository, reopen the shell, and rerun these checks. Do not add Bun itself to `package.json`.

- [ ] **Step 2: Read the integrated GBrain authority files and extension points**

```bash
sed -n '1,320p' CLAUDE.md
sed -n '1,360p' AGENTS.md
sed -n '1,260p' docs/TESTING.md
sed -n '1,280p' docs/tutorials/company-brain.md
sed -n '1,260p' src/core/operations.ts
sed -n '1,260p' evals/brainbench/README.md
sed -n '1,300p' src/eval/brainbench/fixtures.ts
```

Expected: the docs describe operation-first interfaces, PGLite/Postgres parity, source isolation, hermetic tests, and sealed gold. Do not copy the Company Brain tutorial's access-control design into freshness docs.

- [ ] **Step 3: Write `UPSTREAM_BASELINE.md`**

Include all of the following, with no unresolved placeholders:

- upstream URL, tutorial URL, MIT license, tag, exact commit, and integration date;
- inherited capabilities: pages/chunks/embeddings, sources, per-source locks, resumable sync, status, Postgres/PGLite parity, MCP, operation registry, and BrainBench;
- extension points: `src/core/operations.ts`, engine/migration surfaces, source identity, eval loader conventions, CLI/MCP generation;
- known freshness gaps: no shared provider event ledger, provider cursor contract, per-object freshness state, tombstone proof, query-time verification, or freshness receipt;
- update procedure: fetch, review changelog/diff, merge an exact commit, regenerate generated docs, and run both upstream and freshness gates;
- immutable current pin and why eval baselines cannot float with upstream;
- raw documentation regeneration base `https://raw.githubusercontent.com/pavan2184/tencent-hack/main`.

- [ ] **Step 4: Write architecture and data model docs from the approved spec**

`FRESHNESS_ARCHITECTURE.md` must define the six-layer flow:

```text
provider webhook -> durable event -> deterministic worker -> indexed/searchable state
provider delta cursor ------------------------------^
provider slim reconcile ----------------------------^
critical query -> live verify -> fresh | stale | unknown | not_required
selected evidence -> versioned freshness receipt
```

It must define the <=60s webhook, <=300s delta, and <=3600s reconciliation logical-time targets; durable parking and safe fallback; and the boundary between deterministic state ownership and Jev's semantic prioritization.

`FRESHNESS_DATA_MODEL.md` must define future tables, primary identifiers, uniqueness, and lifecycle rules for:

```text
connector_checkpoints
source_change_events
object_freshness
sync_runs
freshness_policies
freshness_receipts
```

For every table specify field names, types at the contract level, nullability, uniqueness, timestamps, state transitions, deletion/tombstone handling, retry/parking fields, and links to GBrain source/page identity. Explicitly state that these are approved future production contracts and no migration exists in this phase.

- [ ] **Step 5: Write the API and operation contract doc**

Define future operation contracts for:

```text
connector_sync
freshness_status
verify_freshness
freshness_receipt
```

For each operation document input, output, error classes, idempotency, source scoping, safe fallback, and CLI/MCP derivation from `src/core/operations.ts`. Define provider webhook routes as thin transport adapters whose successful response means durable acceptance, not completed indexing. Do not add an authorization decision or groundedness score to freshness outputs.

- [ ] **Step 6: Write the eval specification and metric formulas**

`FRESHNESS_EVALS.md` must name all seven suites and define each metric mathematically:

```text
stale_critical_exposures = count(critical selections where status != fresh and evidence was exposed)
accepted_event_loss = count(durably accepted changes absent from applied or durably parked terminal accounting)
cursor_advanced_past_unaccounted_work = count(cursor advances whose preceding page contains an unaccounted change)
duplicate_mutations = sum(max(0, applied_mutation_count_per_change - 1))
tombstone_accuracy = correct_delete_outcomes / expected_delete_outcomes
receipt_field_accuracy = matching_required_receipt_fields / required_receipt_fields
safe_fallback_rate = safe_fallbacks / stale_or_unknown_critical_verifications
eventual_convergence_rate = converged_objects / changed_objects_at_deadline
webhook_max_propagation_seconds = max(searchable_at - durable_accepted_at) for webhook-path changes
delta_max_recovery_seconds = max(searchable_at - provider_changed_at) for delta-recovered changes
reconciliation_max_convergence_seconds = max(converged_at - provider_changed_at) for reconcile-only changes
```

Document zero-denominator behavior: ratio metrics are `1.0` only when the fixture declares the denominator intentionally empty; otherwise a missing denominator is invalid gold. State the hard thresholds exactly as approved. Separate hermetic CI from manual Confluence/Slack smoke checks. State that contract validation is not behavioral scoring.

- [ ] **Step 7: Update decisions, status, project brief, requirements mapping, and security-review scope**

Record dated decisions for the pinned upstream, full derived-copy approach, webhook+delta+reconcile+verify architecture, deterministic state ownership, four-provider contract, live-vs-simulated providers, sealed-gold evals, and `contract_only` baseline.

`PROJECT_STATUS.md` must use these states:

```text
Completed: approved design; pinned upstream integrated; Tencent docs complete
In progress: freshness eval contract/corpus
Not started: production state machine; live connectors; behavioral baseline
Out of scope here: access control; groundedness
```

Add a prominent note to `SECURITY_REVIEW.md` that it is retained historical/team material and is not an access-control deliverable of the freshness workstream. Do not research or expand RBAC content.

- [ ] **Step 8: Add a documentation contract test before relying on prose**

Create `test/freshness-docs-contract.test.ts` with tests that read the Tencent docs and assert:

- every required document exists;
- pin/tag/license/provider names are present;
- each of the six future tables and four future operations is present;
- all 11 metrics/thresholds are present;
- `contract_only` and the non-claim language are present;
- access control and groundedness are named as out of scope;
- no `TODO`, `TBD`, or `<placeholder>` occurs under `docs/tencent/`.

Run first while one required marker is temporarily absent or while the test file itself imports a missing helper only if needed:

```bash
bun test test/freshness-docs-contract.test.ts
```

Expected initial result: FAIL with a message naming the deliberately absent marker. Complete the docs, restore the marker, and rerun.

- [ ] **Step 9: Regenerate the structural test inventory and run doc checks**

```bash
set -e
bun scripts/classify-tests.ts
bun test test/freshness-docs-contract.test.ts
bun run check:structural-manifest
rg -n 'TODO|TBD|<placeholder>' docs/tencent && exit 1 || true
git diff --check
```

Expected: all commands pass; the `rg` command finds nothing.

- [ ] **Step 10: Update status and commit**

Set docs complete and eval contract next in `docs/tencent/PROJECT_STATUS.md`, then:

```bash
git add README.md docs/tencent test/freshness-docs-contract.test.ts scripts/structural-suites.tsv
git commit -m "docs: define Tencent freshness contracts"
```

---

## Task 3: Add strict freshness eval types and sealed corpus loader using TDD

**Files:**

- Create: `src/eval/freshness/types.ts`
- Create: `src/eval/freshness/fixtures.ts`
- Create: `test/freshness-eval-contract.test.ts`
- Modify: `docs/tencent/PROJECT_STATUS.md`

- [ ] **Step 1: Write the failing public-contract and rejection tests**

Define tests for these exported interfaces and functions before creating their modules:

```ts
export const FRESHNESS_SCHEMA_VERSION = 1 as const;
export const FRESHNESS_PROVIDERS = ['confluence', 'slack', 'jira', 'google-drive'] as const;
export const FRESHNESS_SUITES = [
  'fast-path',
  'delta-recovery',
  'reconciliation',
  'critical-verification',
  'receipt-integrity',
  'failure-recovery',
  'cross-platform-contract',
] as const;

export function validateFreshnessFixture(file: string, raw: unknown): FreshnessFixture;
export function validateFreshnessGold(
  file: string,
  raw: unknown,
  fixture: FreshnessFixture,
): FreshnessGold;
export function toPublicFreshnessFixture(fixture: FreshnessFixture): PublicFreshnessFixture;
export async function loadFreshnessCorpus(options?: FreshnessCorpusPaths): Promise<LoadedFreshnessCorpus>;
```

Tests must initially cover:

- strict unknown-key rejection at fixture, object, step, gold, checkpoint, receipt, and metrics levels;
- kebab-case fixture and step IDs;
- supported provider/suite/step enums;
- strictly increasing non-negative `at_seconds` and unique `step_id`;
- unique initial `object_id` per fixture;
- gold fixture ID and checkpoint `after_step` references;
- no inline `gold`, `expected`, `expected_metrics`, or `expected_receipt` key anywhere in a fixture;
- one paired gold file per fixture/holdout and rejection of orphan gold;
- duplicate fixture IDs across gate/holdout rejection;
- deterministic hash changes for fixture-only, holdout-only, and gold-only edits;
- public fixture sanitization that cannot expose gold;
- the five review-focus contract tests named in the Review Focus section.

Run:

```bash
bun test test/freshness-eval-contract.test.ts
```

Expected: FAIL because `src/eval/freshness/types.ts` and `fixtures.ts` do not exist.

- [ ] **Step 2: Implement discriminated types in `types.ts`**

Use these exact core shapes:

```ts
export type FreshnessProvider = typeof FRESHNESS_PROVIDERS[number];
export type FreshnessSuite = typeof FRESHNESS_SUITES[number];
export type VerificationResult = 'fresh' | 'stale' | 'unknown' | 'not_required';
export type FreshnessStatus = 'fresh' | 'stale' | 'unknown' | 'not_searchable' | 'deleted';

export interface ProviderObjectState {
  object_id: string;
  provider_version: string;
  version_order: number | null;
  content_hash: string;
  modified_at: string;
  deleted: boolean;
  searchable: boolean;
  critical: boolean;
}

interface StepBase { step_id: string; at_seconds: number; }
export type FreshnessStep =
  | (StepBase & { kind: 'provider_mutation'; object: ProviderObjectState })
  | (StepBase & { kind: 'webhook'; event_id: string; object_id: string; provider_version: string })
  | (StepBase & { kind: 'delta_poll'; cursor_in: string | null; cursor_out: string; object_ids: string[] })
  | (StepBase & { kind: 'reconcile'; object_ids: string[] })
  | (StepBase & { kind: 'verify'; object_id: string; result: VerificationResult; provider_version: string | null })
  | (StepBase & { kind: 'interrupt'; phase: 'before_apply' | 'after_apply_before_ack'; object_id: string })
  | (StepBase & { kind: 'retry'; event_id: string; attempt: number; outcome: 'applied' | 'parked' | 'rate_limited' })
  | (StepBase & { kind: 'index_outcome'; object_id: string; content_written: boolean; searchable: boolean; embedded: boolean });

export interface FreshnessFixture {
  schema_version: 1;
  fixture_id: string;
  provider: FreshnessProvider;
  suite: FreshnessSuite;
  initial_cursor: string | null;
  initial_objects: ProviderObjectState[];
  steps: FreshnessStep[];
}

export interface ExpectedObjectState extends ProviderObjectState {
  freshness_status: FreshnessStatus;
}

export interface FreshnessCheckpoint {
  after_step: string;
  expected_cursor: string | null;
  expected_objects: ExpectedObjectState[];
  expected_accounted_event_ids: string[];
  expected_parked_event_ids: string[];
}

export interface ExpectedFreshnessReceipt {
  object_id: string;
  provider_version: string | null;
  content_hash: string | null;
  sync_path: 'webhook' | 'delta' | 'reconcile' | 'live_verify';
  verification_result: VerificationResult;
  freshness_status: FreshnessStatus;
  safe_to_use: boolean;
}

export interface FreshnessMetrics {
  stale_critical_exposures: number;
  accepted_event_loss: number;
  cursor_advanced_past_unaccounted_work: number;
  duplicate_mutations: number;
  tombstone_accuracy: number;
  receipt_field_accuracy: number;
  safe_fallback_rate: number;
  eventual_convergence_rate: number;
  webhook_max_propagation_seconds: number | null;
  delta_max_recovery_seconds: number | null;
  reconciliation_max_convergence_seconds: number | null;
}

export interface FreshnessGold {
  schema_version: 1;
  fixture_id: string;
  checkpoints: FreshnessCheckpoint[];
  expected_receipts: ExpectedFreshnessReceipt[];
  expected_metrics: FreshnessMetrics;
}
```

Add `FreshnessCorpusPaths`, `LoadedFreshnessFixture`, `LoadedFreshnessCorpus`, and `PublicFreshnessFixture`. `PublicFreshnessFixture` contains only fixture fields; it has no gold reference or field.

- [ ] **Step 3: Implement strict manual validation and complete-corpus hashing**

Mirror BrainBench's proven pattern rather than adding a schema-validation dependency:

- explicit allowed-key sets at every object level;
- `FreshnessFixtureValidationError` with file and JSON-location context;
- ISO-8601 validation for `modified_at`;
- SHA-256 lowercase 64-hex validation for non-empty content hashes;
- finite integer/non-negative validation for step times, counts, attempts, and metric counters;
- finite `[0,1]` validation for accuracy/rate metrics;
- nullable latency validation because a path can be absent from a scenario;
- gate files from `evals/freshness/fixtures/` and holdouts from `evals/freshness/holdout/`;
- sealed gold from `evals/freshness/gold/`;
- corpus hash over sorted relative path plus exact bytes for all three directories;
- exactly one gold file per gate/holdout fixture and no orphan gold.

For review focus #1, comparable versions use `version_order`; the validator must reject a checkpoint whose expected object has a lower non-null `version_order` than the maximum mutation seen before `after_step` for that object unless a later delete changes the terminal state.

For review focus #2, if a checkpoint advances `expected_cursor` beyond a delta step containing a parked event, that event must appear in `expected_parked_event_ids` and its object must have `freshness_status` `unknown`, `stale`, or `not_searchable`.

For review focus #3, a checkpoint following an `index_outcome` with `searchable: false` or `embedded: false` must not mark the object `fresh`.

For review focus #4, a deleted expected object must be `freshness_status: 'deleted'` and `searchable: false`.

- [ ] **Step 4: Run targeted tests and typecheck**

```bash
set -e
bun test test/freshness-eval-contract.test.ts
bun run typecheck
```

Expected: PASS. If typecheck exposes mismatches with GBrain's TypeScript configuration, correct the implementation rather than weakening compiler settings.

- [ ] **Step 5: Update status and commit**

```bash
git add src/eval/freshness test/freshness-eval-contract.test.ts docs/tencent/PROJECT_STATUS.md
git commit -m "test: add sealed freshness eval contracts"
```

---

## Task 4: Publish JSON Schemas and the 12-scenario gate/holdout corpus

**Files:**

- Create: `evals/freshness/README.md`
- Create: `evals/freshness/schema/fixture.schema.json`
- Create: `evals/freshness/schema/gold.schema.json`
- Create: `evals/freshness/schema/result.schema.json`
- Create: `evals/freshness/schema/baseline.schema.json`
- Create: ten `evals/freshness/fixtures/*.fixture.json` files listed below
- Create: two `evals/freshness/holdout/*.fixture.json` files listed below
- Create: twelve paired `evals/freshness/gold/*.gold.json` files
- Modify: `test/freshness-eval-contract.test.ts`
- Modify: `docs/tencent/PROJECT_STATUS.md`

- [ ] **Step 1: Add failing committed-corpus and schema tests**

Add tests that expect:

```ts
expect(corpus.fixtures).toHaveLength(12);
expect(corpus.gate).toHaveLength(10);
expect(corpus.holdout).toHaveLength(2);
expect(new Set(corpus.fixtures.map(({ fixture }) => fixture.provider))).toEqual(
  new Set(['confluence', 'slack', 'jira', 'google-drive']),
);
expect(new Set(corpus.fixtures.map(({ fixture }) => fixture.suite))).toEqual(
  new Set(FRESHNESS_SUITES),
);
```

Also parse all four JSON Schemas, assert draft 2020-12 `$schema`, `additionalProperties: false` on every public object definition, and confirm no fixture file contains any key beginning with `expected` or named `gold`.

Run:

```bash
bun test test/freshness-eval-contract.test.ts
```

Expected: FAIL because `evals/freshness/` does not exist.

- [ ] **Step 2: Create schemas that match the TypeScript contracts exactly**

Use JSON Schema draft 2020-12 with `$id` values rooted at:

```text
https://raw.githubusercontent.com/pavan2184/tencent-hack/main/evals/freshness/schema/
```

Requirements:

- fixture schema uses `oneOf` for the eight step kinds and disallows undeclared fields;
- gold schema requires all metric keys, checkpoints, and receipt expectations;
- result schema defines the future runner output without implying results currently exist: fixture ID, provider, suite, pass boolean, measured metrics, produced receipts, failure codes, and logical duration;
- baseline schema requires `status: { "const": "contract_only" }` for this phase;
- all schemas have explicit required arrays and range/pattern constraints matching manual validation.

- [ ] **Step 3: Add the ten gate fixtures and paired sealed gold**

Create these exact gate files:

| Fixture | Provider | Suite | Essential steps and sealed expectation |
|---|---|---|---|
| `confluence-critical-runbook-webhook` | Confluence | fast-path | critical runbook v1→v2; webhook accepted; indexed+embedded by logical second 45; receipt uses webhook; no stale exposure |
| `confluence-live-version-drift` | Confluence | critical-verification | indexed v7; provider changes to v8; verify detects drift; expected receipt is stale and `safe_to_use: false` |
| `slack-duplicate-reordered-events` | Slack | cross-platform-contract | event for version order 12 arrives before duplicate version 11 events; expected current object remains 12; duplicate mutations zero |
| `slack-worker-crash-replay` | Slack | failure-recovery | crash after apply before ack; replay same event; exactly one accounted mutation and eventual fresh state |
| `jira-missed-webhook-delta-recovery` | Jira | delta-recovery | no webhook; delta discovers issue version 4; searchable by logical second 240; cursor advances only after accounting |
| `google-drive-delete-reconcile` | Google Drive | reconciliation | file disappears without event; reconcile creates deleted non-searchable tombstone by logical second 3300 |
| `poison-event-durable-parking` | Slack | failure-recovery | delta page contains good and poison events; poison retries then parks; cursor can advance; affected object remains unknown/not-searchable |
| `embedding-failure-not-current` | Confluence | receipt-integrity | content write succeeds, embedding/searchability fails; receipt must be not-searchable and unsafe |
| `rate-limit-durable-retry` | Jira | failure-recovery | initial delta attempt rate-limited; cursor stays put; durable retry applies within 300 logical seconds |
| `mixed-freshness-receipts` | Google Drive | receipt-integrity | fresh, stale, unknown, and deleted objects produce four field-accurate receipts with safe-use decisions |

Every fixture starts at logical second `0`, uses ISO times under a fictional `Example Harbor Finance` organization, uses SHA-256 hex strings generated from synthetic content labels, and contains no gold fields.

Every gold file includes all 11 expected metrics. Use `null` for latency metrics whose path is not exercised, never `0` as a stand-in for missing measurement.

- [ ] **Step 4: Add the two holdout fixtures and paired sealed gold**

Create:

| Fixture | Provider | Suite | Essential steps and sealed expectation |
|---|---|---|---|
| `jira-cursor-page-failure` | Jira | delta-recovery | page 2 fails after page 1; cursor never skips page 2; retry accounts work then advances |
| `google-drive-metadata-only-change` | Google Drive | reconciliation | modified time/version changes while content hash is stable; receipt updates provider metadata without duplicate content mutation |

Holdout fixtures live only in `evals/freshness/holdout/`; their gold still lives only in `evals/freshness/gold/`. `README.md` must warn that holdout gold is committed for deterministic CI integrity but must not be passed to candidate implementations.

- [ ] **Step 5: Add corpus documentation and privacy checks**

`evals/freshness/README.md` must explain directory layout, sealed-gold discipline, logical clock, fixture authoring, hash semantics, gate versus holdout use, metric nullability, and commands.

Run GBrain's existing privacy checks against the new files:

```bash
set -e
bun test test/freshness-eval-contract.test.ts
bun run check:fixture-privacy
bun run check:synthetic-corpus-privacy
bun run typecheck
```

Expected: PASS. If existing privacy scripts do not include `evals/freshness`, add the directory to their existing scan inputs and add/extend their self-tests; do not create a second privacy scanner.

- [ ] **Step 6: Update status and commit**

```bash
git add evals/freshness test/freshness-eval-contract.test.ts docs/tencent/PROJECT_STATUS.md scripts
git commit -m "test: add deterministic freshness eval corpus"
```

---

## Task 5: Add the contract-only baseline and wire its validator into GBrain verification

**Files:**

- Create: `src/eval/freshness/baseline.ts`
- Create: `scripts/check-freshness-evals.ts`
- Create: `test/freshness-eval-baseline.test.ts`
- Create: `evals/freshness/baselines/main.json`
- Modify: `package.json`
- Modify: `scripts/run-verify-parallel.sh`
- Modify generated: `scripts/structural-suites.tsv`
- Modify: `evals/freshness/README.md`
- Modify: `docs/tencent/FRESHNESS_EVALS.md`
- Modify: `docs/tencent/PROJECT_STATUS.md`

- [ ] **Step 1: Write failing baseline tests**

Require these exports:

```ts
export interface FreshnessContractBaseline {
  schema_version: 1;
  baseline_id: 'main';
  status: 'contract_only';
  fixtures_hash: string;
  config: {
    clock: 'logical';
    network: 'disabled';
    llm: 'disabled';
    providers: FreshnessProvider[];
    suites: FreshnessSuite[];
  };
  thresholds: FreshnessMetrics;
  counts: {
    fixtures: 12;
    gate: 10;
    holdout: 2;
    providers: 4;
    suites: 7;
  };
}

export function validateFreshnessContractBaseline(
  file: string,
  raw: unknown,
  corpus: LoadedFreshnessCorpus,
): FreshnessContractBaseline;
```

Tests must reject:

- `status: "measured"`, `status: "passing"`, or any status other than `contract_only`;
- fields named `score`, `passed`, `measured_metrics`, or `results`;
- mismatched fixture hash or counts;
- missing/reordered provider or suite coverage;
- weakened thresholds;
- non-hermetic clock/network/LLM settings;
- a baseline README/doc statement that calls the contract baseline green or behaviorally passing.

Run:

```bash
bun test test/freshness-eval-baseline.test.ts
```

Expected: FAIL because the baseline module/file does not exist.

- [ ] **Step 2: Implement exact hard-threshold validation**

The baseline thresholds are:

```json
{
  "stale_critical_exposures": 0,
  "accepted_event_loss": 0,
  "cursor_advanced_past_unaccounted_work": 0,
  "duplicate_mutations": 0,
  "tombstone_accuracy": 1,
  "receipt_field_accuracy": 1,
  "safe_fallback_rate": 1,
  "eventual_convergence_rate": 1,
  "webhook_max_propagation_seconds": 60,
  "delta_max_recovery_seconds": 300,
  "reconciliation_max_convergence_seconds": 3600
}
```

Unlike gold metrics, baseline latency thresholds are never null. The validator compares exact values and exact canonical provider/suite sets. It validates the current corpus hash from `loadFreshnessCorpus()`.

- [ ] **Step 3: Create the committed baseline from the actual corpus hash**

First implement a temporary test/helper call that prints `corpus.fixtures_hash`, then insert that exact 64-hex value into `evals/freshness/baselines/main.json`. Do not use a sentinel or hand-invented hash.

The complete baseline must have only:

```text
schema_version
baseline_id
status
fixtures_hash
config
thresholds
counts
```

No result cells, scores, pass flags, or measured metrics are permitted.

- [ ] **Step 4: Add a deterministic command-line contract check**

`scripts/check-freshness-evals.ts` must:

1. load gate, holdout, and sealed gold;
2. load and validate `baselines/main.json`;
3. print one stable line containing status, fixture/gate/holdout counts, and hash;
4. exit `0` only when all contract checks pass;
5. never instantiate a GBrain engine or access environment credentials.

Add to `package.json`:

```json
"check:freshness-evals": "bun run scripts/check-freshness-evals.ts"
```

Add `"check:freshness-evals"` to the light tail of `CHECKS` in `scripts/run-verify-parallel.sh`, immediately before `check:structural-manifest`.

- [ ] **Step 5: Run the focused test/check cycle**

```bash
set -e
bun test test/freshness-eval-contract.test.ts test/freshness-eval-baseline.test.ts
bun run check:freshness-evals
bun scripts/classify-tests.ts
bun run check:structural-manifest
bun run typecheck
```

Expected command output includes:

```text
freshness-evals status=contract_only fixtures=12 gate=10 holdout=2 hash=<64 lowercase hex>
```

It must not contain `passed=true`, `green`, or a behavioral score.

- [ ] **Step 6: Document the graduation rule and update status**

Add to both eval docs: replacing `contract_only` requires a separate reviewed production-runner plan, result schema validation, full suite execution, same-hash comparison, and an explicit baseline-bless command. Do not implement that graduation in this phase.

- [ ] **Step 7: Commit**

```bash
git add src/eval/freshness scripts/check-freshness-evals.ts \
  test/freshness-eval-baseline.test.ts evals/freshness package.json \
  scripts/run-verify-parallel.sh scripts/structural-suites.tsv \
  docs/tencent/FRESHNESS_EVALS.md docs/tencent/PROJECT_STATUS.md
git commit -m "test: gate freshness evaluation contracts"
```

---

## Task 6: Add manual live-smoke runbooks without adding provider implementations

**Files:**

- Create: `docs/tencent/runbooks/CONFLUENCE_LIVE_SMOKE.md`
- Create: `docs/tencent/runbooks/SLACK_LIVE_SMOKE.md`
- Modify: `docs/tencent/FRESHNESS_EVALS.md`
- Modify: `docs/tencent/PROJECT_STATUS.md`
- Modify: `test/freshness-docs-contract.test.ts`

- [ ] **Step 1: Add failing runbook contract tests**

Require each runbook to contain:

- prerequisites and test-tenant-only warning;
- credential names referenced only as provider concepts, not invented `.env` variables;
- setup, create/update/delete scenario, expected observation, cleanup, and evidence-capture sections;
- webhook fast-path and cursor/delta recovery checks;
- logical distinction between durable acceptance and completed indexing;
- a statement that the runbook is manual/non-CI and no live result is claimed yet;
- secret redaction and prohibition on committing payloads/tokens;
- no access-control evaluation and no groundedness scoring.

Run:

```bash
bun test test/freshness-docs-contract.test.ts
```

Expected: FAIL because the two runbooks do not exist.

- [ ] **Step 2: Write the Confluence live-smoke runbook**

Use a disposable Confluence test space and synthetic runbook page. Cover page create, update, missed/delayed webhook recovery, version drift live verification, deletion/tombstone observation, receipt fields, failure evidence, and cleanup. Because no adapter exists in this phase, clearly label executable commands as unavailable and point to the future operation names rather than inventing CLI flags.

- [ ] **Step 3: Write the Slack live-smoke runbook**

Use a disposable Slack test workspace/channel and synthetic messages. Cover message create/edit/delete, duplicate/reordered delivery observation, worker replay expectation, delta/history recovery, receipt fields, failure evidence, and cleanup. Do not claim thread/reaction/file support unless the later adapter contract adds it.

- [ ] **Step 4: Run doc tests and commit**

```bash
set -e
bun test test/freshness-docs-contract.test.ts
rg -n 'TODO|TBD|<placeholder>|xox[baprs]-' docs/tencent && exit 1 || true
git diff --check
git add docs/tencent test/freshness-docs-contract.test.ts
git commit -m "docs: add freshness live-smoke runbooks"
```

---

## Task 7: Regenerate fork documentation and perform the full foundation verification

**Files:**

- Modify generated: `llms.txt`
- Modify generated: `llms-full.txt`
- Modify if needed: `scripts/llms-config.ts`
- Modify generated if needed: `scripts/structural-suites.tsv`
- Modify: `docs/tencent/PROJECT_STATUS.md`

- [ ] **Step 1: Make Tencent foundation docs discoverable in the fork documentation index**

Add a `Tencent FinTech freshness extension` section to `scripts/llms-config.ts` with the project brief, upstream baseline, freshness architecture, data model, API contract, eval spec, and runbooks. Include the core contracts in `llms-full.txt`; mark runbooks `includeInFull: false` if needed to stay within the upstream size budget.

- [ ] **Step 2: Regenerate with the fork's raw URL base**

```bash
set -e
LLMS_REPO_BASE=https://raw.githubusercontent.com/pavan2184/tencent-hack/main bun run build:llms
bun scripts/classify-tests.ts
```

Expected: generated links reference `pavan2184/tencent-hack`, not `garrytan/gbrain`, for repository-hosted docs.

- [ ] **Step 3: Run targeted foundation checks first**

```bash
set -e
bun test test/freshness-docs-contract.test.ts \
  test/freshness-eval-contract.test.ts \
  test/freshness-eval-baseline.test.ts
bun run check:freshness-evals
bun run check:fixture-privacy
bun run check:synthetic-corpus-privacy
bun run check:structural-manifest
bun run typecheck
git diff --check
```

Expected: all pass.

- [ ] **Step 4: Run the inherited GBrain verification and unit suite**

```bash
set -e
bun install --frozen-lockfile
bun run verify
bun run test
```

Expected: all inherited checks and unit tests pass. Do not run E2E without its documented database environment. Record any intentionally skipped database E2E in `PROJECT_STATUS.md`.

- [ ] **Step 5: Run a clean-room contract check**

Prove no provider or AI credentials are needed:

```bash
set -e
env -i PATH="$PATH" bun run check:freshness-evals
```

Expected: the same stable `contract_only` summary and corpus hash as the normal shell.

- [ ] **Step 6: Perform the final scope and non-claim audit**

```bash
set -e
test "$(git rev-parse 'v0.54.1.0^{commit}')" = "6040075c6cb95be5881cc2e1b76ef7d71f4e5d29"
git merge-base --is-ancestor 6040075c6cb95be5881cc2e1b76ef7d71f4e5d29 HEAD
test -z "$(git ls-files '.codex/**')"
! rg -n 'TODO|TBD|<placeholder>' docs/tencent evals/freshness src/eval/freshness test/freshness- scripts/check-freshness-evals.ts
! rg -n 'status["'"'=: ]+(measured|passing)|behaviorally green|all freshness behavior passes' evals/freshness docs/tencent
! rg -n 'rbac|permission evaluation|identity mapping implementation' src/eval/freshness evals/freshness
git status --short
```

Expected: no forbidden markers, claims, or access-control implementation; only intended generated/status edits remain.

- [ ] **Step 7: Update final foundation status**

Set:

```text
Docs/eval foundation: complete
Contract gate: passing
Behavioral runner/baseline: not implemented; no behavioral claim
Production freshness implementation: ready for a separate plan
Live smoke execution: not run until adapters and test tenants exist
```

Record exact commands run, their results, Bun version, upstream pin, corpus hash, and skipped E2E reason.

- [ ] **Step 8: Use verification-before-completion and commit generated/final files**

Read and follow `superpowers:verification-before-completion`, rerun any evidence it requires, then:

```bash
git add scripts/llms-config.ts llms.txt llms-full.txt scripts/structural-suites.tsv \
  docs/tencent/PROJECT_STATUS.md
git commit -m "chore: verify GBrain freshness foundation"
git status --short --branch
```

Expected: clean worktree.

- [ ] **Step 9: Review the branch before publishing**

Read and follow `superpowers:requesting-code-review`. Review the complete branch diff against `main`, with the five Review Focus items as explicit reviewer prompts. Resolve findings with targeted tests and separate commits.

```bash
git log --oneline --decorate --graph main..HEAD
git diff --stat main...HEAD
git diff --check main...HEAD
```

- [ ] **Step 10: Publish the branch and use the branch-finishing workflow**

```bash
git push -u origin codex/gbrain-freshness-foundation
```

Then read and follow `superpowers:finishing-a-development-branch` so Pavan can choose merge/PR/cleanup. If a pull request is created, attach it to this Codex task. Do not force-push `main`.

---

## Completion Criteria

This plan is complete only when all of the following are true:

- GBrain `v0.54.1.0` history and MIT attribution are present and the exact pin is documented.
- Upstream root docs/invariants remain authoritative and Tencent docs live under `docs/tencent/`.
- All approved freshness architecture, data, operation, metric, and failure contracts are documented.
- Four providers are represented: Confluence, Slack, Jira, and Google Drive.
- The 12-scenario corpus has 10 gate and 2 holdout fixtures with sealed gold and a deterministic complete-corpus hash.
- The five Review Focus risks have named tests.
- The contract baseline is exactly `contract_only` and cannot be mistaken for a measured passing baseline.
- `check:freshness-evals` is part of inherited `bun run verify`.
- Targeted tests, typecheck, privacy checks, `bun run verify`, and `bun run test` pass.
- No production freshness state machine, migration, adapter, access-control feature, or groundedness feature was added.
- `docs/tencent/PROJECT_STATUS.md` accurately distinguishes complete contracts from unimplemented behavior.
- The branch is pushed without touching local `.codex/` or rewriting `main` history.
