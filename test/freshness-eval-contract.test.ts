import { afterEach, describe, expect, test } from 'bun:test';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  FreshnessFixtureValidationError,
  loadFreshnessCorpus,
  toPublicFreshnessFixture,
  validateFreshnessFixture,
  validateFreshnessGold,
} from '../src/eval/freshness/fixtures.ts';
import { FRESHNESS_PROVIDERS, FRESHNESS_SUITES } from '../src/eval/freshness/types.ts';

const HASH = 'a'.repeat(64);
const OBJECT = {
  object_id: 'obj-1', provider_version: 'v2', version_order: 2,
  content_hash: HASH, modified_at: '2026-09-24T00:00:00Z',
  deleted: false, searchable: true, critical: true,
};
const FIXTURE = {
  schema_version: 1, fixture_id: 'sample-fixture', provider: 'confluence', suite: 'fast-path',
  initial_cursor: null, initial_objects: [{ ...OBJECT, provider_version: 'v1', version_order: 1 }],
  steps: [
    { step_id: 'mutate-object', at_seconds: 0, kind: 'provider_mutation', object: OBJECT },
    { step_id: 'webhook-event', at_seconds: 1, kind: 'webhook', event_id: 'event-1', object_id: 'obj-1', provider_version: 'v2' },
  ],
};
const METRICS = {
  stale_critical_exposures: 0, accepted_event_loss: 0, cursor_advanced_past_unaccounted_work: 0,
  duplicate_mutations: 0, tombstone_accuracy: 1, receipt_field_accuracy: 1,
  safe_fallback_rate: 1, eventual_convergence_rate: 1,
  webhook_max_propagation_seconds: 1, delta_max_recovery_seconds: null,
  reconciliation_max_convergence_seconds: null,
};
const GOLD = {
  schema_version: 1, fixture_id: 'sample-fixture',
  checkpoints: [{ after_step: 'webhook-event', expected_cursor: null,
    expected_objects: [{ ...OBJECT, freshness_status: 'fresh' }],
    expected_accounted_event_ids: ['event-1'], expected_parked_event_ids: [] }],
  expected_receipts: [{ object_id: 'obj-1', provider_version: 'v2', content_hash: HASH,
    sync_path: 'webhook', verification_result: 'not_required', freshness_status: 'fresh', safe_to_use: true }],
  expected_metrics: METRICS,
};

const fixture = () => structuredClone(FIXTURE) as Record<string, any>;
const gold = () => structuredClone(GOLD) as Record<string, any>;
const validFixture = () => validateFreshnessFixture('sample.fixture.json', fixture());
const rejectFixture = (bad: unknown, match: RegExp) =>
  expect(() => validateFreshnessFixture('sample.fixture.json', bad)).toThrow(match);
const rejectGold = (bad: unknown, match: RegExp, f = validFixture()) =>
  expect(() => validateFreshnessGold('sample.gold.json', bad, f)).toThrow(match);

