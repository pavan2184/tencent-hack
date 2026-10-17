# Demo video run sheet

A shot list for the 5–8 minute submission video: the five scenarios in order, with the persona,
the exact question and what to point at. Every step below was checked on 16 October 2026 against
`main` (`df1a8bf0`) with PR #24 merged, using the in-memory seed in mock mode at 1280 × 800.

On the live demo (`PROVIDER_MODE=real`, Tencent Cloud ADP) the model writes the answer, so the
wording of claims will differ. Document counts, freshness rows, "withheld", "deny" and the chain
check should match; rehearse once on the live link before recording.

## Before you record

- **Start from a fresh seed.** Restarting the in-memory API reseeds it; on Docker run
  `make reset && make up && make seed`. Record within an hour of seeding: after an hour the KYC
  runbook ages past its one-hour budget and scenario 2 changes.
- **Pick a persona first.** If the top right says "Unknown persona", choose one from the picker.
  Switching persona clears the page and shows that persona's own recent questions.
- **Keep the order.** Scenario 4 revokes a grant with one click, no confirmation and no undo in
  the UI. To retake anything after it, reseed.
- **Copy the board deck's link now.** As John Tan, open Documents → "Q3 2026 Board Deck —
  Financial Results" and copy the page URL. Scenario 3 needs it, and Mei cannot find it herself.

| Segment                        | Persona                      | Time    |
| ------------------------------ | ---------------------------- | ------- |
| Overview                       | —                            | ~1 min  |
| 1. Unified query               | John Tan                     | ~1 min  |
| 2. Freshness                   | John Tan                     | ~1 min  |
| 3. Negative permission         | Mei Chen                     | ~1 min  |
| 4. Live revocation             | John Tan → Root Admin → John | ~2 min  |
| 5. Audit inquiry               | Sam Lee                      | ~1½ min |
| CodeBuddy/WorkBuddy reflection | —                            | ~1 min  |

## 1. Unified query: one answer across four platforms

**Persona:** John Tan (Finance Ops, Leadership). **Page:** Ask.

**Ask:** `What is the plan for the Rail-B cutover?`

**Point at:**

- The badge above the answer: **11 documents allowed · policy ac-v2**. Access was filtered before
  any model saw evidence.
- **Claims and citations:** eight claims, each with a "supported" badge, cited from **email, Google
  Drive, Slack and Jira**. Each citation shows the source, its version and the exact quote.
- **Grounding:** grounded, **100% claim coverage**, 8 of 8 supported.
- **2 injection flags:** the seed plants a prompt-injection string in the 11 October `#general`
  Slack message, and the sanitizer flagged it.
- **Freshness receipt: mixed.** The payment-rail failover runbook is already marked stale and
  omitted, which sets up scenario 2.

## 2. Freshness: stale evidence is left out

**Persona:** John Tan. **Page:** Ask.

**Ask:** `What is the payment rail failover procedure and the KYC refresh cycle?`

**Point at the freshness receipt:**

- `runbooks/payment-rail-failover` · version 7 · **stale** · 14d 23h against a 1h budget · Used:
  **omitted**. The source has moved on to version 8; the index still holds 7, so it is not served
  as current.
- `runbooks/kyc-refresh` · version 4 · **fresh** · 0s against a 1h budget (checked live just now)
  · Used: **yes**.
- In the answer, the KYC claim ("set to inbound-only … until the refresh is approved") comes from
  the current KYC runbook. Nothing is quoted from the stale failover runbook; the failover
  mentions come from Slack and the board deck.

## 3. Negative permission: nothing leaks to a contractor

**Persona:** Mei Chen (external contractor). **Page:** Ask.

**Ask:** `What were the Q3 board deck revenue figures?`

**Point at:**

- **0 documents allowed**, and "The brain abstained rather than guess." No figures, no deck
  title, no hint that the deck exists.
- The freshness receipt says **not required: no evidence was evaluated**. The deck never reached
  the pipeline.
- Paste the board deck URL you copied earlier: **Not found · There is no document at this
  address.** Change a few characters of the ID and load it again: the page is identical, so a
  denied document and a missing one cannot be told apart.

**Avoid:** the dark tile still reads "100% Claim coverage" on an abstained answer. Don't zoom in
on it.

## 4. Live revocation: access removed, answers follow

**Persona:** John Tan, then Root Admin, then John Tan again.

1. **John, Ask:** `What were the Q3 board deck revenue figures?`
   - **11 documents allowed**. The answer leads with **Q3 2026 revenue: SGD 48.6 million**, up 18%
     year on year, cited to "Q3 2026 Board Deck — Financial Results".
2. **John, Access → Open the access map.**
   - **11 documents in your view · 32 access paths**.
   - Click the board deck: **2 people can read it**, John Tan via `R5:explicit_grant` and Root
     Admin via `R3:owner`. Under "Grants in effect": **group leadership · reaches John Tan**.
3. **Switch to Root Admin** (the deck's owner) and open the access map.
   - Only **2 documents in your view**. An admin role does not bypass access at the source.
   - Click the board deck, then **Revoke** next to group leadership. It applies at once: **1
     person can read it**.
   - Say: this is the in-app path, which applies on the next question. A change made at the source
     in Google Drive is picked up within five minutes.
4. **Switch back to John, page Ask.**
   - In Recent questions, the board deck question now says **withheld**, and so does the
     scenario 2 question, which also used the deck. Saved answers are re-checked too.
   - Click the board deck question to put it back in the box, then **Ask**: **10 documents
     allowed**, and the brain abstains with no figures.
5. **John, Access → Open the access map:** **10 documents in your view · 30 access paths**. The
   deck and John's line to it are gone.

## 5. Audit inquiry: reconstruct what happened

**Persona:** Sam Lee (compliance auditor). **Page:** Audit.

1. The trail lists every ask, the `grant.revoke` by root.admin and each access map view, each row
   hashed.
2. Click John's **first** ask row (`What is the plan for the Rail-B cutover?`).
   - The question, its **Hash** and **Prev hash**.
   - **Retrieved documents and access decisions (11)**: each document with **allow**, the rule
     (`R8:slack`, `R8:jira`, `R5:explicit_grant`, `R3:owner` …) and whether it was cited.
   - **Freshness receipt: mixed · 11 items · 1 omitted as unsafe**.
   - **Answer withheld**: Sam cannot open every document the answer used.
3. Type a reason (`Compliance review of the Rail-B cutover answer`) and click **Reveal**. The
   answer appears, and the reveal is itself recorded in the trail.
4. Click John's **latest** ask row (after the revocation). The board deck row reads **deny ·
   grant revoked**.
5. Click **Verify chain**: **chain intact** with the event count.

**Avoid:**

- The revealed answer currently shows raw markdown (`**2026-10-10**`, `**40% of outbound
volume**`). A fix is needed before recording; until then, don't linger on it.
- On the deny row the rule label reads `R9:permission_snapshot_stale`. Point at "grant revoked"
  underneath it.
- On the dev server, access map views appear in the trail in pairs.

## CodeBuddy/WorkBuddy reflection

Required in the video. Cover what the team used CodeBuddy or WorkBuddy for and what it changed
about how you built. The screenshots for the form are a separate requirement.
