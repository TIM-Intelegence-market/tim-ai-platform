from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import re


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SYMBOL = "BTCUSDT"
MARKET = "BINANCE_SPOT"
DATASET = "aggTrades"


@dataclass(frozen=True, slots=True)
class BinanceArchiveRef:
    trading_date: date
    symbol: str = SYMBOL

    def __post_init__(self) -> None:
        if self.symbol != SYMBOL:
            raise ValueError("V2 evidence scope is fixed to BTCUSDT")

    @property
    def filename(self) -> str:
        return f"{self.symbol}-aggTrades-{self.trading_date.isoformat()}.zip"

    @property
    def url(self) -> str:
        return (
            "https://data.binance.vision/data/spot/daily/aggTrades/"
            f"{self.symbol}/{self.filename}"
        )

    @property
    def checksum_url(self) -> str:
        return self.url + ".CHECKSUM"


def parse_official_checksum(payload: str, *, expected_filename: str) -> str:
    """Parse Binance's checksum sidecar and bind it to the exact archive name."""
    parts = payload.strip().split()
    if len(parts) != 2:
        raise ValueError("checksum sidecar must contain a hash and filename")
    digest, filename = parts
    filename = filename.removeprefix("*")
    if not SHA256_RE.fullmatch(digest.lower()):
        raise ValueError("checksum sidecar does not contain a SHA-256 digest")
    if filename != expected_filename:
        raise ValueError("checksum sidecar filename does not match requested archive")
    return digest.lower()


def verify_archive(payload: bytes, expected_sha256: str) -> bool:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
    return hashlib.sha256(payload).hexdigest() == expected_sha256
