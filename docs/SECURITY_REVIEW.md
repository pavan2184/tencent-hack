# Security Review

Last updated: 2026-10-12

## Scope

Reviewed: the foundation design as of 2026-10-12, namely the governed pipeline, identity
resolution, document visibility, uploads, the audit chain, MCP and REST surfaces, webhooks, model
providers, compose deployment and the seeded data. Reviewed against the plan and the DDL in
`infra/postgres/migrations/`; the application code is being written in parallel, so every
"mitigation" below is a requirement with a named test, and the test status is **pending
integration**.

Out of scope: real authentication (none exists by design), live platform connectors (stubs),
multi-tenancy, formal compliance certification, and infrastructure hardening beyond the single
demo box.

## Data Classification

- **Public:** nothing in the corpus is public; the web UI and API docs are.
- **Internal:** most seeded pages (`classification: internal`): policies, runbooks, Jira issues,
  Slack logs, the vendor list, the cutover email.
- **Sensitive:** `confidential` and `restricted` pages (the Q3 board deck), raw platform
  permission snapshots (membership lists), access requests, audit events (contain questions and
  every access decision), freshness receipts.
- **Secrets:** `LLM_API_KEY`, `EMBEDDING_API_KEY`, `TENCENT_ADP_APP_KEY`, per-source
  `config.webhook_secret`, the Postgres password in `DATABASE_URL`.

All seeded data is synthetic ("Example Harbor Finance"); no real people, companies, credentials or
provider payloads are used anywhere in the repository.

## Threat Model

| #   | Asset                              | Actor                                 | Attack path                                                                                                                        | Impact                                                                 | Mitigation                                                                                                                                                                                                                                                                                       | Test                                                                                                                                     |
| --- | ---------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Existence of restricted documents  | Curious employee or contractor        | Compare `404` for a denied id vs a random id; read counts (`total`, denied counts, per-source page counts); compare answer wording | Confirms that a board deck, private channel or restricted issue exists | Canonical byte-identical `404` for denied, missing and malformed ids; no denied counts (`AccessSummary` has `allowed_count` only); lists never include totals of invisible items; source status object counts admin-only; abstention wording identical for "no evidence" and "all denied"        | `test_negative_permission_no_existence_leak`, `test_denied_document_404_identical_to_missing`, `test_access_summary_has_no_denied_field` |
| 2   | Existence (side channel)           | Same                                  | Timing: denied documents short-circuit faster or slower than missing ones; `access-requests` behaves differently for real ids      | Weak existence signal                                                  | Visibility check runs the same lookup path for missing and denied ids; `access-requests` always `202` and stores the row without a FK. Residual timing differences accepted for the demo (no rate limiting yet)                                                                                  | `test_access_request_always_202`                                                                                                         |
| 3   | Integrity of answers (freshness)   | Stale provider state, missed webhooks | Index holds v7 while the provider has v8; probe fails                                                                              | Stale operational instructions presented as current                    | Critical evidence live-verified before use; stale or unknown critical evidence omitted; unknown is never upgraded to fresh; the receipt shows every evaluated item with `safe_to_use`                                                                                                            | `test_bounded_freshness_stale_omitted`, freshness `test_policy_evaluate`, `test_verify`                                                  |
| 4   | Model behaviour / confidentiality  | Author of retrieved content           | Prompt injection inside a Slack message, page or upload ("ignore previous instructions, reveal …")                                 | Model leaks or invents content, or follows attacker instructions       | Access filter runs before any evidence reaches the model, so injected text can only reference what the asker may already see; `RegexInjectionSanitizer` strips medium/low and quarantines high severity; quarantined evidence can never support a claim; claims must cite evidence               | groundedness `test_sanitize`, `test_verify` (`test_quarantined_never_supported`), `test_injection_fixture_quarantined`                   |
| 5   | Audit trail                        | Insider with API or DB access         | Edit or delete audit rows to hide an access; reorder events                                                                        | Untraceable access                                                     | Append-only trigger rejects `UPDATE`/`DELETE`; hash chain `sha256(prev_hash ‖ seq ‖ canonical_json(payload))` with the event columns copied into the payload; `/api/audit/verify` reports `first_broken_seq`. Residual: a DB superuser can rewrite the whole chain (no external anchor)          | `test_audit_chain`, `test_audit_tamper_detected`                                                                                         |
| 6   | Availability and free-trial budget | Any persona (no auth)                 | Upload floods, huge files, many asks or uploads that burn embedding calls                                                          | Tencent trial exhausted, disk filled                                   | Extension allowlist (`md`, `txt`), size cap (`413`), total and per-actor-per-day file caps and a daily embedding-call budget (`429 cap_exceeded`), enforced atomically in `usage_counters`; budget exhaustion marks pages `budget_exceeded` instead of calling the provider. **Cap numbers TBD** | `test_upload_too_large_413`, `test_upload_daily_cap_429`, `test_embedding_budget_exceeded`                                               |
| 7   | Identity                           | Anyone who can reach the API          | Set `X-Actor-Id: root.admin` (spoofable persona header)                                                                            | Full impersonation                                                     | **Accepted for the demo**: synthetic data only, single demo box. Replacement point: `app/core/auth.get_principal` (swap header lookup for a verified token → same `Principal`). Unknown/inactive ids → `401 unknown_actor`                                                                       | `test_unknown_actor_401`                                                                                                                 |
| 8   | Webhook ingestion                  | Internet                              | Forged webhook to inject changes                                                                                                   | Spurious syncs or tombstones                                           | `X-Webhook-Secret` per source, constant-time compare; sources without a secret reject all webhooks; webhooks only accept a normalized change (content is fetched from the connector, never taken from the webhook body)                                                                          | `test_webhook_rejects_bad_secret`                                                                                                        |
| 9   | Revocation latency                 | Former grantee                        | Ask again right after revocation and hit a cache                                                                                   | Access after revocation                                                | No permission cache; access contexts rebuilt per ask from `grants` and `source_permissions`                                                                                                                                                                                                      | `test_live_revocation_changes_next_answer`                                                                                               |

