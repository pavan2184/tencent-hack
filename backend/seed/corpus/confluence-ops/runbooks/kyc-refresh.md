---
title: KYC Periodic Refresh Runbook
type: runbook
slug: runbooks/kyc-refresh
source_kind: confluence
external_object_id: "CONF-OPS-1088"
provider_version: "4"
version_order: 4
provider_modified_at: "2026-10-05T02:00:00Z"
classification: internal
owner: priya.nair
evidence_class: critical
permission_version: "pv-2026-10-05-1"
permissions:
  kind: confluence
  space_key: OPS
  page_id: "1088"
  space_view_users: []
  space_view_groups: [finance-ops, engineering]
  page_view_users: []
  page_view_groups: [finance-ops]
  ancestors: []
grants: []
tags: [kyc, compliance, runbook, onboarding]
---
This runbook defines how Finance Ops refreshes know-your-customer (KYC) records for existing
business accounts. The page is restricted to the Finance Ops group because it describes screening
thresholds.

## Refresh cycle by risk tier

| Risk tier | Refresh every | Extra checks                                              |
| --------- | ------------- | --------------------------------------------------------- |
| High      | 12 months     | Source-of-funds evidence, senior Finance Ops sign-off     |
| Medium    | 24 months     | Updated director list and shareholding chart              |
| Low       | 36 months     | Confirmation of registered address and business activity |

## Procedure

1. The refresh workflow opens automatically **45 days** before an account's refresh due date.
2. The customer receives reminders at 45, 30 and 14 days before the due date.
3. A Finance Ops analyst re-runs sanctions and politically-exposed-person screening and records the
   result in the case.
4. For high-risk accounts, a senior analyst reviews source-of-funds evidence and approves the case.
5. If the refresh is not complete on the due date, the account is set to **inbound-only**: it can
   receive funds but cannot send payments until the refresh is approved.
6. Accounts that stay inbound-only for 60 days are referred to Compliance for an exit decision.

## Service levels

Analysts aim to close a complete case within 3 business days. The weekly KYC dashboard tracks
overdue cases by risk tier; the backlog target is fewer than 100 overdue high-risk cases.

---

## Timeline

- **2026-04-10** | Confluence — v2: medium-risk cycle changed from 36 to 24 months.
- **2026-08-28** | Confluence — v3: inbound-only restriction added for overdue refreshes.
- **2026-10-05** | Confluence — v4: page restricted to Finance Ops; 60-day Compliance referral added.
