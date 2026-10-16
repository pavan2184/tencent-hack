---
title: Orionix Clearing contract renewal — negotiation brief
type: document
slug: files/orionix-renewal-brief
source_kind: gdrive
external_object_id: "1OrionixRenewalBriefExampleHarbor"
provider_version: "38"
version_order: 38
provider_modified_at: "2026-10-08T09:30:00Z"
classification: confidential
owner: daniel.wong
evidence_class: standard
permission_version: "pv-2026-10-08-1"
permissions:
  kind: gdrive
  file_id: "1OrionixRenewalBriefExampleHarbor"
  parent_ids: ["0FinanceSharedDrive", "1VendorContracts"]
  acl:
    - {
        type: user,
        role: owner,
        email_or_domain: daniel.wong@example-harbor.com,
        inherited: false,
      }
    - {
        type: group,
        role: reader,
        email_or_domain: leadership,
        inherited: false,
      }
    - {
        type: group,
        role: commenter,
        email_or_domain: engineering,
        inherited: false,
      }
# Ethical wall: engineering is granted for the SLA evidence, but one engineer declared a conflict of
# interest with Orionix. The explicit deny (rule R2) wins over the group allow.
grants:
  - {
      subject_type: group,
      subject_id: leadership,
      effect: allow,
      reason: Negotiation team,
    }
  - subject_type: group
    subject_id: engineering
    effect: allow
    reason: Technical SLA evidence for the renewal
  - subject_type: principal
    subject_id: ravi.kumar
    effect: deny
    reason: Declared conflict of interest COI-2026-031 (ethical wall for the Orionix renewal)
tags: [vendors, orionix, rail-a, contract, negotiation, confidential]
---

Negotiating position for renewing the Rail-A contract with Orionix Clearing, which ends on
30 June 2027. Confidential. One engineer has declared a conflict of interest and is walled off
from this document; do not forward it.

## Where we stand

- Two Orionix-caused SEV-2 incidents this year, on 3 August and 14 September. Both were handled by
  failing over to Rail-B. The 14 September incident came from an unannounced certificate rotation.
- After the Rail-B cutover, Orionix's share of our outbound volume falls from 100% to 60%.
- Current price: **SGD 0.21 per credit transfer**, with no service credits for incidents.

## Our asks

1. **Service credits:** 10% of the monthly fee for each SEV-2 caused by Orionix.
2. **Change notice:** 10 business days' notice of gateway or certificate changes.
3. **Price:** SGD 0.17 per transfer at a 60% volume share.
4. **Term:** 3 years, with a break clause after 18 months.

## Walk-away points

- No minimum-volume commitment above 50% of our outbound payments.
- No exclusivity, and no fee for routing traffic to Rail-B during an incident.

## Plan

Open talks in November 2026 and aim to sign by 31 March 2027. Daniel Wong leads; engineering
provides the incident and latency evidence.

---

## Timeline

- **2026-09-29** | Google Drive — Brief created by Daniel Wong.
- **2026-10-05** | Google Drive — Ethical wall added after a conflict-of-interest declaration.
- **2026-10-08** | Google Drive — Engineering SLA evidence added; version 38.
