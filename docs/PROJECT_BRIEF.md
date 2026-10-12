# Project Brief

Last updated: 2026-10-12

## One-Line Description

A permission-aware enterprise knowledge system that proves the freshness, authorization, and provenance of every answer.

## Hackathon Context

- Track: FinTech.
- Industry challenge contributor: Aspire.
- Official challenge: **The Internal Brain - Building a Context-Aware
  Enterprise Knowledge System with RBAC, Security Logging & Audit Trail**.
- Required source platforms: Confluence, Jira, Slack, and Google Drive.
- Full organizer requirements: [Hackathon Requirements](HACKATHON_REQUIREMENTS.md).
- Submission deadline: **16 October 2026**.

## Problem

Enterprise knowledge is fragmented across Slack, Jira, Confluence, and Google Drive. A conventional RAG system can silently return stale information, expose content after permissions change, or provide citations without enough evidence for an audit.

## Target Users

- Primary user: employees searching internal operational and policy knowledge.
- Secondary user: security, compliance, and audit teams reconstructing knowledge access and generated answers.
- Non-users: people without source-system authorization for the underlying evidence.

## User Journeys

1. An employee asks a cross-source question and receives a grounded answer with citations and a freshness receipt.
2. An administrator revokes source access; subsequent retrieval immediately excludes the affected evidence.
3. An auditor reconstructs who asked, what was retrieved, which authorization decisions were made, and what answer was produced.

## MVP Scope

The project pivoted on 2026-10-12 from a TypeScript fork of GBrain to a Python monorepo
(decisions D-001 and D-002 in [Decisions](DECISIONS.md)). The MVP is:

- **GBrain's page model, ported to Python.** We do not run the TypeScript GBrain. We mirror its
  two-layer page (compiled truth above `---`, append-only timeline below), `(source_id, slug)`
  identity, sources as the scoping unit, the `sources/pages/content_chunks/links/tags/
timeline_entries/raw_data/page_versions/ingest_log` tables, hybrid tsvector + pgvector search,
  GBrain-named MCP tools, and import of a GBrain brain directory as a source. See
  [GBrain mapping](GBRAIN_MAPPING.md).
- **Everything is a document.** Uploads, Slack daily conversation logs, emails, and Confluence,
  Jira and Drive content all become pages governed by one set of access-control, freshness and
  groundedness machinery.
- **Three owner-scoped Python libraries** that fill GBrain's documented gaps:
  `groundedness` (claims ↔ evidence, support verification, abstention, injection screening),
  `freshness` (webhook/delta/reconcile/verify state machine and receipts, ported verbatim from the
  approved freshness spec), and `access_control` (principals and groups, raw per-platform
  permission semantics, confidentiality, grant/revoke, no existence leak).
- **One governed query pipeline** in the app: hybrid search → access filter (before any LLM call)
  → freshness evaluation and live verification of critical evidence → sanitize → compose →
  verify → abstain → hash-chained audit → answer envelope with claim-level citations, a freshness
  receipt, a grounding report and an access summary.
- **Three surfaces over the same pipeline:** an MCP server (streamable HTTP at `/mcp`), a REST API
  (`/api`), and a Next.js web UI with a persona switcher.
- **Connectors:** `gbrain_import` and `upload` are real; Confluence, Jira, Slack, Google Drive,
  email and `mcp_external` are typed stubs. Platform permission semantics are demonstrated through
  the seeded corpus, whose pages carry raw per-platform permissions.
- **Persona demo, no authentication.** Seeded personas are selected with the `X-Actor-Id` header.
- **Uploads open but capped** (file size, total files, files per actor per day, embedding-call
  budget) to stay inside the Tencent Cloud free trial. Final numbers are TBD; placeholders live in
  `.env.example`.
- **Model providers:** deterministic mock providers by default (the stack boots and tests with no
  keys); Tencent Cloud ADP is the first real provider.
- **All five official scenarios** with worked examples: unified query, bounded freshness, negative
  permission enforcement without an existence leak, live permission revocation, and audit inquiry.

## Non-MVP Scope

- Live API connectors for Confluence, Jira, Slack and Google Drive (typed stubs only in the MVP).
- Real authentication, SSO or an identity provider; the persona header is the documented
  replacement point.
- Production-scale connector coverage for every source feature.
- Full enterprise identity-governance lifecycle management.
- Multi-tenant isolation; the MVP is one organisation on one box.
- Formal regulatory certification.
- Perfect semantic conflict resolution across all document types.

## Success Metrics

- No critical stale answer escapes in the demo test set.
- Permission revocation is reflected before the next protected answer.
- Fresh content becomes answerable within five minutes in the demonstrated fast path.
- Every answer exposes source version, freshness state, and claim-level provenance.
- Audit records allow deterministic reconstruction of the demo queries.
- Restricted evidence is filtered before model invocation, and negative cases do
  not reveal that inaccessible content exists.
- Every official FinTech scenario has a reproducible worked example.
- Submission evidence includes at least three CodeBuddy or WorkBuddy usage
  screenshots or an accepted screen recording.

## Key Risks

- Product risk: the proof layer may be too technical unless it is visible in the demo.
- Technical risk: source webhooks can be delayed, duplicated, reordered, or missed.
- Data risk: deletions and permission-only changes may not include document content.
- Security/privacy risk: authorization metadata or stale cached evidence could leak restricted information.
- Delivery risk: four days remain; library stubs are the demo floor, so the five scenario tests
  must pass on stubs alone.
