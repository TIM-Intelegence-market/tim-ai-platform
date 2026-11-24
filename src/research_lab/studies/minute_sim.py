"""Shared pieces of S34 and S35a: minute-bar loading, one trade simulator, costs, funding, bootstrap, random control.

Everything is past-only and works on the S8 1.2.0 minute bars (``bars/<SYMBOL>-<day>.csv``) and day profiles
(``profile/<SYMBOL>-<day>.csv``). A missing minute is filled with the previous close and zero volume; nothing is
interpolated otherwise. Costs and rules are the ones frozen in the S34 / S35a pre-registrations.
"""
from __future__ import annotations

import csv
import io
import json
import math
import random
import zipfile
from array import array
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

E8 = 1e8
MINUTE_MS = 60_000
DAY_MS = 86_400_000

# Costs per side (fractions of price): Bitunix VIP0 taker 0.06 % (contract.FEE_TAKER), slippage as research protocol 1.1
# (0.03 % per side, 0.05 % on a stop fill; the spread is part of this slippage). Funding is added separately.
FEE = 0.0006
SLIP = 0.0003
SLIP_STOP = 0.0005


def ms_of(day: date) -> int:
    return (day - date(1970, 1, 1)).days * DAY_MS


def days(first: date, last: date):
    d = first
    while d <= last:
        yield d
        d += timedelta(days=1)


class Minutes:
    """Minute grid from ``first`` 00:00 UTC; index i <-> start_ms = t0 + i * 60000."""

    def __init__(self, root: str | Path, symbol: str, first: date, last: date) -> None:
        self.root, self.symbol, self.first, self.last = Path(root), symbol, first, last
        self.t0 = ms_of(first)
        n = ((last - first).days + 1) * 1440
        self.n = n
        self.open, self.high, self.low, self.close = (array("d", [0.0]) * n for _ in range(4))
        self.buy_q, self.sell_q, self.base = (array("d", [0.0]) * n for _ in range(3))  # quote USDT, base units
        self.valid = bytearray(n)
        manifest = json.loads((self.root / "bars_manifest.json").read_text()) if (self.root / "bars_manifest.json").exists() else {}
        self.width = {k: v["profile_width_e8"] for k, v in manifest.items()}
        prev = 0.0
        for d in days(first, last):
            f = self.root / "bars" / f"{symbol}-{d.isoformat()}.csv"
            base_i = (d - first).days * 1440
            if f.exists():
                with open(f, newline="") as fh:
                    for r in csv.DictReader(fh):
                        i = (int(r["window_start_ms"]) - self.t0) // MINUTE_MS
                        if not 0 <= i < n:
                            continue
                        if int(r["trade_count"]) == 0:
                            continue  # empty minute (all-zero row): filled below with the previous close
                        self.open[i] = int(r["first_price_e8"]) / E8
                        self.high[i] = int(r["high_price_e8"]) / E8
                        self.low[i] = int(r["low_price_e8"]) / E8
                        self.close[i] = int(r["last_price_e8"]) / E8
                        self.buy_q[i] = int(r["buy_quote_e8"]) / E8
                        self.sell_q[i] = int(r["sell_quote_e8"]) / E8
                        self.base[i] = (int(r["buy_sats"]) + int(r["sell_sats"])) / E8
                        self.valid[i] = 1
            for i in range(base_i, base_i + 1440):
                if self.valid[i]:
                    prev = self.close[i]
                else:
                    self.open[i] = self.high[i] = self.low[i] = self.close[i] = prev

    def day_profile(self, d: date):
        """[(minute_of_day, price_center, volume_base)] for one UTC day, or []. Volume in base units."""
        f = self.root / "profile" / f"{self.symbol}-{d.isoformat()}.csv"
        w = self.width.get(d.isoformat())
        if not f.exists() or not w:
            return []
        out = []
        with open(f, newline="") as fh:
            for r in csv.DictReader(fh):
                price = (int(r["bin"]) + 0.5) * w / E8
                out.append((int(r["minute"]), price, (int(r["buy_sats"]) + int(r["sell_sats"])) / E8))
        return out


class Funding:
    """Binance USD-M monthly fundingRate zips; ``cost(direction, entry_ms, exit_ms)`` = sum of rates settled in (entry, exit]
    paid by a long (received by a short). Missing months raise: no silent zero funding."""

    def __init__(self, root: str | Path, symbol: str, first: date, last: date) -> None:
        self.times: list[int] = []
        self.rates: list[float] = []
        y, m = first.year, first.month
        while (y, m) <= (last.year, last.month):
            f = Path(root) / symbol / f"{symbol}-fundingRate-{y}-{m:02d}.zip"
            if not f.exists():
                raise FileNotFoundError(f"no funding file {f}")
            with zipfile.ZipFile(f) as z:
                for r in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
                    self.times.append(int(r["calc_time"]))
                    self.rates.append(float(r["last_funding_rate"]))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        order = sorted(range(len(self.times)), key=self.times.__getitem__)
        self.times = [self.times[i] for i in order]
        self.rates = [self.rates[i] for i in order]

    def cost(self, direction: int, entry_ms: int, exit_ms: int) -> float:
        from bisect import bisect_right
        lo, hi = bisect_right(self.times, entry_ms), bisect_right(self.times, exit_ms)
        return direction * sum(self.rates[lo:hi])


@dataclass(frozen=True)
class Trade:
    symbol: str
    direction: int          # +1 long, -1 short
    signal_ms: int
    entry_ms: int
    exit_ms: int
    entry: float
    stop: float
    target: float | None
    exit: float
    reason: str             # target / stop / time
    gross_r: float
    net_r: float
    stop_frac: float
    target_frac: float | None
    tag: str = ""


