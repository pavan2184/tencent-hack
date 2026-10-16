---
title: Transaction Monitoring Standard — Alert Rules and Handling
type: policy
slug: policies/transaction-monitoring-standard
source_kind: confluence
external_object_id: "CONF-COMP-2001"
provider_version: "6"
version_order: 6
provider_modified_at: "2026-10-07T03:00:00Z"
classification: internal
owner: nora.ibrahim
evidence_class: standard
permission_version: "pv-2026-10-07-1"
permissions:
  kind: confluence
  space_key: COMP
  page_id: "2001"
  space_view_users: []
  space_view_groups: [compliance, finance-ops]
  page_view_users: []
  page_view_groups: []
  ancestors: []
grants: []
tags: [compliance, aml, transaction-monitoring, alerts, rail-b]
---

The rules that raise anti-money-laundering alerts on business accounts, and how alerts are worked.
Owned by the Money Laundering Reporting Officer (MLRO), Nora Ibrahim. Thresholds are internal and
are reviewed every six months.

## Alert rules

| Rule  | Name                 | Raises an alert when                                                                        |
| ----- | -------------------- | ------------------------------------------------------------------------------------------- |
| TM-01 | Rapid movement       | 80% or more of an inbound credit above SGD 50,000 leaves the account within 48 hours        |
| TM-02 | New-account velocity | Outbound payments exceed SGD 200,000 in the first 30 days after onboarding                  |
| TM-03 | Structuring          | 3 or more outbound payments between SGD 18,000 and SGD 19,999 go to one payee within 7 days |
| TM-04 | High-risk corridor   | Any payment goes to a corridor on the internal high-risk list                               |
| TM-05 | Dormant reactivation | An account idle for 12 months sends more than SGD 100,000 within 14 days                    |
| TM-06 | Cross-rail duplicate | The same payment is submitted on Rail-A and Rail-B within 10 minutes (new for the cutover)  |

## Handling

1. **Level 1 triage** within 2 business days: close as explained, or escalate with a written reason.
2. **Level 2 investigation** within 10 business days: review the account's activity, ownership and
   due-diligence file, and contact the relationship manager if needed.
3. **MLRO decision:** the MLRO decides whether to file a suspicious transaction report (STR). The
   internal target is to file within 10 business days of escalation.
4. Accounts with overdue customer due diligence score one risk point higher on every rule.

## Tipping off

Never tell a customer, or anyone outside Compliance, that an alert or STR exists. Relationship
managers receive only "do not process" or "proceed" instructions.

---

## Timeline

- **2026-04-01** | Confluence — v4: TM-05 dormant-reactivation rule added.
- **2026-07-20** | Confluence — v5: TM-03 band moved to SGD 18,000 to SGD 19,999.
- **2026-10-07** | Confluence — v6: TM-06 cross-rail duplicate rule added ahead of the Rail-B cutover.
