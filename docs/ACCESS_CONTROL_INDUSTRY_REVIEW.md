# Access control: how the industry does it, and where we stand

Reviewed: 2026-10-13. Owner: Chai. Sources: vendor documentation, standards and regulators,
listed at the end. Claims about what a vendor "does not document" mean we found nothing in the
public documentation listed here, not that the feature cannot exist.

## Bottom line

- **Our core design is the industry-standard one, on purpose.** Glean, Microsoft 365 Copilot,
  Google Gemini Enterprise, Atlassian Rovo, Amazon Q Business and Elastic all copy each source's
  permissions next to the content and filter before the model sees anything. OWASP, AWS and the
  authorization vendors (OpenFGA, SpiceDB, Cerbos, Oso) recommend the same. Inventing a different
  scheme would be a red flag for a fintech judge, not a strength.
- **We go beyond what the major products publicly document in four places:** a per-document
  allow/deny record for every candidate (including denied ones), a hash-chained audit log, saved
  answers re-checked on every read, and missing or incomplete permissions treated as "deny".
- **We are behind the industry in three places that matter for feasibility:** Slack now has to be
  queried live rather than indexed, permission changes need their own fast sync, and search should
  filter by permission inside the database query, not only afterwards.
- **Jev should not make access decisions.** OWASP, AWS and Jev's own vendor material say
  authorization must stay deterministic in code. It is also manipulable by planted text and
  US-hosted only.

## 1. What the industry does

### The shared pattern

1. Resolve the asker's identity server-side, usually through SSO (Entra ID, Google Identity,
   Okta) and match platform accounts by email.
2. Store each item's source permissions (users, groups, and for Jira an "AND of ORs") next to the
   indexed content ("early binding").
