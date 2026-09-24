# Freshness evaluation corpus

This corpus exercises the approved Tencent freshness contract with a deterministic
logical clock. All objects and labels belong to the fictional Example Harbor
Finance organization. It contains no provider credentials, real contacts, or
production payloads. Contract validation does not claim a behavioral baseline:
the current status is `contract_only`.

## Layout and sealing

- `fixtures/`: ten ordinary gate cases, visible to future candidate adapters.
- `holdout/`: two cases excluded from ordinary gate runs.
- `gold/`: twelve paired sealed expectations, joined by `fixture_id`.
- `schema/`: draft 2020-12 interchange schemas for fixture, gold, future
  result, and contract-only baseline documents.

Holdout gold is committed for deterministic CI integrity and corpus hashing,
but must never be passed to candidate implementations. The loader returns each
fixture with its paired gold for evaluation; adapter calls must receive only
`toPublicFreshnessFixture(fixture)`. Fixture files contain no `gold` or
`expected*` keys. The corpus hash covers sorted fixture, holdout, and gold
paths and their exact bytes.

## Authoring and interpretation

Each scenario begins at logical second 0. Later steps use strictly increasing
integer seconds; provider `modified_at` values are synthetic ISO timestamps.
The clock measures deterministic state transitions, not real provider latency.
Every `content_hash` is lowercase SHA-256 of a synthetic
`Example Harbor Finance | <content label>` string; an empty string marks a
deleted provider object, while receipt hashes are null for deleted evidence.
Changing a label requires updating the paired gold hash.

The `delta_poll.object_ids` and `delta_poll.event_ids` arrays are positional
pairs and must have equal lengths. A retry names both its event and affected
object. Gold checkpoints declare the cursor, object states, accounted events,
and parked events after named steps. The loader enforces safe cursor advancement,
parked non-current objects, monotonic comparable versions, and deletion
tombstones. JSON Schema covers document shape and scalar constraints; these
cross-record rules are enforced by the TypeScript loader.

All eleven metrics are present in every gold file. Latency values are null
only when the corresponding webhook, delta, or reconciliation path is
unexercised. Ratio values use the explicit empty-denominator convention in
`docs/tencent/FRESHNESS_EVALS.md`. Each gold file must list exactly its empty
ratio denominators in sealed `empty_denominators`; those metric values must
be 1.0. The loader derives presence from delete mutations, receipt items,
critical stale/unknown verification, and changed provider objects. An
attempted but failed index is represented
as non-searchable evidence and an unsafe receipt, never as fresh evidence.

Run the contract and privacy checks from the repository root:

```bash
bun test test/freshness-eval-contract.test.ts
bun run check:fixture-privacy
bun run check:synthetic-corpus-privacy
NODE_OPTIONS=--max-old-space-size=6144 bun run typecheck
```

The ten gate cases span all seven suites and all four providers. The holdouts
test a Jira second-page cursor failure and a Google Drive metadata-only update.
No runner result or measured behavioral baseline is committed in this phase.
