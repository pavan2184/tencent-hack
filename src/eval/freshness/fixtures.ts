/** Strict, sealed freshness corpus validation. No provider or database access. */
import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import {
  FRESHNESS_PROVIDERS, FRESHNESS_SCHEMA_VERSION, FRESHNESS_SUITES,
  type ExpectedObjectState, type FreshnessCorpusPaths, type FreshnessFixture,
  type FreshnessGold, type FreshnessStep, type LoadedFreshnessCorpus,
  type LoadedFreshnessFixture, type ProviderObjectState, type PublicFreshnessFixture,
} from './types.ts';

export class FreshnessFixtureValidationError extends Error {
  constructor(public readonly file: string, public readonly location: string, message: string) {
    super(`${file}: ${location}: ${message}`);
    this.name = 'FreshnessFixtureValidationError';
  }
}

const objectKeys = ['object_id', 'provider_version', 'version_order', 'content_hash', 'modified_at', 'deleted', 'searchable', 'critical'];
const fixtureKeys = ['schema_version', 'fixture_id', 'provider', 'suite', 'initial_cursor', 'initial_objects', 'steps'];
const goldKeys = ['schema_version', 'fixture_id', 'checkpoints', 'expected_receipts', 'expected_metrics'];
const checkpointKeys = ['after_step', 'expected_cursor', 'expected_objects', 'expected_accounted_event_ids', 'expected_parked_event_ids'];
const receiptKeys = ['object_id', 'provider_version', 'content_hash', 'sync_path', 'verification_result', 'freshness_status', 'safe_to_use'];
const metricKeys = [
  'stale_critical_exposures', 'accepted_event_loss', 'cursor_advanced_past_unaccounted_work', 'duplicate_mutations',
  'tombstone_accuracy', 'receipt_field_accuracy', 'safe_fallback_rate', 'eventual_convergence_rate',
  'webhook_max_propagation_seconds', 'delta_max_recovery_seconds', 'reconciliation_max_convergence_seconds',
];
const stepKeys: Record<FreshnessStep['kind'], string[]> = {
  provider_mutation: ['object'], webhook: ['event_id', 'object_id', 'provider_version'],
  delta_poll: ['cursor_in', 'cursor_out', 'object_ids', 'event_ids'], reconcile: ['object_ids'],
  verify: ['object_id', 'result', 'provider_version'], interrupt: ['phase', 'object_id'],
  retry: ['event_id', 'object_id', 'attempt', 'outcome'],
  index_outcome: ['object_id', 'content_written', 'searchable', 'embedded'],
};
const forbiddenFixtureKeys = new Set(['gold', 'expected', 'expected_metrics', 'expected_receipt']);
const statuses = ['fresh', 'stale', 'unknown', 'not_searchable', 'deleted'];
const verificationResults = ['fresh', 'stale', 'unknown', 'not_required'];
const kebab = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const sha256 = /^[a-f0-9]{64}$/;
const iso8601 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function validIso8601(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  const parts = iso8601.exec(value);
  if (!parts || Number.isNaN(Date.parse(value))) return false;
  const [year, month, day, hour, minute, second] = parts.slice(1).map(Number);
  const calendar = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  return calendar.getUTCFullYear() === year && calendar.getUTCMonth() + 1 === month
    && calendar.getUTCDate() === day && calendar.getUTCHours() === hour
    && calendar.getUTCMinutes() === minute && calendar.getUTCSeconds() === second;
}

