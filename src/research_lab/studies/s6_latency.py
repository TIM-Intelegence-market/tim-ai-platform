"""Study S6 latency check on USD-M aggTrades (section 6.2, package P5).

A 1-minute low is itself a trade, so "did anything trade below L(1 - delta)" is always true
for a counted fill. This module checks what klines cannot show, per fill and per day drawn
with a fixed seed from the training fill days:

(a) when the first trade at or beyond L(1 - delta) (buy) / L(1 + delta) (sell) happened in
    the fill minute; a fill in the first ``PLACEMENT_MS`` is doubtful (order not yet resting);
(b) whether trades at or through L happened while the order was being placed (first
    ``PLACEMENT_MS``): post-only would have rejected it. The literal count of any trade at
    L before (a) is reported too, for disclosure, but price has to pass L to reach
    L(1 - delta), so it does not decide;
(c) the quantity traded at or beyond L(1 - delta) from (a) on; less than q = N / L is doubtful.

lambda = doubtful / checked, at least ``LAMBDA_MIN``; above ``LAMBDA_RAISE`` the margin
delta has to be raised before the first training run (section 6.2). Daily archives are
verified against Binance's checksum sidecar, reduced to the fill minutes and not kept.
Days from 2025-01-01 on are the holdout and are refused.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from src.research_lab.data.archive import USDM_SYMBOLS
from src.research_lab.data.store import DEFAULT_ROOT, HoldoutLocked, http_fetch
from src.research_lab.hypotheses.s6 import LONG, MINUTE_MS, NOMINAL
from src.research_lab.protocol import HOLDOUT_START_MS
from src.v2_readiness.backfill import parse_official_checksum

AGG_BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
LATENCY_SEED = 20261031
DAYS_PER_SYMBOL = 10
PLACEMENT_MS = 3_000  # the order is not in the book during the first seconds of the minute
LAMBDA_MIN = 0.05
LAMBDA_RAISE = 0.25
MINUTES_SUBDIR = "futures_um/aggTrades_minutes"

Fetcher = Callable[[str], bytes]


def _long_fetch(url: str) -> bytes:
    return http_fetch(url, timeout=600.0)


@dataclass(frozen=True, slots=True)
class AggTradesDayRef:
    symbol: str
    day: date

    def __post_init__(self) -> None:
        if self.symbol not in USDM_SYMBOLS:
            raise ValueError(f"research lab USD-M scope is {', '.join(USDM_SYMBOLS)}")
        if self.start_ms >= HOLDOUT_START_MS:
            raise HoldoutLocked(f"{self.day.isoformat()} lies in the holdout")

    @property
    def filename(self) -> str:
        return f"{self.symbol}-aggTrades-{self.day.isoformat()}.zip"

    @property
    def url(self) -> str:
        return f"{AGG_BASE}/{self.symbol}/{self.filename}"

    @property
    def checksum_url(self) -> str:
        return self.url + ".CHECKSUM"

    @property
    def start_ms(self) -> int:
        return int(datetime(self.day.year, self.day.month, self.day.day, tzinfo=timezone.utc).timestamp() * 1000)

    @property
    def end_ms(self) -> int:
        return self.start_ms + 86_400_000


@dataclass(frozen=True, slots=True)
class AggTrade:
    ts: int  # UTC milliseconds
    price: float
    qty: float


def iter_trades(archive: bytes) -> Iterator[AggTrade]:
    """Stream (ts, price, qty) from a daily aggTrades zip: agg_trade_id, price, quantity, first_id, last_id, transact_time, is_buyer_maker."""
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [n for n in bundle.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("archive must contain exactly one CSV file")
        with bundle.open(names[0]) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            for row in reader:
                if not row or not row[0].strip().isdigit():
                    continue  # header row (USD-M archives since 2022) or blank
                ts = int(row[5])
                if ts > 10**14:  # microseconds in newer archives
                    ts //= 1000
                yield AggTrade(ts, float(row[1]), float(row[2]))


def trades_in_minutes(archive: bytes, minute_starts: Iterable[int]) -> dict[int, list[AggTrade]]:
    wanted = {m: [] for m in minute_starts}
    for trade in iter_trades(archive):
        key = trade.ts - trade.ts % MINUTE_MS
        bucket = wanted.get(key)
        if bucket is not None:
            bucket.append(trade)
    for bucket in wanted.values():
        bucket.sort(key=lambda t: t.ts)
    return wanted


class AggTradesMinuteStore:
    """Downloads a day, verifies it, keeps only the requested minutes as JSON plus the archive SHA-256."""

    def __init__(self, root: Path | str = DEFAULT_ROOT, fetcher: Fetcher = _long_fetch) -> None:
        self.root = Path(root) / MINUTES_SUBDIR
        self.fetcher = fetcher

    def path(self, ref: AggTradesDayRef) -> Path:
        return self.root / ref.symbol / f"{ref.day.isoformat()}.json"

    def load(self, ref: AggTradesDayRef, minute_starts: Iterable[int]) -> tuple[dict[int, list[AggTrade]], str]:
        minutes = sorted(set(minute_starts))
        for m in minutes:
            if not ref.start_ms <= m < ref.end_ms:
                raise ValueError("minute outside the day")
        target = self.path(ref)
        if target.exists():
            stored = json.loads(target.read_text())
            if all(str(m) in stored["minutes"] for m in minutes):
                return ({m: [AggTrade(*row) for row in stored["minutes"][str(m)]] for m in minutes}, stored["archive_sha256"])
        checksum = self.fetcher(ref.checksum_url).decode("utf-8")
        payload = self.fetcher(ref.url)
        expected = parse_official_checksum(checksum, expected_filename=ref.filename)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != expected:
            raise ValueError(f"{ref.filename}: checksum mismatch")
        found = trades_in_minutes(payload, minutes)
        del payload
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"archive": ref.filename, "archive_sha256": digest, "url": ref.url,
                                      "minutes": {str(m): [[t.ts, t.price, t.qty] for t in ts] for m, ts in found.items()}}))
        return found, digest


def sample_days(fill_days: dict[str, Iterable[str]], *, seed: int = LATENCY_SEED, per_symbol: int = DAYS_PER_SYMBOL) -> dict[str, list[str]]:
    """Uniform draw of calendar days per instrument, instruments in sorted order, one generator (section 6.2)."""
    rnd = random.Random(seed)
    out: dict[str, list[str]] = {}
    for symbol in sorted(fill_days):
        days = sorted(set(fill_days[symbol]))
        out[symbol] = sorted(rnd.sample(days, min(per_symbol, len(days))))
    return out


@dataclass(frozen=True, slots=True)
class FillCheck:
    symbol: str
    k: float
    open_time: int
    side: int
    limit: float
    delta: float
    q: float
    trades: int
    first_through_ms: int | None  # offset inside the minute
    pre_crossed_placement: bool  # a trade at/through L inside PLACEMENT_MS before (a)
    pre_crossed_any: bool  # literal reading, disclosure only
    qty_through: float
    reasons: tuple[str, ...]

    @property
    def doubtful(self) -> bool:
        return bool(self.reasons)


def check_fill(trades: Sequence[AggTrade], minute_start: int, *, symbol: str, k: float, side: int, limit: float, delta: float,
               nominal: float = NOMINAL, placement_ms: int = PLACEMENT_MS) -> FillCheck:
    through = limit - delta if side == LONG else limit + delta
    beyond = (lambda p: p <= through) if side == LONG else (lambda p: p >= through)
    at_limit = (lambda p: p <= limit) if side == LONG else (lambda p: p >= limit)
    first: int | None = None
    pre_place = pre_any = False
    qty = 0.0
    for t in trades:
        if first is None:
            if beyond(t.price):
                first = t.ts - minute_start
                qty += t.qty
            elif at_limit(t.price):
                pre_any = True
                if t.ts - minute_start < placement_ms:
                    pre_place = True
        elif beyond(t.price):
            qty += t.qty
    q = nominal / limit
    reasons: list[str] = []
    if first is None:
        reasons.append("no_trade")
    elif first < placement_ms:
        reasons.append("early")
    if pre_place:
        reasons.append("pre_crossed")
    if first is not None and qty < q:
        reasons.append("thin")
    return FillCheck(symbol, k, minute_start, side, limit, delta, q, len(trades), first, pre_place, pre_any, qty, tuple(reasons))


def summarize(checks: Sequence[FillCheck]) -> dict:
    n = len(checks)
    doubtful = sum(1 for c in checks if c.doubtful)
    raw = doubtful / n if n else 0.0
    reasons: dict[str, int] = {}
    for c in checks:
        for r in c.reasons:
            reasons[r] = reasons.get(r, 0) + 1
    offsets = sorted(c.first_through_ms for c in checks if c.first_through_ms is not None)
    return {
        "checked": n,
        "doubtful": doubtful,
        "lambda_raw": round(raw, 4),
        "lambda": round(max(LAMBDA_MIN, raw), 4) if n else None,
        "raise_delta": raw > LAMBDA_RAISE,
        "reasons": dict(sorted(reasons.items())),
        "pre_crossed_any_literal": sum(1 for c in checks if c.pre_crossed_any),
        "first_through_ms_median": offsets[len(offsets) // 2] if offsets else None,
        "first_through_ms_p10": offsets[len(offsets) // 10] if offsets else None,
    }


def check_as_dict(c: FillCheck) -> dict:
    d = asdict(c)
    d["doubtful"] = c.doubtful
    return d
