"""Parse Binance archive CSV payloads and check candle completeness."""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

# Binance switched spot archives to microsecond timestamps in 2025.
_MICROSECOND_THRESHOLD = 10**14


def _to_ms(value: str) -> int:
    stamp = int(value)
    return stamp // 1000 if stamp >= _MICROSECOND_THRESHOLD else stamp


@dataclass(frozen=True, slots=True)
class Kline:
    open_time: int  # UTC milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    taker_buy_volume: float

    @property
    def delta(self) -> float:
        """Taker buy minus taker sell volume (protocol section 3.1)."""
        return 2 * self.taker_buy_volume - self.volume


@dataclass(frozen=True, slots=True)
class FundingRate:
    time: int  # UTC milliseconds
    rate: float
    proxy: bool = False  # flat cost before the perpetual existed, charged to both sides


def read_single_csv(archive: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [name for name in bundle.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("archive must contain exactly one CSV file")
        return bundle.read(names[0]).decode("utf-8")


def _rows(text: str) -> list[list[str]]:
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if rows and not rows[0][0].strip().lstrip("-").isdigit():
        rows = rows[1:]  # header row (USD-M archives since 2022)
    return rows


def parse_klines(text: str) -> list[Kline]:
    result = []
    for row in _rows(text):
        if len(row) < 10:
            raise ValueError("kline row has fewer than 10 columns")
        kline = Kline(
            open_time=_to_ms(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_time=_to_ms(row[6]),
            taker_buy_volume=float(row[9]),
        )
        if kline.low > min(kline.open, kline.close) or kline.high < max(kline.open, kline.close):
            raise ValueError(f"invalid OHLC at {kline.open_time}")
        if kline.volume < 0 or not 0 <= kline.taker_buy_volume <= kline.volume * (1 + 1e-9):
            raise ValueError(f"invalid volume at {kline.open_time}")
        result.append(kline)
    return result


def parse_funding(text: str) -> list[FundingRate]:
    result = []
    for row in _rows(text):
        if len(row) < 3:
            raise ValueError("funding row has fewer than 3 columns")
        result.append(FundingRate(time=_to_ms(row[0]), rate=float(row[2])))
    return result


@dataclass(frozen=True, slots=True)
class Gap:
    after_open_time: int
    before_open_time: int
    missing: int


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    expected: int
    present: int
    duplicates: int
    out_of_order: int
    gaps: tuple[Gap, ...]

    @property
    def missing(self) -> int:
        return sum(gap.missing for gap in self.gaps)

    @property
    def complete(self) -> bool:
        return self.missing == 0 and self.duplicates == 0 and self.out_of_order == 0


def check_completeness(klines: list[Kline], interval_ms: int, start_ms: int, end_ms: int) -> CompletenessReport:
    """Count missing, duplicate and unordered candles in [start_ms, end_ms)."""
    if interval_ms <= 0 or end_ms <= start_ms:
        raise ValueError("invalid range")
    expected = (end_ms - start_ms) // interval_ms
    seen: set[int] = set()
    duplicates = out_of_order = 0
    previous = None
    for kline in klines:
        if kline.open_time in seen:
            duplicates += 1
        seen.add(kline.open_time)
        if previous is not None and kline.open_time < previous:
            out_of_order += 1
        previous = kline.open_time
    times = sorted(t for t in seen if start_ms <= t < end_ms)
    gaps = []
    cursor = start_ms - interval_ms
    for stamp in times + [end_ms]:
        missing = (stamp - cursor) // interval_ms - 1
        if missing > 0:
            gaps.append(Gap(cursor, stamp, missing))
        cursor = stamp
    return CompletenessReport(expected, len(times), duplicates, out_of_order, tuple(gaps))
