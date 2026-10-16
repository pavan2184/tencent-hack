# Demo corpus — Example Harbor Finance

Last updated: 2026-10-16

A small, fully synthetic "company brain" for the five demo scenarios and for every access and
freshness rule the pipeline enforces. Every person, company, vendor, amount and identifier here is
invented. `make seed` (`app/seed.py`, idempotent) loads it: principals and groups from
`../principals.yaml`, freshness policies from `../policies.yaml`, then each source directory below
through the **`gbrain_import`** connector (`sources_add` →
`connector_sync(trigger_kind=reconcile)` → inline `ingest_page` with mock embeddings → audit
`seed.loaded`).

Size: **10 personas** (9 active), 4 groups, 16 freshness policies, **7 sources** and **24 pages**,
with 5 seeded grants. The story is frozen at **12 October 2026, 17:00 SGT** (the test clock,
`FIXED_NOW`): the Rail-B cutover is set for Saturday 17 October and Finance approved it that
morning.

This README is documentation only. The importer must skip it (it is not inside a source directory).

## Layout

```text
corpus/
├── <source-id>/
│   ├── source.yaml          # {id, name, kind, description}
│   └── **/*.md              # one page per file, any depth
```

| Source id               | kind         | Pages                                                                                                                                                                                                              |
| ----------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `confluence-ops`        | `confluence` | `policies/expense-policy`, `runbooks/payment-rail-failover`, `runbooks/kyc-refresh`, `runbooks/rail-a-escalation-contacts-2025`, `incidents/2026-09-14-rail-a-sev2-review`, `treasury/liquidity-prefunding-policy` |
| `confluence-compliance` | `confluence` | `policies/transaction-monitoring-standard`, `registers/str-register-q3-2026`                                                                                                                                       |
| `jira-payments`         | `jira`       | `issues/pay-142`, `issues/pay-150`, `issues/pay-155`                                                                                                                                                               |
| `slack-ops`             | `slack`      | `channels/treasury-ops/2026-10-09`, `channels/general/2026-10-10`, `channels/general/2026-10-11`, `channels/payments-eng/2026-10-11`, `dms/john-daniel/2026-10-11`                                                 |
| `gdrive-finance`        | `gdrive`     | `files/board-deck-q3`, `files/vendor-list`, `files/orionix-renewal-brief`, `files/rail-b-integration-test-plan`, `files/vegaline-due-diligence`, `files/rail-b-support-faq`                                        |
| `email-ops`             | `email`      | `messages/2026-10-10-vendor-cutover`, `messages/2026-10-12-cutover-approval`                                                                                                                                       |
| `uploads`               | `upload`     | none (filled by uploads, `put_page` and `capture`)                                                                                                                                                                 |

`source.yaml.kind` ∈ `confluence | jira | slack | gdrive | email | upload` (the access_control
`SourceKind` vocabulary). The freshness lib's `ConnectorKind` accepts `gdrive` as an input alias
and always emits `google_drive`, which is what freshness tables and `policies.yaml` store.

## Personas

| Id             | Role in the story                   | Roles               | Groups                  | Anchors                                                   |
| -------------- | ----------------------------------- | ------------------- | ----------------------- | --------------------------------------------------------- |
| `alex.tan`     | Payments engineer                   | employee            | engineering             | scenario 2; engineering group grant on the Orionix brief  |
| `ravi.kumar`   | Payments SRE, cutover on-call       | employee            | engineering             | ethical wall: explicit deny on the Orionix brief (R2)     |
| `john.tan`     | Finance Ops manager                 | employee, manager   | finance-ops, leadership | scenarios 1, 2 and 4; sees 23 of 24 pages                 |
| `jordan.lim`   | Treasury analyst                    | employee            | finance-ops             | private `#treasury-ops`, finance-only Jira security level |
| `daniel.wong`  | CFO                                 | employee, manager   | leadership              | DM with John; bcc on the cutover approval                 |
| `nora.ibrahim` | Head of Compliance (MLRO)           | employee, manager   | compliance              | owns the restricted STR register (R3)                     |
| `sam.lee`      | Internal auditor                    | employee, auditor   | compliance              | scenario 5; STR register through a role grant (R5)        |
| `root.admin`   | Administrator                       | admin               | —                       | revokes grants; admin is not a source-access bypass       |
| `mei.chen`     | Vegaline integration contractor     | contractor          | —                       | scenario 3; one live Drive share, one expired             |
| `lena.koh`     | Treasury analyst who left on 30 Sep | employee (inactive) | finance-ops             | R1: still on a Slack roster, denied everything            |

