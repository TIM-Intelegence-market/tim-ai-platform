#!/usr/bin/env python3
"""Live read-only validation harness (NO writes, NO transitions).

Loads a bounded recent window from PRODUCTION via read-only SELECTs
into the NEW dashboard code, serves isolated 127.0.0.1:18767, and checks
DB<->API consistency, filters, pagination, detail, UI honesty.
"""
from __future__ import annotations

import asyncio
import asyncpg
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src.dashboard.app as appmod  # noqa: E402
from src.dashboard.app import DashboardServer, DashboardState  # noqa: E402

PORT = 18767
LIMIT = 2000


def prod_password() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "com.tim.database",
         "-a", "tim", "-w"], capture_output=True, text=True).stdout.strip()


async def load_window() -> tuple[list[dict], dict]:
    con = await asyncpg.connect(host="127.0.0.1", port=5432, database="tim",
                                user="tim", password=prod_password(), timeout=10)
    await con.execute("START TRANSACTION READ ONLY")
    try:
        totals = await con.fetch("SELECT status, count(*) AS n FROM research_cases GROUP BY status")
        rows = await con.fetch(
            "SELECT * FROM research_cases ORDER BY updated_at DESC LIMIT $1", LIMIT)
        return [dict(r) for r in rows], {r["status"]: r["n"] for r in totals}
    finally:
        await con.execute("ROLLBACK")
        await con.close()


def normalize(cases: list[dict]) -> list[dict]:
    for row in cases:
        for key in ("opened_at", "updated_at"):
            row[key] = str(row.get(key))
        for key in ("observation_ids", "evidence", "missing_evidence", "rule_versions"):
            value = row.get(key)
            row[key] = json.loads(value) if isinstance(value, str) else (value or [])
        if "review_history" not in row:
            row["review_history"] = []
    return cases


def main() -> int:
    cases, db_stats = asyncio.run(load_window())
    print(f"DB_TOTAL={sum(db_stats.values())} DB_STATS={db_stats} WINDOW={len(cases)}")
    state = DashboardState()
    state.research_cases = normalize(cases)
    server = DashboardServer(state, "127.0.0.1", PORT)
    thread = threading.Thread(target=server.server.serve_forever, daemon=True)
    thread.start()
    time.sleep(1)
    import urllib.request
    base = f"http://127.0.0.1:{PORT}"
    results: dict[str, object] = {"window": len(cases), "db_stats": db_stats}

    def get(path: str):
        import urllib.error
        try:
            with urllib.request.urlopen(base + path, timeout=20) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    status, collection = get("/api/research-cases?limit=200")
    results["api_total_returned"] = collection["pagination"]["total_matching"]
    results["api_stats_total"] = collection["stats"]["total"]
    from collections import Counter
    window_dist = dict(Counter(str(c.get("status")) for c in cases))
    results["window_dist"] = window_dist
    results["stats_match_window"] = collection["stats"]["by_status"] == window_dist
    _, confirmed = get("/api/research-cases?status=CONFIRMED")
    results["confirmed_empty"] = confirmed["pagination"]["total_matching"] == 0
    _, opened = get("/api/research-cases?status=OPEN&limit=5")
    results["open_filter_ok"] = all(c["status"] == "OPEN" for c in opened["cases"])
    first, second = cases[0], cases[1]
    _, detail = get(f"/api/research-cases/{first['case_id']}")
    results["detail_match"] = (detail["case_id"] == first["case_id"]
                               and detail["status"] == first["status"])
    _, s404 = get("/api/research-cases/does-not-exist")
    results["detail_404"] = s404.get("error") == "case not found"
    _, stats = get("/api/research-cases/stats")
    results["stats_route_ok"] = stats["stats"]["total"] == len(cases)
    # pagination walk
    seen, cursor, pages = [], "", 0
    while pages < 5:
        _, page = get(f"/api/research-cases?limit=200&cursor={cursor}" if cursor else "/api/research-cases?limit=200")
        seen.extend(c["case_id"] for c in page["cases"])
        cursor = page["pagination"]["next_cursor"]
        pages += 1
        if not cursor:
            break
    results["pagination_walk"] = {"pages": pages, "seen": len(seen), "unique": len(set(seen))}
    Path("artifacts/live_validation").mkdir(parents=True, exist_ok=True)
    Path("artifacts/live_validation/db_api_consistency.json").write_text(json.dumps(results, indent=1, default=str))
    print(json.dumps({k: v for k, v in results.items() if k != "db_stats"}, indent=1, default=str))
    server.server.shutdown()
    server.server.server_close()
    ok = (results["stats_match_window"] and results["confirmed_empty"]
          and results["open_filter_ok"] and results["detail_match"]
          and results["detail_404"] and results["stats_route_ok"]
          and results["pagination_walk"]["seen"] == results["pagination_walk"]["unique"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
