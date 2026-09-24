# Project Status

Last updated: 2026-09-24

## Current phase

Pinned GBrain integration and contract-first freshness planning.

## Completed

- Selected the Tencent hackathon FinTech track.
- Chosen GBrain as the base repository to extend.
- Assigned groundedness, data freshness, and access-control research owners.
- Established the layered freshness-mesh direction.
- Created the project repository and planning workspace.
- Reviewed the official hackathon handbook and captured the FinTech challenge,
  submission requirements, judging rubric, organizer timeline, and relevant
  terms in `docs/tencent/HACKATHON_REQUIREMENTS.md`.
- Rehomed Tencent-specific planning documents under `docs/tencent/`.
- Integrated the GBrain `v0.54.1.0` source history at commit
  `6040075c6cb95be5881cc2e1b76ef7d71f4e5d29`, retaining its MIT license,
  upstream documentation, source code, and tests.

## Next

- Choose CodeBuddy or WorkBuddy for documented development use and start
  preserving the mandatory usage evidence.
- Finalize data-freshness research and connector strategy.
- Replace the Tencent freshness placeholders with complete versioned contracts,
  a pinned upstream baseline, and hermetic synthetic evaluation design.
- Select live-demo connectors and controlled simulations.
- Write and approve the system design before implementation.
- Define freshness, authorization, and groundedness test fixtures.
- Map each of the five required FinTech scenarios to a worked demo fixture.
- Draft the architecture and trust-boundary diagram before submission week.

## Known risks

- The implementation window is three days.
- Live enterprise APIs may require app review, scopes, or administrator access.
- GBrain's current access model may need finer-grained source-object permissions.
- Missing CodeBuddy/WorkBuddy usage evidence would make the project ineligible
  for scoring.
- The submission package also needs a cover image, project description,
  measurable impact, live demo walkthrough, and architecture diagram.
