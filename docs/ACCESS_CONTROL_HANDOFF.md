# Access-control handoff

Last updated: 2026-10-12

## Delivered by Chai

`backend/libs/access_control` is the reusable package. The baseline already had
100 tests and pure platform models. This change closes source-permission bypasses,
adds query-time store refresh, a live verifier seam, Slack/Drive capture helpers,
ACL revisions, security regressions and a runnable corpus revocation demonstration.
No runtime dependency was added. The default policy revision changes to `ac-v2`.
The work was reconciled with the new foundation merge `fc0bdf6c` before delivery.

The editable architecture deck is [`docs/presentations/internal-brain-architecture.pptx`](presentations/internal-brain-architecture.pptx)
(15 slides; the submission copy without the internal status slide is
`internal-brain-architecture-submission.pptx`). It shows the implemented app/library path
and the remaining live-provider and authentication boundaries.

## Integration points for Pavan and Raphael

1. Construct `AccessControlService` with authoritative directory, grant and
   snapshot adapters. Take actor identity from a verified server boundary. The
   demo persona switcher is only suitable for synthetic content.
2. Store native ACLs, complete inherited restrictions and source-specific group
   membership. Atomically update document/snapshot permission versions when ACLs
   change. Metadata-only changes need to trigger refresh even if body text is unchanged.
3. Supply `SourcePermissionVerifier` when source-current access is required.
   Bound its transport timeout. A store snapshot alone cannot detect an unseen
   upstream revocation. Do not query as a broad connector account on the user's behalf.
4. Run `await service.filter(actor_id, candidate_contexts, now=...)` before loading
   evidence into freshness or groundedness. Select only `allowed_ids`. Recheck
   before publishing a long-running/cached answer and on every citation read.
5. Record `decisions` only in a protected audit path. Return only `AccessSummary`.
   Give missing/denied documents identical responses, and use the same generic
   no-evidence answer when all candidates are hidden.
6. Protect grant creation/revocation and audit routes with separate management
   privileges. Admin status does not grant native read access. Approval adds a
   local grant only after the integrating app explicitly writes it.

The latest main now includes REST/MCP handlers, SQL adapters and the governed
query path. Its existing `filter_pages`/`visible_page` functions use the updated
pure policy and current store reads. Core REST scenario, revocation, audit-role
and denied/missing response tests pass. `AccessControlService` is an available
query-time orchestration seam; a live source verifier is not yet wired into the
app. Do not connect real enterprise content until identity and native-provider
boundaries are verified end to end.

## Check and demo commands

```bash
cd backend
uv run --frozen pytest -q
uv run --frozen ruff check libs/access_control
uv run --frozen python libs/access_control/examples/revocation_demo.py
```

The demo reports `before_board_allowed: true`, `after_board_allowed: false`,
`outsider_allowed_ids: ["1RailBTestPlanExampleHarbor"]` (the one file shared with the
contractor), `revoked_body_in_model_context: false`, and one `access_stories` entry per rule the
corpus exercises (R1, R2, R3, R5, inherited Confluence restriction, Drive expiry and link-only
shares, DM, bcc, admin without source access). Reuse it for
Tencent scenarios 3 and 4, clearly labelled as synthetic in-memory execution.
A live-provider verifier regression also tests source revocation without
reindexing. The latest main's core REST suite checks all five scenarios, including
audit reconstruction and audit-role restrictions, with in-memory mock execution.

## Compatibility

Pure policy and store signatures remain available. Source restrictions now cap
owner/admin/local grants, public Slack requires proven workspace/channel access,
and conflicting duplicate ids fail closed. Three optional Drive ACL fields are
additive. The existing synthetic seed formats still parse. Callers that relied
on the old permission bypass must update their expectations and invalidate
previously cached answers. No environment variables or lockfiles changed.

## Verified results

174 access-control tests pass. Across the backend, 549 offline tests plus 11
disposable Postgres 17 integration tests pass (560 distinct tests). All 135
Python files pass Ruff lint and formatting. Postgres 16 deployment, credentialed
enterprise provider calls and Tencent model responses remain unverified.
