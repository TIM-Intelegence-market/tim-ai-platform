// One screenshot per chart layer: all layers off, then only this one on (read-only, it only opens pages).
// Usage: node scripts/chart_indicator_screenshots.mjs <base-url> <out-dir> [symbol] [public-url]
// Prints one JSON line: per layer and timeframe the changed canvas pixels against "all off",
// the legend lines and page errors. A layer that draws nothing changes no pixels.
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const [base, outDir, symbol = "BTCUSDT", publicBase = ""] = process.argv.slice(2);

// Layer -> timeframe it is best seen on (footprint and bubbles need short candles).
const SHOTS = [
  ["day", "30m"], ["week", "1h"], ["month", "4h"], ["quarter", "1d"], ["year", "1d"], ["naked", "30m"],
  ["running", "30m"], ["session", "30m"], ["ib", "30m"], ["structure", "30m"], ["structure", "4h"], ["trend", "1h"],
  ["vwap", "1h"], ["vwap_bands", "1h"], ["fib", "30m"], ["fib", "4h"], ["tpo", "30m"], ["vp", "30m"], ["fp", "5m"],
  ["fp", "30m"], ["bubbles", "5m"], ["gamma", "1h"], ["liq", "30m"], ["plans_short", "30m"], ["plans_mid", "1h"],
  ["plans_long", "4h"], ["plans_old", "30m"],
  // lower bands and markers (added 04.11.2026)
  ["cvd", "30m"], ["cvd", "1h"], ["oi", "1h"], ["funding", "4h"], ["premium", "1h"], ["macro", "1d"],
];

// Canvas pixels stay in the page: snapshot() keeps a baseline, changed() counts pixels that differ from it.
const snapshot = () => {
  window.__tcBase = [...document.querySelectorAll("#tc-live-chart canvas")].map(canvas => {
    const ctx = canvas.getContext("2d");
    return ctx && canvas.width && canvas.height ? ctx.getImageData(0, 0, canvas.width, canvas.height).data : null;
  });
};
const changed = () => {
  let count = 0;
  [...document.querySelectorAll("#tc-live-chart canvas")].forEach((canvas, i) => {
    const before = (window.__tcBase || [])[i];
    const ctx = canvas.getContext("2d");
    if (!ctx || !before || !canvas.width || !canvas.height) return;
    const now = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    if (now.length !== before.length) return;
    for (let j = 0; j < now.length; j += 4) if (now[j] !== before[j] || now[j + 1] !== before[j + 1] || now[j + 2] !== before[j + 2]) count++;
  });
  return count;
};

// CHROMIUM_PATH: use a Chromium already on the machine instead of Playwright's own download.
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const rows = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let lastTf = null;
  for (const [layer, tf] of SHOTS) {
    if (tf !== lastTf) {
      await page.goto(`${base}/chart?symbol=${symbol}&tf=${tf}`, { waitUntil: "load" });
      await page.waitForSelector("#tc-live-layers input", { timeout: 30000 });
      await page.waitForTimeout(1500);
      await page.click("button[data-action='none']");
      await page.waitForTimeout(700);
      await page.evaluate(snapshot);
      lastTf = tf;
    }
    const input = page.locator(`#tc-live-layers input[value='${layer}']`);
    if (!(await input.count())) { rows.push({ layer, tf, present: false }); continue; }
    await page.click("button[data-action='none']");
    await input.check();
    // The footprint only shows when zoomed in: the "Footprint" button zooms to the last candles.
    if (layer === "fp") { await page.click("button[data-action='footprint']"); await page.waitForTimeout(900); }
    await page.waitForTimeout(900);
    const changedPixels = await page.evaluate(changed);
    const legend = await page.$$eval("#tc-live-legend *", nodes => nodes.map(n => n.textContent.trim()).filter(Boolean).slice(0, 12));
    const file = `${layer}-${tf}.png`;
    await page.locator("#tc-live").screenshot({ path: path.join(outDir, file) });
    rows.push({ layer, tf, present: true, changedPixels, legend, file });
  }
  // everything at once on the default view, desktop and phone
  await page.goto(`${base}/chart?symbol=${symbol}&tf=30m`, { waitUntil: "load" });
  await page.waitForTimeout(1500);
  await page.click("button[data-action='reset']").catch(() => {});
  await page.waitForTimeout(900);
  await page.locator("#tc-live").screenshot({ path: path.join(outDir, "standard-30m.png") });
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await phone.goto(`${base}/chart?symbol=${symbol}&tf=30m`, { waitUntil: "load" });
  await phone.waitForTimeout(1500);
  await phone.screenshot({ path: path.join(outDir, "standard-30m-handy.png"), fullPage: false });
  // Perp view: footprint from perp trades (switch button, stored in localStorage)
  await page.goto(`${base}/chart?symbol=${symbol}&tf=30m`, { waitUntil: "load" });
  await page.waitForTimeout(1500);
  const perpButton = page.locator("[data-action='market'][data-market='perp']");
  if (await perpButton.count()) {
    await perpButton.first().click();
    await page.waitForTimeout(2500);
    await page.click("button[data-action='footprint']").catch(() => {});
    await page.waitForTimeout(900);
    await page.locator("#tc-live").screenshot({ path: path.join(outDir, "perp-footprint-30m.png") });
    rows.push({ layer: "perp-view", tf: "30m", present: true, file: "perp-footprint-30m.png" });
    await page.locator("[data-action='market'][data-market='spot']").first().click().catch(() => {});
    await page.waitForTimeout(900);
  } else rows.push({ layer: "perp-view", present: false });
  // Public link as visitors see it (desktop and phone)
  if (publicBase) {
    const pub = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const pubErrors = [];
    pub.on("pageerror", error => pubErrors.push(error.message));
    await pub.goto(`${publicBase}/chart?symbol=${symbol}&tf=30m`, { waitUntil: "load" });
    await pub.waitForTimeout(3000);
    await pub.screenshot({ path: path.join(outDir, "oeffentlich-30m.png") });
    const pubPhone = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await pubPhone.goto(`${publicBase}/chart?symbol=${symbol}&tf=30m`, { waitUntil: "load" });
    await pubPhone.waitForTimeout(3000);
    await pubPhone.screenshot({ path: path.join(outDir, "oeffentlich-30m-handy.png") });
    rows.push({ layer: "public", present: true, errors: pubErrors });
  }
  rows.push({ errors });
} finally {
  await browser.close();
}
console.log(JSON.stringify(rows));
