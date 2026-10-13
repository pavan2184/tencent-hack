# Access control

Chai's Tencent Internal Brain library. Pure Python/Pydantic, no app imports or
network clients. Existing store interfaces and deny-reason values are preserved.
Default policy is now `ac-v2`.

## Security rule

For imported content:

**Allowed = active identity AND no explicit deny AND native source access AND local policy.**

Owners, admins and local allow grants cannot bypass source restrictions. A local
grant does not change Confluence, Jira, Slack or Drive permissions. For
confidential/restricted content, native access also needs owner/admin status or a
matching active local grant. App-managed uploads use local owner/admin/grant
semantics. A missing, wrong-kind or mismatched source snapshot denies imported
content even for an admin.

| Source | Read semantics |
| --- | --- |
| Confluence | Space view and page restrictions and every ancestor restriction. Bare ancestor ids mean incomplete capture and deny. |
| Jira | Browse Projects roles and issue security. Connectors must fully resolve dynamic subjects or confirm the asker's read natively. |
| Slack | Explicit channel membership for every channel type. Public channels additionally permit a captured full workspace roster, excluding guests/bots/deactivated users. Missing roster never allows outsiders. |
| Drive | Effective file ACL, including inherited entries. Deleted/expired entries and link-only domain/anyone shares cannot grant search discovery. |
| Email | Sender/recipient mailbox identity, including to/cc/bcc. |
| Upload | Local owner and explicit sharing. Local grants can extend sharing. |
| External MCP | Explicit principal/group allow-list. |

### Permission snapshots expire

Native source access is judged from a captured snapshot, so the snapshot must be recent. An
imported document's snapshot older than its classification's maximum age denies with
`R9:permission_snapshot_stale` until a sync refreshes it:

| Classification | Maximum snapshot age |
| --- | --- |
| public | 24 hours |
| internal | 1 hour |
| confidential, restricted | 5 minutes |

This bounds how long a revocation at the source can go unnoticed: at most the maximum age, even
if a webhook is missed. The app re-reads every page's permissions on each delta sync (every
60 seconds by default), and a failed read keeps the old snapshot, which then ages out. Snapshots
stamped more than 60 seconds in the future are not trusted. Uploads are exempt because their
permissions are local. Each decision records `permission_captured_at` for the audit trail.
Override with `DefaultAccessPolicy(max_permission_age={...})`; `None` disables the check for
offline tools only.

A bound external identity takes precedence over local id/email. Group ids must
be resolved server-side and scoped to the native source. Synthetic fixture groups
are not a production identity provider.

## Integrate before model context

```python
from datetime import UTC, datetime
from access_control import AccessControlService, AccessSummary

access = AccessControlService(
    directory=principal_directory,
    grants=grant_store,
    snapshots=permission_snapshot_store,
    verifier=provider_read_verifier,  # SourcePermissionVerifier, or None offline
)
now = datetime.now(UTC)
result = await access.filter(authenticated_actor_id, candidate_contexts, now=now)
allowed_evidence = await evidence_store.load_for_documents(result.allowed_ids)
# Only allowed_evidence goes to freshness, sanitising, composition and citations.
summary = AccessSummary.from_filter_result(
    result, principal_id=authenticated_actor_id,
    policy_version=access.policy.policy_version, evaluated_at=now,
)
await protected_audit_store.record(result.decisions)
```

The stores are asynchronous Protocols with working in-memory implementations.
`AccessControlService.filter` reloads the principal, groups, grants and snapshots
on every call, replacing cached candidate grants/ACLs. Authority errors deny the
whole batch. A missing grant-store key is an incomplete read and also denies.
There is no cached allow decision.

The optional `SourcePermissionVerifier.verify(principal, doc, now=now)` returns
exactly `True`, `False` or `None`. It runs only for locally allowed candidates.
`True` confirms but cannot widen access. `False` denies, and `None`/exceptions or
non-boolean replies deny as unknown. Adapters must bound transport timeouts and
check the asker's account rather than a broad service account. Without this seam,
source revocation is known only when the snapshot/directory stores refresh.

