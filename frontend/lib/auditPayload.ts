// Reads the `payload` of an `ask` audit event into a reconstruction of that question.
// The payload is jsonb written by services/retrieval.py, so every field is read defensively.
// Expected keys: question, query_id, retrieved_document_ids[], access_decisions[] (alias: decisions),
// freshness_receipt{receipt_id, overall_status, receipt_hash, evidence_items[]}, answer_text
// (alias: answer.text), abstained, abstain_reason, cited_document_ids[], grounding{verdict,
// coverage_ratio}, started_at, completed_at.

export interface AuditAccessDecision {
  document_id: string;
  decision: string;
  reason: string | null;
  matched_rule: string | null;
  permission_version: string | null;
}

export interface AskReconstruction {
  question: string;
  queryId: string | null;
  retrievedDocumentIds: string[];
  decisions: AuditAccessDecision[];
  citedDocumentIds: string[];
  answerText: string | null;
  abstained: boolean;
  abstainReason: string | null;
  receipt: {
    receiptId: string | null;
    overallStatus: string | null;
    receiptHash: string | null;
    itemCount: number;
    unsafeCount: number;
  } | null;
  grounding: { verdict: string | null; coverageRatio: number | null } | null;
  startedAt: string | null;
  completedAt: string | null;
}

type Json = Record<string, unknown>;

function asObject(value: unknown): Json | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Json)
    : null;
}

function asString(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(asString).filter((v): v is string => v !== null)
    : [];
}

function asDecisions(value: unknown): AuditAccessDecision[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw) => {
    const item = asObject(raw);
    const documentId = asString(item?.document_id);
    if (!item || !documentId) return [];
    return [
      {
        document_id: documentId,
        decision: asString(item.decision) ?? "unknown",
        reason: asString(item.reason),
        matched_rule: asString(item.matched_rule),
        permission_version: asString(item.permission_version),
      },
    ];
  });
}

/** Returns null when the payload does not describe an `ask` (no question). */
export function parseAskPayload(payload: Json): AskReconstruction | null {
  const question = asString(payload.question);
  if (!question) return null;

  const receipt = asObject(payload.freshness_receipt);
  const items = Array.isArray(receipt?.evidence_items)
    ? receipt.evidence_items
    : [];
  const grounding = asObject(payload.grounding);
  const answer = asObject(payload.answer);

  return {
    question,
    queryId: asString(payload.query_id),
    retrievedDocumentIds: asStringArray(payload.retrieved_document_ids),
    decisions: asDecisions(payload.access_decisions ?? payload.decisions),
    citedDocumentIds: asStringArray(payload.cited_document_ids),
    answerText: asString(payload.answer_text) ?? asString(answer?.text),
    abstained: payload.abstained === true || answer?.abstained === true,
    abstainReason:
      asString(payload.abstain_reason) ?? asString(answer?.abstain_reason),
    receipt: receipt && {
      receiptId: asString(receipt.receipt_id),
      overallStatus: asString(receipt.overall_status),
      receiptHash: asString(receipt.receipt_hash),
      itemCount: items.length,
      unsafeCount: items.filter((item) => asObject(item)?.safe_to_use === false)
        .length,
    },
    grounding: grounding && {
      verdict: asString(grounding.verdict),
      coverageRatio: asNumber(grounding.coverage_ratio),
    },
    startedAt: asString(payload.started_at),
    completedAt: asString(payload.completed_at),
  };
}
