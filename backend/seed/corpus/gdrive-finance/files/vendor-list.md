---
title: Approved Vendor List — Payments and Operations
type: spreadsheet
slug: files/vendor-list
source_kind: gdrive
external_object_id: "1VendorListExampleHarbor"
provider_version: "57"
version_order: 57
provider_modified_at: "2026-10-03T05:10:00Z"
classification: internal
owner: jordan.lim
evidence_class: standard
permission_version: "pv-2026-10-03-1"
permissions:
  kind: gdrive
  file_id: "1VendorListExampleHarbor"
  parent_ids: ["0FinanceSharedDrive"]
  acl:
    - { type: domain, role: reader, email_or_domain: example-harbor.com, inherited: true }
    - { type: user, role: owner, email_or_domain: jordan.lim@example-harbor.com, inherited: false }
grants: []
tags: [vendors, payments, operations, rail-a, rail-b]
---
The approved vendor list for payments and operations. Everyone at Example Harbor Finance can view
it; Finance Ops maintains it. All vendor names below are fictional.

| Vendor                 | Service                         | Contract ends | Support SLA                 |
| ---------------------- | ------------------------------- | ------------- | --------------------------- |
| Orionix Clearing       | Rail-A, primary payment rail    | 2027-06-30    | SEV-1 response in 15 min    |
| Vegaline Settlement    | Rail-B, secondary payment rail  | 2028-05-31    | SEV-1 response in 20 min    |
| Cobalt Identity Checks | KYC document verification       | 2027-01-31    | 99.5% monthly availability  |
| Larkspur Cloud Hosting | Primary cloud region            | 2027-12-31    | 99.95% monthly availability |
| Tern Card Processing   | Card issuing and authorisations | 2027-09-30    | SEV-1 response in 30 min    |

## Notes

- **Orionix Clearing:** escalation goes through the Orionix operations desk rota; incidents are
  declared on its status page. Settlement files arrive nightly.
- **Vegaline Settlement:** contract signed on 20 May 2026. Settlement notification files arrive
  every 30 minutes. Rail-B cutover is planned for 17 October 2026.
- New vendors need a Finance Ops due-diligence pack and a Compliance review before the first
  payment. Vendors handling customer data also need a security questionnaire.
- Review this list every quarter. The next review is due in January 2027.

---

## Timeline

- **2026-05-20** | Google Drive — Vegaline Settlement added after contract signature.
- **2026-08-12** | Google Drive — Larkspur Cloud Hosting availability SLA corrected to 99.95%.
- **2026-10-03** | Google Drive — Quarterly review completed; no vendors removed.
