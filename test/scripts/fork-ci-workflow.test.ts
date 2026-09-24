import { describe, expect, test } from 'bun:test';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { safeLoad } from 'js-yaml';

const root = join(import.meta.dir, '../..');
const read = (path: string) => readFileSync(join(root, path), 'utf8');
type Workflow = { on: Record<string, { branches?: string[] }>; jobs: Record<string, {
  needs?: string[]; steps?: Array<{ uses?: string; run?: string }>;
}> };
const workflow = (name: string) => safeLoad(readFileSync(join(root, `.github/workflows/${name}.yml`), 'utf8')) as Workflow;

describe('fork CI runs inherited verification on main', () => {
  test.each(['test', 'e2e', 'actionlint', 'semgrep', 'osv-scanner'])('%s gates main pull requests', name => {
    const w = workflow(name);
    expect(w.on.pull_request.branches).toContain('main');
    if (w.on.push) expect(w.on.push.branches).toContain('main');
  });

  test('the Bun test workflow owns verify and freshness; no obsolete starter CI remains', () => {
    expect(existsSync(join(root, '.github/workflows/ci.yml'))).toBe(false);
    const w = workflow('test');
    const steps = w.jobs.verify.steps!;
    expect(steps.some(step => step.uses?.startsWith('oven-sh/setup-bun@'))).toBe(true);
    expect(steps.some(step => step.run === 'bun install --frozen-lockfile')).toBe(true);
    expect(steps.some(step => step.run?.includes('bun run verify'))).toBe(true);
    expect(w.jobs['test-status'].needs).toContain('verify');
    expect(read('scripts/run-verify-parallel.sh')).toContain('"check:freshness-evals"');
  });

  test('BrainBench, E2E selection and coverage resolve the protected fork main ref', () => {
    expect(read('.github/workflows/test.yml').includes('+refs/heads/main:refs/remotes/origin/main')).toBe(true);
    expect(read('.github/workflows/e2e.yml').includes('git fetch origin main --quiet')).toBe(true);
    for (const file of ['scripts/ci-brainbench-gate.sh', 'scripts/select-e2e.ts',
      'scripts/coverage-diff-gate.ts', 'scripts/coverage-baseline-gate.ts']) {
      const source = read(file);
      expect(source.includes('origin/main'), file).toBe(true);
      expect(source.includes('origin/master'), file).toBe(false);
    }
  });
});
