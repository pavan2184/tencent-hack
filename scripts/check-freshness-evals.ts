/** Hermetic contract check. This does not run an adapter or score behavior. */
import { readFile } from 'node:fs/promises';
import { validateFreshnessContractBaseline, validateFreshnessContractDocs } from '../src/eval/freshness/baseline.ts';
import { loadFreshnessCorpus } from '../src/eval/freshness/fixtures.ts';

async function main(): Promise<void> {
  const corpus = await loadFreshnessCorpus();
  const file = 'evals/freshness/baselines/main.json';
  const baseline = validateFreshnessContractBaseline(file, JSON.parse(await readFile(file, 'utf8')), corpus);
  for (const doc of ['evals/freshness/README.md', 'docs/tencent/FRESHNESS_EVALS.md']) {
    validateFreshnessContractDocs(doc, await readFile(doc, 'utf8'));
  }
  console.log(`freshness-evals status=${baseline.status} fixtures=${baseline.counts.fixtures} gate=${baseline.counts.gate} holdout=${baseline.counts.holdout} hash=${baseline.fixtures_hash}`);
}

try { await main(); }
catch (error) {
  console.error(`freshness-evals invalid: ${(error as Error).message}`);
  process.exitCode = 1;
}
