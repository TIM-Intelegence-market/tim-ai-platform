"""TIM chart zones for R-ABS-2: snapshots of the Level-Übersicht, written as they are seen (paper only).

Uzi 19.11.2026: the entry should stand at a price zone the TIM chart shows ("geschätzt, aber belegt geschätzt").
The chart's zones come from :mod:`src.dashboard.level_overview` (every chart line merged into weighted zones). The
recorder builds that overview from public Binance spot candles (the same source as the chart, standard library
only) and appends one snapshot per poll to ``<root>/<UTC day>.jsonl``. R-ABS-2 reads the newest snapshot written
at or before an event, so a zone that the chart only drew later can never count (no look-ahead).

    python -m src.research_lab.forward chart-zones-record --zones DIR [--seconds N]   # ends on DIR/STOP
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SYMBOL = "BTCUSDT"
POLL_SECONDS = 300.0
DAY_MS = 86_400_000

Fetch = Callable[[str, str, datetime], list[dict]]


def _fetch(symbol: str, timeframe: str, now: datetime) -> list[dict]:
    from src.dashboard.chart_history import fetch_history

    return fetch_history(symbol, timeframe, now)


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


class ChartZoneRecorder:
    def __init__(self, root: Path | str, *, fetch: Fetch = _fetch, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.root = Path(root)
        self.fetch, self.clock, self.sleep = fetch, clock, sleep

    def poll(self) -> int:
        """One snapshot of all chart zones; returns the number of zones written."""
        from src.dashboard import level_overview
        from src.dashboard.chart_history import TIMEFRAMES

        now_ms = int(self.clock() * 1000)
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        series = {tf: self.fetch(SYMBOL, tf, now) for tf in TIMEFRAMES}
        view = level_overview.build(series, now)
        if not view:
            return 0
        zones = [{"low": z["low"], "high": z["high"], "mid": z["mid"], "weight": z["weight"], "labels": z["labels"][:5]}
                 for z in view["all"]]
        row = {"at_ms": now_ms, "ruleset": view["ruleset"], "price": view["price"], "zones": zones}
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / f"{_day(now_ms)}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(zones)

    def run(self, *, stop_after: float | None = None, stop_file: Path | None = None) -> dict[str, int]:
        started, counts = self.clock(), {"calls": 0, "zones": 0, "errors": 0}
        while not (stop_file and stop_file.exists()) and (stop_after is None or self.clock() - started < stop_after):
            try:
                counts["zones"] += self.poll()
            except Exception as exc:  # noqa: BLE001 - logged, next round tries again
                counts["errors"] += 1
                print(f"chart-zones: {datetime.now(timezone.utc).isoformat()} {type(exc).__name__}: {exc}", flush=True)
            counts["calls"] += 1
            self.sleep(POLL_SECONDS)
        return counts


def zones_at(root: Path | str, at_ms: int, max_age_ms: int) -> list[dict[str, Any]] | None:
    """Zones of the newest snapshot with ``at_ms - max_age_ms <= snapshot <= at_ms``; None without one."""
    best: dict[str, Any] | None = None
    for day in sorted({_day(at_ms - max_age_ms), _day(at_ms)}):
        path = Path(root) / f"{day}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:   # a half-written last line
                    continue
                if at_ms - max_age_ms <= row["at_ms"] <= at_ms and (best is None or row["at_ms"] > best["at_ms"]):
                    best = row
    return best["zones"] if best else None