describe('freshness fixture contract', () => {
  test('accepts a literal valid fixture and gold with all supported provider and suite values', () => {
    expect(FRESHNESS_PROVIDERS).toEqual(['confluence', 'slack', 'jira', 'google-drive']);
    expect(FRESHNESS_SUITES).toHaveLength(7);
    expect(validFixture().fixture_id).toBe('sample-fixture');
    expect(validateFreshnessGold('sample.gold.json', gold(), validFixture()).expected_metrics.tombstone_accuracy).toBe(1);
    for (const provider of FRESHNESS_PROVIDERS) {
      const f = fixture(); f.provider = provider;
      expect(validateFreshnessFixture('sample.fixture.json', f).provider).toBe(provider);
    }
    for (const suite of FRESHNESS_SUITES) {
      const f = fixture(); f.suite = suite;
      expect(validateFreshnessFixture('sample.fixture.json', f).suite).toBe(suite);
    }
  });

  test('rejects unknown keys at every fixture level with file and location context', () => {
    for (const mutate of [
      (f: any) => { f.surprise = true; },
      (f: any) => { f.initial_objects[0].surprise = true; },
      (f: any) => { f.steps[0].object.surprise = true; },
      (f: any) => { f.steps[1].surprise = true; },
    ]) {
      const f = fixture(); mutate(f);
      rejectFixture(f, /sample\.fixture\.json: fixture\.(?:initial_objects|steps)?[^:]*surprise: unknown key/);
    }
  });

  test('rejects inline expectations at any fixture nesting depth', () => {
    for (const key of ['gold', 'expected', 'expected_metrics', 'expected_receipt']) {
      for (const path of ['root', 'initial', 'step', 'mutation']) {
        const f = fixture();
        const target = path === 'root' ? f : path === 'initial' ? f.initial_objects[0]
          : path === 'step' ? f.steps[0] : f.steps[0].object;
        target[key] = { hidden: true };
        rejectFixture(f, /SEALED/);
      }
    }
  });

  test('rejects invalid IDs, enums, times, duplicate steps and initial objects', () => {
    const edits: Array<(f: any) => void> = [
      f => { f.fixture_id = 'Bad_ID'; }, f => { f.steps[0].step_id = 'Bad_ID'; },
      f => { f.provider = 'unknown'; }, f => { f.suite = 'unknown'; },
      f => { f.steps[0].kind = 'unknown'; }, f => { f.steps[0].at_seconds = -1; },
      f => { f.steps[0].at_seconds = 0.5; }, f => { f.steps[1].at_seconds = 0; },
      f => { f.steps[1].step_id = f.steps[0].step_id; },
      f => { f.initial_objects.push(f.initial_objects[0]); },
    ];
    for (const edit of edits) { const f = fixture(); edit(f); rejectFixture(f, /must|duplicate|unknown/); }
  });

  test('validates each step shape including delta event_ids and retry object_id', () => {
    const steps = [
      { kind: 'delta_poll', cursor_in: null, cursor_out: 'cursor-1', object_ids: ['obj-1'], event_ids: ['event-1'] },
      { kind: 'reconcile', object_ids: ['obj-1'] },
      { kind: 'verify', object_id: 'obj-1', result: 'unknown', provider_version: null },
      { kind: 'interrupt', phase: 'before_apply', object_id: 'obj-1' },
      { kind: 'retry', event_id: 'event-1', object_id: 'obj-1', attempt: 1, outcome: 'parked' },
      { kind: 'index_outcome', object_id: 'obj-1', content_written: true, searchable: false, embedded: false },
    ];
    for (const [i, step] of steps.entries()) {
      const f = fixture(); f.steps.push({ step_id: `step-${i}`, at_seconds: i + 2, ...step });
      expect(validateFreshnessFixture('sample.fixture.json', f).steps).toHaveLength(3);
    }
    const missingEventIds = fixture(); missingEventIds.steps.push({ step_id: 'delta', at_seconds: 2, kind: 'delta_poll', cursor_in: null, cursor_out: 'c', object_ids: ['obj-1'] });
    rejectFixture(missingEventIds, /event_ids/);
    const missingObjectId = fixture(); missingObjectId.steps.push({ step_id: 'retry', at_seconds: 2, kind: 'retry', event_id: 'event-1', attempt: 1, outcome: 'parked' });
    rejectFixture(missingObjectId, /object_id/);
  });

  test('rejects malformed object timestamps, hashes and versions', () => {
    for (const [key, value] of [['modified_at', 'yesterday'], ['modified_at', '2026-02-30T00:00:00Z'], ['content_hash', 'not-sha256'], ['version_order', -1], ['version_order', 1.5]] as const) {
      const f = fixture(); f.initial_objects[0][key] = value; rejectFixture(f, /initial_objects/);
    }
  });

  test('accepts an empty content hash for a deleted provider object', () => {
    const f = fixture(); f.steps[0].object.deleted = true; f.steps[0].object.searchable = false;
    f.steps[0].object.content_hash = '';
    expect(validateFreshnessFixture('sample.fixture.json', f).steps[0].kind).toBe('provider_mutation');
  });
});

