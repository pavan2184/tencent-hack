import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { validateFreshnessFixture, validateFreshnessGold } from '../src/eval/freshness/fixtures.ts';
import type { FreshnessFixture, FreshnessGold, ProviderObjectState } from '../src/eval/freshness/types.ts';

function pair(id: string): { fixture: FreshnessFixture; gold: FreshnessGold } {
  const root = join(import.meta.dir, '../evals/freshness');
  return {
    fixture: validateFreshnessFixture(id, JSON.parse(readFileSync(join(root, 'fixtures', `${id}.fixture.json`), 'utf8'))),
    gold: JSON.parse(readFileSync(join(root, 'gold', `${id}.gold.json`), 'utf8')),
  };
}
function validate(p: ReturnType<typeof pair>): FreshnessGold {
  return validateFreshnessGold('safety.gold.json', p.gold, validateFreshnessFixture('safety.fixture.json', p.fixture));
}

describe('terminal freshness receipt safety', () => {
  test.each(['embedding-failure-not-current', 'google-drive-delete-reconcile', 'poison-event-durable-parking'])
  ('rejects a fresh/safe rewrite of the committed %s receipt', id => {
    const p = pair(id);
    expect(() => validate(p)).not.toThrow();
    const receipt = p.gold.expected_receipts.at(-1)!;
    Object.assign(receipt, { freshness_status: 'fresh', safe_to_use: true,
      verification_result: 'not_required', sync_path: 'reconcile' });
    expect(() => validate(p)).toThrow(/terminal|freshness_status|safe_to_use/);
  });

  test.each(['provider_version', 'content_hash'] as const)('rejects a receipt with mismatched terminal %s', field => {
    const p = pair('confluence-critical-runbook-webhook');
    p.gold.expected_receipts[0][field] = field === 'provider_version' ? 'v1' : 'a'.repeat(64);
    expect(() => validate(p)).toThrow(new RegExp(field));
  });

  test('requires a terminal expected object for each selected receipt', () => {
    const p = pair('confluence-critical-runbook-webhook');
    for (const cp of p.gold.checkpoints) cp.expected_objects = [];
    expect(() => validate(p)).toThrow(/terminal.*object/);
  });

  test('uses the last applicable checkpoint by step order, not gold array order', () => {
    const p = pair('poison-event-durable-parking');
    p.gold.checkpoints.reverse();
    expect(() => validate(p)).not.toThrow();
    p.gold.expected_receipts[0].freshness_status = 'stale';
    p.gold.expected_receipts[0].safe_to_use = false;
    expect(() => validate(p)).toThrow(/terminal|freshness_status/);
  });

  test.each(['delete', 'failed-index', 'parked'] as const)('rejects fresh receipts when %s remains after the last checkpoint', kind => {
    const p = pair('confluence-critical-runbook-webhook');
    const obj = p.gold.checkpoints.at(-1)!.expected_objects[0];
    const at_seconds = p.fixture.steps.at(-1)!.at_seconds + 1;
    if (kind === 'delete') {
      const { freshness_status, ...state } = obj;
      p.fixture.steps.push({ step_id: 'later-delete', at_seconds, kind: 'provider_mutation',
        object: { ...state, deleted: true, searchable: false, version_order: 3, provider_version: 'v3', content_hash: '' } });
      p.gold.empty_denominators = ['safe_fallback_rate'];
    } else if (kind === 'failed-index') {
      p.fixture.steps.push({ step_id: 'later-failure', at_seconds, kind: 'index_outcome',
        object_id: obj.object_id, content_written: true, searchable: false, embedded: false });
    } else {
      p.fixture.steps.push({ step_id: 'later-parking', at_seconds, kind: 'retry',
        event_id: 'ehf-runbook-v2', object_id: obj.object_id, attempt: 1, outcome: 'parked' });
    }
    expect(() => validate(p)).toThrow(/receipt|terminal|fresh|tombstone|parked/);
  });

  test.each(['webhook', 'delta', 'reconcile'] as const)('requires same-object public provenance for %s receipts', path => {
    const p = pair(path === 'webhook' ? 'confluence-critical-runbook-webhook'
      : path === 'delta' ? 'jira-missed-webhook-delta-recovery' : 'google-drive-delete-reconcile');
    const step = p.fixture.steps.find(step => step.kind === (path === 'delta' ? 'delta_poll' : path))!;
    if (step.kind === 'webhook') step.object_id = 'another-object';
    else if (step.kind === 'delta_poll' || step.kind === 'reconcile') step.object_ids = ['another-object'];
    expect(() => validate(p)).toThrow(/sync_path|provenance/);
  });

  test('requires the webhook event version to match the receipt', () => {
    const p = pair('confluence-critical-runbook-webhook');
    const event = p.fixture.steps.find(step => step.kind === 'webhook')!;
    if (event.kind === 'webhook') event.provider_version = 'v1';
    expect(() => validate(p)).toThrow(/sync_path|provenance|provider_version/);
  });

  test('does not infer reconcile provenance from an initial tombstone', () => {
    const p = pair('mixed-freshness-receipts');
    p.fixture.steps = p.fixture.steps.filter(step => step.kind !== 'reconcile');
    p.gold.checkpoints[0].after_step = 'verify-fresh';
    expect(() => validate(p)).toThrow(/sync_path|provenance/);
  });

  test('fresh live-verification receipts require the verified provider version', () => {
    const p = pair('mixed-freshness-receipts');
    const verification = p.fixture.steps.find(step => step.kind === 'verify' && step.result === 'fresh')!;
    if (verification.kind === 'verify') verification.provider_version = 'unmatched-version';
    expect(() => validate(p)).toThrow(/provider_version/);
  });

  test('accepts committed fresh, unsafe, and tombstone receipts with public provenance', () => {
    for (const id of ['confluence-critical-runbook-webhook', 'jira-missed-webhook-delta-recovery',
      'google-drive-delete-reconcile', 'poison-event-durable-parking', 'embedding-failure-not-current',
      'mixed-freshness-receipts']) expect(() => validate(pair(id))).not.toThrow();
  });
});

