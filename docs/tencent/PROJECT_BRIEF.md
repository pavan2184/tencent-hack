# Tencent FinTech Freshness Project Brief

Last updated: 2026-09-24

## Purpose and selected challenge

Build a proof-oriented data-freshness extension on the pinned [GBrain baseline](UPSTREAM_BASELINE.md) for the Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 FinTech track. Aspire's Internal Brain challenge spans Confluence, Jira, Slack, and Google Drive. The full challenge also asks for permission-aware retrieval, answer quality, and auditability; this workstream supplies only source-scoped freshness facts and safe-use signals to those later integrations. The [requirements mapping](HACKATHON_REQUIREMENTS.md) keeps team and organizer scope distinct.

Employees need current operational knowledge without old policy or runbook versions being silently presented as current. The freshness layer will observe provider changes, recover missed changes, prove deletion handling, verify critical evidence at query time, and emit versioned receipts. Downstream consumers can omit or abstain when a critical item is stale or unknown.

## Ownership and providers

Pavan owns data freshness. Chai owns access control; Raphael owns answer groundedness. Access control and groundedness are out of scope for this freshness workstream. Jev may prioritize semantically important changes but does not own deterministic freshness state, provider truth, or fallback decisions.

One normalized contract covers Confluence, Slack, Jira, and Google Drive. Confluence and Slack are live MVP targets using controlled test spaces. Jira and Google Drive are deterministic simulations in the current phase. This is a full derived copy of GBrain, preserving its source history, MIT attribution, source-scoped page identity, operation registry, PGLite/Postgres parity, and test discipline.

## User-visible freshness journey

1. A provider update arrives by webhook or is recovered by delta polling or slim reconciliation. Durable acceptance is recorded before acknowledgement; indexing becomes current only when searchable state matches the provider version.
2. A critical selected item is checked against the provider when policy requires live verification. It becomes `fresh`, `stale`, `unknown`, or `not_required`; stale/unknown critical evidence is omitted or causes abstention before exposure.
3. A versioned receipt states which source-scoped objects and versions were selected, when they were accepted/indexed/verified, their age and budget, and the safe-use result. A tombstone remains visible as a deletion fact.

## Targets and phase boundary

- Webhook propagation: `<=60` logical seconds from durable acceptance to searchability.
- Delta recovery: `<=300` logical seconds from provider change to searchability.
- Slim reconciliation: `<=3600` logical seconds from provider change to convergence.
- Hard future eval gates: zero stale critical exposures, accepted event loss, unsafe cursor advances, and duplicate mutations; exact tombstone, receipt, fallback, and convergence rates of `1.0`.

These are approved design targets, not measured performance. The current phase delivers contracts and a hermetic synthetic eval corpus plan with `contract_only` baseline status. Production tables, state machine, live connectors, webhook routes, and behavioral scoring follow later. The docs and structural test are not proof that any provider already meets the targets.

## Delivery dependencies and risks

The team's combined submission must demonstrate the official five scenarios and preserve CodeBuddy or WorkBuddy usage evidence, a live walkthrough, architecture diagram, repository, description, and cover image. Freshness contributes directly to the bounded-freshness scenario and neutral evidence/receipt signals for the combined demo. Duplicate, reordered, missed, and poisoned events; partial embedding; provider outages; and deletion/search mismatches are the main freshness failure modes. Controlled live provider access remains a delivery dependency. See [architecture](FRESHNESS_ARCHITECTURE.md), [data model](FRESHNESS_DATA_MODEL.md), [operations](FRESHNESS_API_CONTRACT.md), and [evals](FRESHNESS_EVALS.md).
