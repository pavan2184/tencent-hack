# Project Brief

Last updated: 2026-09-23

## One-Line Description

A permission-aware enterprise knowledge system that proves the freshness, authorization, and provenance of every answer.

## Hackathon Context

- Track: FinTech.
- Industry challenge contributor: Aspire.
- Official challenge: **The Internal Brain - Building a Context-Aware
  Enterprise Knowledge System with RBAC, Security Logging & Audit Trail**.
- Required source platforms: Confluence, Jira, Slack, and Google Drive.
- Full organizer requirements: [Hackathon Requirements](HACKATHON_REQUIREMENTS.md).

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

- Extend GBrain rather than rebuild the knowledge system from scratch.
- Demonstrate ingestion or live retrieval across the required enterprise-source categories.
- Preserve source-specific permission semantics instead of flattening them into
  one lossy access model.
- Resolve the asker's identity and permissions at query time and enforce
  authorization before evidence is exposed to the model.
- Maintain freshness through events, delta polling, reconciliation, and query-time verification.
- Attach claim-level citations and an answer audit receipt.
- Record a tamper-evident, complete, queryable audit trail containing the query,
  retrieved document IDs, answer, timestamp, and per-document authorization
  decisions.
- Demonstrate all five official scenarios with worked examples: unified query,
  bounded freshness, negative permission enforcement without an existence leak,
  live permission revocation, and audit inquiry.

## Non-MVP Scope

- Production-scale connector coverage for every source feature.
- Full enterprise identity-governance lifecycle management.
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
- Delivery risk: four production-grade connectors are too broad for the implementation window.
- Eligibility risk: missing CodeBuddy/WorkBuddy usage proof prevents the project
  from proceeding to scoring.
- Submission risk: the required live walkthrough, architecture/trust-boundary
  diagram, cover image, and worked examples may be left too late.

## Open Questions

- Which two connectors will be implemented against live APIs for the demo?
- Which identity provider and role model will drive the permission-change scenario?
- What freshness SLA will the team claim for each source and evidence class?
