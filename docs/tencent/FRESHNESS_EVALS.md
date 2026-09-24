# Freshness Evaluation Contract

Last updated: 2026-09-24 · Evaluation contract version 1

The current baseline status is exactly `contract_only`. Contract validation proves document/schema/corpus integrity; it is not a measured behavioral baseline and does not claim measured production freshness, provider latency, or a green state machine. Behavioral scoring begins only after production adapters and the deterministic freshness state machine exist.

## Hermetic corpus and sealed gold

`evals/freshness/` contains `fixtures/`, separate sealed `gold/`, `holdout/`, JSON schemas for fixture/gold/result/baseline, and `baselines/main.json`. Fixtures expose only synthetic provider state, events, and logical time steps to a future adapter. Expected versions, hashes, cursor moves, tombstones, receipts, and verdicts live only in gold. The loader rejects expectation keys in fixtures, orphan gold, malformed schema, and incomplete runs. A corpus hash covers sorted relative paths and bytes of both fixture and gold files. Two of twelve cases are held out of ordinary CI and reserved for published/manual evaluation.

CI uses a deterministic fake provider, injected logical clock, synthetic Confluence/Slack/Jira/Google Drive content, isolated disposable storage, and no provider credentials, network calls, wall-clock sleeps, or LLM calls. GBrain's `docs/TESTING.md` remains authoritative for test isolation. The upstream BrainBench sealed-gold and protected-main baseline conventions apply. Logical-time gates prove state-machine expectations; they do not measure real provider latency.

## Seven behavioral suites

| Suite | Required cases |
| --- | --- |
| Fast path | Webhook create/update is durably accepted then searchable at the same version within 60 logical seconds. |
| Delta recovery | Missed webhook, pagination failure, duplicate/reordered change, safe cursor, and recovery within 300 logical seconds. |
| Reconciliation | Drift, missed changes, delete/tombstone, unchanged hash with changed provider metadata, convergence within 3600 logical seconds. |
| Critical verification | Matching version, drift, deletion, outage, timeout, malformed response, `fresh`/`stale`/`unknown`/`not_required`, and safe fallback. |
| Receipt integrity | All required receipt fields, source-scoped identities, policy revision, ordering, mixed statuses, and canonical receipt hash. |
| Failure recovery | Duplicate delivery, rate limiting, poison parking, partial embedding/searchability, worker crash, replay, and deterministic final state. |
| Cross-platform contract | Equivalent lifecycle invariants for Confluence, Slack, Jira, and Google Drive adapters. |

The initial synthetic matrix includes a Confluence critical runbook webhook update and verification race; Slack duplicate/reordered thread update and crash replay; Jira missed webhook delta recovery and cursor page retry; Google Drive reconciliation delete and modification-time-only update; plus poison parking, embedding failure, rate-limit retry, and a mixed-source receipt. Fixtures must not mirror a real company, person, incident, provider payload, or credential.

## Metric definitions

Counts are nonnegative integers. A critical selection is one evidence item offered to downstream use under a critical policy. `exposed` means it passed the freshness gate to the consumer. Changed-object deadlines are measured with the injected logical clock. Required receipt fields are those in [the API contract](FRESHNESS_API_CONTRACT.md), not only fields populated by a successful case.

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

`correct_delete_outcomes` requires a tombstone and no retained searchable object. `matching_required_receipt_fields` compares each field with sealed gold. `safe_fallbacks` counts stale/unknown critical verifications that omit or abstain before exposure. `converged_objects` match the gold provider version, hash, tombstone, and searchable state by the suite deadline. Max latency metrics are invalid if a required path has no cases, unless that fixture explicitly declares the path intentionally empty. Ratio metrics are `1.0` only when the fixture declares the denominator intentionally empty; otherwise a missing or zero denominator is invalid gold. An absent timestamp, thrown run, or incomplete accounting is failure, never a skipped pass.

## Hard thresholds

```text
stale_critical_exposures = 0
accepted_event_loss = 0
cursor_advanced_past_unaccounted_work = 0
duplicate_mutations = 0
tombstone_accuracy = 1.0
receipt_field_accuracy = 1.0
safe_fallback_rate = 1.0
eventual_convergence_rate = 1.0
fast_path_sla_pass_rate = 1.0 at 60 logical seconds
delta_recovery_sla_pass_rate = 1.0 at 300 logical seconds
reconciliation_sla_pass_rate = 1.0 at 3600 logical seconds
```

The three SLA pass rates divide eligible path changes meeting their respective deadlines by all eligible changes on that path. They use the same explicit-empty-denominator rule. The corresponding max latency metrics are reported alongside the rates, with expected bounds `webhook_max_propagation_seconds <= 60`, `delta_max_recovery_seconds <= 300`, and `reconciliation_max_convergence_seconds <= 3600` for a passing nonempty suite. Diagnostic reports also include events per run, retry count, logical processing latency distribution, provider calls per changed object, reconcile scan efficiency, and receipt byte size; these are not initial hard gates.

## Baseline governance and limits

The committed `contract_only` baseline binds schema version, canonical provider and suite coverage, hermetic configuration, exact hard thresholds, fixture counts, and the full corpus hash. `bun run check:freshness-evals` checks these contracts and sealed gold without running an adapter. The baseline contains no scores, pass flags, measured metrics, or results.

Replacing `contract_only` requires a separate reviewed production-runner plan, result schema validation, full suite execution, same-hash comparison against the protected main baseline, and an explicit baseline-bless command. That graduation is not implemented in this phase. A future behavioral gate must bind results to corpus hash and run configuration, require the committed baseline to match an actual run after fixture changes, and require written justification for adverse movement. A pull request cannot self-approve by replacing its comparison baseline.

Manual or scheduled Confluence and Slack smoke checks use controlled test spaces. For each mutation they record provider mutation time, webhook receipt and durable acceptance time, indexed/searchable time, provider version/hash, observed wall-clock latency, and the final freshness receipt. They are separate from hermetic CI and do not enter its baseline. Jira and Google Drive remain simulations for this MVP unless the team explicitly expands live scope. Access control and groundedness evaluation belong to separate workstreams.
