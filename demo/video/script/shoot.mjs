// Capture real UI screenshots of BrainSauce for the demo video (v2 script).
// Uses the system Chrome via puppeteer-core; the persona is set through localStorage (lib/persona.ts).
//
//   node script/shoot.mjs <out dir> <seed dir the API was started with>
//
// The API must run in memory mode on a *copy* of backend/seed (SEED_DIR=<seed dir>): scene 5 edits
// the board deck's Drive ACL in that copy and triggers a sync, which is how the source-side
// revocation is reproduced without a real Drive. The file is restored at the end.
import puppeteer from "puppeteer-core";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = process.argv[2] || "./out";
const SEED = process.argv[3];
if (!SEED) throw new Error("usage: node script/shoot.mjs <out dir> <seed dir>");
mkdirSync(OUT, { recursive: true });

const DECK_FILE = join(SEED, "corpus/gdrive-finance/files/board-deck-q3.md");
const LEADERSHIP_ACE =
  "    - { type: group, role: reader, email_or_domain: leadership, inherited: false }\n";
const Q_CUTOVER = process.env.Q_CUTOVER || "What is the plan for the Rail-B cutover?";
const Q_FAILOVER = "What is the payment rail failover procedure?";
const Q_DECK = "What were the Q3 board deck revenue figures?";
const REVEAL_REASON = "Compliance review of board deck access, case 42";

const browser = await puppeteer.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
  args: ["--no-sandbox", "--hide-scrollbars"],
});

async function api(path, actor, init = {}) {
  const res = await fetch(API + path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Actor-Id": actor, ...(init.headers || {}) },
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

async function newPage(actor) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
  await page.evaluateOnNewDocument((id) => {
    window.localStorage.setItem("actorId", id);
  }, actor);
  return page;
}

async function settle(page, ms = 800) {
  await new Promise((r) => setTimeout(r, ms));
  await page.evaluate(() => document.querySelector("nextjs-portal")?.remove());
}

async function shot(page, name, full = false) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  console.log("shot", name);
}

async function ask(page, question, name) {
  await page.goto(`${WEB}/ask`, { waitUntil: "networkidle0" });
  await page.waitForSelector('textarea[aria-label="Question"]');
  await page.type('textarea[aria-label="Question"]', question);
  await page.click('button[type="submit"]');
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll("h3, h2, div")).some((n) => n.textContent === "Answer"),
    { timeout: 30000 },
  );
  await settle(page, 1400);
  await shot(page, `${name}-fold`);
  await shot(page, `${name}-full`, true);
}

async function clickByText(page, text) {
  const btns = await page.$$("button");
  for (const b of btns) {
    const t = await page.evaluate((el) => el.textContent, b);
    if (t && t.trim() === text) {
      await b.click();
      return true;
    }
  }
  return false;
}

async function latestQuery(actor) {
  const { body } = await api("/api/queries?limit=5", actor);
  const items = body?.items || body || [];
  return items[0] || null;
}

async function sync(sourceId) {
  const r = await api(`/api/sources/${sourceId}/sync`, "root.admin", {
    method: "POST",
    body: JSON.stringify({ trigger_kind: "delta" }),
  });
  console.log("sync", sourceId, r.status);
}

async function waitFor(fn, timeoutMs, label) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await fn()) return (Date.now() - started) / 1000;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`timed out waiting for ${label}`);
}

const facts = {};

// 0. Refresh every permission snapshot (confidential ones expire five minutes after capture).
for (const s of ["confluence-ops", "jira-payments", "slack-ops", "gdrive-finance", "email-ops"]) await sync(s);
const docs = await api("/api/documents?q=board%20deck&limit=20", "john.tan");
const deck = (docs.body.items || []).find((d) => d.slug === "files/board-deck-q3");
if (!deck) throw new Error("board deck not visible to john.tan after sync");
facts.deck_id = deck.id;
await waitFor(async () => (await api(`/api/documents/${deck.id}`, "john.tan")).status === 200, 30000, "john sees deck");

// 1. John: Rail-B cutover (scene 2) and the failover runbook (scene 6, stale critical evidence omitted)
{
  const page = await newPage("john.tan");
  await ask(page, Q_CUTOVER, "john-cutover");
  // The composition uses the full-page shot twice (receipt crop, grounding tiles); HyperFrames
  // warns about one file mounted twice, so keep a second copy under its own name.
  copyFileSync(`${OUT}/john-cutover-full.png`, `${OUT}/john-cutover-grounding.png`);
  facts.cutover_query = await latestQuery("john.tan");
  await ask(page, Q_FAILOVER, "john-failover");
  facts.failover_query = await latestQuery("john.tan");
  await page.close();
}

// 2. Mei (contractor): board deck -> abstain, nothing confirms the deck exists
{
  const page = await newPage("mei.chen");
  await ask(page, Q_DECK, "mei-deck");
  await page.close();
}

// 3. John: board deck before the source-side revocation -> cited figure
{
  const page = await newPage("john.tan");
  await ask(page, Q_DECK, "john-deck-before");
  facts.deck_before_query = await latestQuery("john.tan");
  await page.close();
}