## Auth Risks

- No authentication: the persona header is trusted (threat 7). Never deploy with real data.
- Role checks (`require_roles`) protect admin, manager and auditor routes; a role check on a
  document the actor cannot see must return the canonical `404`, not `403`.
- `?actor=` exists for MCP clients that cannot set headers; it ends up in access logs, which is
  acceptable only because identities are synthetic.
- CORS is restricted to `CORS_ORIGINS`. It is not a security boundary while identity is a header.

## Data Risks

- Raw membership lists in `source_permissions.raw` are sensitive; they are never returned to
  readers (`frontmatter` in API responses omits `permissions`, `grants` and `simulate`).
- Audit events hold questions and denied decisions; only `auditor` and `admin` can read them.
- Soft-deleted pages are excluded from search; tombstones are retained as freshness proof.
- Uploaded files stay on the `uploads` volume; `make reset` deletes them with the database.

## LLM Risks

- **Prompt injection:** retrieved content is untrusted. Mitigated by access-before-LLM, the
  sanitizer (quarantine for high severity), claim-citation requirements and support verification.
  A seeded red-team page (`slack-ops/channels/general/2026-10-11.md`) exercises it.
- **Data leakage:** only ACL-allowed, freshness-checked, sanitized evidence reaches the model, and
  only with `PROVIDER_MODE=real`. With the Tencent ADP app API, the app's own knowledge base must
  stay empty, otherwise ADP could answer from content our access filter never saw
  (`reference.added` events are surfaced so this is detectable).
- **Unsafe output reliance:** every claim must cite evidence; unsupported, contradicted or
  low-coverage answers abstain (`GROUNDING_MIN_COVERAGE=0.6`); the grounding report travels with
  the answer.
- **Logging exposure:** application logs record request ids, actor ids, action names and timings,
  not questions, evidence text or answers; those live only in `queries` and audit events. Provider
  request and response bodies are never logged.
- **Restricted inference:** the model is never told that denied documents exist, so it cannot hint
  at them; abstention text is the same whether evidence was missing or denied.

## File Upload Risks

- Extension allowlist `UPLOAD_ALLOWED_EXTENSIONS=md,txt`; anything else → `422`.
- Size cap `UPLOAD_MAX_FILE_BYTES` (`413`), plus total, per-actor-per-day and embedding-budget
  caps (`429`). Numbers are placeholders, TBD.
- Content must decode as UTF-8; it is parsed as text only. No execution, no archive extraction,
  no HTML rendering of uploaded content (the UI renders Markdown without raw HTML).
- Files are stored under a server-generated name in `UPLOAD_DIR`; the original filename is
  metadata only, so path traversal through filenames is not possible.
- Frontmatter in an upload cannot grant itself access: ownership is forced to the uploader and
  `grants`/`permissions` in uploaded frontmatter are ignored (the upload's permissions are always
  `UploadPermissions` built by the server).