function fail(file: string, at: string, message: string): never {
  throw new FreshnessFixtureValidationError(file, at, message);
}
function record(file: string, at: string, raw: unknown, allowed: readonly string[], sealed = false): Record<string, unknown> {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) fail(file, at, 'must be an object');
  const value = raw as Record<string, unknown>;
  for (const key of Object.keys(value)) {
    if (sealed && forbiddenFixtureKeys.has(key)) fail(file, `${at}.${key}`, `${key} is SEALED and belongs in gold`);
    if (!allowed.includes(key)) fail(file, `${at}.${key}`, `unknown key "${key}"`);
  }
  return value;
}
function string(file: string, at: string, value: unknown): string {
  if (typeof value !== 'string' || value.length === 0) fail(file, at, 'must be a non-empty string');
  return value;
}
function nullableString(file: string, at: string, value: unknown): string | null {
  return value === null ? null : string(file, at, value);
}
function oneOf<T extends string>(file: string, at: string, value: unknown, values: readonly T[]): T {
  if (typeof value !== 'string' || !values.includes(value as T)) fail(file, at, `must be one of ${values.join(', ')}`);
  return value as T;
}
function boolean(file: string, at: string, value: unknown): void {
  if (typeof value !== 'boolean') fail(file, at, 'must be boolean');
}
function nonNegativeInteger(file: string, at: string, value: unknown): void {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) fail(file, at, 'must be a non-negative integer');
}
function nonNegativeNumber(file: string, at: string, value: unknown): void {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) fail(file, at, 'must be a non-negative finite number');
}
function stringArray(file: string, at: string, value: unknown, unique = false): string[] {
  if (!Array.isArray(value)) fail(file, at, 'must be an array');
  const result = value.map((item, i) => string(file, `${at}[${i}]`, item));
  if (unique && new Set(result).size !== result.length) fail(file, at, 'duplicate value');
  return result;
}
function objectState(file: string, at: string, raw: unknown, expected = false): ProviderObjectState | ExpectedObjectState {
  const obj = record(file, at, raw, expected ? [...objectKeys, 'freshness_status'] : objectKeys, !expected);
  string(file, `${at}.object_id`, obj.object_id);
  string(file, `${at}.provider_version`, obj.provider_version);
  if (obj.version_order !== null) nonNegativeInteger(file, `${at}.version_order`, obj.version_order);
  if (typeof obj.content_hash !== 'string' || (obj.content_hash !== '' && !sha256.test(obj.content_hash))) {
    fail(file, `${at}.content_hash`, 'must be empty or lowercase SHA-256 hex');
  }
  if (!validIso8601(obj.modified_at)) {
    fail(file, `${at}.modified_at`, 'must be ISO-8601');
  }
  boolean(file, `${at}.deleted`, obj.deleted);
  boolean(file, `${at}.searchable`, obj.searchable);
  boolean(file, `${at}.critical`, obj.critical);
  if (expected) {
    oneOf(file, `${at}.freshness_status`, obj.freshness_status, statuses);
    if (obj.deleted && obj.freshness_status !== 'deleted') fail(file, `${at}.freshness_status`, 'deleted object requires deleted tombstone status');
    if (obj.deleted && obj.searchable) fail(file, `${at}.searchable`, 'deleted object cannot remain searchable');
  }
  return raw as ProviderObjectState | ExpectedObjectState;
}

