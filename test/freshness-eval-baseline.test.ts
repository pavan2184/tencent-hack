import { beforeAll, describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import {
  validateFreshnessContractBaseline, validateFreshnessContractDocs,
  type FreshnessContractBaseline,
} from '../src/eval/freshness/baseline.ts';
import { loadFreshnessCorpus } from '../src/eval/freshness/fixtures.ts';
import { FRESHNESS_PROVIDERS, FRESHNESS_SUITES, type LoadedFreshnessCorpus } from '../src/eval/freshness/types.ts';

const FILE = 'evals/freshness/baselines/main.json';
let corpus: LoadedFreshnessCorpus;

beforeAll(async () => { corpus = await loadFreshnessCorpus(); });

function baseline(): Record<string, any> {
  return {
    schema_version: 1,
    baseline_id: 'main',
    status: 'contract_only',
    fixtures_hash: corpus.fixtures_hash,
    config: {
      clock: 'logical', network: 'disabled', llm: 'disabled',
      providers: [...FRESHNESS_PROVIDERS], suites: [...FRESHNESS_SUITES],
    },
    thresholds: {
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
    },
    counts: { fixtures: 12, gate: 10, holdout: 2, providers: 4, suites: 7 },
  };
}

const rejects = (raw: unknown, path: RegExp) =>
  expect(() => validateFreshnessContractBaseline(FILE, raw, corpus)).toThrow(path);

describe('contract-only freshness baseline', () => {
  test('committed main binds the complete corpus and exact canonical contract', () => {
    const committed = JSON.parse(readFileSync(FILE, 'utf8'));
    expect(validateFreshnessContractBaseline(FILE, committed, corpus)).toEqual(baseline() as unknown as FreshnessContractBaseline);
  });

  test.each(['measured', 'passing', 'green', null])('rejects non-contract status %p', status => {
    const raw = baseline(); raw.status = status;
    rejects(raw, /status/);
  });

  test.each(['score', 'passed', 'measured_metrics', 'results'])('rejects result field %s', key => {
    const raw = baseline(); raw[key] = key === 'passed' ? true : {};
    rejects(raw, new RegExp(key));
  });

  test('rejects a foreign fixture hash and malformed hash', () => {
    const raw = baseline(); raw.fixtures_hash = 'a'.repeat(64);
    rejects(raw, /fixtures_hash/);
    raw.fixtures_hash = 'not-a-hash';
    rejects(raw, /fixtures_hash/);
  });

  test.each(['fixtures', 'gate', 'holdout', 'providers', 'suites'])('rejects wrong %s count', key => {
    const raw = baseline(); raw.counts[key] += 1;
    rejects(raw, new RegExp(key));
  });

  test.each(['providers', 'suites'])('rejects missing and reordered %s coverage', key => {
    const raw = baseline(); raw.config[key].pop();
    rejects(raw, new RegExp(key));
    raw.config[key] = [...baseline().config[key]].reverse();
    rejects(raw, new RegExp(key));
  });

  test.each([
    ['stale_critical_exposures', 1], ['accepted_event_loss', 1],
    ['cursor_advanced_past_unaccounted_work', 1], ['duplicate_mutations', 1],
    ['tombstone_accuracy', 0.99], ['receipt_field_accuracy', 0.99],
    ['safe_fallback_rate', 0.99], ['eventual_convergence_rate', 0.99],
    ['webhook_max_propagation_seconds', 61], ['delta_max_recovery_seconds', 301],
    ['reconciliation_max_convergence_seconds', 3601],
    ['webhook_max_propagation_seconds', null],
  ] as const)('rejects weakened threshold %s', (key, value) => {
    const raw = baseline(); raw.thresholds[key] = value;
    rejects(raw, new RegExp(key));
  });

  test.each([
    ['clock', 'wall'], ['network', 'enabled'], ['llm', 'enabled'],
  ])('rejects non-hermetic %s setting', (key, value) => {
    const raw = baseline(); raw.config[key] = value;
    rejects(raw, new RegExp(key));
  });

  test('rejects documentation that describes this contract as behaviorally green', () => {
    for (const file of ['evals/freshness/README.md', 'docs/tencent/FRESHNESS_EVALS.md']) {
      const current = readFileSync(file, 'utf8');
      expect(() => validateFreshnessContractDocs(file, current)).not.toThrow();
      expect(() => validateFreshnessContractDocs(file, `${current}\nThe contract_only baseline is green and behaviorally passing.\n`)).toThrow(/green|passing/);
    }
  });

  test.each([
    'The contract_only baseline is **green**.',
    'The contract_only baseline is *passing*.',
    'The contract_only baseline is `green`.',
    'The contract_only baseline is [green](https://example.com/status).',
    'The contract_only baseline passes all behavioral tests.',
    'The contract_only baseline, while still contract-only, is green.',
    'The contract_only baseline — despite no runner evidence — is green.',
    'The contract_only baseline (still unmeasured; no runner evidence) is passing.',
    'Context (the contract_only baseline is green) remains.',
    'Context — the contract_only baseline is **passing** — remains.',
    'Context, while the contract_only baseline passes all behavioral tests, remains.',
    'Context (the contract_only baseline — despite no runner evidence — is green) remains.',
    'Context — the contract_only baseline (still unmeasured; no runner evidence) is passing — remains.',
    'Context (note (the contract_only baseline is green)) remains.',
  ])('rejects affirmative documentation claim: %s', sentence => {
    expect(() => validateFreshnessContractDocs('README.md', sentence)).toThrow(/green|passing/);
  });

  test.each([
    'The contract_only baseline is not behaviorally green.',
    'The contract_only baseline does not pass behavioral tests.',
    'The contract_only baseline cannot be promoted to behavioral green by document checks.',
    'The contract_only baseline is not behaviorally green; the measured runner is green.',
    'The contract_only baseline is not green, while the measured runner is passing.',
    'The contract_only baseline is not green — the measured runner is passing.',
    'The contract_only baseline is not green whereas the measured runner is passing.',
    'Context (the contract_only baseline is not green; the measured runner is passing) remains.',
    'Context — the contract_only baseline is not green, while the measured runner is passing — remains.',
    'Context, while the contract_only baseline is not green whereas the measured runner is passing, remains.',
    'The contract_only baseline (the measured runner is green) is not passing.',
    'The contract_only baseline — the measured runner is passing — is not green.',
    'The contract_only baseline, while the measured runner is green, is not passing.',
  ])('accepts cautionary documentation: %s', sentence => {
    expect(() => validateFreshnessContractDocs('README.md', sentence)).not.toThrow();
  });

  test('still rejects a positive contract claim in a later clause', () => {
    expect(() => validateFreshnessContractDocs('README.md',
      'The measured runner is green; the contract_only baseline is **passing**.')).toThrow(/passing/);
  });
});
