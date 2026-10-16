# Submission texts

For the Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 form (FinTech track, Aspire's "The
Internal Brain" challenge). Every figure comes from the repository's tests, the access demo script
or the team's live rehearsal on 13–14 October 2026. Personas and figures are synthetic.

## Project title

Brain Sauce

## Blurb (under 10 words)

**Enterprise answers from only what you're allowed to see** (9 words)

Alternatives: "Permission-aware answers across Slack, Jira, Confluence and Drive" (8 words) or "Ask
anything. See only what you may. Prove it." (9 words).

---

## Project Overview: Target Scenarios, Users, and Value Proposition

**Target scenario.** Staff at a multi-country fintech such as Aspire need answers that sit
across Confluence, Jira, Slack and Google Drive: "What is the plan for the Rail-B cutover?", "What
is the failover procedure?", "What were Q3 revenue figures?". Today they search four tools, each
with its own permissions, and stitch the answer together by hand.

**Users.**

- **Employees** ask one question in plain language, from the web app, the REST API, or AI agents
  through MCP tools.
- **Compliance and audit officers** reconstruct who asked what, what was retrieved, which
  documents were allowed or denied, and what was answered.
- **Document owners and admins** approve access requests and revoke access.

**Value proposition.** One cited answer across all four platforms, built only from evidence the
asker is allowed to see in each platform, with proof attached. Every answer carries claim-level
citations, a freshness receipt, a grounding report and a tamper-evident audit record. Restricted
content never reaches the language model, revocations take effect on the next question in the
app and within five minutes at the source, and the system abstains rather than guesses.

## Real World Scenario Insights: Source of Pain Points, Target Audience and Core Problem Solved

**Source of the pain points.** Aspire has more than 600 employees across nine countries serving
clients in over 30 markets. Its knowledge is split across four platforms with four permission
models: Confluence space and page restrictions (inherited from parent pages), Jira project roles
and issue security levels, Slack channel membership, and Google Drive file, folder, domain and
link sharing. Research into how enterprise AI search products handle this showed the gaps:

- Microsoft documents that its Copilot connector for Confluence picks up permission changes only
  on a daily full crawl, and an open Atlassian ticket reports child pages that inherit a parent's
  restriction being surfaced to unauthorised users.
- Some connectors treat a document with missing permissions as public.
- None of the major products we reviewed documents re-checking saved answers after access is
  revoked, or recording every allow and deny decision in a tamper-evident log.

**Target audience.** Regulated fintechs, where an assistant that leaks one board deck or one
customer record is a reportable incident, and where MAS's AI Risk Management Guidelines (7 October 2026) explicitly cover chatbots that help staff find internal resources.

**Core problem solved.** A chatbot on top of ordinary search fails a regulated company in three
ways:

1. **It leaks**: a contractor asks about Q3 revenue and the bot quotes the confidential board deck,
   because search never checked who was asking.
2. **It goes stale**: the failover runbook changed at the source, but the index still serves the
   old version as current.
3. **It cannot be audited**: nobody can reconstruct what the model was shown or why.

Brain Sauce solves all three, and closes the revocation gap: someone who loses access loses
it in the assistant too, including answers saved earlier.

## Comprehensive Solution Design: Business and Technical Architecture, and How Prompts Drive the AI Generation

**Business architecture.** Four guarantees on every response, delivered through one pipeline
behind three front doors (web app, REST API, MCP tools), so no channel can bypass the checks:

- **Permitted**: native platform permissions are checked per document before any model call.
- **Fresh**: critical evidence is live-verified at the source; stale versions are omitted, never
  shown as current.
- **Grounded**: every claim is checked against its cited evidence, numbers and dates included.
- **Audited**: a hash-chained record holds the asker, retrieved IDs, every allow or deny decision
  and the final answer.

**Technical architecture.** FastAPI and Pydantic v2 on Python 3.12; Postgres 16 with pgvector for
hybrid keyword and vector search; Redis and Celery for ingestion, sync and verification jobs;
Next.js 15 for the web app; an MCP server for AI agents; Tencent Cloud ADP as the language model;
one Docker Compose stack. Every question runs the same governed pipeline:

1. **Identity** is resolved by the server, never trusted from the client.
2. **Hybrid search** finds candidate documents across all four sources.
3. **The access gate** checks every candidate against that platform's native permissions (for
   example every parent page's restriction in Confluence, and expiry, deletion and link-only
   sharing in Drive). A local grant can never widen what the source allows. Missing, incomplete or
   expired permissions mean no access. Permissions are re-read every minute and refused once older
   than five minutes for confidential documents. Denied documents stop here: their text never
   reaches the model, and only the audit log records the decision.
4. **Freshness** live-verifies critical documents and omits stale versions.
5. **Sanitising** quarantines prompt-injection text found inside retrieved documents.
6. **One Tencent Cloud ADP call** writes the answer.
7. **Deterministic verification and abstention**, then a **hash-chained audit event**.

Saved answers are re-checked every time they are opened. Auditors see every decision, but answer
text drawn from documents they cannot open needs a "reveal with reason" that is itself recorded in
the audit chain. Managers and admins also get an **access map**: a live diagram of who can read
each document and why (the platform rule or the grant behind every line), limited to documents
they can read themselves. Revoking a grant there removes the line immediately, and each view of
the map is audited.