`lena.koh` is inactive, so `/api/principals`, the persona switcher and the access map hide the
account, and an `X-Actor-Id: lena.koh` request gets `401 unknown_actor`.

## Page format (gbrain two-layer page)

A page is Markdown with YAML frontmatter. The body is the **compiled truth**, then a line that is
exactly `---`, then `## Timeline` with append-only entries:

```markdown
---
<frontmatter, see below>
---

Compiled truth: the current best statement of what this document says (markdown).

---

## Timeline

- **2026-10-01** | Confluence — v7: added the 16:00 SGT batch-hold step.
```

Timeline entry regex: `^- \*\*(\d{4}-\d{2}-\d{2})\*\* \| (.+?) — (.+)$` → `date`, `source`,
`summary` (the separator before the summary is an em dash `—`). Each entry becomes a
`timeline_entries` row; the raw section is stored in `pages.timeline`.

## Frontmatter schema

| Field                  | Type / values                                         | Notes                                                               |
| ---------------------- | ----------------------------------------------------- | ------------------------------------------------------------------- |
| `title`                | string                                                | required                                                            |
| `type`                 | free text                                             | gbrain page `type` (`policy`, `runbook`, `issue`, `daily_log`, …)   |
| `slug`                 | string, optional                                      | default: path relative to the source dir, without `.md`             |
| `source_kind`          | must equal `source.yaml` `kind`                       | also equals `permissions.kind`                                      |
| `external_object_id`   | string                                                | provider id, unique within the source                               |
| `provider_version`     | string                                                | opaque provider revision                                            |
| `version_order`        | int, optional                                         | makes versions comparable (`older/same/newer`)                      |
| `provider_modified_at` | ISO-8601 UTC string                                   | quoted so YAML does not parse it into a datetime                    |
| `classification`       | `public \| internal \| confidential \| restricted`    | `confidential`/`restricted` need an explicit grant or ownership     |
| `owner`                | principal id or `null`                                | becomes `pages.owner_principal_id`                                  |
| `evidence_class`       | `critical \| standard`                                | critical evidence is live-verified at query time                    |
| `permission_version`   | string                                                | stamped on every access decision                                    |
| `permissions`          | object, shape depends on `kind` (below)               | stored raw in `source_permissions.raw`, never flattened             |
| `grants`               | list of `{subject_type, subject_id, effect, reason?}` | `subject_type: principal \| group \| role`, `effect: allow \| deny` |
| `tags`                 | list of strings                                       | becomes `tags` rows                                                 |
| `simulate`             | object, optional, **demo only**                       | see "Simulated drift"                                               |

Seeded grants are written with `granted_by: system:seed`, `scope: read`. YAML comments in the
frontmatter are ignored; several pages use them to say which story the ACL is there for.

### `permissions` shapes (field names are exact)

- **confluence:** `{kind, space_key, page_id, space_view_users[], space_view_groups[], page_view_users[], page_view_groups[], ancestors: [{page_id, view_users[], view_groups[]}]}`. Empty page lists mean "inherit the space"; every ancestor with a non-empty restriction must also admit the reader.
- **jira:** `{kind, project_key, issue_key, project_roles: {RoleName: [member ids]}, browse_roles: [RoleName], issue_security_level: str|null, security_level_members: []}`
- **slack:** `{kind, workspace_id, channel_id, channel_type: public|private|dm|mpdm, member_ids: [], workspace_member_ids: []|null}`. The workspace roster lists employees only (no guests, no deactivated accounts).
- **gdrive:** `{kind, file_id, parent_ids: [], acl: [{type: user|group|domain|anyone, role: owner|organizer|writer|commenter|reader, email_or_domain: str|null, inherited: bool, expiration_time?: ISO-8601, deleted?: bool, allow_file_discovery?: bool}]}`. An expired or deleted entry grants nothing; a `domain`/`anyone` entry with `allow_file_discovery: false` is a link-only share and grants nothing to search.
- **email:** `{kind, message_id, from_, to: [], cc: [], bcc: []}`
- **upload:** `{kind, owner_principal_id, shared_with_principals: [], shared_with_groups: []}`