Use `DefaultAccessPolicy.decide(principal, doc, now=now)` or `.filter(...)` for
pure deterministic evaluation when all inputs are already current. Use a
timezone-aware clock. Decisions retain R1–R10 labels for audit compatibility,
but the source ceiling now runs before owner/admin/allow checks. Revoked grants
are ignored; an otherwise denied user with only revoked allows receives the
internal `grant_revoked` reason. Explicit deny and inactive identity still win.

## Prevent existence leaks

- `allowed_ids` is the only evidence selection input. If duplicate candidates
  disagree, any denial removes that id. There is one audit decision per input.
- `FilterResult.decisions` is private audit data. It must never enter a public
  answer, model prompt, URL preview or error message.
- `AccessSummary` permits only principal id, policy version, allowed count and
  evaluation time. It forbids extra fields, including denied counts.
- Apply the same gate to REST/MCP asks, listings, downloads and citation reads.
  Missing and denied objects need identical response status/body/headers. This
  library supplies decisions, not an HTTP route implementation.
- Reauthorise cached answers and final citations before publication. Do not cache
  across users or retain evidence after revocation without rechecking.

## Connector capture

`parse_raw_permissions(data)` accepts strict typed native models. Unknown keys
are rejected. `SourcePermissions.from_raw(raw, permission_version=...,
captured_at=..., connector_run_id=...)` wraps the captured ACL.

`slack_permissions_from_api(workspace_id=..., channel=...,
member_pages=..., workspace_pages=...)` accepts conversations.info/members and
optional users.list responses. It excludes restricted guests from the public
workspace audience. Explicit channel membership can still authorise a guest.

`gdrive_permissions_from_api(file=..., permission_pages=...)` accepts file
metadata and the complete effective file ACL. Request type, role, emailAddress,
domain, permissionDetails, deleted, expirationTime and allowFileDiscovery.
Both helpers reject incomplete pagination. Never blindly union parent Drive
ACLs or drop inherited Confluence restrictions.

`permission_fingerprint(raw)` returns a deterministic SHA-256 ACL revision.
Capture time/run id do not affect it. Permission or parent changes do. Write the
current document revision and matching snapshot atomically. Fingerprints are
not cached authorisation decisions.

The existing `GrantStore`, `PrincipalDirectory`, `PermissionSnapshotStore` and
`AccessRequestStore` contracts remain public. Grant revocation is idempotent,
retains its audit row, and takes effect on the next service evaluation. Approving
an access request does not automatically add a grant or change native access.

## Run tests and demonstrate revocation

```bash
cd backend
uv run --frozen pytest libs/access_control/tests -q
uv run --frozen ruff check libs/access_control
uv run --frozen python libs/access_control/examples/revocation_demo.py
```

For the filmed demo, run the end-to-end script. It narrates and checks four scenes: an
authorised employee, a contractor who learns nothing, a revocation at the source (the Drive owner
removes Leadership from the board deck's share, then a sync) including Priya's saved answer being
withheld, and the audit inquiry:

```bash
cd backend
uv run python ../scripts/demo_access_control.py                               # offline, in-process
uv run python ../scripts/demo_access_control.py --api http://localhost:8000   # running stack
```

Offline mode works on a throwaway copy of the seed corpus. Stack mode edits
`backend/seed/corpus/gdrive-finance/files/board-deck-q3.md` (mounted read-only into the
containers), triggers a sync and always restores the file; it needs the Celery worker running.

The library-only demonstration below loads the actual 11-document synthetic corpus, confirms Priya
can read the board deck, revokes its leadership grant, queries again using the
same cached candidates, and asserts the revoked body never reaches model
context. It also asserts the contractor has no evidence. It needs no credentials
or running database. Its internal output is not a public API response.

Research and integration limits: [research](../../../docs/ACCESS_CONTROL_RESEARCH.md),
[handoff](../../../docs/ACCESS_CONTROL_HANDOFF.md),
[security review](../../../docs/ACCESS_CONTROL_SECURITY_REVIEW.md).