export function validateFreshnessFixture(file: string, raw: unknown): FreshnessFixture {
  const f = record(file, 'fixture', raw, fixtureKeys, true);
  if (f.schema_version !== FRESHNESS_SCHEMA_VERSION) fail(file, 'fixture.schema_version', 'must be 1');
  if (!kebab.test(string(file, 'fixture.fixture_id', f.fixture_id))) fail(file, 'fixture.fixture_id', 'must be kebab-case');
  oneOf(file, 'fixture.provider', f.provider, FRESHNESS_PROVIDERS);
  oneOf(file, 'fixture.suite', f.suite, FRESHNESS_SUITES);
  nullableString(file, 'fixture.initial_cursor', f.initial_cursor);
  if (!Array.isArray(f.initial_objects)) fail(file, 'fixture.initial_objects', 'must be an array');
  const objectIds = new Set<string>();
  f.initial_objects.forEach((obj, i) => {
    const at = `fixture.initial_objects[${i}]`;
    const parsed = objectState(file, at, obj);
    if (objectIds.has(parsed.object_id)) fail(file, at, `duplicate initial object_id ${parsed.object_id}`);
    objectIds.add(parsed.object_id);
  });
  if (!Array.isArray(f.steps) || f.steps.length === 0) fail(file, 'fixture.steps', 'must be a non-empty array');
  const stepIds = new Set<string>();
  let lastTime = -1;
  f.steps.forEach((rawStep, i) => {
    const at = `fixture.steps[${i}]`;
    const base = record(file, at, rawStep, Object.keys(rawStep ?? {}), true);
    const kind = oneOf(file, `${at}.kind`, base.kind, Object.keys(stepKeys) as FreshnessStep['kind'][]);
    const step = record(file, at, rawStep, ['step_id', 'at_seconds', 'kind', ...stepKeys[kind]], true);
    const id = string(file, `${at}.step_id`, step.step_id);
    if (!kebab.test(id)) fail(file, `${at}.step_id`, 'must be kebab-case');
    if (stepIds.has(id)) fail(file, `${at}.step_id`, `duplicate step_id ${id}`);
    stepIds.add(id);
    nonNegativeInteger(file, `${at}.at_seconds`, step.at_seconds);
    if ((step.at_seconds as number) <= lastTime) fail(file, `${at}.at_seconds`, 'must be strictly increasing');
    lastTime = step.at_seconds as number;
    switch (kind) {
      case 'provider_mutation': objectState(file, `${at}.object`, step.object); break;
      case 'webhook':
        string(file, `${at}.event_id`, step.event_id); string(file, `${at}.object_id`, step.object_id);
        string(file, `${at}.provider_version`, step.provider_version); break;
      case 'delta_poll':
        nullableString(file, `${at}.cursor_in`, step.cursor_in); string(file, `${at}.cursor_out`, step.cursor_out);
        const objectIds = stringArray(file, `${at}.object_ids`, step.object_ids, true);
        const eventIds = stringArray(file, `${at}.event_ids`, step.event_ids, true);
        if (eventIds.length !== objectIds.length) fail(file, `${at}.event_ids`, 'must pair one event_id with each object_id');
        break;
      case 'reconcile': stringArray(file, `${at}.object_ids`, step.object_ids, true); break;
      case 'verify':
        string(file, `${at}.object_id`, step.object_id);
        oneOf(file, `${at}.result`, step.result, verificationResults);
        nullableString(file, `${at}.provider_version`, step.provider_version); break;
      case 'interrupt':
        string(file, `${at}.object_id`, step.object_id);
        oneOf(file, `${at}.phase`, step.phase, ['before_apply', 'after_apply_before_ack']); break;
      case 'retry':
        string(file, `${at}.event_id`, step.event_id); string(file, `${at}.object_id`, step.object_id);
        nonNegativeInteger(file, `${at}.attempt`, step.attempt);
        oneOf(file, `${at}.outcome`, step.outcome, ['applied', 'parked', 'rate_limited']); break;
      case 'index_outcome':
        string(file, `${at}.object_id`, step.object_id);
        boolean(file, `${at}.content_written`, step.content_written);
        boolean(file, `${at}.searchable`, step.searchable);
        boolean(file, `${at}.embedded`, step.embedded); break;
    }
  });
  return raw as FreshnessFixture;
}

