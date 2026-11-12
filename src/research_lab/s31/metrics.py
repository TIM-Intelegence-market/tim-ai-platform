"""Binance USD-M "metrics" (5-min snapshots): open interest and taker buy/sell volume ratio, read from local daily zips.

Past-only: a window ending at ``end_ms`` uses snapshots with create_time <= end_ms. Missing coverage returns None
(the detector then gives no signal); nothing is interpolated or guessed.
"""
from __future__ import annotations

import csv
import io
import math
import zipfile
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

SNAP_MS = 300_000


def _ms(text: str) -> int:
    y, mo, d = int(text[0:4]), int(text[5:7]), int(text[8:10])
    h, mi, se = int(text[11:13]), int(text[14:16]), int(text[17:19])
    return ((date(y, mo, d) - date(1970, 1, 1)).days * 86400 + h * 3600 + mi * 60 + se) * 1000


class Metrics:
    def __init__(self, times: list[int], oi: list[float], ratio: list[float]) -> None:
        self.times, self.oi, self.ratio = times, oi, ratio

    @classmethod
    def load(cls, root: str | Path, first: date, last: date, symbol: str = "BTCUSDT") -> "Metrics":
        """``root`` = .../metrics/BTCUSDT/5m with <symbol>-metrics-<day>.zip. Missing days are simply absent."""
        times: list[int] = []
        oi: list[float] = []
        ratio: list[float] = []
        seen: dict[int, tuple[float, float]] = {}
        d = first
        while d <= last:
            f = Path(root) / f"{symbol}-metrics-{d.isoformat()}.zip"
            if f.exists():
                with zipfile.ZipFile(f) as z:
                    text = z.read(z.namelist()[0]).decode("utf-8")
                for row in csv.DictReader(io.StringIO(text)):
                    try:
                        t = _ms(row["create_time"])
                        val = (float(row["sum_open_interest"]), float(row["sum_taker_long_short_vol_ratio"]))
                    except (ValueError, KeyError):
                        continue
                    if t in seen and seen[t] != val:
                        raise ValueError(f"two different metrics rows for {row['create_time']}")
                    seen[t] = val
            d += timedelta(days=1)
        for t in sorted(seen):
            times.append(t)
            oi.append(seen[t][0])
            ratio.append(seen[t][1])
        return cls(times, oi, ratio)

    def window(self, end_ms: int, minutes: int) -> tuple[float, float] | None:
        """(open-interest change over the window, mean log taker ratio over it) or None if not fully covered."""
        hi = bisect_right(self.times, end_ms) - 1
        lo = bisect_right(self.times, end_ms - minutes * 60_000) - 1
        if hi < 0 or lo < 0 or end_ms - self.times[hi] > 2 * SNAP_MS or hi - lo < minutes // 5 - 1:
            return None
        if self.oi[lo] <= 0:
            return None
        logs = [math.log(r) for r in self.ratio[lo + 1:hi + 1] if r > 0]
        if not logs:
            return None
        return self.oi[hi] / self.oi[lo] - 1.0, sum(logs) / len(logs)
