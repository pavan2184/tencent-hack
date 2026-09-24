/** Contract-only baseline validation; no behavioral runner or provider access. */
import {
  FRESHNESS_PROVIDERS, FRESHNESS_SUITES,
  type FreshnessProvider, type FreshnessSuite, type LoadedFreshnessCorpus,
} from './types.ts';

/** Approved hard limits. Unlike per-fixture gold, latency limits cannot be null. */
export interface FreshnessThresholds {
  stale_critical_exposures: number;
  accepted_event_loss: number;
  cursor_advanced_past_unaccounted_work: number;
  duplicate_mutations: number;
  tombstone_accuracy: number;
  receipt_field_accuracy: number;
  safe_fallback_rate: number;
  eventual_convergence_rate: number;
  webhook_max_propagation_seconds: number;
  delta_max_recovery_seconds: number;
  reconciliation_max_convergence_seconds: number;
}

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
  thresholds: FreshnessThresholds;
  counts: {
    fixtures: 12;
    gate: 10;
    holdout: 2;
    providers: 4;
    suites: 7;
  };
}

const LIMITS: FreshnessThresholds = {
  stale_critical_exposures: 0,
  accepted_event_loss: 0,
  cursor_advanced_past_unaccounted_work: 0,
  duplicate_mutations: 0,
  tombstone_accuracy: 1,
  receipt_field_accuracy: 1,
  safe_fallback_rate: 1,
  eventual_convergence_rate: 1,
  webhook_max_propagation_seconds: 60,
  delta_max_recovery_seconds: 300,
  reconciliation_max_convergence_seconds: 3600,
};

function fail(file: string, path: string, message: string): never {
  throw new Error(`${file}: ${path}: ${message}`);
}

function record(file: string, path: string, raw: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail(file, path, 'must be an object');
  const value = raw as Record<string, unknown>;
  for (const key of Object.keys(value)) if (!keys.includes(key)) fail(file, `${path}.${key}`, 'unknown field');
  for (const key of keys) if (!(key in value)) fail(file, `${path}.${key}`, 'missing field');
  return value;
}

function exact(file: string, path: string, actual: unknown, expected: unknown): void {
  if (actual !== expected) fail(file, path, `must equal ${JSON.stringify(expected)}`);
}

function exactSequence(file: string, path: string, actual: unknown, expected: readonly string[]): void {
  if (!Array.isArray(actual) || actual.length !== expected.length
    || actual.some((value, index) => value !== expected[index])) {
    fail(file, path, `must equal canonical order ${expected.join(', ')}`);
  }
}

export function validateFreshnessContractBaseline(
  file: string, raw: unknown, corpus: LoadedFreshnessCorpus,
): FreshnessContractBaseline {
  const b = record(file, 'baseline', raw, [
    'schema_version', 'baseline_id', 'status', 'fixtures_hash', 'config', 'thresholds', 'counts',
  ]);
  exact(file, 'baseline.schema_version', b.schema_version, 1);
  exact(file, 'baseline.baseline_id', b.baseline_id, 'main');
  exact(file, 'baseline.status', b.status, 'contract_only');
  if (typeof b.fixtures_hash !== 'string' || !/^[a-f0-9]{64}$/.test(b.fixtures_hash)) {
    fail(file, 'baseline.fixtures_hash', 'must be lowercase SHA-256 hex');
  }
  exact(file, 'baseline.fixtures_hash', b.fixtures_hash, corpus.fixtures_hash);

  const config = record(file, 'baseline.config', b.config, ['clock', 'network', 'llm', 'providers', 'suites']);
  exact(file, 'baseline.config.clock', config.clock, 'logical');
  exact(file, 'baseline.config.network', config.network, 'disabled');
  exact(file, 'baseline.config.llm', config.llm, 'disabled');
  exactSequence(file, 'baseline.config.providers', config.providers, FRESHNESS_PROVIDERS);
  exactSequence(file, 'baseline.config.suites', config.suites, FRESHNESS_SUITES);

  const thresholds = record(file, 'baseline.thresholds', b.thresholds, Object.keys(LIMITS));
  for (const [key, limit] of Object.entries(LIMITS)) exact(file, `baseline.thresholds.${key}`, thresholds[key], limit);

  const all = [...corpus.fixtures, ...corpus.holdouts];
  const expectedCounts = {
    fixtures: all.length, gate: corpus.fixtures.length, holdout: corpus.holdouts.length,
    providers: new Set(all.map(({ fixture }) => fixture.provider)).size,
    suites: new Set(all.map(({ fixture }) => fixture.suite)).size,
  };
  const approvedCounts = { fixtures: 12, gate: 10, holdout: 2, providers: 4, suites: 7 };
  const counts = record(file, 'baseline.counts', b.counts, Object.keys(approvedCounts));
  for (const [key, expected] of Object.entries(approvedCounts)) {
    exact(file, `baseline.counts.${key}`, expectedCounts[key as keyof typeof expectedCounts], expected);
    exact(file, `baseline.counts.${key}`, counts[key], expected);
  }
  return raw as FreshnessContractBaseline;
}

/** Guard the two published contract descriptions against accidental pass claims. */
export function validateFreshnessContractDocs(file: string, contents: string): void {
  const subject = /\b(?:contract_only(?:\s+baseline)?|contract[- ]only\s+baseline)\b/gi;
  const affirmative = /\b(?:is|was|counts as|proves|certifies)\s+(?:a\s+)?(?:behavioral(?:ly)?\s+)?(?:green|passing|pass)\b|\b(?:passes|has passed)\s+(?:(?:all|the)\s+)?behavioral\s+tests\b/i;
  for (const paragraph of contents.split(/\n\s*\n/)) {
    const plain = paragraph
      .replace(/\[([^\]]+)\]\([^\n)]+\)/g, '$1')
      .replace(/\*|`+/g, '')
      .replace(/(?<!\w)_{1,2}(?=\w)|(?<=\w)_{1,2}(?!\w)/g, '')
      .replace(/\s+/g, ' ');
    const pending = [plain];
    while (pending.length > 0) {
      const segment = pending.pop()!;
      const interruption = /\(([^()]*)\)|,\s*((?:while|although|though|despite|which|even though|even if)\b[^,;.!?—]*),\s*|—([^—]*)—/i.exec(segment);
      if (interruption) {
        // Inspect the contents before the rejoined surrounding clause. Each
        // split consumes a delimiter pair, so even nested prose is bounded by
        // its input length without recursive calls or discarded claim text.
        pending.push(
          segment.slice(0, interruption.index) + ' ' + segment.slice(interruption.index + interruption[0].length),
          interruption[1] ?? interruption[2] ?? interruption[3]!,
        );
        continue;
      }
      for (const clause of segment.split(/(?<=[.!?])\s+|\s*[;—]\s*|,\s*(?:but|while)\b\s*|\bwhereas\b\s*/i)) {
        subject.lastIndex = 0;
        for (const match of clause.matchAll(subject)) {
          if (affirmative.test(clause.slice(match.index + match[0].length, match.index + match[0].length + 120))) {
            fail(file, 'documentation', 'contract_only cannot claim green or behaviorally passing');
          }
        }
      }
    }
  }
}
