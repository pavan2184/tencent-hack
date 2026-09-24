import { afterEach, describe, expect, test } from 'bun:test';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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
  empty_denominators: ['tombstone_accuracy', 'safe_fallback_rate'],
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

describe('committed freshness corpus', () => {
  test('contains the exact gate and holdout matrix', async () => {
    const corpus = await loadFreshnessCorpus();
    const all = [...corpus.fixtures, ...corpus.holdouts];
    expect(all).toHaveLength(12);
    expect(corpus.fixtures).toHaveLength(10);
    expect(corpus.holdouts).toHaveLength(2);
    expect(new Set(all.map(({ fixture }) => fixture.provider))).toEqual(new Set(FRESHNESS_PROVIDERS));
    expect(new Set(all.map(({ fixture }) => fixture.suite))).toEqual(new Set(FRESHNESS_SUITES));
    for (const { fixture } of all) expect(fixture.steps[0].at_seconds).toBe(0);
    expect(new Set(corpus.fixtures.map(({ fixture }) => fixture.fixture_id))).toEqual(new Set([
      'confluence-critical-runbook-webhook', 'confluence-live-version-drift',
      'slack-duplicate-reordered-events', 'slack-worker-crash-replay',
      'jira-missed-webhook-delta-recovery', 'google-drive-delete-reconcile',
      'poison-event-durable-parking', 'embedding-failure-not-current',
      'rate-limit-durable-retry', 'mixed-freshness-receipts',
    ]));
    expect(new Set(corpus.holdouts.map(({ fixture }) => fixture.fixture_id))).toEqual(new Set([
      'jira-cursor-page-failure', 'google-drive-metadata-only-change',
    ]));
    for (const { fixture, gold } of all) {
      for (const [kind, metric] of [
        ['webhook', 'webhook_max_propagation_seconds'],
        ['delta_poll', 'delta_max_recovery_seconds'],
        ['reconcile', 'reconciliation_max_convergence_seconds'],
      ] as const) {
        expect(gold.expected_metrics[metric] === null).toBe(!fixture.steps.some(step => step.kind === kind));
      }
    }
  });

  test('keeps sealed expectations out of every fixture file', async () => {
    const corpus = await loadFreshnessCorpus();
    for (const { path } of [...corpus.fixtures, ...corpus.holdouts]) {
      const scan = (value: unknown): void => {
        if (Array.isArray(value)) { value.forEach(scan); return; }
        if (value && typeof value === 'object') {
          for (const [key, nested] of Object.entries(value)) {
            expect(key === 'gold' || key.startsWith('expected')).toBe(false);
            scan(nested);
          }
        }
      };
      scan(JSON.parse(readFileSync(path, 'utf8')));
    }
  });

  test('publishes four strict draft 2020-12 JSON Schemas', () => {
    for (const name of ['fixture', 'gold', 'result', 'baseline']) {
      const schema = JSON.parse(readFileSync(`evals/freshness/schema/${name}.schema.json`, 'utf8'));
      expect(schema.$schema).toBe('https://json-schema.org/draft/2020-12/schema');
      expect(schema.$id).toBe(`https://raw.githubusercontent.com/pavan2184/tencent-hack/main/evals/freshness/schema/${name}.schema.json`);
      const inspect = (value: unknown): void => {
        if (Array.isArray(value)) { value.forEach(inspect); return; }
        if (value && typeof value === 'object') {
          const node = value as Record<string, unknown>;
          if (node.type === 'object') expect(node.additionalProperties).toBe(false);
          Object.values(node).forEach(inspect);
        }
      };
      inspect(schema);
    }
  });

  test('existing privacy guards scan freshness gate, holdout, and gold files', () => {
    const dir = mkdtempSync(join(tmpdir(), 'freshness-privacy-'));
    try {
      for (const part of ['fixtures', 'holdout', 'gold']) mkdirSync(join(dir, part));
      writeFileSync(join(dir, 'fixtures', 'leak.fixture.json'), '{"text":"palantir"}');
      writeFileSync(join(dir, 'holdout', 'leak.fixture.json'), '{"text":"$50M"}');
      writeFileSync(join(dir, 'gold', 'leak.gold.json'), '{"text":"2018"}');
      const stringGuard = Bun.spawnSync(['bash', 'scripts/check-fixture-privacy.sh'], {
        env: { ...process.env, FRESHNESS_FIXTURE_PRIVACY_DIR: dir },
        stdout: 'pipe', stderr: 'pipe',
      });
      expect(stringGuard.exitCode).toBe(1);
      expect(stringGuard.stdout.toString()).toContain('palantir');
      const corpusGuard = Bun.spawnSync(['bash', 'scripts/check-synthetic-corpus-privacy.sh'], {
        env: { ...process.env, FRESHNESS_PRIVACY_DIR: dir },
        stdout: 'pipe', stderr: 'pipe',
      });
      expect(corpusGuard.exitCode).toBe(1);
      expect(corpusGuard.stdout.toString()).toContain('explicit dollar amount');
      expect(corpusGuard.stdout.toString()).toContain('out-of-range year');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

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
  test('requires exact fixture-specific empty-denominator declarations', () => {
    const missing = gold(); delete missing.empty_denominators;
    rejectGold(missing, /empty_denominators/);
    const omitted = gold(); omitted.empty_denominators = [];
    rejectGold(omitted, /tombstone_accuracy|safe_fallback_rate/);
    const spurious = gold(); spurious.empty_denominators.push('receipt_field_accuracy');
    rejectGold(spurious, /receipt_field_accuracy/);
    const duplicate = gold(); duplicate.empty_denominators.push('tombstone_accuracy');
    rejectGold(duplicate, /duplicate/);
    const unknown = gold(); unknown.empty_denominators.push('invented_rate');
    rejectGold(unknown, /invented_rate/);
    const wrongValue = gold(); wrongValue.expected_metrics.safe_fallback_rate = 0.5;
    rejectGold(wrongValue, /safe_fallback_rate/);
  });

  test('derives nonempty safe-fallback and empty receipt-field denominators', () => {
    const verified = fixture();
    verified.steps.push({ step_id: 'verify-stale', at_seconds: 2, kind: 'verify',
      object_id: 'obj-1', result: 'stale', provider_version: 'v3' });
    const declaredEmpty = gold();
    rejectGold(declaredEmpty, /safe_fallback_rate/, validateFreshnessFixture('sample.fixture.json', verified));
    declaredEmpty.empty_denominators = ['tombstone_accuracy'];
    expect(validateFreshnessGold('sample.gold.json', declaredEmpty, validateFreshnessFixture('sample.fixture.json', verified)).empty_denominators)
      .toEqual(['tombstone_accuracy']);
    const noReceipts = gold();
    noReceipts.expected_receipts = [];
    rejectGold(noReceipts, /receipt_field_accuracy/);
  });

  test('live-verify receipts require a matching object and verification result', () => {
    const g = gold();
    g.expected_receipts[0] = { ...g.expected_receipts[0], sync_path: 'live_verify',
      verification_result: 'unknown', freshness_status: 'not_searchable', safe_to_use: false };
    g.checkpoints[0].expected_objects[0].freshness_status = 'not_searchable';
    rejectGold(g, /verify|object_id/);
    const wrong = fixture();
    wrong.steps.push({ step_id: 'verify-other', at_seconds: 2, kind: 'verify',
      object_id: 'obj-other', result: 'unknown', provider_version: null });
    rejectGold(g, /verify|object_id/, validateFreshnessFixture('sample.fixture.json', wrong));
    const mismatch = fixture();
    mismatch.steps.push({ step_id: 'verify-stale', at_seconds: 2, kind: 'verify',
      object_id: 'obj-1', result: 'stale', provider_version: 'v3' });
    rejectGold(g, /verification_result|verify/, validateFreshnessFixture('sample.fixture.json', mismatch));
  });

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
    Object.assign(g.expected_receipts[0], { freshness_status: 'unknown', safe_to_use: false });
    expect(validateFreshnessGold('sample.gold.json', g, validated).checkpoints[0].expected_cursor).toBe('c1');
  });

  test('review focus 2: cursor cannot advance past an unaccounted delta event', () => {
    const f = fixture(); f.steps.push({ step_id: 'delta-page', at_seconds: 2, kind: 'delta_poll', cursor_in: null, cursor_out: 'c1', object_ids: ['obj-1'], event_ids: ['unhandled-event'] });
    const g = gold(); g.checkpoints[0].after_step = 'delta-page'; g.checkpoints[0].expected_cursor = 'c1';
    rejectGold(g, /unhandled-event|accounted/, validateFreshnessFixture('sample.fixture.json', f));
  });

  test('review focus 2: listed parked event without a parked retry cannot advance the cursor', () => {
    const f = fixture(); f.steps.push({ step_id: 'delta-page', at_seconds: 2, kind: 'delta_poll', cursor_in: null, cursor_out: 'c1', object_ids: ['obj-1'], event_ids: ['poison-event'] });
    const g = gold(); g.checkpoints[0].after_step = 'delta-page'; g.checkpoints[0].expected_cursor = 'c1';
    g.checkpoints[0].expected_parked_event_ids = ['poison-event'];
    rejectGold(g, /poison-event|parked retry/, validateFreshnessFixture('sample.fixture.json', f));
  });

  test('review focus 2: parked retry must name the delta event affected object', () => {
    const f = fixture(); f.initial_objects.push({ ...OBJECT, object_id: 'obj-2', provider_version: 'v1', version_order: 1 });
    f.steps.push(
      { step_id: 'delta-page', at_seconds: 2, kind: 'delta_poll', cursor_in: null, cursor_out: 'c1', object_ids: ['obj-1'], event_ids: ['poison-event'] },
      { step_id: 'park-event', at_seconds: 3, kind: 'retry', event_id: 'poison-event', object_id: 'obj-2', attempt: 1, outcome: 'parked' },
    );
    const g = gold(); g.checkpoints[0].after_step = 'park-event'; g.checkpoints[0].expected_cursor = 'c1';
    g.checkpoints[0].expected_parked_event_ids = ['poison-event'];
    g.checkpoints[0].expected_objects.push({ ...OBJECT, object_id: 'obj-2', provider_version: 'v1', version_order: 1, freshness_status: 'unknown' });
    rejectGold(g, /poison-event|obj-1|obj-2/, validateFreshnessFixture('sample.fixture.json', f));
  });

  test('delta event and affected object arrays must have equal lengths', () => {
    const f = fixture(); f.steps.push({ step_id: 'delta-page', at_seconds: 2, kind: 'delta_poll', cursor_in: null, cursor_out: 'c1', object_ids: ['obj-1'], event_ids: ['event-a', 'event-b'] });
    rejectFixture(f, /event_ids|object_ids/);
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
    Object.assign(g.expected_receipts[0], { freshness_status: 'deleted', safe_to_use: false });
    expect(validateFreshnessGold('sample.gold.json', g, validFixture()).checkpoints[0].expected_objects[0].deleted).toBe(true);
  });

  test('review focus 4: provider deletion must remain a tombstone in every later checkpoint until superseded', () => {
    const f = fixture(); f.steps.push({ step_id: 'delete-object', at_seconds: 2, kind: 'provider_mutation', object: { ...OBJECT, provider_version: 'v3', version_order: 3, deleted: true, searchable: false, content_hash: '' } });
    const g = gold(); g.checkpoints[0].after_step = 'delete-object';
    g.checkpoints[0].expected_objects[0].version_order = 3;
    rejectGold(g, /tombstone|deleted|searchable/, validateFreshnessFixture('sample.fixture.json', f));
  });

  test('a later live provider mutation supersedes the tombstone requirement', () => {
    const f = fixture(); f.steps.push(
      { step_id: 'delete-object', at_seconds: 2, kind: 'provider_mutation', object: { ...OBJECT, provider_version: 'v3', version_order: 3, deleted: true, searchable: false, content_hash: '' } },
      { step_id: 'restore-object', at_seconds: 3, kind: 'provider_mutation', object: { ...OBJECT, provider_version: 'v4', version_order: 4 } },
    );
    const g = gold(); g.checkpoints[0].after_step = 'restore-object';
    g.empty_denominators = ['safe_fallback_rate'];
    g.checkpoints[0].expected_objects[0].provider_version = 'v4'; g.checkpoints[0].expected_objects[0].version_order = 4;
    g.expected_receipts[0].provider_version = 'v4';
    f.steps.push({ step_id: 'restore-webhook', at_seconds: 4, kind: 'webhook', event_id: 'event-restore', object_id: 'obj-1', provider_version: 'v4' });
    expect(validateFreshnessGold('sample.gold.json', g, validateFreshnessFixture('sample.fixture.json', f)).checkpoints[0].expected_objects[0].freshness_status).toBe('fresh');
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
