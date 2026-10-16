---
title: "RE: Rail-B cutover plan — Saturday 17 October"
type: email
slug: messages/2026-10-12-cutover-approval
source_kind: email
external_object_id: "<20261012.approval.5120@example-harbor.com>"
provider_version: "1"
version_order: 1
provider_modified_at: "2026-10-12T00:40:00Z"
classification: internal
owner: null
evidence_class: standard
permission_version: "pv-2026-10-12-1"
# Daniel Wong is on bcc: the message is visible to him, while nobody else can tell that.
permissions:
  kind: email
  message_id: "<20261012.approval.5120@example-harbor.com>"
  from_: john.tan@example-harbor.com
  to: [ops@example-harbor.com]
  cc: [jordan.lim@example-harbor.com]
  bcc: [daniel.wong@example-harbor.com]
grants: []
tags: [email, rail-b, cutover, approval, pay-142, pay-155]
---

**From:** John Tan · **To:** ops@example-harbor.com · **Cc:** Jordan Lim ·
**Sent:** Monday 12 October 2026, 08:40 SGT · **Subject:** RE: Rail-B cutover plan — Saturday 17 October

Hi Payments Operations,

Finance approves the Rail-B cutover plan for Saturday 17 October, on these conditions:

1. **PAY-155** (rail_router flag propagation) is deployed to production before the go/no-go call.
   If it is not, add a manual payment-worker restart after every `rail_router` change, and measure
   how long the flag takes to reach every worker during Thursday's rehearsal.
2. **Prefunding:** Rail-B holds at least SGD 2.5 million at 16:00 SGT on Friday. It is at
   SGD 2.5 million now, after last Friday's SGD 600k top-up.
3. **PAY-142:** if the 6 remaining items (SGD 41,870.20) are still open on Thursday, I will
   risk-accept them, capped at SGD 50,000, with the CFO's sign-off recorded in the go/no-go minutes.

You can send the customer-support change notice today. Support should use macro PAY-CUTOVER-01.
Ravi Kumar is primary on call for the window and Alex Tan is secondary.

Thanks,
John

---

## Timeline

- **2026-10-12** | Email — Finance approval sent with three conditions; CFO kept on bcc for the record.
