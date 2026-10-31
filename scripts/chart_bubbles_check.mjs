// Browser check of the TIM chart's volume bubbles: drawn when the layer is on, gone when it is off.
// Usage: node scripts/chart_bubbles_check.mjs <base-url> <out-dir> [timeframe]
// Prints one JSON line. Read-only: it only opens pages and reads the chart canvas.
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const [base, outDir, timeframe = "5m"] = process.argv.slice(2);

// Bright green of the buy bubbles (stroke rgb(38,220,150)); candles are darker (rgb(38,166,154)).
const bubblePixels = () => {
  let count = 0;
  for (const canvas of document.querySelectorAll("#tc-live-chart canvas")) {
    const ctx = canvas.getContext("2d");
    if (!ctx || !canvas.width || !canvas.height) continue;
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 1] >= 200 && data[i] < 80 && data[i + 2] > 120 && data[i + 2] < 180 && data[i + 3] > 200) count++;
    }
  }
  return count;
};

const browser = await chromium.launch();
const result = { errors: [] };
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  page.on("pageerror", error => result.errors.push(error.message));
  await page.goto(`${base}/chart?tf=${timeframe}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await page.click("button[data-action='none']");
  await page.check("#tc-live-layers input[value='bubbles']");
  await page.waitForTimeout(600);
  result.checked = await page.$$eval("#tc-live-layers input", nodes => nodes.filter(n => n.checked).map(n => n.value));
  result.bubblePixels = await page.evaluate(bubblePixels);
  await page.screenshot({ path: path.join(outDir, `bubbles-${timeframe}.png`) });
  await page.uncheck("#tc-live-layers input[value='bubbles']");
  await page.waitForTimeout(600);
  result.bubblePixelsHidden = await page.evaluate(bubblePixels);
} finally {
  await browser.close();
}
console.log(JSON.stringify(result));