3. Filter candidates by those permissions before anything reaches the model. Several vendors say
   so explicitly: Glean ("can't be used as context... or surfaced as a citation"), Microsoft
   ("only surfaces organizational data to which individual users have at least view
   permissions"), Slack ("the LLM only receives data the user can already access").
4. For some sources, check live with the platform at question time instead of indexing
   ("late binding"). This is now required for Slack (below), and Glean and Rovo also fetch pasted
   Drive links with the user's own access.
5. Treat link-only sharing as "not shared" unless the user has opened the file (Glean, Microsoft,
   Notion) or it is not supported at all (Amazon Q).

### How fast revocation takes effect

| Product                                     | When permissions are applied                               | Documented revocation delay                                                         |
| ------------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Glean                                       | Indexed permissions, checked per query; Slack fetched live | Drive identity 1 h, Jira identity 3 h (defaults, not guarantees)                    |
| Microsoft 365 Copilot                       | Native permissions; connector items carry ACLs             | **Confluence permission changes: next full crawl, every 24 h by default**           |
| Gemini Enterprise / Vertex AI Search        | Indexed `acl_info`; Drive and some sources federated       | Identity sync every 30 min to 7 days; incremental syncs skip identity and deletions |
| Atlassian Rovo                              | Teamwork Graph ACLs; Slack and Drive checked live          | Not documented                                                                      |
| Slack enterprise search                     | Live only, nothing stored                                  | Real-time                                                                           |
| Amazon Q Business (closed to new customers) | Indexed ACLs                                               | Each crawl, hourly to monthly                                                       |
| Elastic connectors                          | Indexed `_allow_access_control`                            | Separate scheduled access-control sync                                              |

**For indexed sources, revocation in the big products takes minutes to a day.** Ours is enforced on the very next
query for local grants, and the library supports a live per-request source check that closes
the gap for source-side changes once it is wired in.

### Where vendors still differ or fall short

- **Missing permissions:** Elastic and Amazon Q treat a document with no ACL as public. Microsoft's
  Confluence connector and Glean hide it. We hide it (fail closed).
- **Inherited Confluence restrictions:** Atlassian's API does not return a parent page's
  restriction on its children. Microsoft's connector has an open Atlassian ticket
  (CONFCLOUD-82942) for exposing such child pages; Elastic fixed it in July 2026 by intersecting
  every ancestor's restriction. Our library already requires every ancestor's restriction and
  denies if one was not captured.
- **Audit:** only Microsoft (Purview `CopilotInteraction` records) documents per-resource entries
  with a status. Rovo and Glean log events, not retrieved items. None of the products reviewed
  documents tamper evidence such as a hash chain, or logs the documents that were filtered out.
- **Chat history after revocation:** none of the products reviewed documents re-checking stored
  answers. Slack sidesteps it by discarding summaries; Glean keeps live-fetched content for the
  chat session; Microsoft stores citations in history.
- **Real incidents are oversharing, not bypass:** the AI faithfully surfaces permissions that were
  already too broad (Microsoft's answer is Restricted Content Discovery and Data Access Governance
  reports). EchoLeak (CVE-2025-32711) was a prompt-injection data leak, not an access-control
  bypass, and it beat Microsoft's injection classifier.

## 2. Our design against the industry

| Area                             | Industry practice                                                               | Brain Sauce                                                             | Verdict                                                         |
| -------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------- |
| Filter before the model          | Universal                                                                       | Access gate before freshness, sanitising and the model                  | Matches                                                         |
| Per-platform semantics           | Confluence space + page, Jira AND-of-ORs, Slack membership, Drive effective ACL | Same, plus every Confluence ancestor and Drive expiry/deleted/link-only | Matches, ahead on Confluence inheritance                        |
| Missing permissions              | Mixed: some vendors fail open                                                   | Deny                                                                    | Ahead of Elastic and Amazon Q                                   |
| Revocation latency               | Minutes to 24 h                                                                 | Next query for local grants; source changes need sync or the live check | Ahead for grants; source-side depends on wiring the live check  |
| Saved answers                    | Not documented anywhere                                                         | Re-checked on every read (PR #6)                                        | Ahead                                                           |
| Per-document audit incl. denials | Only Microsoft logs accessed resources                                          | Every candidate's allow/deny, rule and permission version               | Ahead                                                           |
| Tamper evidence                  | Not documented                                                                  | Hash chain, same database                                               | Ahead, but needs an external anchor (section 3)                 |
| Slack                            | Live search via Slack's Real-time Search API                                    | Indexed (synthetic corpus)                                              | **Behind**: Slack's API terms now forbid storing retrieved data |
| Search vs permission filter      | Recommended: filter inside retrieval, re-check final results                    | Search first (4× over-fetch), then check                                | **Behind** at scale; fine for the demo corpus                   |
| Identity                         | SSO, delegated user tokens, MCP OAuth 2.1                                       | Demo persona header                                                     | **Behind**: demo only                                           |

### Why the "behind" items matter

- **Slack must be live, not indexed.** Slack's Real-time Search API page says: "You must not store
  or copy any of the data retrieved from this API." Guests cannot use it, and private channels
  need both admin and user consent. Glean and Rovo moved to it. Our production story for Slack
  therefore has to be late binding: ask Slack at question time with the user's own OAuth token,
  and keep no copy. The synthetic Slack pages in the demo are fine, but the pitch must not claim
  we would index a customer's Slack.
- **Filtering after search loses results.** OWASP's RAG cheat sheet and OpenFGA, SpiceDB and
  Cerbos all recommend filtering inside retrieval and re-checking the final set. pgvector applies
  filters after its approximate index scan, so a user who can see 10% of the corpus gets very few
  results unless iterative scans are on. Post-filtering can also leak existence through ranking
  (Büttcher and Clarke, 2005). Our 4× over-fetch is within OpenFGA's suggested 2-3× range and is
  a documented trade-off; it is acceptable for 11 synthetic pages, not for 12,000 Confluence pages.
- **Permission changes need their own sync.** Every vendor runs identity and permission syncs on
  a separate, faster schedule than content, because incremental content syncs often skip them
  (Microsoft Confluence, Gemini Enterprise).

## 3. What a Singapore fintech regulator expects

- **MAS AI Risk Management Guidelines (final, 7 October 2026; in force 7 October 2027).**
  Paragraph 2.4(f) lists "AI-powered chatbots to assist personnel in locating relevant internal
  resources" among uses that may need only basic AI governance. Footnote 12 still expects data
  management, safety and cybersecurity controls. Paragraph 5.23 suggests logging prompts and
  model responses "together with applicable model versions".
- **MAS Technology Risk Management Guidelines (2021).** Least privilege and prompt revocation
  (9.1.1, 9.1.7), logged user access (9.1.3), logs protected against unauthorised access (12.2.2),
  monitoring through a SOC (12.2.1). MFA for sensitive functions (9.1.5).
- **PDPC Advisory Guidelines on Generative AI (July 2026).** The deployer is primarily
  responsible; prompts, outputs and tool activity are personal data under the Protection
  Obligation, so **the audit log itself must be access-restricted and given a retention period**.
  The model provider is a data intermediary; if processing is outside Singapore, transfer
  limitation applies.
- **NIST SP 800-53 AU-9(2).** Audit records stored on a physically separate system. A hash chain
  in the same Postgres detects edits by anyone except a database administrator, who could rewrite
  rows and recompute the chain.

## 4. Recommendations

### Before filming (14 October), small and in scope

1. Demo a source-side revocation (remove John from the Drive share, sync, ask again), not only a
   local grant revocation. Owner: Chai with Pavan.
2. Add the model and prompt-template version to the `ask` audit payload (MAS AIRG 5.23).
   Owner: Raphael.
3. Export the audit chain's head hash to a separate place on a schedule (an object-lock bucket,
   or at minimum a second store) and show it in the audit view. Owner: Raphael or Pavan.
4. In the deck and video, state the production Slack design as live search with per-user OAuth
   and no stored copy. Owner: Chai.

### After the hackathon (Phase 2)

- Store allowed principals on every chunk and filter inside the SQL query; keep the Python policy
  as the final authority on the top results (pre-filter plus post-check).
- Subscribe to permission-change feeds (Confluence, Jira and Drive webhooks or change APIs; Slack
  events) and run identity sync separately from content sync.
- Wire the live per-request source check (`SourcePermissionVerifier`) using each user's own
  delegated token, never the connector's service account (OWASP LLM06; RFC 8693 delegation).
- SSO with MFA; OAuth 2.1 for the MCP server per the MCP authorization spec (audience-bound tokens,
  no token passthrough).
- Forward audit events to a SIEM; restrict who can read the audit log; set a retention period.
- Confirm Tencent Cloud ADP's data residency, retention and contract terms (audit rights, change
  notification) before any real data.
