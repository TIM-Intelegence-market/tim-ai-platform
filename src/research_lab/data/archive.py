"""References to public Binance archive files (data.binance.vision).

Checksum handling reuses src/v2_readiness/backfill.py so both paths verify
archives the same way.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.research_lab.protocol import HOLDOUT_START_MS, _utc_ms
from src.v2_readiness.backfill import parse_official_checksum, verify_archive

BASE_URL = "https://data.binance.vision/data"
SYMBOL = "BTCUSDT"
# Study S4 (docs/research_lab/studien/S4_...) adds ETH and SOL perpetuals; study S5 (funding carry,
# spot leg) adds the same three spot symbols. Nothing else is in scope.
USDM_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SPOT_SYMBOLS = USDM_SYMBOLS

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class Market(StrEnum):
    SPOT = "spot"
    USDM = "futures/um"


class Dataset(StrEnum):
    KLINES = "klines"
    FUNDING = "fundingRate"


@dataclass(frozen=True, slots=True)
class ArchiveRef:
    """One monthly archive file."""

    market: Market
    dataset: Dataset
    year: int
    month: int
    interval: str | None = None
    symbol: str = SYMBOL

    def __post_init__(self) -> None:
        allowed = USDM_SYMBOLS if self.market is Market.USDM else SPOT_SYMBOLS
        if self.symbol not in allowed:
            raise ValueError(f"research lab scope for {self.market.value} is {', '.join(allowed)}")
        if not 1 <= self.month <= 12 or self.year < 2017:
            raise ValueError("invalid archive month")
        if self.dataset is Dataset.KLINES:
            if self.interval not in INTERVAL_MS:
                raise ValueError(f"unsupported kline interval: {self.interval}")
        else:
            if self.interval is not None:
                raise ValueError("funding archives have no interval")
            if self.market is not Market.USDM:
                raise ValueError("funding rates exist only for USD-M futures")

    @property
    def period(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def filename(self) -> str:
        if self.dataset is Dataset.KLINES:
            return f"{self.symbol}-{self.interval}-{self.period}.zip"
        return f"{self.symbol}-fundingRate-{self.period}.zip"

    @property
    def url(self) -> str:
        if self.dataset is Dataset.KLINES:
            path = f"{self.market.value}/monthly/klines/{self.symbol}/{self.interval}"
        else:
            path = f"{self.market.value}/monthly/fundingRate/{self.symbol}"
        return f"{BASE_URL}/{path}/{self.filename}"

    @property
    def checksum_url(self) -> str:
        return self.url + ".CHECKSUM"

    @property
    def local_path(self) -> str:
        market = self.market.value.replace("/", "_")
        interval = self.interval or "8h"
        return f"{market}/{self.dataset.value}/{self.symbol}/{interval}/{self.filename}"

    @property
    def start_ms(self) -> int:
        return _utc_ms(self.year, self.month, 1)

    @property
    def end_ms(self) -> int:
        year, month = (self.year + 1, 1) if self.month == 12 else (self.year, self.month + 1)
        return _utc_ms(year, month, 1)

    @property
    def touches_holdout(self) -> bool:
        return self.end_ms > HOLDOUT_START_MS


def checked_digest(ref: ArchiveRef, checksum_payload: str, archive_payload: bytes) -> str:
    """Return the verified SHA-256 of an archive or raise if it does not match."""
    digest = parse_official_checksum(checksum_payload, expected_filename=ref.filename)
    if not verify_archive(archive_payload, digest):
        raise ValueError(f"checksum mismatch for {ref.filename}")
    return digest