describe('sealed gold and review focus', () => {
  test('rejects unknown keys at gold, checkpoint, expected object, receipt and metrics levels', () => {
    for (const mutate of [
      (g: any) => { g.surprise = true; }, (g: any) => { g.checkpoints[0].surprise = true; },
      (g: any) => { g.checkpoints[0].expected_objects[0].surprise = true; },
      (g: any) => { g.expected_receipts[0].surprise = true; },
      (g: any) => { g.expected_metrics.surprise = true; },
    ]) { const g = gold(); mutate(g); rejectGold(g, /sample\.gold\.json: .*surprise/); }
  });

  test('rejects mismatched fixture and unknown checkpoint step', () => {
    const a = gold(); a.fixture_id = 'another'; rejectGold(a, /fixture_id/);
    const b = gold(); b.checkpoints[0].after_step = 'missing'; rejectGold(b, /after_step/);
  });

  test('rejects negative counters, out-of-range ratios and invalid nullable latencies', () => {
    for (const [key, value] of [['accepted_event_loss', -1], ['tombstone_accuracy', 1.1], ['webhook_max_propagation_seconds', -1], ['delta_max_recovery_seconds', 'fast']] as const) {
      const g = gold(); g.expected_metrics[key] = value; rejectGold(g, new RegExp(key));
    }
  });

  test('review focus 1: lower comparable version cannot be expected after higher mutation', () => {
    const g = gold(); g.checkpoints[0].expected_objects[0].version_order = 1;
    rejectGold(g, /version_order/);
  });

  test('review focus 2: parked poison event permits cursor advance only with non-current object', () => {
    const f = fixture(); f.steps.push(
      { step_id: 'delta-page', at_seconds: 2, kind: 'delta_poll', cursor_in: null, cursor_out: 'c1', object_ids: ['obj-1'], event_ids: ['poison-event'] },
      { step_id: 'park-event', at_seconds: 3, kind: 'retry', event_id: 'poison-event', object_id: 'obj-1', attempt: 1, outcome: 'parked' },
    );
    const validated = validateFreshnessFixture('sample.fixture.json', f);
    const g = gold(); g.checkpoints[0].after_step = 'park-event'; g.checkpoints[0].expected_cursor = 'c1';
    rejectGold(g, /poison-event|parked/, validated);
    g.checkpoints[0].expected_parked_event_ids = ['poison-event'];
    rejectGold(g, /non-current|freshness_status/, validated);
    g.checkpoints[0].expected_objects[0].freshness_status = 'unknown';
    expect(validateFreshnessGold('sample.gold.json', g, validated).checkpoints[0].expected_cursor).toBe('c1');
  });

  test('review focus 2: cursor cannot advance past an unaccounted delta event', () => {
    const f = fixture(); f.steps.push({ step_id: 'delta-page', at_seconds: 2, kind: 'delta_poll', cursor_in: null, cursor_out: 'c1', object_ids: ['obj-1'], event_ids: ['unhandled-event'] });
    const g = gold(); g.checkpoints[0].after_step = 'delta-page'; g.checkpoints[0].expected_cursor = 'c1';
    rejectGold(g, /unhandled-event|accounted/, validateFreshnessFixture('sample.fixture.json', f));
  });

  test('review focus 3: failed embedding or searchability cannot be expected fresh', () => {
    for (const failure of [{ searchable: false, embedded: true }, { searchable: true, embedded: false }]) {
      const f = fixture(); f.steps.push({ step_id: 'index-result', at_seconds: 2, kind: 'index_outcome', object_id: 'obj-1', content_written: true, ...failure });
      const g = gold(); g.checkpoints[0].after_step = 'index-result';
      rejectGold(g, /not.*fresh|freshness_status/, validateFreshnessFixture('sample.fixture.json', f));
    }
  });

  test('review focus 3: non-current receipt cannot mark failed indexing safe to use', () => {
    const f = fixture(); f.steps.push({ step_id: 'index-result', at_seconds: 2, kind: 'index_outcome', object_id: 'obj-1', content_written: true, searchable: false, embedded: false });
    const g = gold(); g.checkpoints[0].after_step = 'index-result';
    g.checkpoints[0].expected_objects[0].freshness_status = 'not_searchable';
    g.expected_receipts[0].freshness_status = 'not_searchable';
    rejectGold(g, /safe_to_use/, validateFreshnessFixture('sample.fixture.json', f));
  });

  test('critical stale or unknown verification cannot be safe to use', () => {
    for (const result of ['stale', 'unknown']) {
      const g = gold(); g.expected_receipts[0].verification_result = result;
      rejectGold(g, /safe_to_use/);
    }
  });

  test('review focus 4: deletion requires tombstone status and no searchable object', () => {
    const g = gold(); g.checkpoints[0].expected_objects[0].deleted = true;
    rejectGold(g, /deleted|tombstone/);
    g.checkpoints[0].expected_objects[0].freshness_status = 'deleted';
    rejectGold(g, /searchable/);
    g.checkpoints[0].expected_objects[0].searchable = false;
    expect(validateFreshnessGold('sample.gold.json', g, validFixture()).checkpoints[0].expected_objects[0].deleted).toBe(true);
  });

  test('review focus 5: fixture sanitizer exposes no sealed gold or smuggled nested fields', () => {
    const f = validFixture() as any; f.gold = gold(); f.steps[0].object.gold = gold();
    const publicFixture = toPublicFreshnessFixture(f);
    expect(publicFixture).toEqual(FIXTURE as any);
    expect(JSON.stringify(publicFixture)).not.toContain('expected_metrics');
  });
});

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function corpusFiles(files: Record<string, unknown>): { fixtureDir: string; holdoutDir: string; goldDir: string } {
  const root = mkdtempSync(join(tmpdir(), 'freshness-contract-')); roots.push(root);
  const dirs = { fixtureDir: join(root, 'fixtures'), holdoutDir: join(root, 'holdout'), goldDir: join(root, 'gold') };
  for (const dir of Object.values(dirs)) mkdirSync(dir);
  for (const [path, content] of Object.entries(files)) writeFileSync(join(root, path), JSON.stringify(content, null, 2));
  return dirs;
}

