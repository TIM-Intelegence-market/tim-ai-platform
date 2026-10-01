#!/usr/bin/env python3
"""Browser E2E + visual acceptance for the Research Case Explorer (Issue #3, Phasen 7/8).

Isolated harness: a DashboardServer on 127.0.0.1 is fed with the cases
persisted in an isolated TEST database (``--database-url``, name must contain
"test"). Nothing is ingested or written; no production system is touched.

Exits 0 only if every check passes in both viewports (1440x900, 1920x1080):
page loads, default is not CONFIRMED-only, status cards and real rows are
visible, ACTIVE/OPEN/READY_FOR_REVIEW/CONFIRMED filters behave, empty state
differs from a filter without hits, detail shows lifecycle and missing
evidence, API/stats/detail answer, OBSERVE/READ-ONLY is visible, and there
are zero console errors and zero failed requests.

Screenshots: artifacts/research_cases/final/ ; results: test_results/browser_e2e.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dashboard.app import DashboardServer, DashboardState  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = {"OPEN", "MONITORING", "COLLECTING_EVIDENCE", "READY_FOR_REVIEW"}


def require_test_database(url: str) -> None:
    from urllib.parse import urlsplit

    name = urlsplit(url).path.lstrip("/")
    if not any(marker in name for marker in ("test", "pytest", "isolated")):
        raise SystemExit(f"refusing non-test database {name!r}: the E2E harness only reads isolated test databases")


async def seed_test_cases(url: str) -> int:
    """TEST_ONLY: synthetic observations through the real builder, so every
    lifecycle state is rendered. Writes research_cases rows for symbol E2ETEST
    in the isolated test database only."""
    from datetime import datetime, timedelta, timezone
    from uuid import UUID

    from src.database.connection import Database
    from src.database.repository import MarketRepository
    from src.models.market_data import Observation, ObservationKind
    from src.research.case_builder import Gap, materialize

    t0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def obs(n, kind, minute, input_hash=None):
        return Observation(kind, "E2ETEST", "1m", t0 + timedelta(minutes=minute), "TEST_ONLY E2E", 50, {"test_only": True},
                           provenance="PUBLIC_MARKET_DATA_DETERMINISTIC", rule_id="bronxc", rule_version="1.0.0",
                           input_hash=("%064x" % n) if input_hash is None else input_hash, observation_id=UUID(int=n), created_at=t0)

    full = [(ObservationKind.BOS_BULLISH, 1), (ObservationKind.REJECTION, 5), (ObservationKind.WEAK_CONTINUATION, 9)]
    items = [obs(i + 1, kind, minute) for i, (kind, minute) in enumerate(full)]
    items += [obs(10 + i, kind, 60 + minute) for i, (kind, minute) in enumerate(full)]          # gap-exposed window
    items += [obs(20, ObservationKind.REJECTION, 120), obs(21, ObservationKind.REJECTION, 125)]   # collecting evidence
    items += [obs(30, ObservationKind.REJECTION, 180)]                                           # open
    items += [obs(40, ObservationKind.REJECTION, 240), obs(41, ObservationKind.BOS_BULLISH, 241, input_hash="")]  # quarantined
    closes = [{"close_time": t0 + timedelta(minutes=m), "close": 100.0 + 0.1 * m} for m in range(0, 400)]
    gap = Gap("e2e" + "0" * 61, "E2ETEST", t0 + timedelta(minutes=95), t0 + timedelta(minutes=96))
    result = materialize(items, t0 + timedelta(hours=8), gaps=[gap], candles_by_key={("E2ETEST", "1m"): closes})
    db = Database(url)
    await db.connect()
    try:
        async with db.acquire() as con:
            await con.execute("DELETE FROM research_cases WHERE symbol='E2ETEST'")
        await MarketRepository(db).apply_research_cases(result.cases)
    finally:
        await db.close()
    return len(result.cases)


async def load_cases(url: str) -> list[dict]:
    from src.database.connection import Database
    from src.database.repository import _case_from_row

    db = Database(url)
    await db.connect()
    try:
        async with db.acquire() as con:
            rows = await con.fetch("SELECT * FROM research_cases ORDER BY updated_at, case_id")
        return [_case_from_row(row).to_dict() for row in rows]
    finally:
        await db.close()


def serve(state: DashboardState, port: int) -> DashboardServer:
    server = DashboardServer(state, "127.0.0.1", port)
    threading.Thread(target=server.server.serve_forever, daemon=True).start()
    return server


def visible_statuses(page) -> list[str]:
    return page.eval_on_selector_all("#cases-body tr[data-status]", "rows => rows.filter(r => !r.hidden).map(r => r.dataset.status)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--seed-test-cases", action="store_true", help="TEST_ONLY: write synthetic E2ETEST cases into the test DB first")
    parser.add_argument("--out-dir", default=str(ROOT / "artifacts/research_cases"))
    args = parser.parse_args()
    out = Path(args.out_dir)
    (out / "final").mkdir(parents=True, exist_ok=True)
    (out / "test_results").mkdir(parents=True, exist_ok=True)
    require_test_database(args.database_url)
    os.environ["TIM_ENV"] = "test"  # activates the repository's test-database guard
    os.environ["TIM_DURABLE_TEST_DATABASE_URL"] = args.database_url
    if args.seed_test_cases:
        print(f"seeded-test-cases: {asyncio.run(seed_test_cases(args.database_url))}")
    cases = asyncio.run(load_cases(args.database_url))
    print(f"cases-from-test-db: {len(cases)}")
    statuses = {str(case.get("status")) for case in cases}
    servers = [serve(DashboardState(research_cases=cases), args.port), serve(DashboardState(research_cases=[]), args.port + 1)]
    time.sleep(0.5)
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    failed: list[str] = []
    checks: dict[str, bool] = {}
    base, empty_base = f"http://127.0.0.1:{args.port}", f"http://127.0.0.1:{args.port + 1}"
    with sync_playwright() as playwright:
        executable = os.environ.get("TIM_E2E_CHROMIUM")  # pinned browser when the Playwright build differs
        browser = playwright.chromium.launch(executable_path=executable) if executable else playwright.chromium.launch()
        for width, height in ((1440, 900), (1920, 1080)):
            tag = f"{width}x{height}"
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("requestfailed", lambda req: failed.append(req.url))
            page.on("response", lambda res: failed.append(f"{res.status} {res.url}") if res.status >= 400 and "does-not-exist" not in res.url else None)

            page.goto(f"{base}/cases", wait_until="networkidle")
            html = page.content()
            checks[f"{tag}_loads"] = "case-status-summary" in html
            checks[f"{tag}_default_not_confirmed_only"] = page.input_value("#filter-status") == ""
            checks[f"{tag}_rows_visible"] = len(visible_statuses(page)) == len(cases) > 0
            checks[f"{tag}_observe_read_only"] = "OBSERVE / READ-ONLY" in html
            checks[f"{tag}_builder_version"] = "research-case-builder/" in html
            if "CONFIRMED" not in statuses:
                checks[f"{tag}_active_action_when_zero_confirmed"] = "Alle aktiven Cases anzeigen" in html
            page.screenshot(path=str(out / f"final/default_{tag}.png"), full_page=True)

            page.goto(f"{base}/cases?status=ACTIVE", wait_until="networkidle")
            shown = visible_statuses(page)
            checks[f"{tag}_filter_active"] = set(shown) <= ACTIVE and len(shown) == sum(1 for c in cases if c.get("status") in ACTIVE)
            page.screenshot(path=str(out / f"final/all_active_{tag}.png"), full_page=True)
            for status, name in (("OPEN", "open"), ("READY_FOR_REVIEW", "ready_for_review"), ("CONFIRMED", "confirmed")):
                page.select_option("#filter-status", status)
                shown = visible_statuses(page)
                checks[f"{tag}_filter_{name}"] = shown == [status] * sum(1 for c in cases if c.get("status") == status)
                page.screenshot(path=str(out / f"final/{name}_{tag}.png"), full_page=True)

            page.goto(f"{empty_base}/cases", wait_until="networkidle")
            checks[f"{tag}_empty_state"] = "keine materialisierten Research Cases vorhanden" in page.content()
            page.screenshot(path=str(out / f"final/empty_state_{tag}.png"), full_page=True)

            target = next((c for c in cases if c.get("status") == "READY_FOR_REVIEW"), cases[0])
            page.goto(f"{base}/cases?id={target['case_id']}", wait_until="networkidle")
            detail = page.content()
            checks[f"{tag}_detail"] = all(label in detail for label in ("Falldetails", "Outcome / Reife", "Data Quality", "Review", "Provenienz", "Timeline"))
            checks[f"{tag}_missing_evidence_visible"] = all(reason in detail for reason in target.get("missing_evidence", []))
            page.screenshot(path=str(out / f"final/case_detail_{tag}.png"), full_page=True)
            quarantined = next((c for c in cases if c.get("status") == "QUARANTINED"), None)
            if quarantined:
                page.goto(f"{base}/cases?id={quarantined['case_id']}", wait_until="networkidle")
                checks[f"{tag}_quarantine_reason_visible"] = "Data Quality unter Schwelle" in page.content()
                page.screenshot(path=str(out / f"final/missing_evidence_{tag}.png"), full_page=True)

            api = page.request.get(f"{base}/api/research-cases?status=all&limit=200").json()
            stats = page.request.get(f"{base}/api/research-cases/stats").json()["stats"]
            one = page.request.get(f"{base}/api/research-cases/{target['case_id']}").json()
            missing = page.request.get(f"{base}/api/research-cases/does-not-exist")
            checks[f"{tag}_api_list"] = api["pagination"]["total_matching"] == len(cases)
            checks[f"{tag}_api_stats_consistent"] = stats["total"] == len(cases) == sum(stats["by_status"].values())
            checks[f"{tag}_api_detail"] = one["case_id"] == target["case_id"] and "assessment" in one and "timeline" in one
            checks[f"{tag}_api_404"] = missing.status == 404
            api_acceptance = {"stats": stats, "list_total_matching": api["pagination"]["total_matching"],
                              "detail_case_id": one["case_id"], "detail_keys": sorted(one), "unknown_id_status": missing.status,
                              "checks": {key.split("_", 1)[1]: value for key, value in checks.items() if key.startswith(f"{tag}_api")}}
            page.close()
        browser.close()
    for server in servers:
        server.server.shutdown()
        server.server.server_close()
    checks["no_console_errors"] = not errors
    checks["no_failed_requests"] = not failed
    result = {"cases": len(cases), "status_counts": {s: sum(1 for c in cases if c.get("status") == s) for s in sorted(statuses)},
              "checks": checks, "passed": sum(checks.values()), "total": len(checks),
              "console_errors": errors[:5], "failed_requests": failed[:5]}
    (out / "api_acceptance.json").write_text(json.dumps(api_acceptance, indent=1, sort_keys=True, default=str) + "\n")
    (out / "test_results/browser_e2e.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"passed": result["passed"], "total": result["total"]}))
    for name, ok in checks.items():
        if not ok:
            print("FAIL", name)
    return 0 if all(checks.values()) and cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