Membership is matched against the principal's `external_identities[kind]` (Slack member ids such as
`U_JOHN`; Jira and Confluence account ids equal principal ids; Drive and email use the mailbox
address, and a Drive `domain` entry matches the address's domain) and against group ids (a Drive
`group` entry's `email_or_domain` is the group id, e.g. `leadership`).

### Simulated drift (`simulate`, demo only)

Honoured only by the `gbrain_import` connector:

- `live_version`: what `head()` reports as the provider's current version. If it differs from
  `provider_version`, live verification returns `stale` (`provider_newer`).
- `deleted`: `head()` reports the object as deleted. Live verification returns `stale`
  (`provider_deleted`); the page is not tombstoned by the seed. Only **critical** evidence is
  then omitted: standard evidence that is stale is used with a warning
  (`failure_action: allow_with_warning`). That is why the deleted page here is critical.
- `indexed_at`: the importer stamps this as the object's `indexed_at`/`searchable_at` instead of
  "now", simulating an index that is older than the provider's latest change.

### Editing the corpus

A re-sync of an unchanged `provider_version` is a no-op (`same_version_already_applied`), even when
the frontmatter `permissions` changed. When you change a page, **including an ACL-only change**,
bump `provider_version` and `version_order` (and set a new `permission_version`), or `make seed`
on an existing stack keeps the old copy. A fresh database (`make reset && make seed`) always
loads the files as they are.

## Scenario map

| Scenario                        | Personas                 | Pages that make it work                                                                                                                                      |
| ------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1. Unified cited query          | `john.tan`               | Rail-B cutover facts across both emails, PAY-150, PAY-155, `#general`, `#treasury-ops`, the vendor list and the liquidity policy                             |
| 2. Bounded freshness            | `john.tan`, `alex.tan`   | `runbooks/payment-rail-failover` (critical, v7 indexed, live v8 → stale → omitted); `runbooks/kyc-refresh` (critical, fresh); see also the freshness stories |
| 3. Negative permission, no leak | `mei.chen`, `alex.tan`   | `mei.chen` sees only `files/rail-b-integration-test-plan`; `alex.tan` is outside PAY-142's `finance-only` level, `#treasury-ops` and the KYC page            |
| 4. Live revocation              | `john.tan`, `root.admin` | `files/board-deck-q3` is confidential and visible to `john.tan` only through the `leadership` grant, which is revoked live                                   |
| 5. Audit reconstruction         | `sam.lee` (auditor)      | any `ask` above; `GET /api/audit/events/{id}` and `/api/audit/verify`                                                                                        |
| Injection screening (bonus)     | anyone in `#general`     | `channels/general/2026-10-11` contains a prompt-injection string that the sanitizer must quarantine                                                          |

## Access stories

One page per rule or platform nuance. `examples/revocation_demo.py` in the access_control library
reports each one as `access_stories`, and `app/tests/test_seed_stories.py` proves them over REST.

