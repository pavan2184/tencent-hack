# access_control

Permission-aware retrieval for the Internal Brain. **Owner: Chai.** Migration range **0200–0299**.

Answers one question, purely and deterministically: _may this principal read this document right
now?_ The app asks it for every retrieval candidate **before** any evidence reaches an LLM, and a
denied document is indistinguishable from one that does not exist.

Pure Python 3.12, depends on `pydantic` only. **Never imports `app`** (enforced by
`tests/test_models.py::test_no_app_import`). The app implements the async store Protocols.

## Model

**Principals, roles, groups.** A `Principal` is the identity resolved at query time:
`id`, `display_name`, `email`, `roles` (e.g. `employee`, `manager`, `auditor`, `admin`,
`contractor`), `groups` (e.g. `finance-ops`, `leadership`), `external_identities`
(`{"slack": "U_JORDAN", …}` keyed by `SourceKind` value) and `is_active`. Grants target a
principal, a group or a role (`SubjectType`).

**Per-source raw semantics, preserved — never flattened.** Each document carries a
`SourcePermissions` snapshot whose `raw` is a discriminated union on `kind`, kept in the
platform's native shape and evaluated with that platform's own rules:

| `kind`         | Model                    | Read semantics (R8)                                                                                                                                                                                                                                                                                                                         |
| -------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `confluence`   | `ConfluencePermissions`  | Must hold **space** view (`space_view_users`/`space_view_groups`). If the page has view restrictions (`page_view_*` non-empty) they override the space audience by narrowing it — reader must also be listed. Restricted `ancestors` (`ConfluenceAncestor`) are inherited the same way; a bare ancestor id means "no restriction captured". |
| `jira`         | `JiraPermissions`        | Must hold a role in `browse_roles` (via `project_roles` membership, user or group). If `issue_security_level` is set, must also be in `security_level_members` (user or group).                                                                                                                                                             |
| `slack`        | `SlackPermissions`       | `public`: any workspace member (`workspace_member_ids` `None` ⇒ roster not captured ⇒ everyone). `private`/`dm`/`mpdm`: must be in `member_ids`.                                                                                                                                                                                            |
| `gdrive`       | `GDrivePermissions`      | Any ACE matches: `anyone`; `domain` = principal email domain; `user` = principal email; `group` = one of the principal's groups (case-insensitive). `acl` is the effective ACL incl. inherited folder entries.                                                                                                                              |
| `email`        | `EmailPermissions`       | Principal email is the sender or a `to`/`cc`/`bcc` recipient (case-insensitive, `Name <addr>` accepted). Field is `from_`; input may say `from`.                                                                                                                                                                                            |
| `upload`       | `UploadPermissions`      | Owner, or in `shared_with_principals`, or in a `shared_with_groups` group.                                                                                                                                                                                                                                                                  |
| `mcp_external` | `McpExternalPermissions` | In `allowed_principals` or an `allowed_groups` group.                                                                                                                                                                                                                                                                                       |

Platform identity = `external_identities[kind]` if present, else `principal.id`; for `gdrive` and
`email` the principal's `email` is also used. Unknown keys in a permissions block are rejected
(a misspelt _restriction_ must not be silently dropped — that would fail open); numeric ids are
coerced to strings. `SourceKind.gdrive` (not `google_drive`) matches the seed corpus. A
`gbrain_import` page carries the raw permissions of its original platform; R8 dispatches on
`raw.kind`, not on the document's `source_kind`.

Seed frontmatter parses verbatim, e.g.:

```yaml
permissions:
  {
    kind: confluence,
    space_key: OPS,
    page_id: "1042",
    space_view_users: [],
    space_view_groups: [finance-ops, engineering],
    page_view_users: [],
    page_view_groups: [],
    ancestors: [],
  }
permission_version: "3"
```

```python
SourcePermissions.from_raw(
    fm["permissions"],
    permission_version=str(fm["permission_version"]),
    captured_at=now,
    connector_run_id=run_id,
)  # kind inferred from raw
```

**Classification ladder** `public < internal < confidential < restricted`. Classification only
ever tightens: `public`/`internal` still need source membership; `confidential`/`restricted` need
ownership (R3) or an explicit allow grant (R5) — platform membership is not enough. Admins (R4)
are the only other exception.

## Rule order (`DefaultAccessPolicy`, `policy_version="ac-v1"`)

