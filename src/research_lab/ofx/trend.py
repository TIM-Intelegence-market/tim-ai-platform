"""Direction of the day, week and month at signal time (Uzi 10.11.: long time frames as direction filter).

Built from daily closes of completed UTC days only. A week runs Monday to Sunday (UTC), a month is the calendar
month; both count only once their last day is over. The state of a time frame is the sign of its last completed
close against the mean of its last ``LOOKBACK`` completed closes (0 while the history is too short, or flat).
Fixed before the search saw any result; the search may only choose with / against / ignore.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FRAMES = ("d", "w", "m")
LOOKBACK = {"d": 20, "w": 10, "m": 3}
MIT, GEGEN = "MIT", "GEGEN"


def _period(day: date, frame: str) -> tuple[int, int]:
    if frame == "w":
        iso = day.isocalendar()
        return iso[0], iso[1]
    return day.year, day.month


class Trend:
    def __init__(self, closes: Mapping[date, float]) -> None:
        self._closes = dict(sorted(closes.items()))
        self._days = list(self._closes)
        self._cache: dict[tuple[date, str], int] = {}

    def _completed(self, day: date, frame: str) -> list[float]:
        """Closes of the periods that ended before ``day`` began, oldest first."""
        past = [d for d in self._days if d < day]
        if frame == "d":
            return [self._closes[d] for d in past]
        out: list[float] = []
        current = _period(day, frame)
        last_seen: tuple[int, int] | None = None
        for d in past:
            p = _period(d, frame)
            if p == current:
                break  # the running week/month is not complete
            if p == last_seen:
                out[-1] = self._closes[d]
            else:
                out.append(self._closes[d])
                last_seen = p
        return out

    def state(self, day: date, frame: str) -> int:
        key = (day, frame)
        if key not in self._cache:
            closes = self._completed(day, frame)[-LOOKBACK[frame]:]
            if len(closes) < LOOKBACK[frame]:
                self._cache[key] = 0
            else:
                mean = sum(closes) / len(closes)
                self._cache[key] = (closes[-1] > mean) - (closes[-1] < mean)
        return self._cache[key]

    def allows(self, signal_ms: int, direction: int, frame: str, mode: str | None) -> bool:
        """``MIT``: trade only in the direction of the frame; ``GEGEN``: only against it. Unknown or flat: no trade."""
        if mode is None:
            return True
        day = datetime.fromtimestamp(signal_ms / 1000, tz=timezone.utc).date()
        s = self.state(day, frame)
        if s == 0:
            return False
        return (s == direction) if mode == MIT else (s == -direction)


def _close_of(args: tuple[Callable[[], Callable], date]) -> tuple[str, float | None]:
    factory, day = args
    bars, _ = factory()(day)
    traded = [b for b in bars if b.has_trades]
    return day.isoformat(), (traded[-1].last_price_e8 / 1e8 if traded else None)


def store_trend(root: str, first: date, last: date, cache: Path, workers: int = 4) -> Trend:
    """Daily closes of the plain store between ``first`` and ``last`` (training side only: the plain store refuses
    every holdout day). Cached as JSON next to the results; missing days are read again."""
    import functools

    from src.research_lab.of2.__main__ import _store_loader_for
    from src.research_lab.orderflow_ml.store import MinuteBarStore
    known: dict[str, float] = json.loads(cache.read_text()) if cache.exists() else {}
    present = set(MinuteBarStore(root).present_days())
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    todo = [d for d in days if d in present and d.isoformat() not in known]
    if todo:
        factory = functools.partial(_store_loader_for, root)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for iso, close in pool.map(_close_of, [(factory, d) for d in todo], chunksize=16):
                if close is not None:
                    known[iso] = close
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(sorted(known.items()))))
        tmp.replace(cache)
    return Trend({date.fromisoformat(k): v for k, v in known.items() if first <= date.fromisoformat(k) <= last})