| Story                                | Page                                   | Who                                   | Outcome and rule                                                                                                                      |
| ------------------------------------ | -------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Inactive account                     | `channels/treasury-ops/2026-10-09`     | `lena.koh` (still on the roster)      | deny, `R1:inactive_principal`, before any source ACL is read                                                                          |
| Ethical wall                         | `files/orionix-renewal-brief`          | `ravi.kumar` vs `alex.tan`            | Ravi deny `R2:explicit_deny`; Alex allow `R5` through the same engineering group grant                                                |
| Restricted page, owner or role grant | `registers/str-register-q3-2026`       | `nora.ibrahim`, `sam.lee`, `john.tan` | Nora `R3:owner`; Sam `R5` via the `auditor` role; John denied by the page restriction. Revoke the role grant and Sam is denied (`R6`) |
| Inherited Confluence restriction     | `treasury/liquidity-prefunding-policy` | `alex.tan`                            | deny `R8:confluence`: the space admits engineering, the parent Treasury page does not                                                 |
| Expired Drive share                  | `files/vegaline-due-diligence`         | `mei.chen`                            | deny `R8:gdrive`: the contractor share expired on 30 September                                                                        |
| Live external Drive share            | `files/rail-b-integration-test-plan`   | `mei.chen`                            | allow `R8:gdrive` until 31 December                                                                                                   |
| Link-only Drive share                | `files/rail-b-support-faq`             | `alex.tan`                            | deny `R8:gdrive`: "anyone with the link" with discovery off is not searchable                                                         |
| Direct message                       | `dms/john-daniel/2026-10-11`           | `jordan.lim`, `root.admin`            | deny `R8:slack`: only the two members read a DM                                                                                       |
| Public channel via roster            | `channels/payments-eng/2026-10-11`     | `sam.lee` (not a member)              | allow `R8:slack` through the workspace roster; guests and leavers are not on it                                                       |
| Email bcc                            | `messages/2026-10-12-cutover-approval` | `daniel.wong`                         | allow `R8:email` as a bcc recipient; `alex.tan` is not a party                                                                        |
| Admin is not a bypass                | any Slack page, `files/vendor-list`    | `root.admin`                          | no Slack identity, so every Slack page is denied; the vendor list is allowed `R4` inside the Drive domain share                       |
| Confidential needs a grant           | `files/board-deck-q3` after revocation | `john.tan`                            | deny `R7:confidential` (`grant_revoked`) once the leadership grant is revoked                                                         |

## Freshness stories

| Page                                       | Class    | Simulated drift       | At query time                                                          |
| ------------------------------------------ | -------- | --------------------- | ---------------------------------------------------------------------- |
| `runbooks/payment-rail-failover`           | critical | live v8, indexed v7   | `stale`, omitted                                                       |
| `runbooks/kyc-refresh`                     | critical | none                  | live-verified `fresh`, cited                                           |
| `incidents/2026-09-14-rail-a-sev2-review`  | standard | live v5, indexed v4   | `stale` but used with a warning (same drift, different class)          |
| `runbooks/rail-a-escalation-contacts-2025` | critical | deleted in Confluence | `stale` (`provider_deleted`), omitted; the vendor list answers instead |

## Visibility matrix

The rule that allows each persona to read each page under policy `ac-v2`, before any revocation.
Blank means denied. `lena.koh` (inactive) is denied everything. Generated from the real policy
over these files; `libs/access_control/tests/test_seed_demo.py` pins it.

