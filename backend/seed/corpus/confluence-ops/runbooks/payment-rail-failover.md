---
title: Payment Rail Failover Runbook
type: runbook
slug: runbooks/payment-rail-failover
source_kind: confluence
external_object_id: "CONF-OPS-1042"
provider_version: "7"
version_order: 7
provider_modified_at: "2026-10-01T09:30:00Z"
classification: internal
owner: alex.tan
evidence_class: critical
permission_version: "pv-2026-10-01-1"
permissions:
  kind: confluence
  space_key: OPS
  page_id: "1042"
  space_view_users: []
  space_view_groups: [finance-ops, engineering]
  page_view_users: []
  page_view_groups: []
  ancestors: []
grants: []
tags: [payments, runbook, rail-a, rail-b, failover]
simulate:
  live_version: "8"
  deleted: false
  indexed_at: "2026-10-01T10:00:00Z"
---
Use this runbook when **Rail-A** (our primary payment rail, operated by Orionix Clearing) degrades
and outbound payments must fail over to **Rail-B** (the secondary rail, operated by Vegaline
Settlement).

## Trigger

Start the failover procedure when either condition holds:

- Rail-A settlement acknowledgements take longer than **90 seconds** for **3 consecutive minutes**
  (dashboard: Payments / Rail health / ack latency p95); or
- Orionix Clearing declares an incident affecting outbound credit transfers.

## Failover procedure

1. The on-call payments engineer declares a **SEV-2 rail incident** in #treasury-ops and pages the
   Treasury duty manager.
2. In the payments console, set the `rail_router` flag to **`RAIL_B_ONLY`**. New outbound payments
   route to Rail-B within about 2 minutes.
3. Treasury confirms the Rail-B prefunding account holds at least **SGD 2.5 million**. If it is
   lower, request an intraday top-up from the treasury desk before releasing queued payments.
4. **Hold the 16:00 SGT settlement batch** until Vegaline confirms receipt of the Rail-B file. Never
   resubmit the same batch to Rail-A.
5. Customer support posts macro `PAY-FAILOVER-01` ("payments may be delayed up to 30 minutes").

## Recovery

When Rail-A acknowledgements stay below 30 seconds for 15 minutes, set `rail_router` back to
`BALANCED`, then reconcile the day's Rail-B settlement file against the ledger before the 18:00 SGT
close. Open a post-incident review within 2 business days and link it from this page.

---

## Timeline

- **2026-06-02** | Confluence — v5: first version, written after the Vegaline Rail-B contract was signed.
- **2026-09-20** | Confluence — v6: September failover drill; prefunding threshold raised from SGD 1.5M to SGD 2.5M.
- **2026-10-01** | Confluence — v7: added the 16:00 SGT batch-hold step after the drill review.