- Provider risk: the Tencent ADP embedding endpoint and model are unconfirmed; `EMBEDDING_DIM`
  must match the real model before the first real ingest (otherwise `make reset`).
- Identity risk: the persona header is spoofable. Accepted for a synthetic-data demo; see
  [Security review](SECURITY_REVIEW.md).
- Eligibility risk: missing CodeBuddy/WorkBuddy usage proof prevents the project
  from proceeding to scoring.
- Submission risk: the required live walkthrough, architecture/trust-boundary
  diagram, cover image, and worked examples may be left too late.

## Resolved Questions

These were open on 2026-09-23 and were resolved on 2026-10-12.

- **Which connectors run against live APIs?** None in the MVP. `gbrain_import` (walks a brain
  directory of Markdown pages) and `upload` are real connectors. Confluence, Jira, Slack, Google
  Drive, email and `mcp_external` are typed stubs that raise
  `NotImplementedError("<kind> connector is a stub — owner: Pavan")`. The seeded corpus carries
  raw per-platform permissions, so platform semantics are still enforced and demonstrated. This
  replaces the superseded spec's "Confluence and Slack live" target.
- **Which identity provider and role model drive the permission-change scenario?** No identity
  provider. Six seeded personas (`backend/seed/principals.yaml`) are selected with the
  `X-Actor-Id` header (MCP: the same header or `?actor=`), resolved by one dependency,
  `app/core/auth.get_principal`. Roles: `employee`, `manager`, `auditor`, `admin`, `contractor`;
  groups: `engineering`, `finance-ops`, `leadership`, `compliance`. The permission change is the
  live revocation of the `leadership` grant on the Q3 board deck by `root.admin`.
- **What freshness SLA do we claim?** Logical-time budgets from the approved freshness spec:
  **60 s** webhook fast path, **300 s** delta recovery, **3,600 s** reconciliation convergence.
  Evidence budgets per policy: critical evidence 3,600 s index age and 300 s verification age with
  mandatory live verification (omit on failure); standard evidence 86,400 s and 3,600 s (allow
  with warning). The demo target is that uploaded content is answerable within **5 minutes**.

## Team plan

Each owner builds their library behind the stub that ships on 12 October and wires it into the
app only through the listed call sites. Libraries never import `app`.

| Owner   | Library          | Public entry points                                                                                                                                                                                                                                              | App call sites                                                                                                                                                                                         | Migration range | Done by 15 Oct                                                                                                                                                                          |
| ------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Raphael | `groundedness`   | Protocols `EvidenceSanitizer`, `AnswerComposer`, `SupportVerifier`, `AbstentionPolicy`; `RegexInjectionSanitizer`, `ExtractiveComposer`, `ground`, `LexicalOverlapVerifier` (deterministic, `lexical-v2`), `DefaultAbstentionPolicy`; models. Model-free (D-013) | `app/services/retrieval.py` (sanitize → compose → verify → should_abstain), `app/services/compose.py` (`ModelComposer`: generate, then `ground`)                                                       | 0300–0399       | Deterministic `ground` and verifier (done, D-013), generation prompt tuning, injection-pattern corpus, groundedness evals; plus the foundation (app core) and integration               |
| Pavan   | `freshness`      | `FreshnessService(store, clock)`: `accept`, `connector_sync`, `freshness_status`, `evaluate`, `verify_freshness`, `freshness_receipt`; `versioning.compare`; Protocols `FreshnessStore`, `ProviderProbe`, `ChangeSource`, `Clock`; enums and models              | `app/tasks/sync.py` (`connector_sync`), `app/services/retrieval.py` (`evaluate`, `verify_freshness`, `freshness_receipt`), `app/api/routers/webhooks.py` (`accept`), `app/adapters/freshness_store.py` | 0100–0199       | Delta and reconcile algorithms, backoff and parking, Confluence and Slack probes or simulations, ported TS eval fixtures; ingestion pipeline (Celery, connectors); Tencent Cloud deploy |
| Chai    | `access_control` | `DefaultAccessPolicy("ac-v1")`: `decide`, `filter`; Protocols `AccessPolicy`, `GrantStore`, `PermissionSnapshotStore`, `PrincipalDirectory`, `AccessRequestStore`; raw permission models per platform; `AccessSummary`                                           | `app/core/auth.get_principal` (→ `Principal`), `app/services/retrieval.py` (`filter`), `app/api/routers/access.py` (stores), `app/adapters/access_stores.py`                                           | 0200–0299       | Real platform-permission ingestion, group resolution, permission-drift hook with freshness, final deny wording                                                                          |

### Integration order

1. **12 Oct — skeleton merged.** Monorepo, the three libraries with public interfaces, stub
   implementations and tests, the app core composing them into the governed pipeline, compose and
   Makefile, the seeded corpus and personas, and these docs. `make up`, `make seed` and
   `make test` are green in mock mode.
2. **13 Oct — libraries behind the stubs.** Each owner opens PRs that touch only
   `backend/libs/<their lib>`, `backend/app/adapters/<their adapter file>` and
   `infra/postgres/migrations/<their range>`. Anything else goes through Raphael.
3. **14 Oct — demo script and the real ADP provider.** Walk the five scenarios end to end on the
   stack, switch `PROVIDER_MODE=real` against Tencent ADP, fix what breaks.
4. **15 Oct — video and submission package.** Demo video, CodeBuddy/WorkBuddy usage evidence,
   cover image, description, worked examples.
5. **16 Oct — submission deadline.**
