# Security Review

Last updated: 2026-10-12

## Reviewed scope

The access-control package, stores, provider response normalisers, corpus demo,
public summary model and handoff contract. Reviewed by code inspection and
regression tests. Core synthetic REST tests were also checked after integrating main `fc0bdf6c`.
The review does not certify live identity/providers, deployment or cross-system
revocation timing.

## Threats and controls

| Attack or failure | Implemented control | Evidence |
| --- | --- | --- |
| Owner/admin/local grant widens imported source audience | Mandatory native ceiling before local allows | Three bypass regressions and six missing/stale privileged cases |
| Inactive user or explicit deny overrides a grant | Inactive/deny precedence retained | Existing ordering tests |
| Upstream membership or local grant changes while candidate metadata is cached | Reload directory/groups/grants/snapshots every query; optional live check only tightens | Service revocation tests and 11-document demo |
| Incomplete inherited ACL or pagination broadens access | Bare Confluence ancestors deny; provider pages must be complete | Inheritance and connector tests |
| Public Slack exposes content to outsiders or guests | Proven channel membership or explicit full-member roster | Missing-roster and guest/bot/deactivated user tests |
| Drive expired/deleted/link-only permission permits search | Enforce expiry at query time and retain discovery restrictions | Exact-expiry and provider-field regressions |
| Conflicting duplicate candidate allows a denied id | Any denial removes the id from allowed evidence | Both-order duplicate regressions |
| Missing grants or failed provider/store gets treated as no restrictions | Revalidate stored models and fail closed on missing keys, exceptions and ambiguous live replies | Store-failure and verifier-failure tests |
| Denied evidence or hidden-document count leaks through answer | Allowed ids only; strict public AccessSummary; private decisions | Pre-model sentinel tests and summary shape tests |
| Bound platform account also inherits local email access | Bound identity replaces fallback identity | Wrong-account regression |

## Trust and LLM boundaries

Only server-owned identity and metadata may reach the policy. The synthetic
fixture loader intentionally trusts the checked-in test corpus. Arbitrary upload
frontmatter, prompt text, retrieved documents, model output and browser claims
must never create grants, set roles, change classification or replace ACLs.

The library never calls an LLM or logs document text, ACL payloads or credentials.
The integrating app must use `allowed_ids` before constructing prompts, pass
allowed evidence through groundedness sanitising/verification, and protect audit
records. Provider error details and denied decisions must stay out of public
errors and model context. Model output cannot make an authorisation decision.

## Remaining integration risks

- `X-Actor-Id` and the persona switcher are a synthetic demo boundary without
  authentication. Use verified server identity before connecting real data.
- Snapshots do not prove current upstream access. Connectors must refresh complete
  permissions and groups, and a bounded live verifier is required when a query
  must reflect an upstream revocation immediately.
- Native Jira schemes, dynamic subjects, nested groups and Confluence inherited
  restrictions must be completely resolved or authoritatively checked. A partial
  group or ACL mapping is unsafe. Drive link-only content is deliberately omitted
  from search until an explicit identity grant permits it.
- Provider revocation can race a long-running query. Recheck before publication
  and on downloads/citations. This package cannot make remote providers and model
  calls one atomic transaction.
- Core REST missing/denied responses, local upload grant/revoke, source-ceiling
  grant approval, audit roles and all five Tencent scenarios pass in memory.
  Live provider identity, timing/ranking side channels and cached/final-answer
  rechecks still require integration verification.
- The 11 SQL integration tests passed against disposable Postgres 17, including
  round-trips of the new Drive restrictions. The configured Postgres 16 image
  could not be pulled because registry authentication failed. No credentialed
  provider calls, production-load or deployment tests ran. The changes add no
  dependencies, secrets or environment variables.

See [primary-source research](ACCESS_CONTROL_RESEARCH.md) and
[handoff](ACCESS_CONTROL_HANDOFF.md) for provider contracts and integration steps.
