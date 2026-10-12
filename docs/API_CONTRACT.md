# API Contract

Last updated: 2026-10-12

## Overview

- **REST** under `/api` (plus `GET /healthz`), JSON in and out except the multipart upload.
  FastAPI serves OpenAPI at `/docs` and `/openapi.json`.
- **MCP** at `/mcp` (streamable HTTP, JSON responses). Tools are listed in [MCP tools](#mcp-tools).
- REST, MCP and the web UI call the same services, so a question asked through any surface runs
  the same governed pipeline and produces the same `AnswerEnvelope`.
- Payload types that are persisted or cross a component boundary carry `schema_version`
  (currently `1`): `AnswerEnvelope`, `FreshnessReceipt`, `GroundingReport`, audit payloads,
  freshness status reports.
- Times are ISO-8601 UTC strings (`2026-10-12T09:15:02Z`). Ids are UUID strings except principal,
  group, source and policy ids, which are readable strings.

## Auth

- **Scheme:** none (demo personas). The actor is read from the `X-Actor-Id` header, or from the
  `actor` query parameter when a client cannot set headers (`?actor=priya.nair`). The header wins
  when both are present. MCP uses the same header or query parameter.
- **Resolution:** `app/core/auth.get_principal` looks the id up in `principals`. Missing →
  `401 unauthenticated`; unknown or inactive → `401 unknown_actor`. This dependency is the single
  replacement point for real authentication (see [Security review](SECURITY_REVIEW.md)).
- **Request id:** `X-Request-Id` is honoured when it is 1–128 characters of `[A-Za-z0-9._-]`;
  otherwise the server generates one. It is echoed in the `X-Request-Id` response header, stored
  on audit events, and included in every error envelope.
- **Roles:** `employee`, `manager`, `auditor`, `admin`, `contractor`. Route-level role checks use
  `require_roles(...)` and fail with `403 forbidden`. Document-level visibility is decided by
  `access_control` per request and never cached.
- **Personas** (`backend/seed/principals.yaml`): `alex.tan` (employee; engineering),
  `priya.nair` (employee, manager; finance-ops, leadership), `sam.lee` (employee, auditor;
  compliance), `root.admin` (admin), `jordan.lim` (employee; finance-ops), `mei.chen`
  (contractor; no groups).

## Error Format

Every non-2xx response uses one envelope (FastAPI's 422 is rewritten into it):

```json
{
  "error": {
    "code": "cap_exceeded",
    "message": "Daily upload limit reached.",
    "details": {
      "cap": "uploads_per_actor_per_day",
      "limit": 20,
      "window": "day"
    },
    "request_id": "req_01J9ZK3V7Q8M2T4N6P0R5S1W3X"
  }
}
```

| Code                   | HTTP | When                                                                                                   |
| ---------------------- | ---- | ------------------------------------------------------------------------------------------------------ |
| `unauthenticated`      | 401  | no actor supplied; webhook secret missing or wrong                                                     |
| `unknown_actor`        | 401  | actor id not found or inactive                                                                         |
| `forbidden`            | 403  | role check failed on a resource the actor can see, or a route-level role requirement                   |
| `not_found`            | 404  | resource does not exist **or the actor may not see it** (identical bodies, see below)                  |
| `validation_error`     | 422  | body/query validation failed, disallowed upload extension; `details.errors[]` lists fields             |
| `payload_too_large`    | 413  | upload larger than `UPLOAD_MAX_FILE_BYTES`; `details {limit_bytes}`                                    |
| `cap_exceeded`         | 429  | a usage cap is exhausted; `details {cap, limit, window}`                                               |
| `conflict`             | 409  | duplicate source id/name, duplicate active grant, request already decided, receipt conflict            |
| `provider_unavailable` | 503  | the real model provider failed after retries (never used for freshness probes, which return `unknown`) |
| `not_implemented`      | 501  | stub connector (webhook or sync on a stub source)                                                      |
| `internal_error`       | 500  | anything unexpected; details are never leaked                                                          |

Cap names: `uploads_total` (window `total`), `uploads_per_actor_per_day` (window `day`),
`embedding_daily_call_budget` (window `day`). `UPLOAD_MAX_FILE_BYTES` uses `413`, not `429`.

### No existence leaks

- **A denied document produces a byte-identical `404` to a nonexistent one.** Every document route
  (`GET /api/documents/{id}`, its timeline, classification, verify, grants by `document_id` for
  non-admins) checks visibility first and answers with exactly:

  ```json
  {
    "error": {
      "code": "not_found",
      "message": "Document not found.",
      "details": {},
      "request_id": "<X-Request-Id>"
    }
  }
  ```

  Malformed ids get the same body. With the same `X-Request-Id`, the denied and nonexistent
  responses are identical byte for byte (status, headers that depend on the body, body);
  `scripts/smoke.sh` checks this.

- `POST /api/documents/{id}/access-requests` always answers `202 {"status": "received"}`, whether
  the document exists, is visible, or neither.
- `access_summary` exposes `allowed_count` only. There is no denied count, no denied id and no
  denied metadata in any asker-visible payload. Denied decisions appear only in audit events,
  which only auditors and admins can read.
- List endpoints return only visible items and never a total that includes invisible ones.

## Routes

All routes except `GET /healthz`, `GET /api/principals` and the webhook require an actor.

### GET /healthz

Purpose: liveness plus dependency checks. Auth: none. `200` when Postgres and Redis respond,
otherwise `503` with the same shape.

```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "provider_mode": "mock",
  "version": "0.1.0"
}
```

### GET /api/principals

Purpose: persona list for the switcher. Auth: none.

```json
{
  "items": [
    {
      "id": "priya.nair",
      "display_name": "Priya Nair",
      "email": "priya.nair@example-harbor.com",
      "roles": ["employee", "manager"],
      "groups": ["finance-ops", "leadership"],
      "is_active": true
    }
  ]
}
```

### GET /api/me

Purpose: the resolved principal. Response: one principal as above plus `external_identities`.
Errors: `401`.

### GET /api/documents?q=&source_id=&limit=20&offset=0

Purpose: ACL-filtered document list; `q` is a keyword search over title and body. `limit` 1–100.

```json
{
  "items": [
    {
      "id": "3f1c2b7e-8a41-4d55-9c0e-2b7d6a1e9f10",
      "source_id": "confluence-ops",
      "source_kind": "confluence",
      "slug": "runbooks/payment-rail-failover",
      "title": "Payment Rail Failover Runbook",
      "type": "runbook",
      "classification": "internal",
      "evidence_class": "critical",
      "owner_principal_id": "alex.tan",
      "provider_version": "7",
      "provider_modified_at": "2026-10-01T09:30:00Z",
      "updated_at": "2026-10-12T08:00:11Z",
      "freshness_status": "stale",
      "ingest_status": "indexed",
      "tags": ["payments", "runbook", "rail-a", "rail-b", "failover"]
    }
  ],
  "limit": 20,
  "offset": 0,
  "next_offset": null
}
```

### POST /api/documents/upload

Purpose: upload a `.md` or `.txt` file into source `uploads`; the actor becomes the owner.
Request: `multipart/form-data` with `file` (required), `title` (optional, default: the first
heading or the file name), `classification` (optional, default `internal`),
`shared_with_principals` and `shared_with_groups` (optional, comma-separated ids).
`UploadPermissions` = `{owner_principal_id: actor, shared_with_principals, shared_with_groups}`.
Ingestion is enqueued on `q.ingest`; the upload is audited as `document.upload`.

Response `201`:

```json
{
  "upload_id": "8d0f7a52-5c3e-4c84-9a3a-0c2f1d6b7e41",
  "document": {
    "id": "c4a7e2d9-1b6f-4f3a-8e5d-7a9b0c1d2e3f",
    "source_id": "uploads",
    "source_kind": "upload",
    "slug": "uploads/alex.tan/2026-10-12-smoke-note",
    "title": "Smoke test note",
    "type": "note",
    "classification": "internal",
    "evidence_class": "standard",
    "owner_principal_id": "alex.tan",
    "provider_version": "1",
    "provider_modified_at": "2026-10-12T09:20:00Z",
    "updated_at": "2026-10-12T09:20:00Z",
    "freshness_status": "not_searchable",
    "ingest_status": "pending",
    "tags": []
  },
  "ingest": { "status": "queued", "task_id": "5b1e…" }
}
```

Errors: `413 payload_too_large`, `429 cap_exceeded`, `422 validation_error` (extension not in
`UPLOAD_ALLOWED_EXTENSIONS`, empty file, not UTF-8).

### GET /api/documents/{id}

Purpose: one visible document. Response: the list item fields plus:

```json
{
  "compiled_truth": "Use this runbook when **Rail-A** …",
  "timeline": "## Timeline\n\n- **2026-10-01** | Confluence — v7: …",
  "frontmatter": {
    "title": "Payment Rail Failover Runbook",
    "type": "runbook",
    "tags": ["payments"]
  },
  "freshness": {
    "freshness_status": "stale",
    "provider_version": "7",
    "indexed_at": "2026-10-01T10:00:00Z",
    "searchable_at": "2026-10-01T10:00:00Z",
    "last_verified_at": "2026-10-12T09:15:01Z",
    "verification_result": "stale",
    "sync_path": "live_verify"
  },
  "access": {
    "decision": "allow",
    "matched_rule": "R8:confluence",
    "permission_version": "pv-2026-10-01-1"
  },
  "can_manage": false
}
```

`frontmatter` omits `permissions`, `grants` and `simulate` (membership lists are not shown to
readers). Errors: `404` (canonical body).

### GET /api/documents/{id}/timeline · POST /api/documents/{id}/timeline

GET returns `{"items": [{"id", "date", "source", "summary", "detail", "actor_id", "created_at"}]}`.
POST appends an entry (any actor who can read the document; append-only; audited
`document.timeline.add`):

```json
{
  "date": "2026-10-12",
  "source": "Web UI",
  "summary": "Reviewed before the cutover rehearsal.",
  "detail": ""
}
```

Response `201`: the created entry. Errors: `404`, `422`.

### PATCH /api/documents/{id}/classification

Purpose: change classification. Auth: document owner, `manager` or `admin`. Body
`{"classification": "confidential", "reason": "Contains board figures"}`. Response `200`: the
document list item. Audited `document.classification`. Errors: `404` (not visible), `403`
(visible but not allowed), `422`.

### POST /api/documents/{id}/verify

Purpose: live-verify freshness now (runs `verify_object` inline). Auth: `manager` or `admin`.

```json
{
  "schema_version": 1,
  "document_id": "3f1c2b7e-8a41-4d55-9c0e-2b7d6a1e9f10",
  "source_id": "confluence-ops",
  "external_object_id": "CONF-OPS-1042",
  "evidence_class": "critical",
  "expected_provider_version": "7",
  "observed_provider_version": "8",
  "verified_at": "2026-10-12T09:16:40Z",
  "verification_result": "stale",
  "freshness_status": "stale",
  "safe_use": false,
  "fallback_action": "omit"
}
```

A probe failure is `verification_result: "unknown"` with `safe_use: false` for critical
evidence, never an error and never `fresh`. Errors: `404`, `403`.

### POST /api/documents/{id}/access-requests

Body `{"reason": "Need the Q3 figures for the treasury forecast"}`. Response: always
`202 {"status": "received"}`. Requests for visible documents appear in the owner's and admins'
inbox; requests for anything else are stored and never surface.

### GET /api/sources · POST /api/sources · GET /api/sources/{id}/status · POST /api/sources/{id}/sync

`GET /api/sources` →
`{"items": [{"id", "name", "kind", "description", "connector", "last_sync_at", "newest_content_at", "archived"}]}`
(no page counts).

`POST /api/sources` (admin), mirrors MCP `sources_add`:

```json
{
  "id": "confluence-eng",
  "name": "Confluence — ENG space",
  "kind": "confluence",
  "description": "Engineering space",
  "config": {
    "connector": "gbrain_import",
    "local_path": "/app/seed/corpus/confluence-eng"
  }
}
```

Response `201`: the source. Errors: `403`, `409 conflict`, `422`.

`GET /api/sources/{id}/status` (freshness status report):

```json
{
  "schema_version": 1,
  "source_id": "confluence-ops",
  "connector_kind": "confluence",
  "checkpoints": [
    {
      "scope_key": "default",
      "cursor_value": "2026-10-12T08:00:00Z",
      "cursor_version": 3,
      "status": "ready",
      "last_polled_at": "2026-10-12T09:10:00Z",
      "last_reconciled_at": "2026-10-12T09:00:00Z",
      "last_successful_run_id": "a6c0b1e2-3d4f-4a5b-8c6d-7e8f9a0b1c2d"
    }
  ],
  "last_run": {
    "id": "a6c0b1e2-3d4f-4a5b-8c6d-7e8f9a0b1c2d",
    "trigger_kind": "reconcile",
    "status": "completed",
    "started_at": "2026-10-12T09:00:00Z",
    "completed_at": "2026-10-12T09:00:03Z",
    "observed_count": 3,
    "applied_count": 0,
    "tombstoned_count": 0,
    "failed_count": 0
  },
  "pending_events": 0,
  "parked_events": 0,
  "objects_by_status": { "fresh": 2, "stale": 1 }
}
```

`objects_by_status` is present only for `admin` (object counts include documents other actors may
not see). Errors: `404`.

`POST /api/sources/{id}/sync` (`manager` or `admin`), body `{"trigger_kind": "reconcile"}`
(`delta` | `reconcile`, default `reconcile`). The route creates the `sync_runs` row in `queued`
state with idempotency key `manual:<source_id>:<uuid>` and enqueues `sync_source`. Response
`202 {"run_id": "…", "status": "queued"}`. Errors: `404`, `403`, `501` for stub connectors.

### GET /api/access/grants · POST /api/access/grants · DELETE /api/access/grants/{id}

`GET /api/access/grants?document_id=&subject_type=&subject_id=&include_revoked=false`: admins and
managers see all grants; a document owner sees the grants on their documents; anyone else gets
`403`, and `404` when filtering by a document they cannot see.

```json
{
  "items": [
    {
      "id": "e7d6c5b4-a392-4180-9f7e-6d5c4b3a2918",
      "document_id": "0b9a8c7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
      "subject_type": "group",
      "subject_id": "leadership",
      "effect": "allow",
      "scope": "read",
      "granted_by": "system:seed",
      "granted_at": "2026-10-12T08:00:09Z",
      "revoked_at": null,
      "revoked_by": null,
      "reason": null
    }
  ]
}
```

`POST /api/access/grants` (admin or the document's owner): body
`{"document_id", "subject_type", "subject_id", "effect": "allow", "scope": "read", "reason"}` →
`201` grant; `409` when the same active grant exists. Audited `grant.create`.

`DELETE /api/access/grants/{id}` (admin or the document's owner), optional body `{"reason"}` →
`200` grant with `revoked_at` and `revoked_by` set. The next ask re-evaluates access from scratch.
Audited `grant.revoke`. Errors: `404`, `403`, `409` (already revoked).

### GET /api/access/requests · POST /api/access/requests/{id}/approve · POST /api/access/requests/{id}/deny

`GET /api/access/requests?status=pending`: admins see all; owners see requests for their
documents. Items: `{"id", "document_id", "document_title", "principal_id", "reason", "status",
"created_at", "decided_at", "decided_by"}`.

`approve` creates an `allow` grant for the requester (`subject_type: principal`) and returns
`200 {"request": {…}, "grant": {…}}`; `deny` returns `200 {"request": {…}}`. Both audited.
Errors: `404`, `403`, `409` (already decided).

### POST /api/ask

Purpose: the governed pipeline. Request:

```json
{
  "question": "What is the plan for the Rail-B cutover?",
  "source_ids": null,
  "top_k": 8,
  "require_fresh": false
}
```

`question` 1–2,000 characters; `source_ids` restricts retrieval; `top_k` 1–20 (default
`ASK_TOP_K`); `require_fresh=true` also drops standard evidence that is not `fresh` (instead of
allowing it with a warning). Response `200`: `AnswerEnvelope`.

```json
{
  "schema_version": 1,
  "query_id": "6a1f0e2d-3c4b-4a59-8e7d-6f5a4b3c2d1e",
  "audit_id": "9e8d7c6b-5a49-4382-a1b0-c9d8e7f6a5b4",
  "answer": {
    "text": "The production cutover is on Saturday 17 October, 02:00 to 04:00 SGT [E1]. A rehearsal runs in staging on Thursday 15 October [E2], and the Rail-B settlement parser must be merged and on staging before that rehearsal [E3].",
    "abstained": false,
    "abstain_reason": null
  },
  "claims": [
    {
      "id": "c1",
      "text": "The production cutover is on Saturday 17 October, 02:00 to 04:00 SGT.",
      "position": 0,
      "kind": "fact"
    },
    {
      "id": "c2",
      "text": "A rehearsal runs in staging on Thursday 15 October.",
      "position": 1,
      "kind": "fact"
    },
    {
      "id": "c3",
      "text": "The Rail-B settlement parser must be merged and on staging before the rehearsal.",
      "position": 2,
      "kind": "fact"
    }
  ],
  "citations": [
    {
      "claim_id": "c1",
      "evidence_id": "E1",
      "document_id": "1d2c3b4a-5968-4776-8a5b-4c3d2e1f0a9b",
      "slug": "messages/2026-10-10-vendor-cutover",
      "title": "Rail-B cutover plan — Saturday 17 October",
      "source_id": "email-ops",
      "source_kind": "email",
      "quote": "Production cutover: Saturday 17 October, 02:00 to 04:00 SGT.",
      "support": "supported",
      "score": 0.83,
      "provider_version": "1",
      "url": null
    },
    {
      "claim_id": "c2",
      "evidence_id": "E2",
      "document_id": "2e3d4c5b-6a79-4887-9b6c-5d4e3f2a1b0c",
      "slug": "channels/general/2026-10-10",
      "title": "#general — 2026-10-10",
      "source_id": "slack-ops",
      "source_kind": "slack",
      "quote": "Rehearsal is on Thursday 15 October in staging.",
      "support": "supported",
      "score": 0.78,
      "provider_version": "1791602400.001200",
      "url": null
    },
    {
      "claim_id": "c3",
      "evidence_id": "E3",
      "document_id": "3f4e5d6c-7b8a-4998-8c7d-6e5f4a3b2c1d",
      "slug": "issues/pay-150",
      "title": "PAY-150: Rail-B (Vegaline) settlement file parser for the cutover",
      "source_id": "jira-payments",
      "source_kind": "jira",
      "quote": "Merged and deployed to staging before the cutover rehearsal on Thursday 15 October 2026.",
      "support": "partially_supported",
      "score": 0.52,
      "provider_version": "6",
      "url": null
    }
  ],
  "freshness_receipt": {
    "receipt_id": "4b5a6978-8796-4a5b-9c8d-7e6f5a4b3c2d",
    "schema_version": 1,
    "request_key": "ask:6a1f0e2d-3c4b-4a59-8e7d-6f5a4b3c2d1e",
    "request_payload_hash": "5f0c…e21a",
    "created_at": "2026-10-12T09:15:02Z",
    "policy_id": null,
    "policy_schema_version": null,
    "evidence_items": [
      {
        "source_id": "email-ops",
        "external_object_id": "<20261010.cutover.4417@example-harbor.com>",
        "connector_kind": "email",
        "evidence_class": "standard",
        "page_id": "1d2c3b4a-5968-4776-8a5b-4c3d2e1f0a9b",
        "page_slug": "messages/2026-10-10-vendor-cutover",
        "policy_id": "email-standard",
        "policy_schema_version": 1,
        "provider_version": "1",
        "version_order": 1,
        "content_hash": "9a1b…44c0",
        "provider_modified_at": "2026-10-10T06:20:00Z",
        "observed_at": "2026-10-12T08:00:05Z",
        "accepted_at": "2026-10-12T08:00:05Z",
        "indexed_at": "2026-10-12T08:00:06Z",
        "searchable_at": "2026-10-12T08:00:06Z",
        "last_verified_at": null,
        "verification_result": "not_required",
        "sync_path": "reconcile",
        "age_seconds": 4496,
        "budget_seconds": 86400,
        "freshness_status": "fresh",
        "tombstoned": false,
        "safe_to_use": true,
        "fallback_action": null,
        "reason": null
      },
      {
        "source_id": "confluence-ops",
        "external_object_id": "CONF-OPS-1042",
        "connector_kind": "confluence",
        "evidence_class": "critical",
        "page_id": "3f1c2b7e-8a41-4d55-9c0e-2b7d6a1e9f10",
        "page_slug": "runbooks/payment-rail-failover",
        "policy_id": "confluence-critical",
        "policy_schema_version": 1,
        "provider_version": "7",
        "version_order": 7,
        "content_hash": "c3d2…a9f1",
        "provider_modified_at": "2026-10-01T09:30:00Z",
        "observed_at": "2026-10-12T08:00:03Z",
        "accepted_at": "2026-10-12T08:00:03Z",
        "indexed_at": "2026-10-01T10:00:00Z",
        "searchable_at": "2026-10-01T10:00:00Z",
        "last_verified_at": "2026-10-12T09:15:01Z",
        "verification_result": "stale",
        "sync_path": "live_verify",
        "age_seconds": 961502,
        "budget_seconds": 3600,
        "freshness_status": "stale",
        "tombstoned": false,
        "safe_to_use": false,
        "fallback_action": "omit",
        "reason": "provider_version_mismatch"
      }
    ],
    "oldest_evidence_age_seconds": 961502,
    "overall_status": "mixed",
    "receipt_hash": "b7e4…0d93"
  },
  "grounding": {
    "schema_version": 1,
    "verifier": "lexical-overlap-v1",
    "created_at": "2026-10-12T09:15:02Z",
    "claims_total": 3,
    "supported": 2,
    "partially_supported": 1,
    "unsupported": 0,
    "contradicted": 0,
    "coverage_ratio": 0.83,
    "verdict": "grounded",
    "injection_flags": 2,
    "quarantined_evidence_ids": ["E5"],
    "per_claim": [
      {
        "claim_id": "c1",
        "evidence_id": "E1",
        "quote": "Production cutover: Saturday 17 October, 02:00 to 04:00 SGT.",
        "support": "supported",
        "score": 0.83
      },
      {
        "claim_id": "c2",
        "evidence_id": "E2",
        "quote": "Rehearsal is on Thursday 15 October in staging.",
        "support": "supported",
        "score": 0.78
      },
      {
        "claim_id": "c3",
        "evidence_id": "E3",
        "quote": "Merged and deployed to staging before the cutover rehearsal on Thursday 15 October 2026.",
        "support": "partially_supported",
        "score": 0.52
      }
    ],
    "report_hash": "e1f2…7a8b"
  },
  "access_summary": {
    "principal_id": "priya.nair",
    "policy_version": "ac-v1",
    "allowed_count": 7,
    "evaluated_at": "2026-10-12T09:15:01Z"
  },
  "timing": {
    "retrieval_ms": 18,
    "access_ms": 2,
    "freshness_ms": 9,
    "compose_ms": 4,
    "verify_ms": 3,
    "total_ms": 41
  }
}
```

Receipt items cover only evidence that passed the access filter, in evaluation order, including
unsafe items (the failover runbook above is `stale` and was omitted from composition). Abstention
looks like `"answer": {"text": "", "abstained": true, "abstain_reason": "no_usable_evidence"}`
with empty `claims` and `citations`; abstain reasons include `no_usable_evidence`,
`low_coverage` and `contradicted_claim`. Errors: `401`, `422`, `503 provider_unavailable` (real
provider only; the audit event is still written with `status: failed`).

### GET /api/queries · GET /api/queries/{id}

`GET /api/queries?limit=20&offset=0` lists the actor's own queries (`auditor`/`admin` may pass
`actor_id`). Items: `{"id", "question", "status", "answer_text", "created_at", "latency_ms",
"audit_event_id"}`. `GET /api/queries/{id}` returns the stored row with `citations`,
`grounding_report`, `freshness_receipt_id` and `access_summary`; other actors' queries are `404`
unless the caller is an auditor or admin.

Both endpoints re-authorise every stored answer for the **viewer, at read time**. If the viewer
cannot read every document behind the answer right now (revoked, deleted, or evidence that cannot
be traced), the row is served with `"status": "withheld"`, a fixed `answer_text` ("This answer
used sources you can no longer access. …"), `"citations": []`, `"grounding_report": null` and
`"freshness_receipt_id": null`. The question is kept; which document changed is never disclosed.
Restoring access restores the row. Auditors reach the original through `/api/audit/events/{id}`.

### GET /api/audit/events · GET /api/audit/events/{id} · GET /api/audit/verify

Auth: `auditor` or `admin`; everyone else `403`.

`GET /api/audit/events?actor_id=&document_id=&action=&since=&limit=50&before_seq=` →
`{"items": [AuditEvent], "next_before_seq": 1201}`, newest first. `document_id` matches events
whose payload mentions the document (`retrieved_document_ids`, `cited_document_ids`) or whose
`subject_id` is the document.

`GET /api/audit/events/{id}`:

```json
{
  "id": "9e8d7c6b-5a49-4382-a1b0-c9d8e7f6a5b4",
  "seq": 1204,
  "occurred_at": "2026-10-12T09:15:02Z",
  "actor_id": "priya.nair",
  "action": "ask",
  "request_id": "req_01J9ZK3V7Q8M2T4N6P0R5S1W3X",
  "subject_type": "query",
  "subject_id": "6a1f0e2d-3c4b-4a59-8e7d-6f5a4b3c2d1e",
  "payload": {
    "schema_version": 1,
    "actor_id": "priya.nair",
    "action": "ask",
    "occurred_at": "2026-10-12T09:15:02Z",
    "request_id": "req_01J9ZK3V7Q8M2T4N6P0R5S1W3X",
    "subject_type": "query",
    "subject_id": "6a1f0e2d-3c4b-4a59-8e7d-6f5a4b3c2d1e",
    "question": "What is the plan for the Rail-B cutover?",
    "query_id": "6a1f0e2d-3c4b-4a59-8e7d-6f5a4b3c2d1e",
    "retrieved_document_ids": ["1d2c…", "2e3d…", "3f4e…", "3f1c…", "0b9a…"],
    "access_decisions": [
      {
        "document_id": "1d2c…",
        "decision": "allow",
        "reason": null,
        "matched_rule": "R8:email",
        "permission_version": "pv-2026-10-10-1"
      },
      {
        "document_id": "0b9a…",
        "decision": "deny",
        "reason": "grant_revoked",
        "matched_rule": "R7:confidential",
        "permission_version": "pv-2026-10-06-1"
      }
    ],
    "freshness_receipt": {
      "receipt_id": "4b5a6978-8796-4a5b-9c8d-7e6f5a4b3c2d",
      "overall_status": "mixed",
      "receipt_hash": "b7e4…0d93",
      "evidence_items": [
        {
          "page_id": "1d2c…",
          "freshness_status": "fresh",
          "safe_to_use": true
        },
        {
          "page_id": "3f1c…",
          "freshness_status": "stale",
          "safe_to_use": false,
          "fallback_action": "omit"
        }
      ]
    },
    "answer_text": "The production cutover is on Saturday 17 October …",
    "abstained": false,
    "abstain_reason": null,
    "cited_document_ids": ["1d2c…", "2e3d…", "3f4e…"],
    "grounding": { "verdict": "grounded", "coverage_ratio": 0.83 },
    "started_at": "2026-10-12T09:15:01.950Z",
    "completed_at": "2026-10-12T09:15:02.000Z"
  },
  "prev_hash": "0c1d…88ef",
  "hash": "a9b8…1f2e",
  "reconstruction": {
    "query": {
      "id": "6a1f0e2d-3c4b-4a59-8e7d-6f5a4b3c2d1e",
      "status": "answered",
      "latency_ms": 41
    },
    "freshness_receipt": {
      "receipt_id": "4b5a6978-8796-4a5b-9c8d-7e6f5a4b3c2d",
      "overall_status": "mixed"
    }
  }
}
```

The `ask` payload keys are fixed (the audit UI reads them in `frontend/lib/auditPayload.ts`):
`question`, `query_id`, `retrieved_document_ids[]`, `access_decisions[]` (`{document_id,
decision, reason, matched_rule, permission_version}`, one per retrieved document including
denied ones), `freshness_receipt` (`{receipt_id, overall_status, receipt_hash,
evidence_items[]}`), `evidence_document_ids[]` (the documents behind the evidence spans the
composer saw; used to re-authorise stored answers), `answer_text`, `abstained`, `abstain_reason`, `cited_document_ids[]`,
`grounding` (`{verdict, coverage_ratio}`), `started_at`, `completed_at`. The copies of the event
columns (`schema_version`, `actor_id`, `action`, `occurred_at`, `request_id`, `subject_type`,
`subject_id`) are recommended so the chain hash covers them. Denied decisions appear in audit
events and nowhere else.

`reconstruction` is present for `ask` and `mcp.query` events and `null` otherwise; it embeds the
stored `queries` row and the full persisted receipt. Errors: `403`, `404`.

`GET /api/audit/verify` →
`{"ok": true, "length": 1204, "head_hash": "a9b8…1f2e", "first_broken_seq": null}`. A modified
or deleted row makes `ok` false and `first_broken_seq` the first sequence whose hash or link does
not match.

### POST /api/webhooks/{connector_kind}/{source_id}

Purpose: durable acceptance of a provider change (freshness `accept`), then enqueue processing.
Auth: no actor; header `X-Webhook-Secret` must equal the source's `config.webhook_secret`
(constant-time compare). Sources without a configured secret reject every webhook.
`connector_kind` is the source's connector (`gbrain_import`, `upload`, `confluence`, `jira`,
`slack`, `gdrive`, `email`, `mcp_external`; `google_drive` is accepted as an alias of `gdrive`).

Body for `gbrain_import` (generic normalized change; stub connectors will define their own
provider envelopes):

```json
{
  "provider_event_id": "evt-2026-10-12-0001",
  "external_object_id": "CONF-OPS-1042",
  "change_kind": "upsert",
  "provider_version": "8",
  "version_order": 8,
  "observed_at": "2026-10-12T09:00:00Z",
  "scope_key": "default"
}
```

Response `202`:

```json
{
  "accepted": true,
  "event_id": "d1e2f3a4-b5c6-4d7e-8f90-a1b2c3d4e5f6",
  "duplicate": false,
  "state": "accepted"
}
```

A duplicate `provider_event_id` returns `202` with the existing `event_id` and
`"duplicate": true`, and causes no second mutation. Errors: `401 unauthenticated` (bad secret),
`404` (unknown source), `422` (kind does not match the source's connector, bad body),
`501 not_implemented` (stub connectors). If durable storage fails the route returns `5xx` so the
provider retries; it never acknowledges an event it did not store.

## MCP tools

Server `MCPServer("internal-brain")`, streamable HTTP mounted at `/mcp` (requests go to `/mcp/`;
`/mcp` redirects). Clients send `Accept: application/json, text/event-stream`. The actor comes from
`X-Actor-Id` or `?actor=` on the MCP URL. Every tool call runs the same services as REST, is
audited as `mcp.<tool>`, and returns JSON text content. Tool failures return `isError: true` with
the REST error envelope as the text; a document the actor cannot see is the same `not_found` as a
missing one.

| Tool                 | Params                                                                         | Purpose                                                                                                                     | Mirror                                                |
| -------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `whoami`             | —                                                                              | The resolved principal (id, roles, groups)                                                                                  | gbrain `whoami`                                       |
| `search`             | `query`, `source_ids?`, `limit=20`                                             | ACL-filtered hybrid search hits (`document_id, source_id, slug, title, chunk_id, snippet, score, freshness_status`); no LLM | gbrain `search`                                       |
| `query`              | `question`, `source_ids?`, `top_k?`, `require_fresh=false`                     | The governed pipeline; returns an `AnswerEnvelope`                                                                          | gbrain `query` (name; ours returns a governed answer) |
| `assemble_evidence`  | `question?` or `hits?: [{source_id, slug, chunk_id?}]`, `token_budget=4000`    | ACL-filtered, freshness-checked, sanitized evidence spans plus a freshness receipt; no answer                               | gbrain master `assemble_evidence`                     |
| `get_page`           | `slug` + `source_id`, or `document_id`                                         | One visible page (same shape as `GET /api/documents/{id}`)                                                                  | gbrain `get_page`                                     |
| `put_page`           | `slug`, `content` (Markdown, optional frontmatter), `source_id="uploads"`      | Create or replace a page in `uploads` owned by the actor; caps apply; other sources are connector-owned (`403`)             | gbrain `put_page`                                     |
| `list_pages`         | `source_id?`, `type?`, `tag?`, `limit=50`, `offset=0`                          | ACL-filtered page summaries                                                                                                 | gbrain `list_pages`                                   |
| `capture`            | `text`, `title?`                                                               | Quick note into `uploads` at `inbox/<date>-<hash>`; idempotent on content                                                   | gbrain `capture`                                      |
| `add_timeline_entry` | `slug` + `source_id` or `document_id`, `date`, `summary`, `source?`, `detail?` | Append a dated entry to a visible page's timeline                                                                           | gbrain `add_timeline_entry`                           |
| `get_timeline`       | `slug` + `source_id` or `document_id`, `since?`, `until?`                      | Timeline entries of a visible page                                                                                          | gbrain `get_timeline`                                 |
| `log_ingest`         | `source_id`, `source_type`, `source_ref`, `pages_updated[]`, `summary`         | Record an ingestion event in `ingest_log` (`manager`/`admin`)                                                               | gbrain `log_ingest`                                   |
| `sources_list`       | —                                                                              | Sources (no page counts)                                                                                                    | gbrain `sources_list`                                 |
| `sources_status`     | `source_id`                                                                    | Freshness status report for a source                                                                                        | gbrain `sources_status`                               |
| `sources_add`        | `id`, `name`, `kind`, `description?`, `config?`                                | Register a source (`admin`)                                                                                                 | gbrain `sources_add`                                  |
| `freshness_status`   | `document_id` or (`source_id`, `external_object_id`)                           | Object freshness without changing state                                                                                     | ours                                                  |
| `verify_freshness`   | `document_id`                                                                  | Live verification (`manager`/`admin`); same result as `POST /api/documents/{id}/verify`                                     | ours                                                  |
| `request_access`     | `document_id`, `reason`                                                        | Always `{"status": "received"}`                                                                                             | ours                                                  |
| `audit_lookup`       | `audit_id?` or `actor_id?`, `document_id?`, `action?`, `since?`, `limit=20`    | Audit events (`auditor`/`admin`)                                                                                            | ours                                                  |

## API Compatibility Rules

- Within `schema_version: 1`, changes are additive only: new optional fields and new endpoints.
  Removing or renaming a field, or changing its meaning, bumps `schema_version` for that type.
- Clients ignore unknown fields. Stored receipts, grounding reports and audit payloads keep their
  original `schema_version` and stay readable.
- Error `code` values are stable identifiers; `message` text may change.
- Enum values listed in [Data model](DATA_MODEL.md) are closed for version 1; adding one is a
  breaking change for exhaustive clients and is announced in `docs/DECISIONS.md`.
- The canonical `404` body for invisible documents never changes shape; any change must keep
  denied and nonexistent responses identical.
- MCP tool names that mirror GBrain keep GBrain's names; our additions never reuse a GBrain name
  with different meaning (except `query`, documented above).

## Open API Questions

- Should `/api` be versioned (`/api/v1`) before anything outside the team depends on it?
- Do we expose `url` deep links for synthetic sources, or leave them `null` until real connectors
  exist?
- Final caps and their `details.limit` values depend on the upload numbers that are still TBD.