| Page                                                               | Alex | Ravi | John | Jordan | Daniel | Nora | Sam | Admin | Mei |
| ------------------------------------------------------------------ | ---- | ---- | ---- | ------ | ------ | ---- | --- | ----- | --- |
| `confluence-compliance` `policies/transaction-monitoring-standard` |      |      | R8   | R8     |        | R3   | R8  |       |     |
| `confluence-compliance` `registers/str-register-q3-2026`           |      |      |      |        |        | R3   | R5  |       |     |
| `confluence-ops` `incidents/2026-09-14-rail-a-sev2-review`         | R8   | R3   | R8   | R8     |        |      |     |       |     |
| `confluence-ops` `policies/expense-policy`                         | R8   | R8   | R3   | R8     |        |      |     |       |     |
| `confluence-ops` `runbooks/kyc-refresh`                            |      |      | R3   | R8     |        |      |     |       |     |
| `confluence-ops` `runbooks/payment-rail-failover`                  | R3   | R8   | R8   | R8     |        |      |     |       |     |
| `confluence-ops` `runbooks/rail-a-escalation-contacts-2025`        | R3   | R8   | R8   | R8     |        |      |     |       |     |
| `confluence-ops` `treasury/liquidity-prefunding-policy`            |      |      | R8   | R3     |        |      |     |       |     |
| `email-ops` `messages/2026-10-10-vendor-cutover`                   |      |      | R8   | R8     |        |      |     |       |     |
| `email-ops` `messages/2026-10-12-cutover-approval`                 |      |      | R8   | R8     | R8     |      |     |       |     |
| `gdrive-finance` `files/board-deck-q3`                             |      |      | R5   |        | R5     |      |     | R3    |     |
| `gdrive-finance` `files/orionix-renewal-brief`                     | R5   |      | R5   |        | R3     |      |     |       |     |
| `gdrive-finance` `files/rail-b-integration-test-plan`              | R3   | R8   | R8   | R8     |        |      |     |       | R8  |
| `gdrive-finance` `files/rail-b-support-faq`                        |      |      | R3   | R8     |        |      |     |       |     |
| `gdrive-finance` `files/vegaline-due-diligence`                    |      |      | R8   | R3     |        | R8   | R8  |       |     |
| `gdrive-finance` `files/vendor-list`                               | R8   | R8   | R8   | R3     | R8     | R8   | R8  | R4    |     |
| `jira-payments` `issues/pay-142`                                   |      |      | R8   | R3     |        |      |     |       |     |
| `jira-payments` `issues/pay-150`                                   | R3   | R8   | R8   | R8     |        |      |     |       |     |
| `jira-payments` `issues/pay-155`                                   | R8   | R3   | R8   | R8     |        |      |     |       |     |
| `slack-ops` `channels/general/2026-10-10`                          | R8   | R8   | R8   | R8     | R8     | R8   | R8  |       |     |
| `slack-ops` `channels/general/2026-10-11`                          | R8   | R8   | R8   | R8     | R8     | R8   | R8  |       |     |
| `slack-ops` `channels/payments-eng/2026-10-11`                     | R8   | R8   | R8   | R8     | R8     | R8   | R8  |       |     |
| `slack-ops` `channels/treasury-ops/2026-10-09`                     |      |      | R8   | R8     |        |      |     |       |     |
| `slack-ops` `dms/john-daniel/2026-10-11`                           |      |      | R8   |        | R8     |      |     |       |     |
| **Visible pages**                                                  | 12   | 11   | 23   | 20     | 8      | 7    | 7   | 2     | 1   |

## Questions to ask

| Ask as        | Question                                                               | What it shows                                                                |
| ------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `john.tan`    | What is the plan for the Rail-B cutover?                               | answer drawn from emails, Jira, Slack and Drive (scenario 1)                 |
| `john.tan`    | What is the payment rail failover procedure and the KYC refresh cycle? | stale critical runbook omitted, fresh KYC runbook cited (scenario 2)         |
| `john.tan`    | What were the Q3 board deck revenue figures?                           | SGD 48.6 million; ask again after revoking the leadership grant (scenario 4) |
| `mei.chen`    | What were the Q3 board deck revenue figures?                           | abstains, with no hint that the deck exists (scenario 3)                     |
| `mei.chen`    | What is the Rail-B rehearsal plan?                                     | answered from the one shared test plan                                       |
| `ravi.kumar`  | What is our negotiating position for the Orionix renewal?              | the brief is walled off for Ravi; `alex.tan` is answered from it             |
| `daniel.wong` | Did Finance approve the Rail-B cutover and on what conditions?         | three conditions, read through the bcc and the DM                            |
| `sam.lee`     | How many STRs were filed in Q3?                                        | 14, from the restricted register; `john.tan` cannot see it                   |
| `alex.tan`    | Who do we escalate Rail-A incidents to?                                | the deleted 2025 contacts page is omitted                                    |
| `alex.tan`    | What happened in the September Rail-A SEV-2 incident?                  | the incident review is cited with a staleness warning                        |

The facts line up across sources: Rail-B prefunding minimum SGD 2.5 million, the 16:00 SGT batch
hold, the `rail_router` flag taking about 4 minutes (fixed by PAY-155), PAY-142's 6 open items
worth SGD 41,870.20 with a SGD 50,000 risk-acceptance cap, and the cutover window on Saturday
17 October, 02:00 to 04:00 SGT.

The board deck's Drive owner is `admin@example-harbor.com`, not John, and its frontmatter `owner`
is `root.admin`: if John owned it, rule R3 (owner → allow) would keep that access after the grant
is revoked and scenario 4 could not be shown.