function restoration(version_order: number | null, provider_version = 'restored'): ReturnType<typeof pair> {
  const p = pair('google-drive-delete-reconcile');
  const obj: ProviderObjectState = { ...p.fixture.initial_objects[0], provider_version, version_order };
  p.fixture.steps.push({ step_id: 'restore-object', at_seconds: 3301, kind: 'provider_mutation', object: obj });
  p.gold.checkpoints.push({ ...structuredClone(p.gold.checkpoints[0]), after_step: 'restore-object',
    expected_objects: [{ ...obj, freshness_status: 'fresh' }] });
  Object.assign(p.gold.expected_receipts[0], { provider_version, content_hash: obj.content_hash,
    freshness_status: 'fresh', safe_to_use: true });
  return p;
}

describe('deletion preserves provider version high-water', () => {
  test.each([2, 3, 4])('rejects comparable resurrection at version order %s after deletion at 4', order => {
    expect(() => validate(restoration(order))).toThrow(/tombstone|version_order/);
  });

  test('retains the pre-deletion high-water when the deletion itself is incomparable', () => {
    const p = restoration(2);
    const deletion = p.fixture.steps[0];
    if (deletion.kind === 'provider_mutation') deletion.object.version_order = null;
    p.gold.checkpoints[0].expected_objects[0].version_order = null;
    expect(() => validate(p)).toThrow(/tombstone|version_order/);
  });

  test('accepts a strictly higher comparable live revision', () => {
    expect(() => validate(restoration(5))).not.toThrow();
  });

  test('rejects incomparable resurrection on arrival alone', () => {
    expect(() => validate(restoration(null))).toThrow(/tombstone|verify/);
  });

  test.each(['wrong-object', 'wrong-version', 'stale', 'before-mutation'] as const)
  ('rejects incomparable resurrection with %s verification', fault => {
    const p = restoration(null, 'opaque-restored');
    const verification = { step_id: 'verify-restoration', at_seconds: 3302, kind: 'verify' as const,
      object_id: fault === 'wrong-object' ? 'another-object' : p.fixture.initial_objects[0].object_id,
      result: fault === 'stale' ? 'stale' as const : 'fresh' as const,
      provider_version: fault === 'wrong-version' ? 'opaque-other' : 'opaque-restored' };
    if (fault === 'before-mutation') {
      verification.at_seconds = 3301;
      p.fixture.steps.at(-1)!.at_seconds = 3302;
      p.fixture.steps.splice(-1, 0, verification);
    } else {
      p.fixture.steps.push(verification);
      p.gold.checkpoints.at(-1)!.after_step = verification.step_id;
    }
    if (fault === 'stale') p.gold.empty_denominators = [];
    expect(() => validate(p)).toThrow(/tombstone|verify/);
  });

  test('accepts incomparable resurrection after a later matching fresh verification', () => {
    const p = restoration(null, 'opaque-restored');
    p.fixture.steps.push({ step_id: 'verify-restoration', at_seconds: 3302, kind: 'verify',
      object_id: p.fixture.initial_objects[0].object_id, result: 'fresh', provider_version: 'opaque-restored' });
    p.gold.checkpoints.at(-1)!.after_step = 'verify-restoration';
    expect(() => validate(p)).not.toThrow();
  });

  test('incomparable restoration cannot claim a different version than the one verified', () => {
    const p = restoration(null, 'opaque-restored');
    p.fixture.steps.push({ step_id: 'verify-restoration', at_seconds: 3302, kind: 'verify',
      object_id: p.fixture.initial_objects[0].object_id, result: 'fresh', provider_version: 'opaque-restored' });
    p.gold.checkpoints.at(-1)!.after_step = 'verify-restoration';
    p.gold.checkpoints.at(-1)!.expected_objects[0].provider_version = 'opaque-unverified';
    p.gold.expected_receipts[0].provider_version = 'opaque-unverified';
    expect(() => validate(p)).toThrow(/verified|provider_version/);
  });

  test('ordinary non-deletion version regression is still rejected', () => {
    const p = pair('confluence-critical-runbook-webhook');
    p.gold.checkpoints.at(-1)!.expected_objects[0].version_order = 1;
    expect(() => validate(p)).toThrow(/version_order/);
  });
});