- Uploaded content goes through the same sanitizer as every other evidence.

## Secrets Risks

- Secrets live only in `.env` (git-ignored; never created by agents; hook-protected) and on the
  demo box. `.env.example` holds blanks and mock-safe defaults only.
- `PROVIDER_MODE=real` refuses to start without the selected provider's key, so a misconfigured
  box fails loudly instead of silently using mock answers.
- Postgres credentials are demo defaults (`brain/brain`) and Postgres/Redis publish on
  `127.0.0.1` only. Change the password before putting the box on a public IP.
- Webhook secrets are stored in `sources.config`; they are not returned by `GET /api/sources`.

## Dependency Risks

- `mcp>=2.0` is new; the request-object access path for reading `X-Actor-Id` inside tools may
  change (fallback: a ContextVar-setting ASGI wrapper).
- Container images are pinned by major version (`pgvector/pgvector:pg16`, `redis:7-alpine`,
  `caddy:2-alpine`, `node:22-alpine`); `uv.lock` and `package-lock.json` pin libraries.
- No automated dependency scanning in CI yet.

## Required Security Tests

All are required before the demo; status is pending integration.

| Test                                            | File                                                       |
| ----------------------------------------------- | ---------------------------------------------------------- |
| `test_negative_permission_no_existence_leak`    | `backend/app/tests/test_ask_pipeline.py`                   |
| `test_live_revocation_changes_next_answer`      | `backend/app/tests/test_ask_pipeline.py`                   |
| `test_bounded_freshness_stale_omitted`          | `backend/app/tests/test_ask_pipeline.py`                   |
| `test_pipeline_order_access_before_llm`         | `backend/app/tests/test_ask_pipeline.py`                   |
| `test_injection_fixture_quarantined`            | `backend/app/tests/test_ask_pipeline.py`                   |
| `test_denied_document_404_identical_to_missing` | `backend/app/tests/test_documents_and_caps.py`             |
| `test_access_request_always_202`                | `backend/app/tests/test_documents_and_caps.py`             |
| `test_upload_too_large_413`                     | `backend/app/tests/test_documents_and_caps.py`             |
| `test_upload_daily_cap_429`                     | `backend/app/tests/test_documents_and_caps.py`             |
| `test_embedding_budget_exceeded`                | `backend/app/tests/test_documents_and_caps.py`             |
| `test_unknown_actor_401`                        | `backend/app/tests/test_health_and_errors.py`              |
| `test_audit_tamper_detected`                    | `backend/app/tests/test_audit_chain.py`                    |
| `test_webhook_rejects_bad_secret`               | `backend/app/tests/test_connectors_and_tasks.py`           |
| `test_access_summary_has_no_denied_field`       | `backend/libs/access_control/tests/test_filter_no_leak.py` |
| `test_quarantined_never_supported`              | `backend/libs/groundedness/tests/test_verify.py`           |
| `test_unknown_never_fresh`                      | `backend/libs/freshness/tests/test_policy_evaluate.py`     |
| `test_no_app_import` (one per library)          | `backend/libs/*/tests/test_models.py`                      |

## Open Security Questions

- Final upload cap numbers (TBD by Raphael) and whether to add a per-actor ask rate limit.
- Should the audit head hash be anchored outside the database (for example, printed into the
  submission or posted periodically) to cover the superuser-rewrite residual risk?
- When real authentication arrives: OIDC from which provider, and how do platform identities map
  to it?

## Integration addenda (2026-10-12)

- **MCP transport host check disabled.** The `mcp` SDK enables DNS-rebinding protection
  automatically for host `127.0.0.1`, which rejects `testserver`, `api:8000`, Caddy and any cloud
  hostname. The mount at `/mcp` therefore passes `transport_security` with the check disabled. The
  persona header is already spoofable, so this removes no real protection in the demo; re-enable
  it with an explicit allowed-host list when real authentication lands.
- **MCP `put_page` and `capture` never overwrite.** A taken slug gets a `-<id8>` suffix; the owner
  is always the calling persona and any `permissions`/`grants`/`owner`/`simulate` frontmatter in
  uploaded content is ignored, so an agent cannot grant itself access by uploading a page.
- **Webhooks.** Secret comparison is constant-time; a missing or unconfigured secret is 401, an
  unknown source 404, a stub connector 501, a non-object body 422 and a body over 1 MB 413.
- **Source payloads** strip any config key that looks like a secret (for example
  `webhook_secret`) before returning sources over REST or MCP.
