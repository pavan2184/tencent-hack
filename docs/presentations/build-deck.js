/* Brain Sauce architecture deck generator (pptxgenjs). See README.md in this folder. */
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const si = require("react-icons/si");
const fa = require("react-icons/fa6");
// Writes THEME's colours into the .pptx theme part; without it, scheme colours fall back to
// Office defaults. APPLY_THEME is the path to the pptx skill's scripts/apply_theme.js.
const { applyTheme } = require(process.env.APPLY_THEME);

const OUT = process.argv[2] || "deck.pptx";

// Palette follows the web UI's Housend-derived tokens (frontend/app/globals.css, D-020): near-
// monochrome greys, one muted green accent, and amber/red kept only for status. Role names are
// historical: "navy" is the ink used for headings and dark bands, "blue" the secondary ink, and
// "teal" the green accent (accent-strong, so small text stays AA-legible).
const HEX = {
  ink: "1D1D1D",
  navy: "1D1D1D",
  mist: "F5F5F5",
  white: "FFFFFF",
  teal: "3F8243",
  green: "549F58",
  coral: "D9433B",
  amber: "C77A0A",
  blue: "8C8C8C",
  violet: "666666",
  slate: "737373",
  line: "D7D7D7",
  tealT: "EAF3EA",
  coralT: "FBECEB",
  amberT: "FCF3E3",
  blueT: "F5F5F5",
  violetT: "F5F5F5",
  ice: "A6A6A6",
  bar: "A6A6A6",
  soft: "8C8C8C",
};
const THEME = {
  name: "Brain Sauce",
  // Arial is the closest metric-safe stand-in for the UI's Inter Tight grotesque.
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: HEX.ink,
    lt1: HEX.white,
    dk2: HEX.navy,
    lt2: HEX.mist,
    accent1: HEX.teal,
    accent2: HEX.coral,
    accent3: HEX.amber,
    accent4: HEX.blue,
    accent5: HEX.violet,
    accent6: HEX.slate,
    hlink: HEX.blue,
    folHlink: HEX.violet,
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "Brain Sauce: architecture and trust boundaries";
pres.author = "Chai Pin Zheng";
pres.theme = {
  headFontFace: THEME.headFontFace,
  bodyFontFace: THEME.bodyFontFace,
};
const C = pres.SchemeColor;
// Scheme colours by role
const S = {
  ink: C.text1,
  navy: C.text2,
  white: C.background1,
  mist: C.background2,
  teal: C.accent1,
  coral: C.accent2,
  amber: C.accent3,
  blue: C.accent4,
  violet: C.accent5,
  slate: C.accent6,
};
const W = 13.333;
const FOOTER =
  "Brain Sauce  ·  Tencent Cloud AI CAN DO IT Hackathon SG 2026  ·  FinTech track, Aspire case study";

// ---------------------------------------------------------------- layouts
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: S.white },
  objects: [
    {
      placeholder: {
        options: {
          name: "title",
          type: "title",
          x: 0.7,
          y: 1.55,
          w: 8.6,
          h: 1.2,
          fontSize: 60,
          bold: true,
          color: S.navy,
          valign: "top",
          align: "left",
          margin: 0,
        },
        text: "",
      },
    },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: S.white },
  objects: [
    {
      placeholder: {
        options: {
          name: "title",
          type: "title",
          x: 0.6,
          y: 0.35,
          w: 12.1,
          h: 0.85,
          fontSize: 26,
          bold: true,
          color: S.navy,
          valign: "middle",
          align: "left",
          margin: 0,
        },
        text: "",
      },
    },
    {
      text: {
        text: FOOTER,
        options: {
          x: 0.6,
          y: 7.0,
          w: 10.5,
          h: 0.3,
          fontSize: 10,
          color: S.slate,
          margin: 0,
        },
      },
    },
  ],
  slideNumber: {
    x: 12.3,
    y: 7.0,
    w: 0.45,
    h: 0.3,
    fontSize: 10,
    color: S.slate,
    align: "right",
  },
});
pres.defineSlideMaster({
  title: "CLOSING_DARK",
  background: { color: S.navy },
  objects: [
    {
      placeholder: {
        options: {
          name: "title",
          type: "title",
          x: 0.7,
          y: 1.6,
          w: 11.9,
          h: 1.6,
          fontSize: 40,
          bold: true,
          color: S.white,
          valign: "top",
          align: "left",
          margin: 0,
        },
        text: "",
      },
    },
  ],
});

// ---------------------------------------------------------------- helpers
async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color: "#" + color, size: String(size) }),
  );
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

let objCount = 0;
const nm = (p) => `${p}-${++objCount}`;

function card(slide, o) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: o.x,
    y: o.y,
    w: o.w,
    h: o.h,
    rectRadius: o.r ?? 0.05,
    fill: { color: o.fill ?? S.white },
    line:
      o.line === null
        ? { type: "none" }
        : {
            color: o.line ?? HEX.line,
            width: o.lw ?? 1,
            dashType: o.dash ?? "solid",
          },
    // Flat surfaces (D-020): no drop shadows; hairline borders separate cards.
    objectName: nm(o.name ?? "card"),
  });
}

// Two-tone display title, as in the web UI: the claim in ink, the qualifier in soft grey.
function titleRuns(primary, secondary, colors = {}) {
  return [
    { text: primary, options: { color: colors.primary ?? S.navy } },
    { text: secondary, options: { color: colors.secondary ?? HEX.soft } },
  ];
}

function text(slide, runs, o) {
  slide.addText(runs, {
    x: o.x,
    y: o.y,
    w: o.w,
    h: o.h,
    margin: o.margin ?? 0,
    fontSize: o.size ?? 14,
    color: o.color ?? S.ink,
    bold: o.bold,
    italic: o.italic,
    align: o.align ?? "left",
    valign: o.valign ?? "top",
    isTextBox: true,
    paraSpaceAfter: o.psa,
    lineSpacingMultiple: o.lsm,
    objectName: nm(o.name ?? "text"),
    fit: "none",
  });
}

function arrow(slide, x1, y1, x2, y2, o = {}) {
  const x = Math.min(x1, x2),
    y = Math.min(y1, y2);
  slide.addShape(pres.shapes.LINE, {
    x,
    y,
    w: Math.abs(x2 - x1) || 0.0001,
    h: Math.abs(y2 - y1) || 0.0001,
    flipH: x2 < x1,
    flipV: y2 < y1,
    line: {
      color: o.color ?? S.slate,
      width: o.width ?? 1.75,
      dashType: o.dash ?? "solid",
      endArrowType: o.head === false ? undefined : "triangle",
      beginArrowType: o.both ? "triangle" : undefined,
    },
    objectName: nm("arrow"),
  });
}

function pill(slide, label, o) {
  slide.addText(label, {
    shape: pres.shapes.ROUNDED_RECTANGLE,
    rectRadius: o.h / 2,
    x: o.x,
    y: o.y,
    w: o.w,
    h: o.h,
    fill: { color: o.fill },
    color: o.color ?? S.white,
    fontSize: o.size ?? 11,
    bold: true,
    align: "center",
    valign: "middle",
    margin: 0,
    objectName: nm("pill"),
    isTextBox: true,
  });
}

function numDot(slide, n, x, y, d, fill) {
  // Web UI "01" markers: grey disc with ink numerals; the accent marks a positive outcome.
  const accent = fill === S.teal;
  slide.addText(String(n).padStart(2, "0"), {
    shape: pres.shapes.OVAL,
    x,
    y,
    w: d,
    h: d,
    fill: { color: accent ? S.teal : S.white },
    line: accent ? undefined : { color: HEX.line, width: 1 },
    color: accent ? S.white : S.navy,
    fontSize: d > 0.4 ? 14 : 10,
    bold: true,
    align: "center",
    valign: "middle",
    margin: 0,
    objectName: nm("num"),
    isTextBox: true,
  });
}

