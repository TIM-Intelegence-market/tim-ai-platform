// Browser check of the TIM chart's footprint: hint when zoomed out, numbers after the "Footprint" button,
// and old saved layer choices (from before the footprint existed) still show it.
// Usage: node scripts/chart_footprint_check.mjs <base-url> <out-dir>
// Prints one JSON line. Read-only: it only opens pages and reads the chart canvas.
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const [base, outDir] = process.argv.slice(2);

// Pixels close to the footprint POC frame colour (#f5c542) on the chart canvases.
const yellowPixels = () => {
  let count = 0;
  for (const canvas of document.querySelectorAll("#tc-live-chart canvas")) {
    const ctx = canvas.getContext("2d");
    if (!ctx || !canvas.width || !canvas.height) continue;
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 0; i < data.length; i += 4) {
      if (Math.abs(data[i] - 245) < 12 && Math.abs(data[i + 1] - 197) < 12 && Math.abs(data[i + 2] - 66) < 12 && data[i + 3] > 200) count++;
    }
  }
  return count;
};

const browser = await chromium.launch();
const result = { errors: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  page.on("pageerror", error => result.errors.push(error.message));
  // Only the footprint layer on, so yellow can only come from its POC frames.
  await page.addInitScript(() => {
    if (sessionStorage.getItem("seeded")) return;
    sessionStorage.setItem("seeded", "1");
    localStorage.setItem("tim-chart-layers-v1", JSON.stringify(["fp"]));
    localStorage.setItem("tim-chart-layers-known-v1", JSON.stringify(["day", "week", "month", "naked", "structure", "trend", "tpo", "vp", "fp"]));
  });
  await page.goto(`${base}/chart?tf=5m`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  result.yellowZoomedOut = await page.evaluate(yellowPixels);
  await page.click("button[data-action='footprint']");
  await page.waitForTimeout(800);
  result.yellowFootprint = await page.evaluate(yellowPixels);
  await page.screenshot({ path: path.join(outDir, "footprint-5m.png") });

  // A choice saved before the footprint existed (no list of known layers) gets vp and fp added.
  const legacy = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  legacy.on("pageerror", error => result.errors.push(error.message));
  await legacy.addInitScript(() => localStorage.setItem("tim-chart-layers-v1", JSON.stringify(["day", "tpo"])));
  await legacy.goto(`${base}/chart?tf=5m`, { waitUntil: "networkidle" });
  await legacy.waitForTimeout(1000);
  result.legacyChecked = await legacy.$$eval("#tc-live-layers input", nodes => nodes.filter(n => n.checked).map(n => n.value));
} finally {
  await browser.close();
}
console.log(JSON.stringify(result));
