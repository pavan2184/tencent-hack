# Tencent Freshness Decisions

Last updated: 2026-09-24. All decisions below are accepted for the freshness foundation; implementation remains future work.

## 2026-09-24 — Pin the upstream foundation

Decision: derive from GBrain `v0.54.1.0` at exact commit `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29`, retain its Git history and MIT license, and record the merge. Future upstream changes require exact-commit review and rerunning upstream plus freshness gates. Evaluation baselines cannot float with upstream.

Consequence: reproducible comparisons and inherited source/operation/engine behavior; explicit merge maintenance cost. [Baseline record](UPSTREAM_BASELINE.md).

## 2026-09-24 — Use a full derived copy

Decision: keep GBrain as the root application and Tencent contracts in `docs/tencent/`, extending its operation registry, source identity, engines, migrations, and eval conventions when production work begins. Do not create a wrapper that duplicates those seams.

Consequence: changes stay reviewable against upstream; PGLite/Postgres parity and source isolation remain binding.

## 2026-09-24 — Layer webhook, delta, reconciliation, verification, and receipt

Decision: durably accept provider webhooks, recover missed changes with safe provider cursors, run slim reconciliation for drift and deletes, live-verify critical evidence, and issue versioned freshness receipts. Targets are 60/300/3600 logical seconds for webhook/delta/reconcile paths.

Consequence: durable ledger and retry complexity, with a safe fallback when freshness cannot be established. An acknowledged webhook is not an indexing success.

## 2026-09-24 — Keep freshness state deterministic

Decision: deterministic code owns versions, hashes, clocks, cursors, tombstones, retries, policy evaluation, and safe fallback. Jev may prioritize work semantically but cannot determine provider truth or override safety decisions.

Consequence: replay and eval results can be reproduced without an LLM.

## 2026-09-24 — Normalize four providers, limit live MVP to two

Decision: Confluence, Slack, Jira, and Google Drive share one connector contract. Confluence and Slack are live MVP targets; Jira and Google Drive are deterministic simulations during this phase.

Consequence: cross-platform invariants can be tested without requiring four live integrations; simulation alone cannot establish real provider latency or API behavior.

## 2026-09-24 — Seal evaluation gold and preserve holdout

Decision: keep adapter-visible synthetic fixtures separate from sealed expected outcomes, hash the full corpus, and hold out about 15% from ordinary CI. Compare future behavioral runs with a protected-main baseline, not a branch's self-replaced file.

Consequence: contract validation can catch corpus errors, while later adapters must earn behavioral scores. All CI checks remain hermetic.

## 2026-09-24 — Label the first baseline `contract_only`

Decision: the initial baseline is exactly `contract_only`. It records contract and corpus integrity, not measured freshness behavior. No document or schema check may be reported as passing a production SLA.

Consequence: downstream demos and reports must distinguish design targets, deterministic future evals, and manual Confluence/Slack wall-clock smokes.

## Workstream boundary

Access control and groundedness are out of scope here. This workstream exports neutral source-scoped evidence identity, provider version/hash, freshness status, tombstone state, receipt, and safe-use/fallback signal. Team integrations can consume these without assigning authorization or claim entailment to freshness.