First match wins. Every `AccessDecision` stamps `matched_rule`, `permission_version` (document's,
else the snapshot's), `policy_version` and `evaluated_at = now`.

| Rule  | Condition                                                                            | Effect | Reason                          | `matched_rule`                   |
| ----- | ------------------------------------------------------------------------------------ | ------ | ------------------------------- | -------------------------------- |
| R1    | principal `is_active` is false                                                       | deny   | `policy_default`                | `R1:inactive_principal`          |
| R2    | unrevoked `deny` grant matching principal id, any of its groups, or any of its roles | deny   | `explicit_deny`                 | `R2:explicit_deny`               |
| R3    | `owner_principal_id == principal.id`                                                 | allow  | —                               | `R3:owner`                       |
| R4    | principal has role `admin`                                                           | allow  | —                               | `R4:admin`                       |
| R5    | unrevoked `allow` grant matching principal / group / role                            | allow  | —                               | `R5:explicit_grant`              |
| R6    | classification `restricted`                                                          | deny   | `classification_requires_grant` | `R6:restricted`                  |
| R7    | classification `confidential`                                                        | deny   | `classification_requires_grant` | `R7:confidential`                |
| R8    | snapshot present: raw platform membership (table above)                              | allow  | —                               | `R8:<kind>`                      |
| R8    | … not a member                                                                       | deny   | `no_source_membership`          | `R8:<kind>`                      |
| R9    | no snapshot                                                                          | deny   | `unknown_permissions`           | `R9:unknown_permissions`         |
| R9    | `doc.permission_version` set and ≠ `snapshot.permission_version` (stale snapshot)    | deny   | `unknown_permissions`           | `R9:permission_version_mismatch` |
| R10   | nothing else applied (unsupported raw kind)                                          | deny   | `policy_default`                | `R10:default_deny`               |
| guard | any exception while evaluating (malformed input) — `decide` never raises             | deny   | `unknown_permissions`           | `ERR:evaluation_error`           |

Grants only count when `grant.document_id == doc.document_id` and `grant.scope == "read"`.

**Revoked grants and `grant_revoked`.** R2 and R5 ignore revoked grants, so a formerly-allowed
principal falls through to R6+. If that fall-through ends in a **deny from R6–R10** and the
principal matches at least one **revoked allow** grant on the document, the `reason` becomes
`grant_revoked` while `matched_rule` keeps the rule that actually denied (e.g.
`reason=grant_revoked, matched_rule=R7:confidential`). No unrevoked matching grant can exist at
that point (R2/R5 would have fired), so "the only matching grants were revoked" holds by
construction. R1, R2 and guard reasons are never rewritten; revoked _deny_ grants never produce
`grant_revoked`; and if R8 still allows (the principal is a platform member anyway), access stays.

## Invariants

1. **Decisions are taken before the LLM.** `services/retrieval.py` calls `filter` on the
   over-fetched candidates and drops every denied one before freshness, sanitising, composing or
   verifying.
2. **One decision per candidate.** `filter` returns exactly `len(inputs)` decisions in input
   order; `allowed_ids ⊆ inputs`, input order, de-duplicated; a denied id never appears in it.
3. **Denied ⇒ byte-identical 404.** A document the principal may not read gets exactly the
   response of a nonexistent id (same status, body, headers). `DenyReason` is audit vocabulary,
   never response wording.
4. **No denied counts anywhere in responses.** `AccessSummary` carries `principal_id`,
   `policy_version`, `allowed_count`, `evaluated_at` — and nothing named or meaning "denied"
   (`extra="forbid"`, tested). Denied `AccessDecision`s go to the audit log only.
5. **`permission_version` on every decision**, so the audit trail can reconstruct which snapshot
   authorised which read, and a snapshot that no longer matches the page fails closed (R9).
6. **Fail closed.** Missing or malformed data denies (`unknown_permissions`); empty membership
   lists grant nothing.

## Public API

Everything is importable from the package root (`from access_control import …`):

- **Models:** `SourceKind`, `Classification`, `Effect`, `SubjectType`, `DenyReason`,
  `AccessRequestStatus`, `Principal`, `Grant`, `AccessRequest`, `DocumentAccessContext`,
  `AccessDecision`, `FilterResult`, `AccessSummary` (+ `AccessSummary.from_filter_result(result, *,
principal_id, policy_version, evaluated_at)`).
- **Raw permissions:** `ConfluencePermissions`, `ConfluenceAncestor`, `JiraPermissions`,
  `SlackPermissions`, `SlackChannelType`, `GDrivePermissions`, `GDriveAce`, `GDriveAceType`,
  `GDriveRole`, `EmailPermissions`, `UploadPermissions`, `McpExternalPermissions`,
  `RawPermissions`, `parse_raw_permissions(data)`, `SourcePermissions` (+ `.from_raw(raw, *,
permission_version, captured_at, connector_run_id=None)`).
- **Policy:** `DefaultAccessPolicy(policy_version="ac-v1")`, `DEFAULT_POLICY_VERSION`,
  `ADMIN_ROLE`, `has_source_membership(principal, raw)`, `platform_identities(principal, kind)`.
- **Protocols + errors:** `AccessPolicy`, `GrantStore`, `PermissionSnapshotStore`,
  `PrincipalDirectory`, `AccessRequestStore`, `AccessControlError`, `GrantNotFound`,
  `AccessRequestNotFound`.
- **In-memory stores** (lib tests + the app's conftest): `InMemoryGrantStore`,
  `InMemoryPermissionSnapshotStore`, `InMemoryPrincipalDirectory` (+ `upsert`),
  `InMemoryAccessRequestStore`.
- `SCHEMA_VERSION = 1`, `__version__ = "0.1.0"`.

| Protocol                  | Methods (stores are `async`)                                                                                                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `AccessPolicy`            | `policy_version: str`; `decide(principal, doc, *, now) -> AccessDecision`; `filter(principal, docs, *, now) -> FilterResult` (sync, pure, never raise)                                           |
| `GrantStore`              | `list_for_documents(ids) -> dict[str, list[Grant]]` (key per id, revoked included); `add(grant)`; `revoke(grant_id, *, by, at)` (soft, idempotent); `list_for_subject(subject_type, subject_id)` |
| `PermissionSnapshotStore` | `get_many(ids) -> dict[str, SourcePermissions]` (missing ids omitted); `put(document_id, perms)` (replace)                                                                                       |
| `PrincipalDirectory`      | `get(id) -> Principal \| None` (inactive returned too); `list()`; `groups_of(id) -> list[str]` (`[]` if unknown)                                                                                 |
| `AccessRequestStore`      | `create(req)`; `list_pending()`; `decide(request_id, *, approved, by, at)` (not found → `AccessRequestNotFound`, already decided → `AccessControlError`)                                         |

## How the app calls it

- **`app/core/auth.get_principal`** resolves `X-Actor-Id` (or `?actor=`) through the repo /
  `PrincipalDirectory` into an `access_control.Principal`; unknown or inactive → 401
  `unknown_actor`.
- **`app/services/retrieval.py`** (governed pipeline): hybrid search over-fetch → for the
  candidate page ids, `GrantStore.list_for_documents` + `PermissionSnapshotStore.get_many` → build
  one `DocumentAccessContext` per page (`classification`, `owner_principal_id`,
  `permission_version` from `pages`) → `policy.filter(principal, contexts, now=now)` → keep only
  `allowed_ids` → freshness → groundedness. Decisions go to `audit.record("ask", …)`; the
  response carries only `AccessSummary.from_filter_result(...)`. Document reads
  (`GET /api/documents/{id}`) use `decide` and return the not-found envelope on deny.
- **`app/api/routers/access.py`** + **`app/adapters/access_stores.py`** implement the four stores
  over `infra/postgres/migrations/0200_access_init.sql` (`source_permissions`, `grants`; plus
  `principals`/`group_memberships`/`access_requests` from `0001`). `DELETE /api/access/grants/{id}`
  → `GrantStore.revoke`; approving an access request → `AccessRequestStore.decide(approved=True)`
  **then** `GrantStore.add(Grant(effect=allow, subject_type=principal, …))` (the store does not
  create grants itself). `POST /api/documents/{id}/access-requests` is always 202.
- Ingestion (`gbrain_import` / connectors) parses frontmatter `permissions:` with
  `SourcePermissions.from_raw` and writes it with `PermissionSnapshotStore.put`.

## What Chai builds next

1. **Ingest real platform permissions** into `SourcePermissions` from the Confluence (space
   permissions + page/ancestor restrictions), Jira (project roles, permission scheme, issue
   security), Slack (`conversations.members`, workspace roster) and Drive (`permissions.list`
   incl. inherited) APIs, instead of seed frontmatter.
2. **Group resolution from an identity provider** (nested groups, platform-group ↔ org-group
   mapping, e.g. Drive group e-mails ↔ `groups`), feeding `PrincipalDirectory.groups_of`.
3. **Permission-drift hook** with freshness: when a permission change is observed, bump
   `permission_version` (page + snapshot) alongside freshness's version tracking so stale
   authorisation can never expose content (R9 mismatch already fails closed).
4. **Deny-wording review**: audit every response path (REST, MCP, UI, error envelope, timing)
   for existence leaks; keep `DenyReason` internal.
5. **Policy evals**: persona × document matrix fixtures from the seed corpus, plus regression
   cases for each platform's edge semantics.

## Tests

```bash
cd backend && uv run --no-sync pytest -q libs/access_control/tests
```

`test_models` (vocabulary, union round-trip per kind incl. exact seed shapes, `from_` alias,
no-app-import), `test_policy_rules` (rule order), `test_platform_semantics` (one or more per
platform), `test_filter_no_leak`, `test_stores`. Tests use fixtures only (no
`from conftest import`), so they also run under `--import-mode=importlib`.