function iconDot(slide, data, x, y, d, fill, pad = 0.22) {
  slide.addShape(pres.shapes.OVAL, {
    x,
    y,
    w: d,
    h: d,
    fill: { color: fill },
    line: { type: "none" },
    objectName: nm("icon-bg"),
  });
  const s = d * (1 - 2 * pad);
  slide.addImage({
    data,
    x: x + (d - s) / 2,
    y: y + (d - s) / 2,
    w: s,
    h: s,
    objectName: nm("icon"),
  });
}

// ---------------------------------------------------------------- build
(async () => {
  const I = {
    confluence: await icon(si.SiConfluence, "1868DB"),
    jira: await icon(si.SiJira, "1868DB"),
    slack: await icon(si.SiSlack, "4A154B"),
    drive: await icon(si.SiGoogledrive, "1FA463"),
    shieldW: await icon(fa.FaShieldHalved, HEX.white),
    shieldTeal: await icon(fa.FaShieldHalved, HEX.teal),
    lockOpen: await icon(fa.FaLockOpen, HEX.white),
    clock: await icon(fa.FaClockRotateLeft, HEX.white),
    eyeSlash: await icon(fa.FaEyeSlash, HEX.white),
    shield: await icon(fa.FaShieldHalved, HEX.white),
    refresh: await icon(fa.FaArrowsRotate, HEX.white),
    quote: await icon(fa.FaQuoteLeft, HEX.white),
    chain: await icon(fa.FaLink, HEX.white),
    user: await icon(fa.FaUserTie, HEX.white),
    userX: await icon(fa.FaUserSlash, HEX.white),
    userClock: await icon(fa.FaUserClock, HEX.white),
    check: await icon(fa.FaCircleCheck, HEX.teal),
    xmark: await icon(fa.FaCircleXmark, HEX.coral),
    ban: await icon(fa.FaBan, HEX.coral),
    robot: await icon(fa.FaRobot, HEX.violet),
    db: await icon(fa.FaDatabase, HEX.blue),
    gears: await icon(fa.FaGears, HEX.blue),
    idcard: await icon(fa.FaIdBadge, HEX.blue),
    search: await icon(fa.FaMagnifyingGlass, HEX.blue),
    gate: await icon(fa.FaShieldHalved, HEX.white),
    fresh: await icon(fa.FaArrowsRotate, HEX.amber),
    verify: await icon(fa.FaListCheck, HEX.blue),
    ledger: await icon(fa.FaBook, HEX.violet),
    users: await icon(fa.FaUsers, HEX.slate),
  };

  // ============================================================ 1. Title
  pres.addSection({ title: "Story" });
  {
    const s = pres.addSlide({
      masterName: "TITLE_DARK",
      sectionTitle: "Story",
    });
    pill(s, "FINTECH TRACK  ·  ASPIRE CASE STUDY", {
      x: 0.7,
      y: 0.8,
      w: 3.9,
      h: 0.42,
      fill: HEX.tealT,
      color: S.teal,
      size: 12,
    });
    // Two-tone display headline, as in the web UI's page headers.
    s.addText("Brain Sauce.", { placeholder: "title" });
    text(s, "Answers with receipts.", {
      x: 0.7,
      y: 2.5,
      w: 8.6,
      h: 1.0,
      size: 54,
      bold: true,
      color: HEX.ice,
    });
    text(
      s,
      "Ask one question across Confluence, Jira, Slack and Google Drive. Get an answer built only from what you are allowed to see, with the proof attached.",
      { x: 0.7, y: 3.85, w: 7.4, h: 1.0, size: 18, color: HEX.violet },
    );
    text(
      s,
      [
        { text: "Challenge: ", options: { bold: true, color: S.navy } },
        {
          text: "Brain Sauce: a context-aware enterprise knowledge system with RBAC, security logging and audit trail",
        },
      ],
      { x: 0.7, y: 5.0, w: 7.4, h: 0.7, size: 13, color: HEX.violet },
    );
    text(
      s,
      "Team: Chai · Raphael · Pavan     |     Tencent Cloud AI CAN DO IT Hackathon Singapore 2026",
      { x: 0.7, y: 6.6, w: 11.5, h: 0.35, size: 12, color: S.slate },
    );

    // Visual: four sources -> governed answer
    const srcs = [
      ["Confluence", I.confluence],
      ["Jira", I.jira],
      ["Slack", I.slack],
      ["Google Drive", I.drive],
    ];
    srcs.forEach(([label, data], i) => {
      const y = 1.0 + i * 1.18;
      iconDot(s, data, 9.15, y, 0.8, S.mist, 0.22);
      text(s, label, {
        x: 8.95,
        y: y + 0.84,
        w: 1.2,
        h: 0.28,
        size: 11,
        color: S.slate,
        align: "center",
      });
      arrow(s, 10.05, y + 0.4, 11.0, 3.1, { color: HEX.line, width: 1.25 });
    });
    iconDot(s, I.shieldW, 11.05, 2.6, 1.1, HEX.green, 0.24);
    text(s, "Governed answer", {
      x: 10.7,
      y: 3.8,
      w: 1.8,
      h: 0.3,
      size: 12,
      bold: true,
      color: S.navy,
      align: "center",
    });
    text(s, "permitted · fresh · grounded · audited", {
      x: 10.4,
      y: 4.1,
      w: 2.4,
      h: 0.3,
      size: 10,
      color: S.slate,
      align: "center",
    });
    s.addNotes(
      "Open with the case study: Aspire's Internal Brain challenge in the FinTech track. One sentence: we answer across the four platforms, but only from evidence the asker may see, and every answer carries its proof.",
    );
  }

  // ============================================================ 2. Problem
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Story" });
    s.addText(titleRuns("A chatbot on top of search fails a fintech", " in three ways"), {
      placeholder: "title",
    });
    const cards = [
      [
        I.lockOpen,
        S.coral,
        "It leaks",
        "A contractor asks about Q3 revenue and the bot quotes the confidential board deck, because search never checked who was asking.",
      ],
      [
        I.clock,
        S.amber,
        "It goes stale",
        "The payment-rail failover runbook changed at the source. The index still serves the old version as if it were current.",
      ],
      [
        I.eyeSlash,
        S.violet,
        "It cannot be audited",
        "Compliance cannot reconstruct who asked, what was retrieved, what was denied and what the model answered.",
      ],
    ];
    cards.forEach(([ic, col, head, body], i) => {
      const x = 0.6 + i * 4.1;
      card(s, {
        x,
        y: 1.55,
        w: 3.85,
        h: 3.55,
        fill: S.mist,
        line: null,
        name: "problem-card",
      });
      iconDot(s, ic, x + 0.35, 1.85, 0.8, col);
      text(s, head, {
        x: x + 0.35,
        y: 2.85,
        w: 3.2,
        h: 0.5,
        size: 22,
        bold: true,
        color: S.navy,
      });
      text(s, body, {
        x: x + 0.35,
        y: 3.4,
        w: 3.2,
        h: 1.6,
        size: 15,
        color: S.ink,
      });
    });
    card(s, {
      x: 0.6,
      y: 5.45,
      w: 12.1,
      h: 1.2,
      fill: S.navy,
      line: null,
      name: "context-band",
    });
    const stats = [
      ["600+", "employees"],
      ["9", "countries"],
      ["30+", "client markets"],
      ["4", "platforms, 4 permission models"],
    ];
    stats.forEach(([n, l], i) => {
      const x = 0.95 + i * 2.55;
      text(s, n, {
        x,
        y: 5.55,
        w: 2.3,
        h: 0.6,
        size: 30,
        bold: true,
        color: S.white,
      });
      text(s, l, { x, y: 6.12, w: 2.4, h: 0.4, size: 13, color: HEX.ice });
    });
    text(s, "Aspire, per the challenge brief", {
      x: 10.9,
      y: 5.62,
      w: 1.7,
      h: 0.9,
      size: 11,
      italic: true,
      color: HEX.ice,
    });
  }

  // ============================================================ 3. Four guarantees
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Story" });
    s.addText(
      titleRuns("One governed pipeline,", " four guarantees on every answer"),
      { placeholder: "title" },
    );
    const p = [
      [
        I.shield,
        S.teal,
        HEX.tealT,
        "Permitted",
        "Native Confluence, Jira, Slack and Drive permissions are checked per document, before any model call.",
      ],
      [
        I.refresh,
        S.amber,
        HEX.amberT,
        "Fresh",
        "Critical evidence is live-verified at the source. Stale versions are omitted, never shown as current.",
      ],
      [
        I.quote,
        S.blue,
        HEX.blueT,
        "Grounded",
        "Every claim is checked against its cited evidence, numbers and dates included. Below the bar, the system abstains rather than guesses.",
      ],
      [
        I.chain,
        S.violet,
        HEX.violetT,
        "Audited",
        "A hash-chained record of the asker, retrieved IDs, every allow/deny decision and the final answer.",
      ],
    ];
    p.forEach(([ic, col, tint, head, body], i) => {
      const x = 0.6 + i * 3.08;
      card(s, {
        x,
        y: 1.55,
        w: 2.85,
        h: 4.0,
        fill: tint,
        line: null,
        name: "pillar",
      });
      iconDot(s, ic, x + 0.3, 1.85, 0.85, col);
      text(s, head, {
        x: x + 0.3,
        y: 2.95,
        w: 2.3,
        h: 0.55,
        size: 24,
        bold: true,
        color: S.navy,
      });
      text(s, body, {
        x: x + 0.3,
        y: 3.55,
        w: 2.3,
        h: 2.2,
        size: 15,
        color: S.ink,
      });
    });
    text(
      s,
      [
        {
          text: "One pipeline, three front doors: ",
          options: { bold: true, color: S.navy },
        },
        {
          text: "the web app, the REST API and MCP tools for AI agents all run the same checks, so there is no back door around them.",
        },
      ],
      { x: 0.6, y: 5.75, w: 12.1, h: 0.6, size: 15 },
    );
  }

  // ============================================================ 4. Architecture (hero)
  pres.addSection({ title: "Architecture" });
  {
    const s = pres.addSlide({
      masterName: "CONTENT",
      sectionTitle: "Architecture",
    });
    s.addText(
      titleRuns("Restricted evidence never reaches", " the language model"),
      { placeholder: "title" },
    );

    const BW = 1.5,
      BH = 1.32,
      Y = 2.05,
      gap = 0.33;
    const X = (i) => 0.6 + i * (BW + gap) - 0.18 * (i > 0 ? 0 : 0);
    const xs = [0.45, 2.28, 4.11, 5.94, 7.77, 9.6, 11.43];

    // Zones
    card(s, {
      x: 0.32,
      y: 1.6,
      w: 1.76,
      h: 1.92,
      fill: S.white,
      line: S.slate,
      dash: "dash",
      r: 0.06,
      name: "zone-untrusted",
    });
    text(s, "UNTRUSTED", {
      x: 0.32,
      y: 1.64,
      w: 1.76,
      h: 0.25,
      size: 10,
      bold: true,
      color: S.slate,
      align: "center",
    });
    card(s, {
      x: 2.15,
      y: 1.6,
      w: 7.25,
      h: 1.92,
      fill: HEX.mist,
      line: null,
      r: 0.06,
      name: "zone-server",
    });
    text(s, "TRUSTED SERVER  ·  governed pipeline", {
      x: 2.25,
      y: 1.64,
      w: 5,
      h: 0.25,
      size: 10,
      bold: true,
      color: S.navy,
    });
    card(s, {
      x: 9.47,
      y: 1.6,
      w: 1.76,
      h: 1.92,
      fill: HEX.violetT,
      line: S.violet,
      dash: "dash",
      r: 0.06,
      name: "zone-model",
    });
    text(s, "MODEL ZONE", {
      x: 9.47,
      y: 1.64,
      w: 1.76,
      h: 0.25,
      size: 10,
      bold: true,
      color: S.violet,
      align: "center",
    });
    card(s, {
      x: 11.3,
      y: 1.6,
      w: 1.76,
      h: 1.92,
      fill: HEX.mist,
      line: null,
      r: 0.06,
      name: "zone-server-2",
    });
    text(s, "TRUSTED SERVER", {
      x: 11.3,
      y: 1.64,
      w: 1.76,
      h: 0.25,
      size: 10,
      bold: true,
      color: S.navy,
      align: "center",
    });

    const boxes = [
      ["Asker", "Employee, contractor, auditor or agent", S.white, S.slate],
      [
        "① Identity",
        "Resolved server-side; demo personas, SSO in production",
        S.white,
        S.blue,
      ],
      [
        "② Search",
        "Hybrid keyword + vector search across all four sources",
        S.white,
        S.blue,
      ],
      [
        "③ Access gate",
        "Allow/deny per document; permissions under 5 min old",
        HEX.tealT,
        S.teal,
      ],
      [
        "④ Fresh + safe",
        "Live-verify critical docs; screen injection",
        S.white,
        S.amber,
      ],
      [
        "⑤ LLM",
        "Tencent Cloud ADP composes from cited spans",
        S.white,
        S.violet,
      ],
      ["⑥ Verify", "Deterministic check of each claim; no LLM judge", S.white, S.blue],
    ];
    boxes.forEach(([h, b, fill, col], i) => {
      card(s, {
        x: xs[i],
        y: Y,
        w: BW,
        h: BH,
        fill,
        line: col,
        lw: i === 3 ? 2.25 : 1.25,
        name: "step",
      });
      text(s, h, {
        x: xs[i] + 0.1,
        y: Y + 0.1,
        w: BW - 0.2,
        h: 0.32,
        size: 13,
        bold: true,
        color: S.navy,
      });
      text(s, b, {
        x: xs[i] + 0.1,
        y: Y + 0.45,
        w: BW - 0.2,
        h: 0.82,
        size: 10.5,
        color: S.ink,
      });
      if (i < boxes.length - 1)
        arrow(s, xs[i] + BW, Y + BH / 2, xs[i + 1], Y + BH / 2, {
          color: i === 3 || i === 4 ? S.teal : S.slate,
        });
    });

    // Answer return path (top)
    const ry = 1.42;
    arrow(s, xs[6] + BW / 2, 1.6, xs[6] + BW / 2, ry, {
      head: false,
      color: S.teal,
    });
    arrow(s, xs[6] + BW / 2, ry, xs[0] + BW / 2, ry, {
      head: false,
      color: S.teal,
    });
    arrow(s, xs[0] + BW / 2, ry, xs[0] + BW / 2, 1.6, { color: S.teal });
    text(
      s,
      "Cited answer + freshness receipt + grounding report + access summary (allowed count only)",
      {
        x: 2.4,
        y: 1.17,
        w: 8.5,
        h: 0.24,
        size: 10.5,
        bold: true,
        color: S.teal,
        align: "center",
      },
    );

    // Model-context boundary
    const tbx = 7.6;
    arrow(s, tbx, 1.55, tbx, 3.5, {
      head: false,
      color: S.coral,
      width: 2.25,
      dash: "dash",
    });
    pill(s, "MODEL-CONTEXT BOUNDARY", {
      x: tbx - 0.95,
      y: 3.5,
      w: 1.9,
      h: 0.3,
      fill: S.coral,
      size: 8,
    });

    // Denied callout
    card(s, {
      x: 7.75,
      y: 3.95,
      w: 2.3,
      h: 0.92,
      fill: HEX.coralT,
      line: S.coral,
      name: "denied-callout",
    });
    s.addImage({
      data: I.ban,
      x: 7.85,
      y: 4.05,
      w: 0.3,
      h: 0.3,
      objectName: nm("ban"),
    });
    text(
      s,
      [
        {
          text: "Denied documents stop at the gate. ",
          options: { bold: true, color: S.coral },
        },
        {
          text: "Their text never reaches the model; only the audit log records it.",
        },
      ],
      { x: 8.22, y: 3.99, w: 1.78, h: 0.85, size: 9.5, valign: "middle" },
    );

    // Ingestion row
    const by = 5.1,
      bh = 1.45;
    card(s, {
      x: 0.32,
      y: by - 0.12,
      w: 2.0,
      h: bh + 0.24,
      fill: S.white,
      line: S.slate,
      dash: "dash",
      r: 0.06,
      name: "zone-sources",
    });
    text(s, "SOURCES  (text is untrusted)", {
      x: 0.32,
      y: by - 0.08,
      w: 2.0,
      h: 0.22,
      size: 9,
      bold: true,
      color: S.slate,
      align: "center",
    });
    [
      ["Confluence", I.confluence],
      ["Jira", I.jira],
      ["Slack", I.slack],
      ["Google Drive", I.drive],
    ].forEach(([l, d], i) => {
      const yy = by + 0.2 + i * 0.34;
      s.addImage({
        data: d,
        x: 0.5,
        y: yy,
        w: 0.26,
        h: 0.26,
        objectName: nm("src-icon"),
      });
      text(s, l, {
        x: 0.85,
        y: yy,
        w: 1.4,
        h: 0.26,
        size: 12,
        valign: "middle",
      });
    });
    const ing = [
      [
        2.6,
        2.35,
        I.gears,
        "Sync workers",
        "Celery: webhooks and syncs. Re-reads every page's permissions each minute.",
      ],
      [
        5.25,
        3.1,
        I.db,
        "Postgres + pgvector",
        "Pages, chunks, embeddings, permission snapshots and grants",
      ],
      [
        9.6,
        3.33,
        I.ledger,
        "Audit log",
        "Append-only, hash-chained: who asked, what was retrieved, each allow/deny, the answer",
      ],
    ];
    ing.forEach(([x, w, ic, h, b]) => {
      card(s, {
        x,
        y: by,
        w,
        h: bh,
        fill: S.white,
        line: x > 9 ? S.violet : S.blue,
        lw: 1.25,
        name: "store",
      });
      s.addImage({
        data: ic,
        x: x + 0.15,
        y: by + 0.15,
        w: 0.34,
        h: 0.34,
        objectName: nm("store-icon"),
      });
      text(s, h, {
        x: x + 0.58,
        y: by + 0.13,
        w: w - 0.7,
        h: 0.38,
        size: 13,
        bold: true,
        color: S.navy,
        valign: "middle",
      });
      text(s, b, { x: x + 0.15, y: by + 0.6, w: w - 0.3, h: 0.95, size: 11 });
    });
    arrow(s, 2.32, by + bh / 2, 2.6, by + bh / 2);
    arrow(s, 4.95, by + bh / 2, 5.25, by + bh / 2);
    // Store -> search / gate
    arrow(s, 5.0, by, 5.0, Y + BH, { color: S.blue });
    text(s, "candidates", {
      x: 4.12,
      y: 3.92,
      w: 0.85,
      h: 0.22,
      size: 9.5,
      color: S.blue,
      align: "right",
    });
    arrow(s, 6.55, by, 6.55, Y + BH, { color: S.teal });
    text(s, "permissions, reloaded every query", {
      x: 6.62,
      y: 4.45,
      w: 1.1,
      h: 0.42,
      size: 9.5,
      color: S.teal,
    });
    // Verify -> audit
    arrow(s, xs[6] + BW / 2, Y + BH, xs[6] + BW / 2, by, { color: S.violet });
    text(s, "one audit event per question", {
      x: 10.1,
      y: 3.92,
      w: 1.95,
      h: 0.42,
      size: 9.5,
      color: S.violet,
      align: "right",
    });

    text(
      s,
      "Green path: authorised evidence only.  Red dashed line: nothing denied crosses it.  Dashed boxes: untrusted or external.  Production Slack is searched live, never stored.",
      {
        x: 0.32,
        y: 6.75,
        w: 12.7,
        h: 0.24,
        size: 9.5,
        italic: true,
        color: S.slate,
      },
    );
    s.addNotes(
      "Walk left to right. Identity is resolved by the server, never trusted from the client. Search over-fetches candidates. The access gate evaluates each document against native permissions reloaded on every query. Only then does anything reach freshness checks, prompt-injection screening and the Tencent ADP model. The red line is the key trust boundary: denied text never crosses it. Verification drops unsupported claims; one hash-chained audit event records the whole decision trail. Precision for questions: ingestion does embed every document so search works, so the embedding provider processes all content and the vector store is protected like the source data. The gate protects the language model that writes the answer.",
    );
  }

  // ============================================================ 5. Trust boundaries
  {
    const s = pres.addSlide({
      masterName: "CONTENT",
      sectionTitle: "Architecture",
    });
    s.addText(titleRuns("Four trust boundaries,", " each failing closed"), {
      placeholder: "title",
    });
    const rows = [
      [
        S.blue,
        "Who is asking",
        "The server resolves the asker and their current groups. The client's claim is never trusted.",
        "Unknown or inactive principal: deny everything",
      ],
      [
        S.teal,
        "What they may see",
        "Every candidate document is checked against its native platform permissions before any model call. Permissions over 5 minutes old no longer count.",
        "Missing, unreadable or expired permissions: deny",
      ],
      [
        S.coral,
        "What the model receives",
        "Only authorised, fresh, sanitised evidence spans. Retrieved text is treated as data, never as instructions.",
        "Prompt-injection text: quarantined",
      ],
      [
        S.violet,
        "What leaves the system",
        "Denials look exactly like missing documents. Saved answers are re-checked each time they are opened.",
        "Revoked or untraceable evidence: answer withheld",
      ],
    ];
    rows.forEach(([col, head, body, fail], i) => {
      const y = 1.5 + i * 1.32;
      card(s, {
        x: 0.6,
        y,
        w: 12.1,
        h: 1.15,
        fill: S.mist,
        line: null,
        name: "tb-row",
      });
      numDot(s, i + 1, 0.85, y + 0.3, 0.55, col);
      text(s, head, {
        x: 1.65,
        y: y + 0.14,
        w: 2.85,
        h: 0.85,
        size: 18,
        bold: true,
        color: S.navy,
        valign: "middle",
      });
      text(s, body, {
        x: 4.6,
        y: y + 0.14,
        w: 4.75,
        h: 0.88,
        size: 14,
        valign: "middle",
      });
      card(s, {
        x: 9.55,
        y: y + 0.2,
        w: 2.95,
        h: 0.75,
        fill: S.white,
        line: col,
        name: "failclosed",
      });
      text(s, fail, {
        x: 9.7,
        y: y + 0.22,
        w: 2.7,
        h: 0.71,
        size: 12,
        bold: true,
        color: col,
        valign: "middle",
      });
    });
    text(s, "FAILS CLOSED TO", {
      x: 9.55,
      y: 1.25,
      w: 2.95,
      h: 0.24,
      size: 10,
      bold: true,
      color: S.slate,
    });
  }

  // ============================================================ 6. Native permissions
  {
    const s = pres.addSlide({
      masterName: "CONTENT",
      sectionTitle: "Architecture",
    });
    s.addText(
      titleRuns("Each platform keeps its own permission model,", " never flattened"),
      { placeholder: "title" },
    );
    const src = [
      [
        I.confluence,
        "Confluence",
        "Space view permission, plus page restrictions, plus every parent page's restrictions",
        "A parent page whose restrictions were not captured denies access",
      ],
      [
        I.jira,
        "Jira",
        "Browse Projects role, plus the issue's security level",
        "Project access alone never reveals a restricted issue",
      ],
      [
        I.slack,
        "Slack",
        "Channel membership. Production: live search as the user, nothing stored",
        "Guests, bots and other workspaces never inherit public access",
      ],
      [
        I.drive,
        "Google Drive",
        "Effective file permissions: users, groups and domains",
        "Expired, deleted and link-only shares do not make a file searchable",
      ],
    ];
    src.forEach(([ic, name, rule, edge], i) => {
      const x = 0.6 + (i % 2) * 6.15,
        y = 1.45 + Math.floor(i / 2) * 2.15;
      card(s, {
        x,
        y,
        w: 5.95,
        h: 1.95,
        fill: S.white,
        line: HEX.line,
        shadow: true,
        name: "src-card",
      });
      iconDot(s, ic, x + 0.25, y + 0.25, 0.7, S.mist, 0.2);
      text(s, name, {
        x: x + 1.1,
        y: y + 0.3,
        w: 4.6,
        h: 0.5,
        size: 20,
        bold: true,
        color: S.navy,
        valign: "middle",
      });
      text(s, rule, { x: x + 1.1, y: y + 0.85, w: 4.65, h: 0.5, size: 13 });
      s.addImage({
        data: I.check,
        x: x + 1.1,
        y: y + 1.45,
        w: 0.25,
        h: 0.25,
        objectName: nm("check"),
      });
      text(s, edge, {
        x: x + 1.45,
        y: y + 1.4,
        w: 4.35,
        h: 0.45,
        size: 12,
        italic: true,
        color: S.teal,
        valign: "middle",
      });
    });
    card(s, {
      x: 0.6,
      y: 5.85,
      w: 12.1,
      h: 0.95,
      fill: S.navy,
      line: null,
      name: "equation",
    });
    text(
      s,
      [
        {
          text: "Native source access  ∩  local policy  =  allowed evidence",
          options: {
            bold: true,
            fontSize: 20,
            color: S.white,
            breakLine: true,
          },
        },
        {
          text: "A local grant can narrow access, never widen it. Confidential documents also need the owner, an admin or an active grant.",
          options: { fontSize: 13, color: HEX.ice },
        },
      ],
      { x: 0.9, y: 5.92, w: 11.6, h: 0.82, valign: "middle" },
    );
  }

  // ============================================================ 7. Demo storyboard
  pres.addSection({ title: "Proof" });
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
    s.addText(titleRuns("The access-control demo", " in three scenes"), {
      placeholder: "title",
    });
    const scenes = [
      [
        I.user,
        S.teal,
        "Authorised employee",
        "John Tan · Finance Ops, Leadership",
        "“What were the Q3 board deck revenue figures?”",
        [
          {
            text: "Q3 2026 revenue: SGD 48.6 million, up 18% year on year",
            options: { bold: true, breakLine: true },
          },
          {
            text: "[E4] Q3 2026 Board Deck · Google Drive · 8/8 claims supported",
            options: { color: S.blue, fontSize: 11 },
          },
        ],
        "Answered, with citations",
        HEX.tealT,
      ],
      [
        I.userX,
        S.coral,
        "Unauthorised contractor",
        "Mei Chen · external contractor",
        "“What were the Q3 board deck revenue figures?”",
        [
          {
            text: "“There is not enough evidence to answer this question.”",
            options: { bold: true, breakLine: true },
          },
          {
            text: "11 of 11 candidates denied before the model; opening the deck gives the same 404 as a missing file",
            options: { fontSize: 11, color: S.slate },
          },
        ],
        "Nothing leaked, nothing confirmed",
        HEX.coralT,
      ],
      [
        I.userClock,
        S.amber,
        "Revoked at the source",
        "Drive owner removes Leadership from the share",
        "John asks again, then reopens the earlier answer",
        [
          {
            text: "Next sync (each minute): the deck is gone",
            options: { bold: true, breakLine: true },
          },
          {
            text: "The saved answer is withheld too",
            options: { fontSize: 11, color: S.slate },
          },
        ],
        "Enforced within 5 minutes, even if a sync is missed",
        HEX.amberT,
      ],
    ];
    scenes.forEach(([ic, col, head, who, q, ans, verdict, tint], i) => {
      const x = 0.6 + i * 4.1;
      card(s, {
        x,
        y: 1.45,
        w: 3.85,
        h: 5.3,
        fill: S.mist,
        line: null,
        name: "scene",
      });
      numDot(s, i + 1, x + 0.25, 1.65, 0.45, col);
      text(s, head, {
        x: x + 0.85,
        y: 1.62,
        w: 2.9,
        h: 0.5,
        size: 18,
        bold: true,
        color: S.navy,
        valign: "middle",
      });
      iconDot(s, ic, x + 0.25, 2.3, 0.55, col);
      text(s, who, {
        x: x + 0.95,
        y: 2.3,
        w: 2.8,
        h: 0.55,
        size: 12,
        color: S.slate,
        valign: "middle",
      });
      text(s, q, {
        x: x + 0.25,
        y: 3.05,
        w: 3.35,
        h: 0.75,
        size: 14,
        italic: true,
        color: S.ink,
      });
      card(s, {
        x: x + 0.25,
        y: 3.9,
        w: 3.35,
        h: 1.35,
        fill: S.white,
        line: HEX.line,
        name: "answer-mock",
      });
      text(s, ans, {
        x: x + 0.4,
        y: 3.98,
        w: 3.05,
        h: 1.2,
        size: 13,
        valign: "middle",
      });
      card(s, {
        x: x + 0.25,
        y: 5.45,
        w: 3.35,
        h: 1.05,
        fill: tint,
        line: col,
        name: "verdict",
      });
      text(s, verdict, {
        x: x + 0.4,
        y: 5.5,
        w: 3.05,
        h: 0.95,
        size: 14,
        bold: true,
        color: col,
        valign: "middle",
      });
      if (i < 2)
        arrow(s, x + 3.88, 4.55, x + 4.08, 4.55, {
          color: S.slate,
          width: 1.5,
        });
    });
    text(
      s,
      "Synthetic company and figures. Each scene is an automated test: test_ask_pipeline.py, test_permission_freshness.py and test_query_history_access.py.",
      {
        x: 0.6,
        y: 6.78,
        w: 12.1,
        h: 0.22,
        size: 10,
        italic: true,
        color: S.slate,
      },
    );
  }

  // ============================================================ 8. Five scenarios
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
    s.addText(
      titleRuns("All five mandatory scenarios run end to end,", " and each is a test"),
      { placeholder: "title" },
    );
    const H = (t) => ({
      text: t,
      options: {
        bold: true,
        color: S.white,
        fill: { color: S.navy },
        fontSize: 13,
      },
    });
    const row = (n, a, b, c) => [
      {
        text: n,
        options: { bold: true, color: S.navy, align: "center", fontSize: 16 },
      },
      { text: a, options: { bold: true, color: S.navy } },
      { text: b },
      { text: c, options: { fontSize: 11, color: S.slate } },
    ];
    s.addTable(
      [
        [H(""), H("Scenario"), H("What a judge sees"), H("Proof")],
        row(
          "1",
          "Unified query",
          "John asks about the Rail-B cutover and gets one answer citing an email, Jira PAY-150, two Slack channels and the Drive vendor list (8/8 claims supported)",
          "test_unified_cited_query",
        ),
        row(
          "2",
          "Data freshness",
          "The failover runbook is v8 at the source but v7 in the index: omitted as stale. The fresh KYC runbook is cited",
          "test_bounded_freshness_stale_omitted",
        ),
        row(
          "3",
          "Negative permission",
          "Mei, a contractor, gets no restricted content; a denied document returns the same 404 as a missing one",
          "test_negative_permission_no_existence_leak",
        ),
        row(
          "4",
          "Live revocation",
          "Leadership is removed from the Drive share (or the in-app grant revoked): John's next answer drops the board deck and the saved answer is withheld",
          "test_permission_freshness, test_live_revocation_changes_next_answer, test_query_history_access",
        ),
        row(
          "5",
          "Audit inquiry",
          "Sam, an auditor, reconstructs the question, retrieved IDs and each allow/deny; the answer needs a recorded reveal with a reason. The hash chain verifies",
          "test_audit_reconstruction, test_audit_need_to_know",
        ),
      ],
      {
        x: 0.6,
        y: 1.45,
        w: 12.1,
        colW: [0.55, 2.0, 6.15, 3.4],
        fontSize: 13,
        color: S.ink,
        border: { type: "solid", pt: 0.75, color: HEX.line },
        fill: { color: S.white },
        valign: "middle",
        margin: [0.06, 0.1, 0.06, 0.1],
        rowH: [0.45, 0.85, 0.85, 0.85, 0.85, 0.85],
        objectName: nm("scenario-table"),
      },
    );
    text(
      s,
      "Bonus: a prompt-injection string planted in #general is quarantined by the sanitiser before composition.",
      {
        x: 0.6,
        y: 6.4,
        w: 12.1,
        h: 0.3,
        size: 12,
        italic: true,
        color: S.slate,
      },
    );
  }

  // ============================================================ 9. Answer receipts
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
    s.addText(titleRuns("Every answer ships", " with its own receipts"), {
      placeholder: "title",
    });
    // Answer card, laid out like the web UI's answer view, with values from a real run on main
    // (demo corpus, mock model, 16 Oct 2026).
    card(s, {
      x: 0.6,
      y: 1.5,
      w: 5.9,
      h: 5.2,
      fill: S.white,
      line: HEX.line,
      name: "answer-card",
    });
    text(s, "“What were the Q3 board deck revenue figures?”  ·  John Tan", {
      x: 0.9,
      y: 1.68,
      w: 5.3,
      h: 0.35,
      size: 12,
      italic: true,
      color: S.slate,
    });
    text(
      s,
      [
        {
          text: "Q3 2026 revenue: SGD 48.6 million, up 18% year on year (Q3 2025: SGD 41.2 million). ",
          options: { color: S.ink },
        },
        { text: "[E4]", options: { color: S.teal, bold: true } },
        { text: " Q4 2026 revenue guidance: SGD 50 to 52 million. ", options: { color: S.ink } },
        { text: "[E1]", options: { color: S.teal, bold: true } },
      ],
      { x: 0.9, y: 2.08, w: 5.3, h: 1.05, size: 14 },
    );
    // Grounding tiles: the green coverage tile and grey stat tiles, as in the app.
    card(s, { x: 0.9, y: 3.25, w: 1.6, h: 1.25, fill: HEX.green, line: null, name: "coverage-tile" });
    text(s, "100%", { x: 1.02, y: 3.32, w: 1.4, h: 0.6, size: 30, bold: true, color: S.white });
    text(s, "Claim coverage", { x: 1.02, y: 4.1, w: 1.4, h: 0.3, size: 10, color: S.white });
    [
      ["8", "claims", S.navy],
      ["8", "supported", S.navy],
      ["2", "injection flags", S.coral],
    ].forEach(([n, label, col], i) => {
      const x = 2.6 + i * 1.22;
      card(s, { x, y: 3.25, w: 1.12, h: 1.25, fill: S.mist, line: null, name: "stat-tile" });
      text(s, n, { x: x + 0.12, y: 3.32, w: 0.9, h: 0.6, size: 26, bold: true, color: col });
      text(s, label, { x: x + 0.12, y: 4.1, w: 0.95, h: 0.3, size: 10, color: S.slate });
    });
    const parts = [
      [S.navy, "[E4]  Q3 2026 Board Deck · Google Drive · supported"],
      [S.amber, "Freshness: mixed · stale failover runbook omitted"],
      [S.teal, "Access: 11 documents allowed · policy ac-v2"],
      [S.navy, "Audit #f40c83b6 · hash chain verified"],
    ];
    parts.forEach(([col, label], i) => {
      const y = 4.68 + i * 0.42;
      card(s, {
        x: 0.9,
        y,
        w: 5.3,
        h: 0.34,
        fill: S.white,
        line: HEX.line,
        r: 0.17,
        name: "receipt-line",
      });
      text(s, label, {
        x: 1.08,
        y,
        w: 5.0,
        h: 0.34,
        size: 11,
        color: col,
        bold: true,
        valign: "middle",
      });
    });
    text(s, "Real output on main (demo corpus, mock model), 16 Oct 2026.", {
      x: 0.9,
      y: 6.38,
      w: 5.3,
      h: 0.26,
      size: 9.5,
      italic: true,
      color: S.slate,
    });

    const notes = [
      [
        S.blue,
        "Claim-level citations",
        "Each claim links to the quoted span and the source document, issue, message or file.",
      ],
      [
        S.amber,
        "Freshness receipt",
        "Per-document status. Critical evidence is live-verified; stale items are omitted and flagged.",
      ],
      [
        S.teal,
        "Grounding report",
        "Support score per claim, overall verdict, quarantined injection evidence. Below the bar, it abstains.",
      ],
      [
        S.teal,
        "Access summary",
        "Only the allowed count. Never denied counts, titles or reasons.",
      ],
      [
        S.violet,
        "Audit ID",
        "Opens the hash-chained record. Auditors see every decision; answer text they can't open needs a recorded reveal.",
      ],
    ];
    notes.forEach(([col, h, b], i) => {
      const y = 1.5 + i * 1.04;
      numDot(s, i + 1, 6.95, y + 0.08, 0.42, col);
      text(s, h, {
        x: 7.55,
        y,
        w: 5.1,
        h: 0.36,
        size: 16,
        bold: true,
        color: S.navy,
      });
      text(s, b, { x: 7.55, y: y + 0.36, w: 5.1, h: 0.6, size: 12.5 });
    });
  }

  // ============================================================ 9b. How we compare
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
    s.addText(titleRuns("Glean and Copilot's foundation,", " plus what they don't document"), {
      placeholder: "title",
    });
    const H = (t, ours = false) => ({
      text: t,
      options: {
        bold: true,
        color: S.white,
        fill: { color: ours ? S.teal : S.navy },
        fontSize: 12,
        align: "center",
      },
    });
    const yes = (t = "Yes") => ({ text: t, options: { color: S.teal, bold: true, align: "center" } });
    const no = (t) => ({ text: t, options: { color: S.coral, bold: true, align: "center" } });
    const nd = (t = "Not documented") => ({ text: t, options: { color: S.slate, align: "center" } });
    const ours = (t) => ({
      text: t,
      options: { color: S.teal, bold: true, align: "center", fill: { color: HEX.tealT } },
    });
    const row = (label, cells, o) => [
      { text: label, options: { bold: true, color: S.navy } },
      ...cells,
      ours(o),
    ];
    s.addTable(
      [
        [
          { text: "", options: { fill: { color: S.navy } } },
          H("Glean"),
          H("Microsoft 365 Copilot"),
          H("Gemini Enterprise"),
          H("Amazon Q Business"),
          H("Brain Sauce", true),
        ],
        row("Filters evidence before the model", [yes(), yes(), yes(), yes()], "Yes"),
        row(
          "Missing permissions mean no access",
          [nd(), yes("Yes (Confluence connector)"), nd(), no("No: treated as public")],
          "Yes",
        ),
        row("Saved answers re-checked after revocation", [nd(), nd(), nd(), nd()], "Yes"),
        row(
          "Audit logs every allow/deny, including filtered-out documents",
          [nd("Events only"), nd("Accessed items only"), nd("Prompts and grounding, opt-in"), nd("Conversation logs")],
          "Yes",
        ),
        row("Tamper-evident audit log", [nd(), nd(), nd(), nd()], "Hash chain"),
        row(
          "Delay before a permission change applies",
          [nd("Drive: 1 h default"), nd("Confluence: daily full crawl"), nd("Identity sync: 30 min to 7 days"), nd("Each crawl: hourly or slower")],
          "5 min maximum, enforced",
        ),
      ],
      {
        x: 0.6,
        y: 1.45,
        w: 12.1,
        colW: [2.9, 1.7, 1.95, 1.85, 1.85, 1.85],
        fontSize: 11.5,
        color: S.ink,
        border: { type: "solid", pt: 0.75, color: HEX.line },
        fill: { color: S.white },
        valign: "middle",
        margin: [0.05, 0.08, 0.05, 0.08],
        rowH: [0.5, 0.62, 0.62, 0.62, 0.72, 0.62, 0.72],
        objectName: nm("comparison-table"),
      },
    );
    text(
      s,
      "From each vendor's public documentation as of 13 Oct 2026. “Not documented” means we found nothing in their docs, not that the feature is absent. Sources: docs/ACCESS_CONTROL_INDUSTRY_REVIEW.md.",
      { x: 0.6, y: 6.15, w: 12.1, h: 0.5, size: 10.5, italic: true, color: S.slate },
    );
    s.addNotes(
      "We did not invent a new access model: the foundation is the one Glean, Microsoft and Google document. What we add is accountability: saved answers re-checked, every allow and deny logged in a tamper-evident chain, and a hard five-minute limit on stale permissions. Sources: Glean docs (security principles, crawl refresh rates), Microsoft Learn (Confluence Cloud connector, Purview Copilot audit), Google Cloud (Gemini Enterprise connectors), AWS Amazon Q Business connector concepts.",
    );
  }

  // ============================================================ 9c. Revocation delay chart
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
    s.addText(titleRuns("A revocation at the source", " is enforced within 5 minutes"), {
      placeholder: "title",
    });
    s.addChart(
      pres.charts.BAR,
      [
        {
          name: "Minutes until a permission change applies",
          labels: [
            "Microsoft 365 Copilot, Confluence connector",
            "Glean, Google Drive identity refresh",
            "Gemini Enterprise, fastest identity sync",
            "Brain Sauce, confidential documents",
          ],
          values: [1440, 60, 30, 5],
        },
      ],
      {
        x: 0.6,
        y: 1.45,
        w: 7.7,
        h: 4.75,
        barDir: "bar",
        catAxisOrientation: "maxMin",
        valAxisLogScaleBase: 10,
        valAxisMinVal: 1,
        valAxisMaxVal: 10000,
        valAxisHidden: true,
        valGridLine: { style: "none" },
        catGridLine: { style: "none" },
        catAxisLabelColor: HEX.ink,
        catAxisLabelFontSize: 12,
        catAxisLabelFontFace: "+mn-lt",
        catAxisLineShow: false,
        chartColors: [HEX.bar, HEX.bar, HEX.bar, HEX.green],
        barGapWidthPct: 60,
        showValue: true,
        dataLabelPosition: "outEnd",
        dataLabelFormatCode: '#,##0" min"',
        dataLabelColor: HEX.ink,
        dataLabelFontSize: 13,
        dataLabelFontBold: true,
        dataLabelFontFace: "+mn-lt",
        showLegend: false,
        showTitle: false,
        objectName: nm("revocation-chart"),
      },
    );
    text(s, "Minutes until a permission change applies (log scale)", {
      x: 0.6,
      y: 6.2,
      w: 7.7,
      h: 0.3,
      size: 11,
      color: S.slate,
    });
    card(s, { x: 8.7, y: 1.55, w: 4.0, h: 3.45, fill: S.mist, line: null, name: "chart-notes" });
    text(
      s,
      [
        { text: "Their numbers are sync intervals.", options: { bold: true, color: S.navy, breakLine: true } },
        { text: "Until the next sync, the old permissions still grant access.", options: { breakLine: true } },
        { text: " ", options: { fontSize: 8, breakLine: true } },
        { text: "Ours is a hard limit.", options: { bold: true, color: S.teal, breakLine: true } },
        { text: "Permissions older than 5 minutes are refused, so access fails closed even if a sync or webhook is missed.", options: { breakLine: true } },
        { text: " ", options: { fontSize: 8, breakLine: true } },
        { text: "In-app grants apply on the next query.", options: { bold: true, color: S.navy } },
      ],
      { x: 8.95, y: 1.8, w: 3.5, h: 4.2, size: 15 },
    );
    text(
      s,
      "Vendor figures are documented defaults or minimums for one connector each (Microsoft Learn, Glean docs, Google Cloud docs, Oct 2026). Ours: DefaultAccessPolicy max age plus a per-minute permission refresh (PR #9).",
      { x: 0.6, y: 6.5, w: 12.1, h: 0.42, size: 9.5, italic: true, color: S.slate },
    );
  }

  // ============================================================ 10. Trade-offs
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
    s.addText(titleRuns("Design trade-offs", " we chose deliberately"), {
      placeholder: "title",
    });
    const H = (t) => ({
      text: t,
      options: {
        bold: true,
        color: S.white,
        fill: { color: S.navy },
        fontSize: 13,
      },
    });
    const r = (a, b, c) => [
      { text: a, options: { bold: true, color: S.navy } },
      { text: b },
      { text: c, options: { color: S.slate } },
    ];
    s.addTable(
      [
        [H("Choice"), H("What we gain"), H("What we accept")],
        r(
          "Check permissions in Python after search, over-fetching 4×",
          "Each platform's real rules, not a lossy SQL filter",
          "A heavily restricted user may get fewer candidates: the safe failure",
        ),
        r(
          "Native permissions cap local grants; admins are not all-seeing",
          "The assistant never shows more than the source would",
          "Approving a request cannot unlock a document the source withholds",
        ),
        r(
          "Omit stale critical evidence",
          "Old instructions are never presented as current",
          "Answers can be thinner, or abstain",
        ),
        r(
          "Live-verify critical evidence on the ask path",
          "Bounded freshness for what matters most",
          "Extra latency, capped by a verify timeout",
        ),
        r(
          "Hash-chained audit in the same Postgres",
          "Edits and deletions are detectable; simple to run",
          "No external anchor yet against a full database rewrite",
        ),
        r(
          "Permission snapshots expire (5 min for confidential)",
          "A revocation at the source is enforced within 5 minutes",
          "If syncing stops, confidential documents become unavailable",
        ),
        r(
          "Persona header in the demo",
          "Fast to film and to test",
          "Spoofable; one swap point for SSO before real data",
        ),
      ],
      {
        x: 0.6,
        y: 1.45,
        w: 12.1,
        colW: [4.1, 4.0, 4.0],
        fontSize: 13,
        color: S.ink,
        border: { type: "solid", pt: 0.75, color: HEX.line },
        fill: { color: S.white },
        valign: "middle",
        margin: [0.06, 0.12, 0.06, 0.12],
        rowH: [0.45, 0.7, 0.7, 0.64, 0.64, 0.64, 0.64, 0.64],
        objectName: nm("tradeoff-table"),
      },
    );
  }

  // ============================================================ 11. Numbers + stack
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
    s.addText(titleRuns("Tested offline,", " built to run on Tencent Cloud"), {
      placeholder: "title",
    });
    const stats = [
      [
        "676",
        "automated tests pass with no network, using mock providers and in-memory stores",
        S.teal,
      ],
      ["0", "restricted documents in the contractor's model context", S.coral],
      [
        "5 min",
        "max time a source revocation goes unnoticed (confidential); in-app grants: next query",
        S.amber,
      ],
    ];
    stats.forEach(([n, l, col], i) => {
      const y = 1.5 + i * 1.7;
      text(s, n, {
        x: 0.6,
        y,
        w: 5.6,
        h: 0.85,
        size: 48,
        bold: true,
        color: col,
      });
      text(s, l, { x: 0.6, y: y + 0.85, w: 5.6, h: 0.65, size: 15 });
    });
    card(s, {
      x: 6.85,
      y: 1.5,
      w: 5.85,
      h: 5.2,
      fill: S.mist,
      line: null,
      name: "stack",
    });
    text(s, "Stack", {
      x: 7.15,
      y: 1.65,
      w: 5,
      h: 0.45,
      size: 18,
      bold: true,
      color: S.navy,
    });
    const stack = [
      [
        "Model",
        "Tencent Cloud ADP chat; the demo uses local vectors, so no text goes to an embedding service",
      ],
      ["API", "FastAPI + Pydantic v2; MCP server for AI agents"],
      ["Data", "Postgres 16 + pgvector hybrid search"],
      ["Jobs", "Redis + Celery: ingest, sync, verify, watchdog"],
      ["Web", "Next.js 15 + Tailwind"],
      ["Deploy", "One Docker Compose stack, ready for a single Tencent Cloud server"],
    ];
    stack.forEach(([k, v], i) => {
      const y = 2.25 + i * 0.72;
      pill(s, k, {
        x: 7.15,
        y: y + 0.06,
        w: 1.1,
        h: 0.42,
        fill: S.navy,
        size: 11,
      });
      text(s, v, { x: 8.45, y, w: 4.1, h: 0.55, size: 13.5, valign: "middle" });
    });
    text(
      s,
      "Test count: main, 16 Oct 2026 (11 SQL tests run separately against Postgres).",
      {
        x: 0.6,
        y: 6.55,
        w: 6.0,
        h: 0.4,
        size: 10,
        italic: true,
        color: S.slate,
      },
    );
  }

  // ============================================================ 12. Closing
  {
    const s = pres.addSlide({
      masterName: "CLOSING_DARK",
      sectionTitle: "Proof",
    });
    s.addText(
      titleRuns("Ask anything. See only what you are allowed to.", " Prove every answer.", { primary: S.white, secondary: HEX.green }),
      { placeholder: "title" },
    );
    const items = [
      [I.shield, S.teal, "Permitted"],
      [I.refresh, S.amber, "Fresh"],
      [I.quote, S.blue, "Grounded"],
      [I.chain, S.violet, "Audited"],
    ];
    items.forEach(([ic, col, l], i) => {
      const x = 0.7 + i * 2.9;
      iconDot(s, ic, x, 3.75, 0.8, col);
      text(s, l, {
        x: x + 0.95,
        y: 3.75,
        w: 1.6,
        h: 0.8,
        size: 20,
        bold: true,
        color: S.white,
        valign: "middle",
      });
    });
    text(s, "github.com/pavan2184/tencent-hack", {
      x: 0.7,
      y: 5.4,
      w: 8,
      h: 0.4,
      size: 16,
      color: HEX.ice,
    });
    text(
      s,
      "Chai · Raphael · Pavan  ·  Tencent Cloud AI CAN DO IT Hackathon Singapore 2026",
      { x: 0.7, y: 6.55, w: 11.5, h: 0.4, size: 13, color: HEX.ice },
    );
  }

  // The internal status slide is left out of the submission build (DECK_SUBMISSION=1).
  if (!process.env.DECK_SUBMISSION) {
  // ============================================================ 13. Internal status
  pres.addSection({ title: "Internal" });
  {
    const s = pres.addSlide({
      masterName: "CONTENT",
      sectionTitle: "Internal",
    });
    s.addText(titleRuns("Team status, 13 Oct", " (internal: remove before submission)"), {
      placeholder: "title",
    });
    const cols = [
      [
        S.teal,
        HEX.tealT,
        "Done",
        [
          "Access-control library v2: native permission ceiling, fail-closed checks, Slack/Drive normalisers",
          "Research note with primary sources for all four platforms",
          "Saved-answer revocation fix (PR #6)",
          "Permission expiry: source revocation enforced within 5 min (PR #9)",
          "Industry review: Glean, Copilot, Gemini, Rovo, MAS rules",
        ],
      ],
      [
        S.amber,
        HEX.amberT,
        "Needs team agreement",
        [
          "Adopt v2 rules and permission expiry, PR #9: admins no longer see everything (Raphael, Pavan)",
          "Demo stack must run Celery worker and beat, or confidential docs go dark after 5 min (Pavan)",
          "Audit need-to-know with recorded reveal, and approval feedback, PR #10 (Raphael)",
          "Wire the query-time access service into the app (Pavan)",
        ],
      ],
      [
        S.blue,
        HEX.blueT,
        "Next",
        [
          "Store the audit chain's latest hash outside the app database (Raphael)",
          "Log model and prompt-template version per answer (Raphael)",
          "Signed demo sessions instead of the spoofable persona header (Raphael)",
          "CodeBuddy / WorkBuddy screenshots: at least three (everyone)",
          "Submit 16 Oct: URL, video, this PPT, GitHub",
        ],
      ],
    ];
    cols.forEach(([col, tint, head, items], i) => {
      const x = 0.6 + i * 4.1;
      card(s, {
        x,
        y: 1.45,
        w: 3.85,
        h: 4.2,
        fill: tint,
        line: null,
        name: "status-col",
      });
      text(s, head, {
        x: x + 0.3,
        y: 1.65,
        w: 3.3,
        h: 0.5,
        size: 19,
        bold: true,
        color: col,
      });
      s.addText(
        items.map((t, j) => ({
          text: t,
          options: { bullet: true, breakLine: j < items.length - 1 },
        })),
        {
          x: x + 0.3,
          y: 2.25,
          w: 3.35,
          h: 4.35,
          fontSize: 13.5,
          color: S.ink,
          valign: "top",
          paraSpaceAfter: 9,
          margin: 0,
          isTextBox: true,
          objectName: nm("status-list"),
        },
      );
    });
  }

  } // end internal slides
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
