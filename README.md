# Tencent Hack — Proof-Carrying Enterprise Knowledge

FinTech-track project for the Tencent Cloud AI CAN DO IT Hackathon Singapore 2026.

The project extends [GBrain](https://github.com/garrytan/gbrain) into a context-aware enterprise knowledge system spanning Slack, Jira, Confluence, and Google Drive. Its core goal is to produce permission-aware, current, grounded answers with a reconstructable audit trail.

## Product thesis

Enterprise AI should not merely claim that an answer is current and authorized. It should prove:

- which sources and versions supported the answer;
- when each source was last synchronized or verified;
- which access-control decisions were applied before retrieval;
- which claims are grounded in which evidence; and
- how an auditor can reconstruct the result later.

## Team workstreams

- Groundedness — Raphael
- Data freshness — Pavan
- Access control — Chai

## Current data-freshness direction

Use a layered freshness mesh:

1. Webhook fast path for source events.
2. Cursor or delta polling as a recovery path.
3. Periodic reconciliation for missed updates, deletions, and permission drift.
4. Query-time verification for critical evidence.
5. Freshness receipts exposing content version, source timestamp, index timestamp, and verification status.

Jev may help classify the semantic importance of a change, but deterministic code remains responsible for synchronization, timestamps, version checks, permission changes, retries, and safe fallback behavior.

## Timeline

These are internal team milestones leading up to the organizer's official
submission deadline:

- 3 October 2026 — team check-in
- 10 October 2026 — research finalized
- 11–13 October 2026 — implementation
- 14–15 October 2026 — video demo and submission preparation
- 16 October 2026 — submission deadline

The official handbook also lists finalist announcements on 23 October 2026 and
the Singapore Hackathon Demo Day on 3 November 2026 (TBC).

## Official requirements

The submission must use CodeBuddy or WorkBuddy and include proof of that usage.
For the FinTech track, the solution must demonstrate unified querying, bounded
data freshness, negative permission enforcement, live permission revocation,
and audit reconstruction. See the [hackathon requirements](docs/HACKATHON_REQUIREMENTS.md)
for the verified checklist, judging rubric, and organizer timeline.

## Project documents

- [Project brief](docs/PROJECT_BRIEF.md)
- [Hackathon requirements](docs/HACKATHON_REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data model](docs/DATA_MODEL.md)
- [API contract](docs/API_CONTRACT.md)
- [Testing](docs/TESTING.md)
- [Security review](docs/SECURITY_REVIEW.md)
- [Decisions](docs/DECISIONS.md)
- [Project status](docs/PROJECT_STATUS.md)
- [Project workflow](PROJECT_STARTER_SYSTEM.md)
