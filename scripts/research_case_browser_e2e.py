#!/usr/bin/env python3
"""Browser E2E for Research Case Explorer (Phase 7/8).

Isolated harness: DashboardServer (worktree code, quick-win renderer)
on 127.0.0.1:18766 fed with cases read from the isolated TEST DB.
No production, no ingestion, no mutation. Exits 0 only if:
- /cases renders with status cards + rows + default filter
- /api/research-cases + /stats + detail work
- zero console errors and zero failed requests (both viewports)
- screenshots land in artifacts/research_cases/final/
"""
from __future__ import annotations

import asyncio
import asyncpg
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src.dashboard.app as appmod  # noqa: E402 (applies explorer rendering)
from src.dashboard.app import DashboardServer, DashboardState  # noqa: E402

SECRET_FILE = Path.home() / "Library/Application Support/TIM/test-database-password"
PORT = 18766
errors: list[str] = []
failed: list[str] = []


async def load_cases() -> list[dict]:
    pw = SECRET_FILE.read_text().strip()
    con = await asyncpg.connect(host="127.0.0.1", port=5433, database="tim_test",
                                user="tim_test", password=pw, timeout=5)
    try:
        rows = await con.fetch("SELECT * FROM research_cases ORDER BY updated_at DESC")
        return [dict(r) for r in rows]
    finally:
        await con.close()


def json_default(value):
    return str(value)


def main() -> int:
    cases = asyncio.run(load_cases())
    print(f"cases-from-test-db: {len(cases)}")
    for row in cases:
        for key in ("opened_at", "updated_at"):
            row[key] = str(row.get(key))
        for key in ("observation_ids", "evidence", "missing_evidence", "rule_versions"):
            value = row.get(key)
            row[key] = json.loads(value) if isinstance(value, str) else (value or [])
    state = DashboardState()
    state.research_cases = cases
    server = DashboardServer(state, "127.0.0.1", PORT)
    thread = threading.Thread(target=server.server.serve_forever, daemon=True)
    thread.start()
    time.sleep(1)
    from playwright.sync_api import sync_playwright
    checks: dict[str, bool] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height, tag in ((1440, 900, "1440x900"), (1920, 1080, "1920x1080")):
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("requestfailed", lambda req: failed.append(req.url))
            page.goto(f"http://127.0.0.1:{PORT}/cases", wait_until="networkidle", timeout=30000)
            html = page.content()
            checks[f"cards_{tag}"] = "case-status-summary" in html
            checks[f"rows_{tag}"] = "case_" in html
            checks[f"filter_{tag}"] = "Alle aktiven / alle Status" in html
            checks[f"stand_{tag}"] = "Datenstand:" in html
            page.screenshot(path=f"artifacts/research_cases/final/cases_{tag}.png")
            api = page.goto(f"http://127.0.0.1:{PORT}/api/research-cases", timeout=15000)
            checks[f"api_{tag}"] = api is not None and api.ok
            stats = page.goto(f"http://127.0.0.1:{PORT}/api/research-cases/stats", timeout=15000)
            checks[f"stats_{tag}"] = stats is not None and stats.ok
            first = cases[0]["case_id"] if cases else "none"
            if cases:
                detail = page.goto(f"http://127.0.0.1:{PORT}/api/research-cases/{first}", timeout=15000)
                checks[f"detail_{tag}"] = detail is not None and detail.ok
            page.close()
        browser.close()
    server.server.shutdown()
    server.server.server_close()
    checks["no_console_errors"] = not errors
    checks["no_failed_requests"] = not failed
    print(json.dumps(checks, indent=1))
    if errors:
        print("CONSOLE-ERRORS:", errors[:5])
    if failed:
        print("FAILED-REQUESTS:", failed[:5])
    Path("artifacts/research_cases/test_results").mkdir(parents=True, exist_ok=True)
    Path("artifacts/research_cases/test_results/browser_e2e.json").write_text(json.dumps(checks, indent=1))
    return 0 if all(checks.values()) and cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
