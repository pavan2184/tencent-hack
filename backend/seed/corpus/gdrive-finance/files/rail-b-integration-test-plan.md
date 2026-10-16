---
title: Rail-B integration test plan (Vegaline)
type: document
slug: files/rail-b-integration-test-plan
source_kind: gdrive
external_object_id: "1RailBTestPlanExampleHarbor"
provider_version: "61"
version_order: 61
provider_modified_at: "2026-10-11T08:00:00Z"
classification: internal
owner: alex.tan
evidence_class: standard
permission_version: "pv-2026-10-11-1"
# Shared outside the company with the integration contractor's own address, until 31 December.
permissions:
  kind: gdrive
  file_id: "1RailBTestPlanExampleHarbor"
  parent_ids: ["0EngineeringSharedDrive"]
  acl:
    - {
        type: user,
        role: owner,
        email_or_domain: alex.tan@example-harbor.com,
        inherited: false,
      }
    - {
        type: group,
        role: writer,
        email_or_domain: engineering,
        inherited: true,
      }
    - {
        type: group,
        role: reader,
        email_or_domain: finance-ops,
        inherited: false,
      }
    - type: user
      role: commenter
      email_or_domain: mei.chen@contractor-example.com
      inherited: false
      expiration_time: "2026-12-31T15:59:59Z"
grants: []
tags: [rail-b, vegaline, testing, cutover, engineering]
---

How we test the Rail-B integration with Vegaline Settlement before the production cutover. Mei Chen
(integration contractor) replays Vegaline's sandbox files; engineering owns the results.

## Scope

- Parsing Vegaline's ISO 20022 `camt.054` notification files (PAY-150).
- Matching every entry to the ledger by end-to-end transaction id.
- Dropping and logging duplicate entries.
- The late-file warning after 45 minutes without a file.
- Rollback to `BALANCED` routing with Rail-A as primary.

## Test cases

| Id    | Case                                                 | Pass when                                |
| ----- | ---------------------------------------------------- | ---------------------------------------- |
| TC-01 | Full sandbox day, 48 files                           | 0 reconciliation exceptions              |
| TC-02 | Partial file followed by a complete resend           | No entry is posted twice                 |
| TC-03 | Duplicate end-to-end id inside one file              | Second entry dropped and logged          |
| TC-04 | No file for 45 minutes during business hours         | Warning raised in #treasury-ops          |
| TC-05 | Malformed XML                                        | File rejected whole, alert raised        |
| TC-06 | `rail_router` change during traffic                  | All workers on the new route within 30 s |
| TC-07 | Rollback to `BALANCED`                               | Completed within 10 minutes              |
| TC-08 | 40% of a normal Saturday's volume replayed on Rail-B | p95 acknowledgement under 20 seconds     |

## Rehearsal

Thursday 15 October 2026, 14:00 SGT, in staging. Exit criteria: TC-01 to TC-08 pass, and rollback
is rehearsed end to end in under 10 minutes.

---

## Timeline

- **2026-10-05** | Google Drive — Plan drafted by Alex Tan; shared with Mei Chen as commenter until 31 December.
- **2026-10-11** | Google Drive — TC-06 added for the flag-propagation fix (PAY-155).
