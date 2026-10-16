---
title: Vegaline Settlement — vendor due-diligence summary
type: document
slug: files/vegaline-due-diligence
source_kind: gdrive
external_object_id: "1VegalineDueDiligenceExampleHarbor"
provider_version: "24"
version_order: 24
provider_modified_at: "2026-05-18T06:00:00Z"
classification: internal
owner: jordan.lim
evidence_class: standard
permission_version: "pv-2026-05-18-1"
# The contractor's share was time-boxed to the onboarding questionnaire and expired on 30 September.
# An expired Drive permission grants nothing, even though it is still listed on the file.
permissions:
  kind: gdrive
  file_id: "1VegalineDueDiligenceExampleHarbor"
  parent_ids: ["0FinanceSharedDrive", "1VendorContracts"]
  acl:
    - {
        type: user,
        role: owner,
        email_or_domain: jordan.lim@example-harbor.com,
        inherited: false,
      }
    - {
        type: group,
        role: reader,
        email_or_domain: finance-ops,
        inherited: false,
      }
    - {
        type: group,
        role: reader,
        email_or_domain: compliance,
        inherited: false,
      }
    - type: user
      role: commenter
      email_or_domain: mei.chen@contractor-example.com
      inherited: false
      expiration_time: "2026-09-30T15:59:59Z"
grants: []
tags: [vendors, vegaline, rail-b, due-diligence, compliance]
---

Summary of the due diligence completed on Vegaline Settlement before the Rail-B contract was signed
on 20 May 2026. Finance Ops prepared it and Compliance approved it on 18 May 2026.

## Findings

- **Licensing:** holds the payments licence required in its home market, checked against the
  regulator's public register on 12 May 2026.
- **Financials:** three years of audited accounts, all with unqualified opinions.
- **Security:** SOC 2 Type II report for the period ending 31 March 2026 with no exceptions;
  external penetration test in January 2026 with no open high findings.
- **Resilience:** recovery time objective 4 hours, recovery point objective 15 minutes.
- **Data:** settlement files are stored in a Singapore cloud region; two sub-processors, both
  reviewed.
- **Sanctions:** owners and directors screened; no matches.

## Residual risk

**Medium.** Vegaline runs from a single pair of data centres. Mitigation: keep Rail-A as the
primary rail until the Q1 2027 review, and keep 60% of outbound volume on Rail-A after the cutover.

---

## Timeline

- **2026-05-12** | Google Drive — Due-diligence pack completed by Jordan Lim.
- **2026-05-18** | Google Drive — Approved by Compliance; residual risk rated medium.
