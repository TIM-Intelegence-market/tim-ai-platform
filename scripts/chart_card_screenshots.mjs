// Screenshots and DOM checks of the TIM chart's analysis card on every timeframe.
// Usage: node scripts/chart_card_screenshots.mjs <base-url> <out-dir>
// Prints one JSON line with a row per timeframe. Read-only: it only opens pages.
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const [base, outDir] = process.argv.slice(2);
const TIMEFRAMES = ["30m", "1h", "4h", "1d", "1w", "1M"];

const browser = await chromium.launch();
const rows = [];
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  for (const tf of TIMEFRAMES) {
    await page.goto(`${base}/chart?tf=${tf}`, { waitUntil: "load" });
    const row = await page.evaluate(() => {
      const card = document.querySelector(".tc-card");
      const journal = card?.querySelector("[data-field='journal'] dd");
      return {
        card: Boolean(card),
        decision: card?.querySelector("[data-field='decision']")?.textContent?.trim() ?? null,
        fields: card ? card.querySelectorAll(".tc-card__item").length : 0,
        plans: card ? card.querySelectorAll("tr.tc-card-plan").length : 0,
        journal: journal ? journal.childNodes[0]?.textContent?.trim() : null,
        svg: Boolean(document.querySelector("svg.tc-svg")),
        overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    });
    await page.screenshot({ path: path.join(outDir, `chart-${tf}.png`), fullPage: true });
    rows.push({ tf, ...row });
  }
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await phone.goto(`${base}/chart?tf=30m`, { waitUntil: "load" });
  await phone.locator(".tc-card").screenshot({ path: path.join(outDir, "chart-30m-phone-card.png") });
} finally {
  await browser.close();
}
console.log(JSON.stringify(rows));