describe('complete corpus loader', () => {
  const files = () => ({ 'fixtures/sample-fixture.fixture.json': fixture(), 'gold/sample-fixture.gold.json': gold() });
  test('loads paired gate and holdout fixtures with stable hash', async () => {
    const f = files(); const holdout = fixture(); holdout.fixture_id = 'held-out';
    const heldGold = gold(); heldGold.fixture_id = 'held-out';
    const dirs = corpusFiles({ ...f, 'holdout/held-out.fixture.json': holdout, 'gold/held-out.gold.json': heldGold });
    const a = await loadFreshnessCorpus(dirs); const b = await loadFreshnessCorpus(dirs);
    expect(a.fixtures).toHaveLength(1); expect(a.holdouts).toHaveLength(1);
    expect(a.fixtures_hash).toBe(b.fixtures_hash);
    expect(a.fixtures_hash).toMatch(/^[0-9a-f]{64}$/);
  });

  test('rejects missing gold, orphan gold and duplicate IDs across gate and holdout', async () => {
    await expect(loadFreshnessCorpus(corpusFiles({ 'fixtures/sample-fixture.fixture.json': fixture() }))).rejects.toThrow(/no gold/);
    await expect(loadFreshnessCorpus(corpusFiles({ ...files(), 'gold/ghost.gold.json': { ...gold(), fixture_id: 'ghost' } }))).rejects.toThrow(/orphan gold/);
    await expect(loadFreshnessCorpus(corpusFiles({ ...files(), 'holdout/copy.fixture.json': fixture() }))).rejects.toThrow(/duplicate fixture_id/);
  });

  test('fixture-only, holdout-only and gold-only byte edits each change the corpus hash', async () => {
    const held = fixture(); held.fixture_id = 'held-out'; const hg = gold(); hg.fixture_id = 'held-out';
    const base = { ...files(), 'holdout/held-out.fixture.json': held, 'gold/held-out.gold.json': hg };
    const hash = async (input: Record<string, unknown>) => (await loadFreshnessCorpus(corpusFiles(input))).fixtures_hash;
    const original = await hash(base);
    const editedFixture = fixture(); editedFixture.initial_objects[0].modified_at = '2026-09-24T01:00:00Z';
    const editedHoldout = structuredClone(held); editedHoldout.initial_objects[0].modified_at = '2026-09-24T01:00:00Z';
    const editedGold = gold(); editedGold.expected_metrics.accepted_event_loss = 1;
    expect(await hash({ ...base, 'fixtures/sample-fixture.fixture.json': editedFixture })).not.toBe(original);
    expect(await hash({ ...base, 'holdout/held-out.fixture.json': editedHoldout })).not.toBe(original);
    expect(await hash({ ...base, 'gold/sample-fixture.gold.json': editedGold })).not.toBe(original);
  });
});