- Consider a relationship-based authorization engine (OpenFGA or SpiceDB) only when list-filtering
  at scale or change feeds become the bottleneck; our raw per-platform rules already cover the
  semantics.

## 5. Jev

Jev (TypeSafe AI, released September 2026) is a discriminative model: it returns typed answers
(yes/no, choice, score) with probabilities rather than text.

- **Not for access decisions.** OWASP LLM06 and LLM07 say authorization must be deterministic and
  never delegated to a model; AWS calls LLMs "untrusted entities" for authorization. Vercel's Jev
  guide says application code enforces permissions and "the classifier's judgment cannot give the
  agent additional access".
- **Manipulable.** Published tests show planted text (a fake "pre-approved" note) shifting its
  verdicts, and option order changing about a third of answers in one study.
- **Hosting.** US-hosted only per a third-party security review; sending Aspire content to it
  would need PDPA transfer and MAS third-party AI review.
- **Where it could help later:** a fast, cheap second opinion for groundedness checks or flagging
  suspicious retrieved text, always behind the deterministic gate and never as the only control.
  Not worth adding before 16 October.

## 6. What we can say in the pitch

Defensible:

- "We enforce each platform's native permissions before the model sees anything, the same model
  Glean and Microsoft 365 Copilot use."
- "Revocation of a grant applies on the very next question, including answers you saved earlier.
  Big products document delays of up to 24 hours for some sources."
- "Every question records an allow or deny for every document considered, in a hash-chained log
  an auditor can replay."
- "Missing or incomplete permissions mean no access, never open access."

Avoid:

