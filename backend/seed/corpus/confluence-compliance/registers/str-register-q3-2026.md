---
title: STR Register — Q3 2026 Summary
type: register
slug: registers/str-register-q3-2026
source_kind: confluence
external_object_id: "CONF-COMP-2014"
provider_version: "3"
version_order: 3
provider_modified_at: "2026-10-06T08:00:00Z"
classification: restricted
owner: nora.ibrahim
evidence_class: standard
permission_version: "pv-2026-10-06-1"
# The COMP space admits finance-ops, but this page is restricted to compliance. Being in compliance
# is still not enough: `restricted` needs ownership or an explicit grant (rule R6). Internal audit
# reads it through a grant to the `auditor` role, not to a named person.
permissions:
  kind: confluence
  space_key: COMP
  page_id: "2014"
  space_view_users: []
  space_view_groups: [compliance, finance-ops]
  page_view_users: []
  page_view_groups: [compliance]
  ancestors: []
grants:
  - subject_type: role
    subject_id: auditor
    effect: allow
    reason: Internal audit fieldwork for the Q4 2026 AML review
tags: [compliance, aml, str, register, restricted]
---

Quarterly summary of the suspicious transaction report (STR) register for July to September 2026.
Restricted: the full case files stay in the case-management system. This summary carries no
customer names.

## Q3 2026 in numbers

- **14 STRs filed** (Q2 2026: 11), case references STR-2026-031 to STR-2026-044.
- **Alerts:** 1,862 raised, 1,790 closed at level 1, 58 investigated at level 2.
- **Median time from escalation to filing:** 6 business days, against a 10-day target. One filing
  took 13 business days because the account's ownership chart had to be rebuilt.
- **Outcomes:** 4 accounts exited, 6 placed under enhanced monitoring, 4 still under review.

## Typologies

| Typology                                     | STRs | Main rule    |
| -------------------------------------------- | ---- | ------------ |
| Rapid in-and-out on newly onboarded accounts | 9    | TM-01, TM-02 |
| Structuring below internal thresholds        | 3    | TM-03        |
| Referred by the card processor               | 2    | (external)   |

## Notes for the Q4 audit

- Every STR in the quarter has a recorded MLRO decision and a filing receipt.
- Two level-2 investigations missed the 10-day target; both were escalated to the MLRO.
- Access to this register is logged. Do not copy it into other spaces or chat channels.

---

## Timeline

- **2026-10-02** | Confluence — v1: Q3 summary drafted by Nora Ibrahim.
- **2026-10-06** | Confluence — v3: figures reconciled with the case-management export; role grant added for internal audit.
