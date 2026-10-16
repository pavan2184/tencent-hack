---
title: "Post-incident review: Rail-A acknowledgement latency SEV-2 (14 Sep 2026)"
type: incident_review
slug: incidents/2026-09-14-rail-a-sev2-review
source_kind: confluence
external_object_id: "CONF-OPS-1120"
provider_version: "4"
version_order: 4
provider_modified_at: "2026-10-02T01:00:00Z"
classification: internal
owner: ravi.kumar
evidence_class: standard
permission_version: "pv-2026-10-02-1"
permissions:
  kind: confluence
  space_key: OPS
  page_id: "1120"
  space_view_users: []
  space_view_groups: [finance-ops, engineering]
  page_view_users: []
  page_view_groups: []
  ancestors: []
grants: []
tags: [incident, post-incident-review, rail-a, rail-b, sev-2]
# Demo: the live page has moved on to v5 (action-item statuses were updated after indexing). This is
# standard evidence, so the brain still uses it, with a staleness warning, where the critical
# failover runbook in the same state is omitted.
simulate:
  live_version: "5"
  deleted: false
  indexed_at: "2026-10-02T01:30:00Z"
---

Blameless review of incident **INC-2026-0914**, a SEV-2 on Rail-A (Orionix Clearing) on Monday
14 September 2026. Incident commander: Ravi Kumar. Treasury duty manager: Jordan Lim.

## Summary

Orionix rotated a certificate on its acknowledgement gateway without notice. Rail-A settlement
acknowledgements slowed to a p95 of 140 seconds, the failover trigger was met, and outbound payments
ran on Rail-B for 1 hour 48 minutes. No customer funds were lost.

## Timeline (SGT)

- **09:52** Orionix starts a certificate rotation on its acknowledgement gateway (Orionix ref ORX-7781).
- **10:04** Ack latency p95 crosses 90 seconds; by **10:07** it has stayed above 90 seconds for 3 minutes.
- **10:08** Ravi Kumar declares a SEV-2 rail incident in #treasury-ops and pages the Treasury duty manager.
- **10:10** `rail_router` set to `RAIL_B_ONLY`. The last payment worker picks up the flag at **10:14**,
  about 4 minutes later, not the 2 minutes the runbook expects.
- **11:05** The Rail-B prefunding balance can no longer cover the queued payments; 214 payments wait
  25 minutes for a SGD 1 million intraday top-up.
- **11:58** Orionix confirms the fix. Acks stay below 30 seconds from 11:47 to 12:02.
- **12:02** `rail_router` back to `BALANCED`; the Rail-B settlement file is reconciled by 17:40.

## Impact

Rail-B carried 1,240 payments worth SGD 6.8 million. The worst customer delay was 34 minutes, and
support received 37 tickets.

## Action items

| Id   | Action                                                                  | Owner      | Status (as of 2 Oct) |
| ---- | ----------------------------------------------------------------------- | ---------- | -------------------- |
| AI-1 | Raise the Rail-B prefunding minimum from SGD 1.5 million to 2.5 million | Jordan Lim | Done (20 Sep)        |
| AI-2 | Add a hold on the 16:00 SGT settlement batch to the runbook             | Alex Tan   | Done (1 Oct)         |
| AI-3 | Find out why the `rail_router` flag takes about 4 minutes to propagate  | Ravi Kumar | Open                 |
| AI-4 | Ask Orionix for 10 business days' notice of gateway changes             | John Tan   | Open                 |

---

## Timeline

- **2026-09-16** | Confluence — v1: review drafted by Ravi Kumar.
- **2026-09-18** | Confluence — v3: review meeting held; four action items agreed.
- **2026-10-02** | Confluence — v4: AI-1 and AI-2 marked done.