function recoveredParking(indexed = true): ReturnType<typeof pair> {
  const p = pair('poison-event-durable-parking');
  const obj = p.gold.checkpoints.at(-1)!.expected_objects[1];
  p.fixture.steps.push({ step_id: 'poison-applied', at_seconds: 40, kind: 'retry',
    event_id: 'ehf-poison-v2', object_id: obj.object_id, attempt: 3, outcome: 'applied' });
  if (indexed) p.fixture.steps.push({ step_id: 'poison-searchable', at_seconds: 41, kind: 'index_outcome',
    object_id: obj.object_id, content_written: true, searchable: true, embedded: true });
  const recovered = structuredClone(p.gold.checkpoints.at(-1)!);
  recovered.after_step = indexed ? 'poison-searchable' : 'poison-applied';
  recovered.expected_parked_event_ids = [];
  recovered.expected_accounted_event_ids.push('ehf-poison-v2');
  Object.assign(recovered.expected_objects[1], { searchable: true, freshness_status: 'fresh' });
  p.gold.checkpoints.push(recovered);
  Object.assign(p.gold.expected_receipts[1], { freshness_status: 'fresh', safe_to_use: true, verification_result: 'not_required' });
  return p;
}

describe('parked retry recovery', () => {
  test('accepts applied retry plus successful indexing while preserving the earlier parked checkpoint', () => {
    const p = recoveredParking();
    expect(validate(p).checkpoints.map(cp => cp.expected_parked_event_ids)).toEqual([[], ['ehf-poison-v2'], []]);
  });

  test('rejects recovery without a later successful index_outcome', () => {
    expect(() => validate(recoveredParking(false))).toThrow(/successful index_outcome/);
  });

  test('rejects recovery indexed for another object', () => {
    const p = recoveredParking();
    const index = p.fixture.steps.at(-1)!;
    if (index.kind === 'index_outcome') index.object_id = p.fixture.initial_objects[0].object_id;
    expect(() => validate(p)).toThrow(/successful index_outcome/);
  });

  test('rejects successful indexing for a superseded version', () => {
    const p = recoveredParking();
    const { freshness_status, ...obj } = p.gold.checkpoints.at(-1)!.expected_objects[1];
    p.fixture.steps.push({ step_id: 'later-version', at_seconds: 42, kind: 'provider_mutation',
      object: { ...obj, provider_version: 'v3', version_order: 3 } });
    p.gold.checkpoints.at(-1)!.after_step = 'later-version';
    Object.assign(p.gold.checkpoints.at(-1)!.expected_objects[1], { provider_version: 'v3', version_order: 3 });
    p.gold.expected_receipts[1].provider_version = 'v3';
    expect(() => validate(p)).toThrow(/successful index_outcome/);
  });
});
