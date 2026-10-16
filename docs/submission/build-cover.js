/* Submission cover image (16:9). Usage: node cover.js <outDir> */
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const si = require("react-icons/si");
const fa = require("react-icons/fa6");

const out = process.argv[2];
const W = 1520,
  H = 864; // 4x of 380x216, downscaled for crisp text
const NAVY = "#0B2545",
  TEAL = "#0E9F8E",
  ICE = "#C9D8EE",
  WHITE = "#FFFFFF";
const FONT = "Helvetica, Arial, sans-serif";

async function iconPng(Comp, color, size) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color, size: String(size) }),
  );
  return sharp(Buffer.from(svg)).png().toBuffer();
}

(async () => {
  const sources = [
    [si.SiConfluence, "#1868DB"],
    [si.SiJira, "#1868DB"],
    [si.SiSlack, "#4A154B"],
    [si.SiGoogledrive, "#1FA463"],
  ];
  const cx = 1060,
    d = 118,
    gap = 34;
  const top = (H - (4 * d + 3 * gap)) / 2;
  const shieldX = 1290,
    shieldD = 190;
  const rowY = (i) => top + i * (d + gap) + d / 2;

  const lines = sources
    .map(
      (_, i) =>
        `<line x1="${cx + d / 2 + 6}" y1="${rowY(i)}" x2="${shieldX - 10}" y2="${H / 2}" stroke="${ICE}" stroke-width="4" stroke-opacity="0.7"/>`,
    )
    .join("");
  const circles = sources
    .map(
      (_, i) =>
        `<circle cx="${cx}" cy="${rowY(i)}" r="${d / 2}" fill="${WHITE}"/>`,
    )
    .join("");

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">
    <rect width="${W}" height="${H}" fill="${NAVY}"/>
    ${lines}${circles}
    <circle cx="${shieldX + shieldD / 2}" cy="${H / 2}" r="${shieldD / 2}" fill="${TEAL}"/>
    <rect x="96" y="176" rx="28" ry="28" width="560" height="56" fill="${TEAL}"/>
    <text x="376" y="214" font-family="${FONT}" font-size="27" font-weight="700" fill="${WHITE}" text-anchor="middle" letter-spacing="1">FINTECH · ASPIRE CHALLENGE</text>
    <text x="90" y="400" font-family="${FONT}" font-size="132" font-weight="700" fill="${WHITE}">Brain Sauce</text>
    <text x="96" y="500" font-family="${FONT}" font-size="44" fill="${ICE}">Answers only from what</text>
    <text x="96" y="556" font-family="${FONT}" font-size="44" fill="${ICE}">you're allowed to see.</text>
    <text x="96" y="688" font-family="${FONT}" font-size="30" font-weight="700" fill="${TEAL}">Permitted · Fresh · Grounded · Audited</text>
  </svg>`;

  const iconSize = Math.round(d * 0.6);
  const composites = [];
  for (let i = 0; i < sources.length; i++) {
    const [Comp, color] = sources[i];
    composites.push({
      input: await iconPng(Comp, color, iconSize),
      left: Math.round(cx - iconSize / 2),
      top: Math.round(rowY(i) - iconSize / 2),
    });
  }
  const sIcon = Math.round(shieldD * 0.52);
  composites.push({
    input: await iconPng(fa.FaShieldHalved, WHITE, sIcon),
    left: Math.round(shieldX + (shieldD - sIcon) / 2),
    top: Math.round(H / 2 - sIcon / 2),
  });

  const full = await sharp(Buffer.from(svg))
    .composite(composites)
    .png()
    .toBuffer();
  await sharp(full).resize(760, 432).png().toFile(`${out}/cover-760x432.png`);
  await sharp(full).resize(380, 216).png().toFile(`${out}/cover-380x216.png`);
  console.log("wrote covers to", out);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