function validateCheckpointSemantics(file: string, at: string, checkpoint: Record<string, unknown>, fixture: FreshnessFixture, stepIndex: number): void {
  const objects = checkpoint.expected_objects as ExpectedObjectState[];
  const objectById = new Map(objects.map(obj => [obj.object_id, obj]));
  const newest = new Map<string, number>();
  const failedIndex = new Set<string>();
  const deletedObjects = new Set<string>();
  for (const obj of fixture.initial_objects) {
    if (obj.deleted) deletedObjects.add(obj.object_id);
    else if (obj.version_order !== null) newest.set(obj.object_id, obj.version_order);
  }
  const deltas: Array<Extract<FreshnessStep, { kind: 'delta_poll' }>> = [];
  const parked = new Map<string, string>();
  for (const step of fixture.steps.slice(0, stepIndex + 1)) {
    if (step.kind === 'provider_mutation') {
      if (step.object.deleted) {
        newest.delete(step.object.object_id);
        deletedObjects.add(step.object.object_id);
      } else {
        deletedObjects.delete(step.object.object_id);
        if (step.object.version_order !== null) newest.set(step.object.object_id, Math.max(newest.get(step.object.object_id) ?? -1, step.object.version_order));
      }
    } else if (step.kind === 'index_outcome') {
      if (!step.searchable || !step.embedded || !step.content_written) failedIndex.add(step.object_id);
      else failedIndex.delete(step.object_id);
    } else if (step.kind === 'delta_poll') deltas.push(step);
    else if (step.kind === 'retry' && step.outcome === 'parked') parked.set(step.event_id, step.object_id);
  }
  for (const [objectId, high] of newest) {
    const obj = objectById.get(objectId);
    if (obj && obj.version_order !== null && obj.version_order < high) fail(file, `${at}.expected_objects`, `${objectId} version_order is lower than accepted mutation`);
  }
  for (const objectId of deletedObjects) {
    const obj = objectById.get(objectId);
    if (!obj || !obj.deleted || obj.searchable || obj.freshness_status !== 'deleted') {
      fail(file, `${at}.expected_objects`, `${objectId} requires a deleted, non-searchable tombstone`);
    }
  }
  for (const objectId of failedIndex) {
    if (objectById.get(objectId)?.freshness_status === 'fresh') fail(file, `${at}.expected_objects`, `${objectId} cannot be fresh after failed index_outcome`);
  }
  const cursor = checkpoint.expected_cursor;
  if (cursor === fixture.initial_cursor) return;
  const reached = deltas.findIndex(step => step.cursor_out === cursor);
  if (reached < 0) fail(file, `${at}.expected_cursor`, 'must match an observed delta cursor_out');
  const accounted = new Set(checkpoint.expected_accounted_event_ids as string[]);
  const expectedParked = new Set(checkpoint.expected_parked_event_ids as string[]);
  for (const delta of deltas.slice(0, reached + 1)) {
    for (const [i, eventId] of delta.event_ids.entries()) {
      const affectedObject = delta.object_ids[i];
      if (!accounted.has(eventId) && !expectedParked.has(eventId)) fail(file, `${at}.expected_cursor`, `cannot advance past unaccounted event ${eventId}`);
      const parkedObject = parked.get(eventId);
      if (parkedObject && parkedObject !== affectedObject) {
        fail(file, `${at}.expected_cursor`, `parked retry ${eventId} names ${parkedObject}, expected affected object ${affectedObject}`);
      }
      if (expectedParked.has(eventId) && !parkedObject) {
        fail(file, `${at}.expected_parked_event_ids`, `event ${eventId} has no preceding parked retry`);
      }
      if (parkedObject) {
        if (!expectedParked.has(eventId)) fail(file, `${at}.expected_parked_event_ids`, `parked event ${eventId} must be recorded`);
        const status = objectById.get(affectedObject)?.freshness_status;
        if (status !== 'unknown' && status !== 'stale' && status !== 'not_searchable') {
          fail(file, `${at}.expected_objects`, `parked event ${eventId} requires a non-current freshness_status for ${affectedObject}`);
        }
      }
    }
  }
}