- Claiming we index Slack in production (Slack's terms forbid it).
- Claiming the audit log is tamper-proof (it is tamper-evident until anchored externally).
- Claiming instant revocation for source-side changes until the live check or change feed is
  wired.

## Sources

Products

- Glean permissions: https://developers.glean.com/libraries/indexing-sdk/permissions ;
  security principles: https://docs.glean.com/security/security-principles ; refresh rates:
  https://docs.glean.com/connectors/crawling-refresh-rates ; Drive sharing:
  https://docs.glean.com/connectors/native/gdrive/security/permissions
- Microsoft 365 Copilot privacy:
  https://learn.microsoft.com/en-us/microsoft-365-copilot/microsoft-365-copilot-privacy ;
  Confluence connector:
  https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/confluence-cloud-overview ;
  Purview audit: https://learn.microsoft.com/en-us/purview/audit-copilot ; open inheritance issue:
  https://jira.atlassian.com/browse/CONFCLOUD-82942
- Gemini Enterprise / Vertex AI Search access control:
  https://docs.cloud.google.com/generative-ai-app-builder/docs/data-source-access-control ;
  connector syncs:
  https://docs.cloud.google.com/gemini/enterprise/docs/introduction-to-connectors-and-data-stores
- Atlassian Teamwork Graph permissions:
  https://developer.atlassian.com/platform/teamwork-graph/permissions/ ; Slack connector:
  https://support.atlassian.com/organization-administration/docs/connect-slack-to-teamwork-graph/
- Slack enterprise search engineering:
  https://slack.engineering/how-we-built-enterprise-search-to-be-secure-and-private/ ;
  Real-time Search API: https://docs.slack.dev/apis/web-api/real-time-search-api
- Amazon Q Business connectors:
  https://docs.aws.amazon.com/amazonq/latest/qbusiness-ug/connector-concepts.html
- Elastic document-level security:
  https://www.elastic.co/docs/reference/search-connectors/es-dls-overview ; Confluence
  inheritance fix: https://github.com/elastic/connectors/pull/4297
- Notion AI connectors: https://www.notion.com/en-gb/help/notion-ai-connectors-for-slack

Authorization practice and security

- OWASP RAG Security Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html
- OWASP LLM06 Excessive Agency: https://genai.owasp.org/llmrisk/llm062025-excessive-agency/ ;
  LLM07: https://genai.owasp.org/llmrisk/llm072025-system-prompt-leakage/ ; LLM08:
  https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/
- AWS, authorizing data access with RAG:
  https://aws.amazon.com/blogs/security/authorizing-access-to-data-with-rag-implementations
- OpenFGA RAG authorization: https://openfga.dev/docs/modeling/agents/rag-authorization ; search
  with permissions: https://openfga.dev/docs/interacting/search-with-permissions
- SpiceDB querying data: https://authzed.com/docs/spicedb/concepts/querying-data ; consistency:
  https://authzed.com/docs/spicedb/concepts/consistency
- Cerbos RAG authorization: https://docs.cerbos.dev/cerbos/0.42.0/recipes/ai/rag-authorization
- Oso on RAG authorization: https://www.osohq.com/post/right-approach-to-authorization-in-rag
- pgvector filtering and iterative scans: https://github.com/pgvector/pgvector
- MCP authorization spec:
  https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- RFC 8693 token exchange: https://datatracker.ietf.org/doc/html/rfc8693
- Zanzibar: https://research.google/pubs/pub48190/
- Büttcher and Clarke, FAST '05:
  https://static.usenix.org/event/fast05/tech/full_papers/buettcher/buettcher_html/index.html
- EchoLeak: https://thehackernews.com/2025/06/zero-click-ai-vulnerability-exposes.html

Regulation and standards

- MAS AI Risk Management Guidelines (7 Oct 2026):
  https://www.mas.gov.sg/regulation/guidelines/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions
- MAS Technology Risk Management Guidelines (2021):
  https://www.mas.gov.sg/-/media/mas/regulations-and-financial-stability/regulatory-and-supervisory-framework/risk-management/trm-guidelines-18-january-2021.pdf
- PDPC Advisory Guidelines on Generative AI:
  https://www.pdpc.gov.sg/organisations/regulations-decisions/regulatory-guidance/advisory-guidelines-on-use-of-personal-data-in-generative-ai
- NIST SP 800-53 Rev. 5: https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
- NIST AI 600-1: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf

Jev

- https://en.wikipedia.org/wiki/Jev_(AI_model) ; https://vercel.com/i/jev-use-cases ;
  https://neuraltrust.ai/blog/jev-typesafe-ai-security