**How prompts drive the AI generation.**

- The prompt contains **only allowed, fresh, sanitised evidence**, one line per item, labelled
  `[E1] title — text`, `[E2] …`. Quarantined text is never listed.
- The instruction is to **answer from the evidence only, end every sentence with its `[E#]`
  labels, or reply exactly `ABSTAIN`**.
- Generation runs at **temperature 0 with a 20-second deadline**. On timeout or provider error the
  system falls back to an extractive answer and records that in the audit log.
- A **deterministic grounding step** attaches each sentence to its evidence and verifies it. A
  numeric gate means a wrong amount, date or time can never be marked supported. **If under 60% of
  the answer is supported, the system abstains.**
- There is **one model call per question** and no second model acting as a judge, so results are
  reproducible and quota-friendly.

**Deliberate trade-offs.** Permissions are checked after search with 4× over-fetching to keep each
platform's exact rules; stale critical evidence is omitted even if answers get thinner; and if
syncing stops, confidential documents become unavailable after five minutes, trading availability
for safety. In production, Slack is searched live with each user's own login and nothing is stored,
as Slack's API terms require; the demo uses a synthetic corpus.

## Business Value: Quantifiable Metrics or Clearly Defined Impact

| Metric                                                                     | Result                                                                                                                |
| -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Mandatory challenge scenarios demonstrated end to end                      | **5 of 5**, each an automated test                                                                                    |
| Restricted documents in a contractor's model context                       | **0**; a denied document returns the same 404 as a missing one                                                        |
| Time for an in-app revocation to take effect                               | **The next question**, including previously saved answers                                                             |
| Longest a revocation at the source goes unnoticed (confidential documents) | **5 minutes**, enforced as a hard limit (Microsoft documents a daily full crawl for its Copilot Confluence connector) |
| Time for an edited source page to be picked up (live rehearsal)            | **15 seconds** after the edit                                                                                         |
| Model calls per question                                                   | **1**; grounding and verification are deterministic                                                                   |
| Audit coverage                                                             | **Every** candidate document's allow or deny decision, in a hash-chained log that verifies end to end                 |
| Automated tests                                                            | **711 pass offline**, plus 11 database tests against Postgres; the access demo passes 15 of 15 checks                 |

**Clearly defined impact for Aspire.**

- **Risk**: confidential material such as board decks and customer data cannot leak through the
  assistant to contractors or to staff whose access was revoked, closing the most likely path to a
  reportable data incident.
- **Compliance**: auditors can replay any answer (who asked, what was retrieved, what was allowed
  or denied, what was answered) with tamper evidence, which matches the logging and least-privilege
  expectations in MAS's technology and AI risk guidelines. Managers can see at a glance why each
  person has access, which supports the periodic access reviews MAS expects.
- **Productivity**: one question replaces searching four tools, and the answer arrives with its
  citations and freshness status, so staff can trust it without re-checking every source.

---

## Worked example per scenario

1. **Unified query**: John (Finance Ops) asks about the Rail-B cutover. The facts are spread across
   email, Jira, Slack and Drive, and one answer cites several of them.
2. **Data freshness**: the payment-rail failover runbook is version 8 at the source but version 7
   in the index, so it is omitted as stale; the current KYC runbook is cited.
3. **Negative permission**: Mei, an external contractor, asks for Q3 revenue and gets no figures,
   no title and no hint the board deck exists.
4. **Live revocation**: the Drive owner removes Leadership from the board deck's share. After the
   next sync, John's answer no longer uses the deck, the earlier saved answer is withheld, and
   John's line to the deck disappears from the access map, which runs the same check as retrieval.
5. **Audit inquiry**: Sam (compliance) reconstructs the question, retrieved documents and every
   allow or deny decision, reveals the answer with a recorded reason, and verifies the hash chain.

## Short description (about 120 words, if a field limits length)

Brain Sauce answers questions across Confluence, Jira, Slack and Google Drive using only
evidence the asker may see. Each platform's native permissions are checked per document before
Tencent Cloud ADP writes a word. Revocations apply on the next question in the app and within five
minutes at the source, including saved answers. Every claim is verified deterministically
(numbers and dates included), the system abstains below 60% support, and every answer carries
citations, a freshness receipt and a hash-chained audit record that compliance can replay. All
five scenarios in Aspire's challenge run end to end as automated tests: 711 pass offline, and a
contractor's model context contains zero restricted documents.

## Form checklist

| Field                        | Where                                                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Cover image, 16:9, 380 × 216 | `docs/submission/cover-380x216.png` (2×: `cover-760x432.png`)                                                |
| Architecture PPT             | `docs/presentations/internal-brain-architecture-submission.pptx` (14 slides, internal slide removed); swap the slide 9 mock-up for a real screenshot if time allows |
| GitHub URL                   | `https://github.com/pavan2184/tencent-hack`; must be public or shared with judges                            |
| Project / demo URL           | Pavan's live link, with a passcode in front of it                                                            |
| Demo video (5–8 min)         | Overview, the five scenarios, CodeBuddy reflection                                                           |
| CodeBuddy / WorkBuddy usage  | At least three screenshots of real project work: required for eligibility                                    |