export function validateFreshnessGold(file: string, raw: unknown, fixture: FreshnessFixture): FreshnessGold {
  const g = record(file, 'gold', raw, goldKeys);
  if (g.schema_version !== FRESHNESS_SCHEMA_VERSION) fail(file, 'gold.schema_version', 'must be 1');
  if (g.fixture_id !== fixture.fixture_id) fail(file, 'gold.fixture_id', `must match fixture_id ${fixture.fixture_id}`);
  if (!Array.isArray(g.checkpoints)) fail(file, 'gold.checkpoints', 'must be an array');
  const stepIndices = new Map(fixture.steps.map((step, i) => [step.step_id, i]));
  const seenCheckpoints = new Set<string>();
  g.checkpoints.forEach((rawCheckpoint, i) => {
    const at = `gold.checkpoints[${i}]`;
    const cp = record(file, at, rawCheckpoint, checkpointKeys);
    const afterStep = string(file, `${at}.after_step`, cp.after_step);
    const index = stepIndices.get(afterStep);
    if (index === undefined) fail(file, `${at}.after_step`, `unknown step ${afterStep}`);
    if (seenCheckpoints.has(afterStep)) fail(file, `${at}.after_step`, `duplicate checkpoint ${afterStep}`);
    seenCheckpoints.add(afterStep);
    nullableString(file, `${at}.expected_cursor`, cp.expected_cursor);
    if (!Array.isArray(cp.expected_objects)) fail(file, `${at}.expected_objects`, 'must be an array');
    const seenObjects = new Set<string>();
    cp.expected_objects.forEach((obj, j) => {
      const parsed = objectState(file, `${at}.expected_objects[${j}]`, obj, true);
      if (seenObjects.has(parsed.object_id)) fail(file, `${at}.expected_objects[${j}]`, `duplicate object_id ${parsed.object_id}`);
      seenObjects.add(parsed.object_id);
    });
    stringArray(file, `${at}.expected_accounted_event_ids`, cp.expected_accounted_event_ids, true);
    stringArray(file, `${at}.expected_parked_event_ids`, cp.expected_parked_event_ids, true);
    validateCheckpointSemantics(file, at, cp, fixture, index);
  });
  if (!Array.isArray(g.expected_receipts)) fail(file, 'gold.expected_receipts', 'must be an array');
  g.expected_receipts.forEach((rawReceipt, i) => {
    const at = `gold.expected_receipts[${i}]`;
    const receipt = record(file, at, rawReceipt, receiptKeys);
    string(file, `${at}.object_id`, receipt.object_id);
    nullableString(file, `${at}.provider_version`, receipt.provider_version);
    if (receipt.content_hash !== null && (typeof receipt.content_hash !== 'string' || !sha256.test(receipt.content_hash))) {
      fail(file, `${at}.content_hash`, 'must be null or lowercase SHA-256 hex');
    }
    oneOf(file, `${at}.sync_path`, receipt.sync_path, ['webhook', 'delta', 'reconcile', 'live_verify']);
    oneOf(file, `${at}.verification_result`, receipt.verification_result, verificationResults);
    oneOf(file, `${at}.freshness_status`, receipt.freshness_status, statuses);
    boolean(file, `${at}.safe_to_use`, receipt.safe_to_use);
    if (receipt.safe_to_use && (receipt.freshness_status !== 'fresh'
      || receipt.verification_result === 'stale' || receipt.verification_result === 'unknown')) {
      fail(file, `${at}.safe_to_use`, 'non-current or unverified evidence cannot be safe to use');
    }
  });
  const metrics = record(file, 'gold.expected_metrics', g.expected_metrics, metricKeys);
  for (const key of metricKeys) {
    const value = metrics[key];
    const at = `gold.expected_metrics.${key}`;
    if (key.endsWith('_accuracy') || key.endsWith('_rate')) {
      if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) fail(file, at, 'must be finite in [0,1]');
    } else if (key.endsWith('_seconds')) {
      if (value !== null) nonNegativeNumber(file, at, value);
    } else nonNegativeInteger(file, at, value);
  }
  return raw as FreshnessGold;
}

function publicObject(obj: ProviderObjectState): ProviderObjectState {
  return {
    object_id: obj.object_id, provider_version: obj.provider_version, version_order: obj.version_order,
    content_hash: obj.content_hash, modified_at: obj.modified_at, deleted: obj.deleted,
    searchable: obj.searchable, critical: obj.critical,
  };
}
function publicStep(step: FreshnessStep): FreshnessStep {
  const base = { step_id: step.step_id, at_seconds: step.at_seconds };
  switch (step.kind) {
    case 'provider_mutation': return { ...base, kind: step.kind, object: publicObject(step.object) };
    case 'webhook': return { ...base, kind: step.kind, event_id: step.event_id, object_id: step.object_id, provider_version: step.provider_version };
    case 'delta_poll': return { ...base, kind: step.kind, cursor_in: step.cursor_in, cursor_out: step.cursor_out, object_ids: [...step.object_ids], event_ids: [...step.event_ids] };
    case 'reconcile': return { ...base, kind: step.kind, object_ids: [...step.object_ids] };
    case 'verify': return { ...base, kind: step.kind, object_id: step.object_id, result: step.result, provider_version: step.provider_version };
    case 'interrupt': return { ...base, kind: step.kind, object_id: step.object_id, phase: step.phase };
    case 'retry': return { ...base, kind: step.kind, event_id: step.event_id, object_id: step.object_id, attempt: step.attempt, outcome: step.outcome };
    case 'index_outcome': return { ...base, kind: step.kind, object_id: step.object_id, content_written: step.content_written, searchable: step.searchable, embedded: step.embedded };
  }
}

