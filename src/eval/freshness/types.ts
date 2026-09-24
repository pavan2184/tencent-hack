/** Versioned, synthetic freshness evaluation interchange contract. */
export const FRESHNESS_SCHEMA_VERSION = 1 as const;
export const FRESHNESS_PROVIDERS = ['confluence', 'slack', 'jira', 'google-drive'] as const;
export const FRESHNESS_SUITES = [
  'fast-path', 'delta-recovery', 'reconciliation', 'critical-verification',
  'receipt-integrity', 'failure-recovery', 'cross-platform-contract',
] as const;

export type FreshnessProvider = typeof FRESHNESS_PROVIDERS[number];
export type FreshnessSuite = typeof FRESHNESS_SUITES[number];
export type VerificationResult = 'fresh' | 'stale' | 'unknown' | 'not_required';
export type FreshnessStatus = 'fresh' | 'stale' | 'unknown' | 'not_searchable' | 'deleted';

export interface ProviderObjectState {
  object_id: string;
  provider_version: string;
  version_order: number | null;
  content_hash: string;
  modified_at: string;
  deleted: boolean;
  searchable: boolean;
  critical: boolean;
}

interface StepBase { step_id: string; at_seconds: number; }
export type FreshnessStep =
  | (StepBase & { kind: 'provider_mutation'; object: ProviderObjectState })
  | (StepBase & { kind: 'webhook'; event_id: string; object_id: string; provider_version: string })
  | (StepBase & { kind: 'delta_poll'; cursor_in: string | null; cursor_out: string; object_ids: string[]; event_ids: string[] })
  | (StepBase & { kind: 'reconcile'; object_ids: string[] })
  | (StepBase & { kind: 'verify'; object_id: string; result: VerificationResult; provider_version: string | null })
  | (StepBase & { kind: 'interrupt'; phase: 'before_apply' | 'after_apply_before_ack'; object_id: string })
  | (StepBase & { kind: 'retry'; event_id: string; object_id: string; attempt: number; outcome: 'applied' | 'parked' | 'rate_limited' })
  | (StepBase & { kind: 'index_outcome'; object_id: string; content_written: boolean; searchable: boolean; embedded: boolean });

export interface FreshnessFixture {
  schema_version: 1;
  fixture_id: string;
  provider: FreshnessProvider;
  suite: FreshnessSuite;
  initial_cursor: string | null;
  initial_objects: ProviderObjectState[];
  steps: FreshnessStep[];
}

export interface ExpectedObjectState extends ProviderObjectState {
  freshness_status: FreshnessStatus;
}

export interface FreshnessCheckpoint {
  after_step: string;
  expected_cursor: string | null;
  expected_objects: ExpectedObjectState[];
  expected_accounted_event_ids: string[];
  expected_parked_event_ids: string[];
}

export interface ExpectedFreshnessReceipt {
  object_id: string;
  provider_version: string | null;
  content_hash: string | null;
  sync_path: 'webhook' | 'delta' | 'reconcile' | 'live_verify';
  verification_result: VerificationResult;
  freshness_status: FreshnessStatus;
  safe_to_use: boolean;
}

export interface FreshnessMetrics {
  stale_critical_exposures: number;
  accepted_event_loss: number;
  cursor_advanced_past_unaccounted_work: number;
  duplicate_mutations: number;
  tombstone_accuracy: number;
  receipt_field_accuracy: number;
  safe_fallback_rate: number;
  eventual_convergence_rate: number;
  webhook_max_propagation_seconds: number | null;
  delta_max_recovery_seconds: number | null;
  reconciliation_max_convergence_seconds: number | null;
}

export interface FreshnessGold {
  schema_version: 1;
  fixture_id: string;
  checkpoints: FreshnessCheckpoint[];
  expected_receipts: ExpectedFreshnessReceipt[];
  expected_metrics: FreshnessMetrics;
}

export interface FreshnessCorpusPaths {
  fixtureDir?: string;
  holdoutDir?: string;
  goldDir?: string;
}

export interface LoadedFreshnessFixture {
  fixture: FreshnessFixture;
  gold: FreshnessGold;
  path: string;
}

export interface LoadedFreshnessCorpus {
  fixtures: LoadedFreshnessFixture[];
  holdouts: LoadedFreshnessFixture[];
  fixtures_hash: string;
  fixture_dir: string;
  holdout_dir: string;
  gold_dir: string;
}

/** The adapter-visible shape; no sealed expectation is included. */
export interface PublicFreshnessFixture extends FreshnessFixture {}
