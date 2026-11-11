"""Daily USD-M "metrics" archive files (open interest) from data.binance.vision.

Binance publishes open interest only as daily files (``futures/um/daily/metrics``), with one 5-minute
snapshot per row. The files for 2020-09 to 2021-11 were added on 2026-03-18; older notes saying the
archive starts in 12/2021 predate that. Some days were uploaded again later (2026-07 to 2026-10), so the
store pins the SHA-256 of the first verified download in its manifest and the dataset hash records it.

``MetricsRef`` has the same surface ``ArchiveStore.fetch`` uses for monthly files (url, checksum_url,
filename, local_path, touches_holdout), so fetching, checksum checks and the holdout lock are shared.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from src.research_lab.data.archive import BASE_URL, USDM_SYMBOLS
from src.research_lab.protocol import HOLDOUT_START_MS

FIRST_DAY = date(2020, 9, 1)  # first daily metrics file for BTCUSDT (listing checked 2026-11-11)
_DAY_MS = 86_400_000


def _day_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class MetricsRef:
    """One daily metrics archive file (USD-M futures)."""

    day: date
    symbol: str = "BTCUSDT"

    def __post_init__(self) -> None:
        if self.symbol not in USDM_SYMBOLS:
            raise ValueError(f"research lab scope for futures/um is {', '.join(USDM_SYMBOLS)}")
        if self.day < FIRST_DAY:
            raise ValueError("the metrics archive starts on 2020-09-01")

    @property
    def filename(self) -> str:
        return f"{self.symbol}-metrics-{self.day.isoformat()}.zip"

    @property
    def url(self) -> str:
        return f"{BASE_URL}/futures/um/daily/metrics/{self.symbol}/{self.filename}"

    @property
    def checksum_url(self) -> str:
        return self.url + ".CHECKSUM"

    @property
    def local_path(self) -> str:
        return f"futures_um/metrics/{self.symbol}/5m/{self.filename}"

    @property
    def start_ms(self) -> int:
        return _day_ms(self.day)

    @property
    def end_ms(self) -> int:
        return self.start_ms + _DAY_MS

    @property
    def touches_holdout(self) -> bool:
        return self.end_ms > HOLDOUT_START_MS


def days(first: date, last: date) -> list[date]:
    """Inclusive list of days."""
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


@dataclass(frozen=True, slots=True)
class OpenInterest:
    time: int  # UTC milliseconds of the snapshot (create_time)
    contracts: float  # sum_open_interest, in BTC; not the USD value, so the price does not enter twice


def _to_ms(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)


def parse_metrics(text: str) -> list[OpenInterest]:
    """Snapshots sorted by time. Files up to 2021-11 repeat every row; repeats with the same value collapse,
    two different values for one time are an error (nothing is guessed)."""
    by_time: dict[int, float] = {}
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].strip() == "create_time":
            continue
        if len(row) < 3:
            raise ValueError("metrics row has fewer than 3 columns")
        t, oi = _to_ms(row[0]), float(row[2])
        if t in by_time and by_time[t] != oi:
            raise ValueError(f"two open interest values for one snapshot ({row[0]})")
        by_time[t] = oi
    return [OpenInterest(t, v) for t, v in sorted(by_time.items())]
