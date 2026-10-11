# Demo corpus — Example Harbor Finance

Last updated: 2026-10-12

A small, fully synthetic "company brain" for the five demo scenarios. Every person, company,
vendor, amount and identifier here is invented. `make seed` (`app/seed.py`, idempotent) loads it:
principals and groups from `../principals.yaml`, freshness policies from `../policies.yaml`, then
each source directory below through the **`gbrain_import`** connector (`sources_add` →
`connector_sync(trigger_kind=reconcile)` → inline `ingest_page` with mock embeddings → audit
`seed.loaded`).

This README is documentation only. The importer must skip it (it is not inside a source directory).

## Layout

```text
corpus/
├── <source-id>/
│   ├── source.yaml          # {id, name, kind, description}
│   └── **/*.md              # one page per file, any depth
```

| Source id        | kind         | Pages                                                                                            |
| ---------------- | ------------ | ------------------------------------------------------------------------------------------------ |
| `confluence-ops` | `confluence` | `policies/expense-policy`, `runbooks/payment-rail-failover`, `runbooks/kyc-refresh`              |
| `jira-payments`  | `jira`       | `issues/pay-142`, `issues/pay-150`                                                               |
| `slack-ops`      | `slack`      | `channels/treasury-ops/2026-10-09`, `channels/general/2026-10-10`, `channels/general/2026-10-11` |
| `gdrive-finance` | `gdrive`     | `files/board-deck-q3`, `files/vendor-list`                                                       |
| `email-ops`      | `email`      | `messages/2026-10-10-vendor-cutover`                                                             |
| `uploads`        | `upload`     | none (filled by uploads, `put_page` and `capture`)                                               |

`source.yaml.kind` ∈ `confluence | jira | slack | gdrive | email | upload` (the access_control
`SourceKind` vocabulary). The freshness lib calls Google Drive `google_drive`; the app maps
`gdrive` → `google_drive` when it picks a freshness policy or writes freshness rows.

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

| Field                  | Type / values                                      | Notes                                                               |
| ---------------------- | -------------------------------------------------- | ------------------------------------------------------------------- |
| `title`                | string                                             | required                                                            |
| `type`                 | free text                                          | gbrain page `type` (`policy`, `runbook`, `issue`, `daily_log`, …)   |
| `slug`                 | string, optional                                   | default: path relative to the source dir, without `.md`             |
| `source_kind`          | must equal `source.yaml` `kind`                    | also equals `permissions.kind`                                      |
| `external_object_id`   | string                                             | provider id, unique within the source                               |
| `provider_version`     | string                                             | opaque provider revision                                            |
| `version_order`        | int, optional                                      | makes versions comparable (`older/same/newer`)                      |
| `provider_modified_at` | ISO-8601 UTC string                                | quoted so YAML does not parse it into a datetime                    |
| `classification`       | `public \| internal \| confidential \| restricted` | `confidential`/`restricted` need an explicit grant or ownership     |
| `owner`                | principal id or `null`                             | becomes `pages.owner_principal_id`                                  |
| `evidence_class`       | `critical \| standard`                             | critical evidence is live-verified at query time                    |
| `permission_version`   | string                                             | stamped on every access decision                                    |
| `permissions`          | object, shape depends on `kind` (below)            | stored raw in `source_permissions.raw`, never flattened             |
| `grants`               | list of `{subject_type, subject_id, effect}`       | `subject_type: principal \| group \| role`, `effect: allow \| deny` |
| `tags`                 | list of strings                                    | becomes `tags` rows                                                 |
| `simulate`             | object, optional, **demo only**                    | see "Simulated drift"                                               |

Seeded grants are written with `granted_by: system:seed`, `scope: read`.

### `permissions` shapes (field names are exact)

- **confluence:** `{kind, space_key, page_id, space_view_users[], space_view_groups[], page_view_users[], page_view_groups[], ancestors[]}`. Empty page lists mean "inherit the space".
- **jira:** `{kind, project_key, issue_key, project_roles: {RoleName: [member ids]}, browse_roles: [RoleName], issue_security_level: str|null, security_level_members: []}`
- **slack:** `{kind, workspace_id, channel_id, channel_type: public|private|dm|mpdm, member_ids: [], workspace_member_ids: []|null}`
- **gdrive:** `{kind, file_id, parent_ids: [], acl: [{type: user|group|domain|anyone, role: owner|organizer|writer|commenter|reader, email_or_domain: str|null, inherited: bool}]}`
- **email:** `{kind, message_id, from_, to: [], cc: [], bcc: []}`
- **upload:** `{kind, owner_principal_id, shared_with_principals: [], shared_with_groups: []}`

Membership is matched against the principal's `external_identities[kind]` (Slack member ids such as
`U_PRIYA`; Jira and Confluence account ids equal principal ids; Drive and email use the mailbox
address, and a Drive `domain` entry matches the address's domain) and against group ids (a Drive
`group` entry's `email_or_domain` is the group id, e.g. `leadership`).

### Simulated drift (`simulate`, demo only)

Honoured only by the `gbrain_import` connector:

- `live_version`: what `head()` reports as the provider's current version. If it differs from
  `provider_version`, live verification returns `stale`.
- `deleted`: `head()` reports the object as deleted (tombstone path).
- `indexed_at`: the importer stamps this as the object's `indexed_at`/`searchable_at` instead of
  "now", simulating an index that is older than the provider's latest change.

## Scenario map

| Scenario                        | Personas                   | Pages that make it work                                                                                                      |
| ------------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1. Unified cited query          | `priya.nair`               | Rail-B cutover facts spread across the email, PAY-150, `#general`, `#treasury-ops` and the vendor list                       |
| 2. Bounded freshness            | `priya.nair`, `alex.tan`   | `runbooks/payment-rail-failover` (critical, v7 indexed, live v8 → stale → omitted); `runbooks/kyc-refresh` (critical, fresh) |
| 3. Negative permission, no leak | `mei.chen`, `alex.tan`     | `mei.chen` matches nothing; `alex.tan` is outside PAY-142's `finance-only` security level, `#treasury-ops` and the KYC page  |
| 4. Live revocation              | `priya.nair`, `root.admin` | `files/board-deck-q3` is confidential and visible to `priya.nair` only through the `leadership` grant, which is revoked live |
| 5. Audit reconstruction         | `sam.lee` (auditor)        | any `ask` above; `GET /api/audit/events/{id}` and `/api/audit/verify`                                                        |
| Injection screening (bonus)     | anyone in `#general`       | `channels/general/2026-10-11` contains a prompt-injection string that the sanitizer must quarantine                          |

Distinctive facts to ask about: "What is the payment rail failover procedure?" (runbook: 90-second
trigger, `RAIL_B_ONLY`, SGD 2.5 million prefunding, 16:00 SGT batch hold) and "What were the Q3 board
deck revenue figures?" (SGD 48.6 million, up 18% year on year; EBITDA SGD 9.8 million).

The board deck's Drive owner is `admin@example-harbor.com`, not Priya, and its frontmatter `owner`
is `root.admin`: if Priya owned it, rule R3 (owner → allow) would keep her access after the grant
is revoked and scenario 4 could not be shown.
