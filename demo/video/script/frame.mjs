// Render single frames of the composition without a full HyperFrames render.
// Loads index.html in headless Chrome, seeks the registered root timeline, screenshots at 1920x1080.
//
//   node script/frame.mjs <out dir> <time>[ <time> ...]     e.g. node script/frame.mjs out/frames 5 20.5 131
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const [outDir, ...times] = process.argv.slice(2);
if (!outDir || times.length === 0) throw new Error("usage: node script/frame.mjs <out dir> <time>...");
mkdirSync(outDir, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
  args: ["--no-sandbox", "--hide-scrollbars", "--allow-file-access-from-files"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
await page.goto("file://" + resolve("index.html"), { waitUntil: "networkidle0" });
await page.evaluate(() => document.fonts.ready);
for (const t of times) {
  const seconds = Number(t);
  await page.evaluate((s) => {
    const tl = window.__timelines && window.__timelines["main"];
    if (!tl) throw new Error("root timeline not registered");
    tl.seek(s, false);
    // Scene clips are shown/hidden by the runtime; emulate it so stills match the render.
    document.querySelectorAll("section.clip").forEach((el) => {
      const start = Number(el.dataset.start);
      const dur = Number(el.dataset.duration);
      el.style.visibility = s >= start && s < start + dur ? "visible" : "hidden";
    });
  }, seconds);
  await new Promise((r) => setTimeout(r, 150));
  const name = `${outDir}/t${String(seconds).replace(".", "_")}.png`;
  await page.screenshot({ path: name });
  console.log("frame", name);
}
await browser.close();
