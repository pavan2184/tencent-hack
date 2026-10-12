# Access-control research and integration

Reviewed: 2026-10-12. Owner: Chai.

## Conclusion

Extend the existing Python library and preserve native read permissions. Local
roles/grants may narrow an external audience but cannot expand it. Refresh
authority per request, fail closed on incomplete data, and remove denied evidence
before model calls. These are project decisions inferred from the challenge and
the primary sources below.

## Baseline

Initial merged baseline: `50a1a6cd`. Final integrated baseline: `fc0bdf6c`.
The new foundation merge landed during this work and was incorporated before
final verification.
The original 100 access tests pass. Review found local source bypasses, public
Slack access without a captured roster, unknown Confluence ancestors treated as
unrestricted, and denied duplicate ids still eligible for release.

## Primary sources

| Source | Rule or guidance | Library response |
| --- | --- | --- |
| [OWASP authorisation](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) | Deny by default and check each request | Pure policy plus query-time authority refresh |
| [Confluence permission check](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content-permissions/) | Checks site, space and content access for a specified subject | Space/page/ancestor intersection and live-verifier seam |
| [Confluence restrictions](https://support.atlassian.com/confluence-cloud/docs/add-or-remove-page-restrictions/) | View restrictions inherit from parent content | Require every captured ancestor restriction |
| [Jira issue API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/) | Issue visibility requires browse and applicable issue security | Intersect browse roles with issue-security membership |
| [Slack conversation members](https://docs.slack.dev/reference/methods/conversations.members/) | Channel members are paginated identities | Refuse incomplete membership pages |
| [Slack users](https://docs.slack.dev/reference/methods/users.list/) and [user object](https://docs.slack.dev/reference/objects/user-object/) | Roster includes deleted users and guest flags | Exclude deleted users/bots/guests from full-member discovery |
| [Slack guest roles](https://slack.com/help/articles/202518103-Understand-guest-roles-in-Slack) | Guests access assigned channels | Guest workspace presence never grants public discovery |
| [Drive permission resource](https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions) | Expiry, deleted subject and discovery flags affect access | Retain fields and enforce at decision time |
| [Drive sharing](https://developers.google.com/workspace/drive/api/guides/manage-sharing) | Effective access includes inheritance | Consume effective file ACLs, not guessed parent unions |

## Connector contract

HTTP 200 is not an allow decision. A connector/bot's ability to fetch content
does not prove the asker can read it. Use verified identity mapping, complete
pagination and source-scoped group resolution. Missing scopes, rate limits,
transport errors and unknown memberships deny until a complete check succeeds.

- Confluence: capture space/page view lists and all ancestor restrictions.
  `POST /wiki/rest/api/content/{id}/permission/check` accepts `operation: read`
  and the asker's account id. Checking another identity requires the documented
  administrator permission. Inspect `hasPermission`, not HTTP status alone.
- Jira: capture Browse Projects roles and issue-security members. A user-bound
  `GET /rest/api/3/issue/{issueIdOrKey}` checks actual visibility. Project-level
  permissions alone cannot prove issue access.
- Slack: collect `conversations.info`, all `conversations.members` pages and
  optionally all `users.list` pages. Retain team identity, deletion and restricted
  guest flags. Respect Slack Connect and token workspace scope. The normaliser
  refuses unfinished cursors and filters the workspace-wide audience.
- Drive: collect file metadata and all `permissions.list` pages, including type,
  role, email/domain, inheritance details, expirationTime, deleted,
  allowFileDiscovery and nextPageToken. Resolve groups through the directory.
  Link-only domain/anyone entries do not permit discovery through this library.

Use `permission_fingerprint` when no ACL revision exists. Update the page's
expected revision and snapshot together, and notify Pavan's freshness pipeline
when ACLs change even if content did not change.

## Revocation and disclosure

`AccessControlService` refreshes principal/groups/grants/snapshots per call, even
when candidate objects are reused. Live-verifier errors never fall back to a
cached allow. Recheck final citations and cached/long-running answers before
publication. Mid-request revocation remains a race unless the app rechecks.

Only allowed evidence and `AccessSummary` reach the model/asker. Denied ids,
reasons and raw ACL membership belong in privileged audit storage. Missing and
denied API responses must be identical. This controls payload disclosure, not
all timing or retrieval-ranking side channels.

## Limits

This is a tested library, normalisers and offline stores, not four authenticated
live connectors. No credentials are required. The app's `X-Actor-Id` header is
spoofable and suitable only for the synthetic corpus. Live authentication
and native provider verification remain integration requirements. The final
main now contains REST/MCP, SQL and audit adapters; core synthetic REST tests
pass with the new policy. Credentialed tenant/deployment behaviour is not proven
by those offline tests.
