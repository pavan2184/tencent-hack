---
title: "Rail-B cutover plan — Saturday 17 October"
type: email
slug: messages/2026-10-10-vendor-cutover
source_kind: email
external_object_id: "<20261010.cutover.4417@example-harbor.com>"
provider_version: "1"
version_order: 1
provider_modified_at: "2026-10-10T06:20:00Z"
classification: internal
owner: null
evidence_class: standard
permission_version: "pv-2026-10-10-1"
permissions:
  kind: email
  message_id: "<20261010.cutover.4417@example-harbor.com>"
  from_: ops@example-harbor.com
  to: [john.tan@example-harbor.com]
  cc: [jordan.lim@example-harbor.com]
  bcc: []
grants: []
tags: [email, rail-b, cutover, vendor]
---
**From:** ops@example-harbor.com · **To:** John Tan · **Cc:** Jordan Lim ·
**Sent:** Saturday 10 October 2026, 14:20 SGT · **Subject:** Rail-B cutover plan — Saturday 17 October

Hi John,

Confirming the Rail-B cutover plan agreed with Vegaline Settlement on yesterday's vendor call.

1. **Rehearsal:** Thursday 15 October, 14:00 SGT, in staging, using the new Rail-B settlement
   parser from PAY-150.
2. **Go/no-go call:** Friday 16 October, 17:00 SGT. Go criteria: PAY-150 merged and deployed;
   Rail-B prefunding at or above SGD 2.5 million; PAY-142 reconciliation closed or risk-accepted
   by Finance.
3. **Production cutover:** Saturday 17 October, 02:00 to 04:00 SGT. We move **40% of outbound
   volume** to Rail-B and keep 60% on Rail-A as the agreed first step.
4. **Rollback:** if Rail-B rejects more than 0.5% of files in the first hour, set `rail_router`
   back to `BALANCED` with Rail-A as primary. Rollback must complete within 10 minutes.
5. **Contacts:** Vegaline's on-call desk is on the vendor escalation rota in the vendor list.

Please reply with your approval so I can send the change notice to customer support on Monday.

Thanks,
Payments Operations

---

## Timeline

- **2026-10-10** | Email — Cutover plan sent to John Tan, copied to Jordan Lim.
- **2026-10-12** | Email — Awaiting Finance approval before the customer-support change notice.
