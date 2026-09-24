import { describe, expect, test } from 'bun:test';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const docsDir = join(import.meta.dir, '..', 'docs', 'tencent');
const requiredDocs = [
  'PROJECT_BRIEF.md',
  'HACKATHON_REQUIREMENTS.md',
  'UPSTREAM_BASELINE.md',
  'FRESHNESS_ARCHITECTURE.md',
  'FRESHNESS_DATA_MODEL.md',
  'FRESHNESS_API_CONTRACT.md',
  'FRESHNESS_EVALS.md',
  'DECISIONS.md',
  'PROJECT_STATUS.md',
  'SECURITY_REVIEW.md',
];

function doc(name: string): string {
  return readFileSync(join(import.meta.dir, '../docs/tencent/', name), 'utf8');
}

describe('Tencent freshness documentation contract', () => {
  test('publishes every required document', () => {
    for (const name of requiredDocs) {
      expect(existsSync(join(docsDir, name)), name).toBe(true);
    }
  });

  test('identifies the pinned upstream and four provider roles', () => {
    const baseline = doc('UPSTREAM_BASELINE.md');
    for (const marker of ['v0.54.1.0', '6040075c6cb95be5881cc2e1b76ef7d71f4e5d29', 'MIT']) {
      expect(baseline, marker).toContain(marker);
    }
    const architecture = doc('FRESHNESS_ARCHITECTURE.md');
    for (const provider of ['Confluence', 'Slack', 'Jira', 'Google Drive']) {
      expect(architecture, provider).toContain(provider);
    }
  });

  test('defines all future entities and operations', () => {
    const model = doc('FRESHNESS_DATA_MODEL.md');
    for (const table of [
      'connector_checkpoints', 'source_change_events', 'object_freshness',
      'sync_runs', 'freshness_policies', 'freshness_receipts',
    ]) {
      expect(model, table).toContain(table);
    }
    const api = doc('FRESHNESS_API_CONTRACT.md');
    for (const operation of ['connector_sync', 'freshness_status', 'verify_freshness', 'freshness_receipt']) {
      expect(api, operation).toContain(operation);
    }
  });

  test('scopes receipt replay to persisted requests', () => {
    const model = doc('FRESHNESS_DATA_MODEL.md');
    const receipts = model.split('## `freshness_receipts`')[1]?.split('\n## ')[0] ?? '';
    expect(receipts).toMatch(/request_key[^\n]*globally unique/i);
    expect(receipts).toMatch(/request_payload_hash[^\n]*SHA-256[^\n]*required/i);
    expect(receipts).toMatch(/atomic[^\n]*(?:reserv|insert)/i);

    const api = doc('FRESHNESS_API_CONTRACT.md');
    const receiptOperation = api.split('## `freshness_receipt`')[1]?.split('\n## ')[0] ?? '';
    expect(receiptOperation).toMatch(/persist:\s*true[^\n]*request_payload_hash/i);
    const ephemeral = receiptOperation.split('\n').find((line) => line.includes('persist: false')) ?? '';
    expect(ephemeral).toMatch(/ephemeral/i);
    expect(ephemeral).toMatch(/no cross-call[^\n]*restart[^\n]*(?:replay|conflict)/i);
    expect(ephemeral).not.toMatch(/(?:guaranteed|guarantees) (?:cross-call|replay|conflict)/i);
  });

  test('publishes the required metrics and hard thresholds', () => {
    const evals = doc('FRESHNESS_EVALS.md');
    for (const metric of [
      'stale_critical_exposures', 'accepted_event_loss', 'cursor_advanced_past_unaccounted_work',
      'duplicate_mutations', 'tombstone_accuracy', 'receipt_field_accuracy',
      'safe_fallback_rate', 'eventual_convergence_rate',
      'webhook_max_propagation_seconds', 'delta_max_recovery_seconds',
      'reconciliation_max_convergence_seconds',
    ]) {
      expect(evals, metric).toContain(metric);
    }
    for (const threshold of [
      'stale_critical_exposures = 0', 'accepted_event_loss = 0',
      'cursor_advanced_past_unaccounted_work = 0', 'duplicate_mutations = 0',
      'tombstone_accuracy = 1.0', 'receipt_field_accuracy = 1.0',
      'safe_fallback_rate = 1.0', 'eventual_convergence_rate = 1.0',
      'fast_path_sla_pass_rate = 1.0', 'delta_recovery_sla_pass_rate = 1.0',
      'reconciliation_sla_pass_rate = 1.0',
    ]) {
      expect(evals, threshold).toContain(threshold);
    }
  });

  test('limits baseline claims and separates team scope', () => {
    const evals = doc('FRESHNESS_EVALS.md');
    expect(evals).toContain('contract_only');
    expect(evals).toMatch(/not (a |yet )?measured|does not (prove|claim) measured/i);
    const brief = doc('PROJECT_BRIEF.md');
    expect(brief).toMatch(/access control.{0,80}out of scope|out of scope.{0,80}access control/i);
    expect(brief).toMatch(/groundedness.{0,80}out of scope|out of scope.{0,80}groundedness/i);
  });

  test('contains no unfinished authoring markers', () => {
    for (const name of readdirSync(docsDir).filter((file) => file.endsWith('.md'))) {
      expect(doc(name), name).not.toMatch(/\bTODO\b|\bTBD\b|<placeholder>/);
    }
  });
});
