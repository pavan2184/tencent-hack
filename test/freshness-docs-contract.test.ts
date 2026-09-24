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

  test('publishes bounded manual live-smoke runbooks for Confluence and Slack', () => {
    for (const provider of ['CONFLUENCE', 'SLACK']) {
      const name = `runbooks/${provider}_LIVE_SMOKE.md`;
      expect(existsSync(join(docsDir, name)), name).toBe(true);
      const text = doc(name);
      for (const section of [
        'Prerequisites', 'Setup', 'Scenario', 'Expected observation',
        'Evidence capture', 'Cleanup',
      ]) {
        expect(text, `${name}: ${section}`).toMatch(new RegExp(`^## ${section}`, 'im'));
      }
      expect(text, name).toMatch(/test[- ]tenant[- ]only/i);
      expect(text, name).toMatch(/manual.{0,30}non-CI|non-CI.{0,30}manual/i);
      expect(text, name).toMatch(/no live result.{0,20}claim|no live result has been claimed/i);
      expect(text, name).toMatch(/webhook.{0,80}(fast.path|durable acceptance)/i);
      expect(text, name).toMatch(/cursor.{0,80}delta|delta.{0,80}cursor/i);
      expect(text, name).toMatch(/durable acceptance[\s\S]{0,300}(?:not|distinct|separate|before) [\s\S]{0,100}(?:completed indexing|searchab)/i);
      expect(text, name).toMatch(/redact.{0,100}secret|secret.{0,100}redact/i);
      expect(text, name).toMatch(/(?:do not|never) commit.{0,80}(?:payload|token)/i);
      expect(text, name).toMatch(/access.control.{0,60}out of scope/i);
      expect(text, name).toMatch(/groundedness.{0,60}out of scope/i);
      expect(text, name).toMatch(/commands? (?:are|is) unavailable|no executable commands?/i);
      expect(text, name).not.toMatch(/\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|KEY|CLIENT_ID)\b/);
    }
  });

  test('requires provider-specific mutation and recovery observations', () => {
    const confluence = doc('runbooks/CONFLUENCE_LIVE_SMOKE.md');
    for (const marker of ['create', 'update', 'delete', 'tombstone', 'version drift', 'live verification']) {
      expect(confluence.toLowerCase(), marker).toContain(marker);
    }
    expect(confluence).toMatch(/missed.{0,30}webhook/i);
    const slack = doc('runbooks/SLACK_LIVE_SMOKE.md');
    for (const marker of ['create', 'edit', 'delete', 'duplicate', 'reordered', 'worker replay']) {
      expect(slack.toLowerCase(), marker).toContain(marker);
    }
    expect(slack).toMatch(/history.{0,30}recovery|recovery.{0,30}history/i);
  });

  test('prepares Confluence webhook and cursor before creating the measured page', () => {
    const confluence = doc('runbooks/CONFLUENCE_LIVE_SMOKE.md');
    const setup = confluence.split('## Setup\n')[1]?.split('\n## Scenario')[0] ?? '';
    const scenario = confluence.split('## Scenario\n')[1]?.split('\n## Expected observation')[0] ?? '';
    expect(setup).toMatch(/(?:configure|ready).{0,100}connector/i);
    expect(setup).toMatch(/webhook/i);
    expect(setup).toMatch(/initial.{0,30}cursor/i);
    expect(setup).not.toMatch(/(?:create|publish|post).{0,100}(?:synthetic|runbook|test) page/i);
    expect(scenario).toMatch(/^1\.\s+\*\*Create[^\n]*\*\*[^\n]*Create the (?:single )?synthetic page/im);
  });

  test('contains no unfinished authoring markers', () => {
    for (const name of readdirSync(docsDir).filter((file) => file.endsWith('.md'))) {
      expect(doc(name), name).not.toMatch(/\bTODO\b|\bTBD\b|<placeholder>/);
    }
  });
});
