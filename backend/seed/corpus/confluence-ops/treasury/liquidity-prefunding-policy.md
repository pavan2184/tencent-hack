---
title: Intraday Liquidity and Rail Prefunding Policy
type: policy
slug: treasury/liquidity-prefunding-policy
source_kind: confluence
external_object_id: "CONF-OPS-1104"
provider_version: "9"
version_order: 9
provider_modified_at: "2026-09-21T02:30:00Z"
classification: internal
owner: jordan.lim
evidence_class: standard
permission_version: "pv-2026-09-21-1"
# The page itself carries no restriction, but its parent "Treasury" (page 1100) is restricted to
# finance-ops. Confluence restrictions inherit downwards, so engineering cannot read this page even
# though the OPS space grants engineering view access.
permissions:
  kind: confluence
  space_key: OPS
  page_id: "1104"
  space_view_users: []
  space_view_groups: [finance-ops, engineering]
  page_view_users: []
  page_view_groups: []
  ancestors:
    - { page_id: "1100", view_users: [], view_groups: [finance-ops] }
grants: []
tags: [treasury, liquidity, prefunding, rail-a, rail-b, safeguarding]
---

How much cash Example Harbor Finance keeps on each payment rail during the day, who may approve a
top-up, and how customer money is safeguarded. This page sits under the restricted Treasury
section; only Finance Ops can view it.

## Minimum prefunding per rail

| Rail   | Operator            | Minimum balance                         | Checked at              |
| ------ | ------------------- | --------------------------------------- | ----------------------- |
| Rail-A | Orionix Clearing    | SGD 4.0 million at 08:00 SGT            | 08:00, 12:00, 15:30 SGT |
| Rail-B | Vegaline Settlement | SGD 2.5 million at all times while live | 08:00, 12:00, 15:30 SGT |

An alert fires when a rail balance falls below 110% of its minimum. During a failover or the
Rail-B cutover window, Treasury checks the Rail-B balance every 30 minutes instead.

## Top-up approvals

1. **Up to SGD 1 million:** the treasury analyst requests it and the Treasury duty manager approves.
2. **SGD 1 million to SGD 5 million:** the Finance Ops manager approves.
3. **Above SGD 5 million:** the CFO approves in writing.

Intraday top-ups are requested from the treasury desk and normally land within 45 minutes.

## Liquidity buffer

Across all rails, Treasury holds a buffer of **120% of the largest single-day net outflow** in the
previous 90 days. The current requirement is **SGD 9.1 million**, recalculated every Monday.

## Safeguarding customer money

Customer money is held in a segregated safeguarding account and is never used to prefund a rail.
The safeguarding account is reconciled against customer balances every business day by 11:00 SGT.
Any shortfall is topped up the same day and reported to Compliance within one business day.

---

## Timeline

- **2026-06-03** | Confluence — v7: Rail-B added with a SGD 1.5 million minimum.
- **2026-09-21** | Confluence — v9: Rail-B minimum raised to SGD 2.5 million after the September drill; 30-minute checks added for failover and cutover windows.