// 4. The Drive owner removes the leadership group from the share; the next sync reads it
const original = readFileSync(DECK_FILE, "utf8");
if (!original.includes(LEADERSHIP_ACE)) throw new Error("leadership ACE not found in seed copy");
writeFileSync(DECK_FILE, original.replace(LEADERSHIP_ACE, ""), "utf8");
try {
  await sync("gdrive-finance");
  facts.revoke_seconds = await waitFor(
    async () => (await api(`/api/documents/${deck.id}`, "john.tan")).status === 404,
    90000,
    "john loses the deck",
  );
  console.log("john lost the deck", facts.revoke_seconds, "s after the sync request");

  // 5. John asks again -> no deck; the earlier saved answer is withheld in history
  {
    const page = await newPage("john.tan");
    await ask(page, Q_DECK, "john-deck-after");
    facts.deck_after_query = await latestQuery("john.tan");
    const saved = await api(`/api/queries/${facts.deck_before_query.id}`, "john.tan");
    facts.deck_before_saved_status = saved.body?.status;
    // reload so the history card reflects the withheld status, then capture the card alone
    await page.goto(`${WEB}/ask`, { waitUntil: "networkidle0" });
    await settle(page, 1200);
    const card = await page.evaluateHandle(() => {
      const t = Array.from(document.querySelectorAll("*")).find((n) => n.textContent === "Recent questions");
      return t ? t.closest("[data-slot=card], .rounded-xl, div") : null;
    });
    const el = card.asElement();
    if (el) {
      await el.screenshot({ path: `${OUT}/john-history.png` });
      console.log("shot john-history");
    }
    await shot(page, "john-ask-history");
    await page.close();
  }

  // 6. Sam (compliance): chain verify, the withheld event, the reveal, the reveal event, the deny
  {
    const page = await newPage("sam.lee");
    await page.goto(`${WEB}/audit`, { waitUntil: "networkidle0" });
    await settle(page, 1000);
    await clickByText(page, "Verify chain");
    await settle(page, 1400);
    await shot(page, "sam-audit-list");

    const beforeId = facts.deck_before_query.audit_event_id;
    await page.goto(`${WEB}/audit?event=${beforeId}`, { waitUntil: "networkidle0" });
    await settle(page, 1400);
    await shot(page, "sam-audit-withheld");
    await shot(page, "sam-audit-withheld-full", true);
    await page.type('input[aria-label="Reason for revealing the answer"]', REVEAL_REASON);
    await settle(page, 300);
    await shot(page, "sam-audit-reason");
    await clickByText(page, "Reveal");
    await settle(page, 1600);
    await shot(page, "sam-audit-revealed");
    await shot(page, "sam-audit-revealed-full", true);

    await page.goto(`${WEB}/audit`, { waitUntil: "networkidle0" });
    await settle(page, 1200);
    await shot(page, "sam-audit-list-after-reveal");

    const afterId = facts.deck_after_query.audit_event_id;
    await page.goto(`${WEB}/audit?event=${afterId}`, { waitUntil: "networkidle0" });
    await settle(page, 1400);
    await shot(page, "sam-audit-deny");
    await shot(page, "sam-audit-deny-full", true);
    await page.close();

    facts.audit_before = (await api(`/api/audit/events/${beforeId}`, "sam.lee")).body;
    facts.audit_after = (await api(`/api/audit/events/${afterId}`, "sam.lee")).body;
    facts.audit_reveals = (await api(`/api/audit/events?action=audit.reveal&limit=5`, "sam.lee")).body;
    facts.audit_verify = (await api(`/api/audit/verify`, "sam.lee")).body;
    facts.audit_recent = (await api(`/api/audit/events?limit=14`, "sam.lee")).body;
  }

  // 7. Mei: the deck and a random id return the same 404
  {
    for (const [name, id] of [
      ["mei-deck-404", deck.id],
      ["mei-random-404", "00000000-0000-4000-8000-000000000000"],
    ]) {
      const page = await newPage("mei.chen");
      await page.goto(`${WEB}/documents/${id}`, { waitUntil: "networkidle0" });
      await settle(page, 1200);
      await shot(page, name);
      await page.close();
    }
    facts.mei_404 = [
      (await api(`/api/documents/${deck.id}`, "mei.chen")).body,
      (await api(`/api/documents/00000000-0000-4000-8000-000000000000`, "mei.chen")).body,
    ];
  }
} finally {
  writeFileSync(DECK_FILE, original, "utf8");
  console.log("restored the leadership share in the seed copy (API state left as revoked)");
}

// Determinism evidence for the groundedness scene: the same ask twice, compare the grounding reports.
{
  const runs = [];
  for (let i = 0; i < 2; i++) {
    const r = await api("/api/ask", "john.tan", {
      method: "POST",
      body: JSON.stringify({ question: Q_CUTOVER }),
    });
    const env = r.body || {};
    const report = env.grounding_report || env.grounding || null;
    runs.push({
      status: r.status,
      answer_status: env.status ?? env.answer?.status,
      report: report && Object.fromEntries(Object.entries(report).filter(([k]) => k !== "claims")),
      access_summary: env.access_summary,
      composer: env.composer_id ?? env.answer?.composer_id,
      timings: env.timings,
    });
  }
  facts.determinism = runs;
}
facts.health = (await api("/healthz", "john.tan")).body;
writeFileSync(`${OUT}/facts.json`, JSON.stringify(facts, null, 2));
console.log("wrote facts.json");
await browser.close();