export function toPublicFreshnessFixture(fixture: FreshnessFixture): PublicFreshnessFixture {
  return {
    schema_version: fixture.schema_version, fixture_id: fixture.fixture_id, provider: fixture.provider,
    suite: fixture.suite, initial_cursor: fixture.initial_cursor,
    initial_objects: fixture.initial_objects.map(publicObject), steps: fixture.steps.map(publicStep),
  };
}

const defaultRoot = 'evals/freshness';
export async function loadFreshnessCorpus(options: FreshnessCorpusPaths = {}): Promise<LoadedFreshnessCorpus> {
  const fixtureDir = options.fixtureDir ?? join(defaultRoot, 'fixtures');
  const holdoutDir = options.holdoutDir ?? join(defaultRoot, 'holdout');
  const goldDir = options.goldDir ?? join(defaultRoot, 'gold');
  const directories = [
    { label: 'fixtures', dir: fixtureDir, suffix: '.fixture.json' },
    { label: 'holdout', dir: holdoutDir, suffix: '.fixture.json' },
    { label: 'gold', dir: goldDir, suffix: '.gold.json' },
  ];
  const entries = (await Promise.all(directories.map(async ({ label, dir, suffix }) => {
    let names: string[];
    try { names = (await readdir(dir)).filter(name => name.endsWith(suffix)); }
    catch (error) { throw new Error(`freshness: cannot read ${label} dir ${dir}: ${(error as Error).message}`); }
    return names.map(name => ({ relative: `${label}/${name}`, path: join(dir, name), label, name }));
  }))).flat().sort((a, b) => a.relative.localeCompare(b.relative));
  const contents = await Promise.all(entries.map(entry => readFile(entry.path)));
  const hash = createHash('sha256');
  const parsed = entries.map((entry, i) => {
    hash.update(`${entry.relative}\n`); hash.update(contents[i]);
    try { return { ...entry, raw: JSON.parse(contents[i].toString('utf8')) as unknown }; }
    catch (error) { throw new FreshnessFixtureValidationError(entry.path, '$', `invalid JSON: ${(error as Error).message}`); }
  });
  const goldById = new Map<string, { path: string; raw: unknown }>();
  for (const entry of parsed.filter(entry => entry.label === 'gold')) {
    const raw = record(entry.path, 'gold', entry.raw, goldKeys);
    const id = string(entry.path, 'gold.fixture_id', raw.fixture_id);
    if (goldById.has(id)) fail(entry.path, 'gold.fixture_id', `duplicate gold for fixture_id ${id}`);
    goldById.set(id, { path: entry.path, raw: entry.raw });
  }
  const fixtures: LoadedFreshnessFixture[] = [];
  const holdouts: LoadedFreshnessFixture[] = [];
  const seen = new Set<string>();
  for (const entry of parsed.filter(entry => entry.label !== 'gold')) {
    const fixture = validateFreshnessFixture(entry.path, entry.raw);
    if (seen.has(fixture.fixture_id)) fail(entry.path, 'fixture.fixture_id', `duplicate fixture_id ${fixture.fixture_id}`);
    seen.add(fixture.fixture_id);
    const paired = goldById.get(fixture.fixture_id);
    if (!paired) fail(entry.path, 'fixture.fixture_id', `no gold file for fixture_id ${fixture.fixture_id}`);
    const loaded = { fixture, gold: validateFreshnessGold(paired.path, paired.raw, fixture), path: entry.path };
    if (entry.label === 'holdout') holdouts.push(loaded); else fixtures.push(loaded);
  }
  for (const [id, paired] of goldById) if (!seen.has(id)) fail(paired.path, 'gold.fixture_id', `orphan gold file for fixture_id ${id}`);
  return { fixtures, holdouts, fixtures_hash: hash.digest('hex'), fixture_dir: fixtureDir, holdout_dir: holdoutDir, gold_dir: goldDir };
}
