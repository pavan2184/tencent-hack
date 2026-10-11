import { apiFetch, type ApiFetchInit } from "./apiClient";
import type {
  AccessDecisionAction,
  AccessRequest,
  AnswerEnvelope,
  AskRequest,
  AuditEvent,
  AuditQuery,
  AuditVerify,
  Classification,
  Document,
  DocumentDetail,
  DocumentQuery,
  Grant,
  GrantCreate,
  Principal,
  QueryRecord,
  Source,
  SourceStatus,
  SyncAccepted,
  SyncTriggerKind,
  VerifyResult,
} from "./types";

// List routes may return a bare array or `{ items: [...] }`; both are accepted.
type ListResponse<T> = T[] | { items: T[] };

async function list<T>(path: string, init?: ApiFetchInit): Promise<T[]> {
  const body = await apiFetch<ListResponse<T>>(path, init);
  return Array.isArray(body) ? body : body.items;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

const id = encodeURIComponent;

function json(body: unknown): RequestInit {
  return { body: JSON.stringify(body) };
}

// --- Identity ------------------------------------------------------------

export function listPrincipals(): Promise<Principal[]> {
  return list<Principal>("/principals", { anonymous: true });
}

export function me(): Promise<Principal> {
  return apiFetch<Principal>("/me");
}

// --- Ask -----------------------------------------------------------------

export function ask(request: AskRequest): Promise<AnswerEnvelope> {
  return apiFetch<AnswerEnvelope>("/ask", { method: "POST", ...json(request) });
}

export function listQueries(): Promise<QueryRecord[]> {
  return list<QueryRecord>("/queries");
}

// --- Documents -----------------------------------------------------------

export function listDocuments(params: DocumentQuery = {}): Promise<Document[]> {
  return list<Document>(`/documents${query({ ...params })}`);
}

/** multipart: `file` (required), `title` and `classification` (optional). */
export function uploadDocument(formData: FormData): Promise<Document> {
  return apiFetch<Document>("/documents/upload", {
    method: "POST",
    body: formData,
  });
}

export function getDocument(documentId: string): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>(`/documents/${id(documentId)}`);
}

export function setClassification(
  documentId: string,
  classification: Classification,
): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>(
    `/documents/${id(documentId)}/classification`,
    {
      method: "PATCH",
      ...json({ classification }),
    },
  );
}

export function verifyDocument(documentId: string): Promise<VerifyResult> {
  return apiFetch<VerifyResult>(`/documents/${id(documentId)}/verify`, {
    method: "POST",
  });
}

/** Always 202 whether or not the document exists or is visible (no existence leak). */
export async function requestAccess(
  documentId: string,
  reason: string,
): Promise<void> {
  await apiFetch<unknown>(`/documents/${id(documentId)}/access-requests`, {
    method: "POST",
    ...json({ reason }),
  });
}

// --- Sources -------------------------------------------------------------

export function listSources(): Promise<Source[]> {
  return list<Source>("/sources");
}

export function getSourceStatus(sourceId: string): Promise<SourceStatus> {
  return apiFetch<SourceStatus>(`/sources/${id(sourceId)}/status`);
}

export function syncSource(
  sourceId: string,
  trigger_kind: SyncTriggerKind,
): Promise<SyncAccepted> {
  return apiFetch<SyncAccepted>(`/sources/${id(sourceId)}/sync`, {
    method: "POST",
    ...json({ trigger_kind }),
  });
}

// --- Access --------------------------------------------------------------

export function listGrants(documentId: string): Promise<Grant[]> {
  return list<Grant>(`/access/grants${query({ document_id: documentId })}`);
}

export function addGrant(grant: GrantCreate): Promise<Grant> {
  return apiFetch<Grant>("/access/grants", { method: "POST", ...json(grant) });
}

export async function revokeGrant(grantId: string): Promise<void> {
  await apiFetch<unknown>(`/access/grants/${id(grantId)}`, {
    method: "DELETE",
  });
}

export function listAccessRequests(): Promise<AccessRequest[]> {
  return list<AccessRequest>("/access/requests");
}

export function decideAccessRequest(
  requestId: string,
  decision: AccessDecisionAction,
): Promise<AccessRequest> {
  return apiFetch<AccessRequest>(
    `/access/requests/${id(requestId)}/${decision}`,
    {
      method: "POST",
    },
  );
}

// --- Audit ---------------------------------------------------------------

export function listAuditEvents(
  params: AuditQuery = {},
): Promise<AuditEvent[]> {
  return list<AuditEvent>(`/audit/events${query({ ...params })}`);
}

export function getAuditEvent(eventId: string): Promise<AuditEvent> {
  return apiFetch<AuditEvent>(`/audit/events/${id(eventId)}`);
}

export function verifyAuditChain(): Promise<AuditVerify> {
  return apiFetch<AuditVerify>("/audit/verify");
}
