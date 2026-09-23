# Hackathon Requirements

Last updated: 2026-09-23

## Source and Scope

This document summarizes the requirements relevant to this repository from the
Tencent Cloud AI CAN DO IT Hackathon Singapore 2026 handbook. It is a planning
aid, not a replacement for the official handbook or submission form.

Primary handbook references:

- FinTech track and Aspire context: pages 14-19.
- Suggested tools: page 35.
- Submission requirements: page 36.
- Official competition timeline: page 37.
- Participation and submission links: page 38.
- Judging: page 39.
- Awards and participant benefits: page 40.
- Intellectual-property and privacy terms: page 41.

## Selected Track

- Track: FinTech.
- Industry challenge contributor: Aspire.
- Challenge: **The Internal Brain - Building a Context-Aware Enterprise
  Knowledge System with RBAC, Security Logging & Audit Trail**.
- The FinTech section presents one case study, and the presentation must clearly
  identify the selected case study at the beginning.

Aspire is described in the handbook as a Singapore-based fintech company with
more than 600 employees across nine countries, serving clients in more than 30
markets.

## Official Challenge Objective

Build an AI-augmented enterprise knowledge system that unifies context from:

- Confluence;
- Jira;
- Slack; and
- Google Drive.

The system must answer natural-language questions from the user's authorized
context while preserving the original platforms' access controls. It must also
provide a complete audit trail of who asked a question, what was retrieved, the
authorization decision for each item, and what answer was returned.

The challenge explicitly distinguishes the desired system from a chatbot placed
on top of ordinary search. The intended result is a governed,
permission-aware knowledge fabric with an LLM reasoning layer.

## Source-System Context

The handbook's illustrative Company A has:

- Confluence: more than 50 spaces and 12,000 pages, with space-level and
  page-level restrictions.
- Jira: more than 30 projects, project-specific role schemes, and issue-level
  security.
- Slack: more than 200 channels across multiple workspaces, including private
  channels and direct messages, retention policies, and nested threads.
- Google Drive: shared and personal drives, file-level and folder-level sharing,
  view/comment/edit permissions, and some external sharing.

These figures describe the challenge context; they are not an MVP load-test
target unless the team explicitly adopts them as one.

## Required Capabilities

### Heterogeneous source integration

- Preserve the distinct API, pagination, rate-limit, data-model, and permission
  behavior of each platform.
- Do not flatten away source-specific authorization semantics:
  - Confluence: space and page permissions.
  - Jira: project, role, and issue-level permissions.
  - Slack: channel membership.
  - Google Drive: file, folder, and user permissions.

### Permission-aware retrieval

- Resolve the asker's identity, roles, and permissions at query time.
- Filter evidence before it reaches the LLM.
- Reflect permission changes after ingestion so stale authorization cannot expose
  content.
- Avoid revealing the existence of restricted content through metadata or denial
  wording.

### Cross-platform context assembly

- Fan retrieval out across relevant platforms.
- Rank results across source types.
- Assemble a coherent context window while applying authorization to every
  constituent item.
- Return grounded answers with links to the source documents, issues, messages,
  and files.

### Security logging and audit trail

Every meaningful action must be recorded in a way that is:

- Tamper-evident: modification or deletion can be detected.
- Complete: identity, query, retrieved document IDs, final answer, timestamp, and
  per-document allow/deny decisions are captured.
- Queryable: administrators and compliance officers can investigate access by
  user or document.

### LLM safety

- Mitigate hallucination and unsupported completion.
- Prevent restricted retrieved content from entering model context.
- Account for prompt injection in retrieved content.
- Do not let the model infer or confidently invent restricted information it was
  not given.

## Mandatory Demonstration Scenarios

The handbook says the solution must demonstrably solve all five scenarios, with
a worked example for each in the submission.

1. **Unified natural-language query:** route a question to relevant platforms,
   retrieve permission-filtered evidence, and return one cited answer.
2. **Data freshness:** make created or updated source content answerable within a
   bounded, predictable window on the order of minutes to approximately one
   hour, without silently presenting stale data as current.
3. **Correct negative permission enforcement:** refuse or filter unauthorized
   evidence without leaking its contents or confirming its existence beyond
   what the user may already know.
4. **Live permission-change handling:** ensure a subsequent query no longer uses
   evidence after the user's access is revoked.
5. **Audit inquiry:** let a compliance officer reconstruct what a user asked,
   what was retrieved, the authorization decisions, and the answer, with
   timestamps.

