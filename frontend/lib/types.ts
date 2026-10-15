// Mirrors of the backend's response schemas (docs/API_CONTRACT.md, app/schemas/*).
// Enum-like fields use the library vocabularies; free-form backend strings stay `string`.

// --- Shared vocabularies -------------------------------------------------

export type SupportLabel =
  | "supported"
  | "partially_supported"
  | "unsupported"
  | "contradicted"
  | "not_checked";

export type Verdict =
  "grounded" | "partially_grounded" | "ungrounded" | "abstained";

export type FreshnessStatus =
  "fresh" | "stale" | "unknown" | "not_searchable" | "deleted";

export type VerificationResult = "fresh" | "stale" | "unknown" | "not_required";

export type OverallFreshness =
  "fresh" | "stale" | "unknown" | "not_required" | "mixed";

export type Classification =
  "public" | "internal" | "confidential" | "restricted";

export const CLASSIFICATIONS: readonly Classification[] = [
  "public",
  "internal",
  "confidential",
  "restricted",
];

export type EvidenceClass = "critical" | "standard";

export type Effect = "allow" | "deny";

export type SubjectType = "principal" | "group" | "role";

export type CheckpointStatus = "ready" | "polling" | "degraded" | "paused";

export type AccessRequestStatus = "pending" | "approved" | "denied";

export type AccessDecisionAction = "approve" | "deny";

export type SyncTriggerKind = "delta" | "reconcile";

// --- Identity ------------------------------------------------------------

export interface Principal {
  id: string;
  display_name: string;
  email: string | null;
  roles: string[];
  groups: string[];
}

// --- Ask / AnswerEnvelope ------------------------------------------------

export interface AskRequest {
  question: string;
  source_ids?: string[];
  top_k?: number;
  require_fresh?: boolean;
}

export interface Answer {
  text: string;
  abstained: boolean;
  abstain_reason: string | null;
  partial_notice: string | null;
}

export interface Claim {
  id: string;
  text: string;
  position: number;
  kind: "fact" | "inference";
}

export interface AnswerCitation {
  claim_id: string;
  evidence_id: string;
  document_id: string;
  slug: string;
  title: string;
  source_id: string;
  source_kind: string;
  quote: string | null;
  support: SupportLabel;
  score: number;
  provider_version: string | null;
  url: string | null;
}

export interface ReceiptItem {
  external_object_id: string;
  source_id: string;
  page_slug: string | null;
  freshness_status: FreshnessStatus;
  verification_result: VerificationResult | null;
  age_seconds: number | null;
  budget_seconds: number | null;
  safe_to_use: boolean;
  provider_version: string | null;
}

export interface FreshnessReceipt {
  receipt_id: string;
  overall_status: OverallFreshness;
  evidence_items: ReceiptItem[];
  receipt_hash: string;
  created_at: string;
}

export interface GroundingReport {
  verdict: Verdict;
  coverage_ratio: number;
  claims_total: number;
  supported: number;
  partially_supported: number;
  unsupported: number;
  contradicted: number;
  injection_flags: number;
  report_hash: string;
}

// Deliberately has no denied count: denials must never be observable to the asker.
export interface AccessSummary {
  principal_id: string;
  policy_version: string;
  allowed_count: number;
  evaluated_at: string;
}

export interface AskTiming {
  retrieval_ms: number;
  access_ms: number;
  freshness_ms: number;
  compose_ms: number;
  verify_ms: number;
  total_ms: number;
}

export interface AnswerEnvelope {
  schema_version: number;
  query_id: string;
  audit_id: string;
  answer: Answer;
  claims: Claim[];
  citations: AnswerCitation[];
  freshness_receipt: FreshnessReceipt | null;
  grounding: GroundingReport;
  access_summary: AccessSummary;
  timing: AskTiming;
}

export interface QueryRecord {
  id: string;
  question: string;
  status: string;
  answer_text: string | null;
  audit_event_id: string | null;
  created_at?: string;
}

// --- Documents -----------------------------------------------------------

export interface Document {
  id: string;
  source_id: string;
  source_kind: string;
  slug: string;
  title: string;
  classification: Classification;
  evidence_class: EvidenceClass;
  provider_version: string | null;
  provider_modified_at: string | null;
  updated_at: string;
  freshness_status?: FreshnessStatus | null;
  ingest_status: string;
}

export interface TimelineEntry {
  date?: string | null;
  summary?: string | null;
  detail?: string | null;
  source?: string | null;
}

export interface DocumentFreshness {
  indexed_at: string | null;
  searchable_at: string | null;
  last_verified_at: string | null;
  verification_result: VerificationResult | null;
  freshness_status: FreshnessStatus;
}

export interface DocumentDetail extends Document {
  owner_principal_id?: string | null;
  compiled_truth: string;
  // Markdown below the `---` separator, or structured timeline_entries rows.
  timeline: string | TimelineEntry[];
  frontmatter: Record<string, unknown>;
  freshness: DocumentFreshness | null;
}

export interface DocumentQuery {
  q?: string;
  source_id?: string;
  limit?: number;
  offset?: number;
}

export interface VerifyResult {
  verification_result: VerificationResult;
  freshness_status: FreshnessStatus;
}

// --- Sources -------------------------------------------------------------

export interface Source {
  id: string;
  name: string;
  kind: string;
  last_sync_at: string | null;
  page_count?: number | null;
  checkpoint_status?: CheckpointStatus | null;
}

// Shape owned by the freshness workstream; rendered generically.
export type SourceStatus = Record<string, unknown>;

export interface SyncAccepted {
  run_id: string;
}

// --- Access --------------------------------------------------------------

export interface Grant {
  id: string;
  document_id: string;
  subject_type: SubjectType;
  subject_id: string;
  effect: Effect;
  granted_by: string;
  granted_at: string;
  revoked_at: string | null;
}

export interface GrantCreate {
  document_id: string;
  subject_type: SubjectType;
  subject_id: string;
  effect: Effect;
}

export interface AccessRequest {
  id: string;
  document_id: string;
  principal_id: string;
  reason: string;
  status: AccessRequestStatus;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
}

// --- Audit ---------------------------------------------------------------

export interface AuditEvent {
  id: string;
  seq: number;
  occurred_at: string;
  actor_id: string;
  action: string;
  request_id: string | null;
  subject_type: string | null;
  subject_id: string | null;
  payload: Record<string, unknown>;
  prev_hash: string | null;
  hash: string;
}

export interface AuditQuery {
  actor_id?: string;
  document_id?: string;
  action?: string;
  since?: string;
  limit?: number;
}

export interface AuditVerify {
  ok: boolean;
  length: number;
  head_hash: string | null;
  first_broken_seq: number | null;
}

// --- Errors --------------------------------------------------------------

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: unknown;
    request_id: string | null;
  };
}
