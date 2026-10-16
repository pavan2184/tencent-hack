---
title: Rail-A Escalation Contacts (2025)
type: runbook
slug: runbooks/rail-a-escalation-contacts-2025
source_kind: confluence
external_object_id: "CONF-OPS-1031"
provider_version: "3"
version_order: 3
provider_modified_at: "2025-11-04T06:00:00Z"
classification: internal
owner: alex.tan
evidence_class: critical
permission_version: "pv-2025-11-04-1"
permissions:
  kind: confluence
  space_key: OPS
  page_id: "1031"
  space_view_users: []
  space_view_groups: [finance-ops, engineering]
  page_view_users: []
  page_view_groups: []
  ancestors: []
grants: []
tags: [rail-a, escalation, contacts, runbook]
# Demo: this page was deleted in Confluence when the contacts moved to the vendor escalation rota.
# The index still holds the old copy; live verification reports the deletion, and the critical
# policy omits it, so outdated contacts are never cited.
simulate:
  deleted: true
---

Who to call when Rail-A (Orionix Clearing) has a problem. Use this page during Rail-A incidents.

## Escalation chain

1. Open a ticket with the Orionix service desk and quote our member code **HBF-01**.
2. If there is no response in **20 minutes**, call the Orionix duty manager on the 2025 escalation
   line.
3. If there is no response in **45 minutes**, our Head of Payments calls the Orionix account
   director.

## Notes

- Orionix posts incident updates on its status page every 30 minutes.
- Settlement file questions go to the Orionix reconciliation team, not the service desk.

---

## Timeline

- **2025-03-10** | Confluence — v1: page created for the 2025 Orionix escalation chain.
- **2025-11-04** | Confluence — v3: account director contact updated.