def simulate(m: Minutes, funding: Funding | None, symbol: str, direction: int, i_entry: int, stop: float, target: float | None,
             max_minutes: int, signal_ms: int, tag: str = "", entry_override: float | None = None) -> Trade | None:
    """Enter at the open of minute ``i_entry``; per minute the stop is checked before the target (stop first when both touch
    inside one minute); otherwise exit at the close of the last allowed minute. None when the entry is already beyond the stop
    or the target (no trade)."""
    entry = m.open[i_entry] if entry_override is None else entry_override
    if direction > 0 and (entry <= stop or (target is not None and entry >= target)):
        return None
    if direction < 0 and (entry >= stop or (target is not None and entry <= target)):
        return None
    last = min(i_entry + max_minutes, m.n) - 1
    reason, exit_price, j_exit = "time", m.close[last], last
    for j in range(i_entry, last + 1):
        hit_stop = m.low[j] <= stop if direction > 0 else m.high[j] >= stop
        hit_tgt = target is not None and (m.high[j] >= target if direction > 0 else m.low[j] <= target)
        if hit_stop:
            reason, exit_price, j_exit = "stop", stop, j
            break
        if hit_tgt:
            reason, exit_price, j_exit = "target", target, j
            break
    entry_ms = m.t0 + i_entry * MINUTE_MS
    exit_ms = m.t0 + (j_exit + 1) * MINUTE_MS
    risk = abs(entry - stop) / entry
    gross = direction * (exit_price - entry) / entry
    cost = 2 * FEE + SLIP + (SLIP_STOP if reason == "stop" else SLIP)
    fund = funding.cost(direction, entry_ms, exit_ms) if funding is not None else 0.0
    return Trade(symbol, direction, signal_ms, entry_ms, exit_ms, entry, stop, target, exit_price, reason,
                 gross / risk, (gross - cost - fund) / risk, risk, None if target is None else abs(target - entry) / entry, tag)


def year_of(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap_lower(values: list[float], level: float = 0.90, draws: int = 10_000, seed: int = 34) -> float:
    """Lower bound of the one-sided ``level`` interval of the mean (iid bootstrap): the (1 - level) quantile."""
    if not values:
        return float("nan")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(draws))
    return means[int((1 - level) * draws)]


def random_control(m: Minutes, funding: Funding | None, symbol: str, trades: list[Trade], eligible: list[int], max_minutes: int,
                   draws: int = 1000, seed: int = 35) -> dict:
    """Same number of trades, same direction mix, same stop and target distance (as fractions of the entry), entry minute drawn
    at random from ``eligible`` (indices of candle starts in the period). p = share of draws with a mean net R >= the real one."""
    rng = random.Random(seed)
    real = mean([t.net_r for t in trades])
    means = []
    for _ in range(draws):
        res = []
        for t in trades:
            for _try in range(20):
                i = eligible[rng.randrange(len(eligible))]
                e = m.open[i]
                stop = e * (1 - t.direction * t.stop_frac)
                tgt = None if t.target_frac is None else e * (1 + t.direction * t.target_frac)
                x = simulate(m, funding, symbol, t.direction, i, stop, tgt, max_minutes, m.t0 + i * MINUTE_MS)
                if x is not None:
                    res.append(x.net_r)
                    break
        means.append(mean(res))
    p = (1 + sum(1 for x in means if x >= real)) / (draws + 1)
    means.sort()
    return {"real_mean_net_r": real, "random_mean": mean(means), "random_p95": means[int(0.95 * draws)], "p": p, "draws": draws}


def summary(trades: list[Trade]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0}
    by_year: dict[int, list[float]] = {}
    for t in trades:
        by_year.setdefault(year_of(t.entry_ms), []).append(t.net_r)
    return {
        "n": n,
        "stop_share": sum(t.reason == "stop" for t in trades) / n,
        "target_share": sum(t.reason == "target" for t in trades) / n,
        "time_share": sum(t.reason == "time" for t in trades) / n,
        "gross_mean_r": mean([t.gross_r for t in trades]),
        "net_mean_r": mean([t.net_r for t in trades]),
        "mean_stop_pct": 100 * mean([t.stop_frac for t in trades]),
        "net_r_by_year": {y: {"n": len(v), "mean": mean(v), "sum": sum(v)} for y, v in sorted(by_year.items())},
    }


def leave_one_year_out(trades: list[Trade], min_trades: int = 10, share: float = 0.6) -> dict:
    """Carried by one year or by < min_trades? Pass when every leave-one-year-out mean net R stays > 0, no year holds more than
    ``share`` of the positive total and the years that count have >= min_trades trades (others are listed, not counted)."""
    by_year: dict[int, list[float]] = {}
    for t in trades:
        by_year.setdefault(year_of(t.entry_ms), []).append(t.net_r)
    total = sum(sum(v) for v in by_year.values())
    rows, ok = {}, True
    for y, v in by_year.items():
        rest = [x for yy, vv in by_year.items() if yy != y for x in vv]
        loo = mean(rest) if rest else float("nan")
        carries = total > 0 and sum(v) / total > share and len(by_year) > 1
        thin = len(v) < min_trades
        rows[y] = {"n": len(v), "sum_r": sum(v), "leave_out_mean": loo, "carries_total": carries, "thin": thin}
        if not (loo > 0) or carries:
            ok = False
    return {"ok": ok and len(by_year) > 1, "years": rows}