The team's five-minute freshness goal in `PROJECT_BRIEF.md` is deliberately
stricter than the handbook's baseline.

## FinTech Deliverables

The challenge statement asks for:

- A live demo walkthrough.
- An architecture diagram showing architecture, trust boundaries, and key
  design trade-offs.
- Complete source code submitted through a GitHub repository.

The handbook notes that the listed feature details are guidance and allows
alternative approaches that meaningfully solve the problem statement. The five
demonstration scenarios above remain phrased as outcomes the solution must
demonstrably solve.

## Program-Level Submission Requirements

### Eligibility and tool use

- The project must be original.
- It must be built using at least one of CodeBuddy or WorkBuddy.
- Proof of that product usage is mandatory. Accepted evidence includes chat
  screenshots, API-call logs, or a written development-process description.
- The submission table specifically requires at least three screenshots or a
  screen recording of CodeBuddy/WorkBuddy conversation history.
- Without usage proof, the project does not proceed to scoring.

Because the handbook later says participants may build using CodeBuddy,
WorkBuddy, or Miora, this project follows the stricter submission rule: use and
document CodeBuddy or WorkBuddy even if Miora or other Tencent Cloud services are
also used.

### Required submission items

- Project title.
- Short blurb with a hard limit of fewer than 10 words.
- Project description covering:
  - target scenarios, users, and value proposition;
  - real-world pain points, target audience, and core problems;
  - business and technical architecture, including how prompts drive AI
    generation; and
  - quantified metrics or a clearly defined impact.
- At least three screenshots or a screen recording of CodeBuddy/WorkBuddy usage.
- A 16:9 cover image; recommended size: 380 x 216 pixels.

### Optional submission items

- A 5-8 minute demo video covering the project overview, core agent features and
  usage, and a short reflection on the build approach and CodeBuddy/WorkBuddy
  tips.
- A live project or demo URL, which can earn bonus points.

Although the program-level table marks the recorded demo video optional, the
FinTech challenge separately asks for a live demo walkthrough.

Submission form: <https://tinyurl.com/TCHackathonSGProjectSubmission>

## Official Competition Timeline

| Date | Official milestone |
| --- | --- |
| 16 September 2026 | Challenge kick-off and submissions open |
| 16 September-16 October 2026 | Online and offline training |
| 16 October 2026 | Project submission deadline |
| 23 October 2026 | Finalist announcement; top two teams per track advance |
| 3 November 2026 (TBC) | Singapore Hackathon Demo Day |

The earlier dates in the repository README are internal team milestones, not
organizer deadlines.

## Judging

Preliminary technical judging is performed by the challenge-contributing
industry organization and Tencent Cloud experts. The handbook says detailed
track criteria will be shared after registration.

The published general rubric allocates 10 points to each dimension, for a total
of 100 points:

| Dimension | Review focus |
| --- | --- |
| Impact & Relevance | Solves a real-world problem and creates meaningful value |
| Human-Centered Design | Serves real users well |
| AI Interaction | Quality and depth of AI usage |
| Technical Execution | Technical quality and completeness |
| Feasibility | Realistic and scalable beyond the hackathon |
| Demo & Storytelling | Effective presentation and communication |
| Innovation & Creativity | Originality and uniqueness |
| User Experience (UX & Accessibility) | Usability and accessibility |
| Responsible AI & Ethics | Responsible and trustworthy AI practices |
| Overall Quality & Judge's Impression | Overall assessment |

## Participation and Terms Relevant to the Team

- One registration is required per team.
- Teams may have one to three members, and participants must be based in
  Singapore.
- Entry intellectual-property rights remain with the entrant or team.
- Entrants must ensure the work is original and does not infringe third-party
  rights.
- Entrants grant Tencent Cloud a non-exclusive, royalty-free license to use the
  project name, description, demo screenshots or screencasts, and team
  information for non-commercial promotion, with project and team credit.

Registration link: <https://qdrl.qq.com/65xN1yft>

## Repository Compliance Checklist

- [ ] Use CodeBuddy or WorkBuddy during development.
- [ ] Preserve at least three acceptable pieces of product-usage evidence.
- [ ] Prepare a project title and a blurb under 10 words.
- [ ] Prepare the required project description and measurable impact statement.
- [ ] Prepare a 16:9 cover image.
- [ ] Demonstrate all five FinTech scenarios with worked examples.
- [ ] Prepare the live demo walkthrough.
- [ ] Prepare the architecture and trust-boundary diagram with trade-offs.
- [ ] Keep complete source code in the GitHub repository.
- [ ] Submit by 16 October 2026.
