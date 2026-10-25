"""Gemeinsame Helfer für das Trading-Team (nur öffentliche Daten, nur Papier).

Kein Modul dieses Skills spricht private Börsen-Endpunkte an, liest API-Schlüssel
oder sendet Orders. Ein statischer Test (tests/test_safety.py) wacht darüber.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

USER_AGENT = "TIM-trading-team/1.0 (paper only)"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

BINANCE_BASE = "https://api.binance.com"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Stablecoins und gehebelte Token haben keine sinnvollen Ausbrüche.
STABLE_BASES = {
    "USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "USDD", "PYUSD", "EUR", "EURI",
    "AEUR", "USDE", "XUSD", "USD1", "BFUSD", "GBP", "TRY", "BRL",
}
# Kein "UP": sonst fielen echte Coins wie JUP oder SYRUP heraus (Binance-Hebel-Token sind ohnehin delistet).
LEVERAGED_SUFFIXES = ("DOWN", "BULL", "BEAR")


def default_data_dir() -> Path:
    """Ablage für CSVs und Zustand. Standard: ./state/trading-team (per .gitignore ausgeschlossen)."""
    return Path(os.environ.get("TRADING_TEAM_DIR", "state/trading-team"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def ms_to_dt(ms: int | float) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def dt_to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def http_get_bytes(url: str, timeout: float = 15.0) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"nur https erlaubt: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (nur https, oben geprüft)
        data = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Antwort zu groß: {url}")
    return data


def http_get_json(url: str, timeout: float = 15.0):
    return json.loads(http_get_bytes(url, timeout).decode("utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def append_rows(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def signal_key(symbol: str, candle_close_time: str) -> str:
    return f"{symbol}@{candle_close_time}"


class BinancePublic:
    """Nur öffentliche Marktdaten-Endpunkte von Binance Spot (ohne Schlüssel)."""

    def __init__(self, base: str = BINANCE_BASE, timeout: float = 15.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def tickers_24h(self) -> list[dict]:
        return http_get_json(f"{self.base}/api/v3/ticker/24hr", self.timeout)

    def klines(self, symbol: str, interval: str, limit: int, start_ms: int | None = None) -> list[list]:
        url = f"{self.base}/api/v3/klines?symbol={urllib.parse.quote(symbol)}&interval={interval}&limit={int(limit)}"
        if start_ms is not None:
            url += f"&startTime={int(start_ms)}"
        return http_get_json(url, self.timeout)

    def price(self, symbol: str) -> float:
        data = http_get_json(f"{self.base}/api/v3/ticker/price?symbol={urllib.parse.quote(symbol)}", self.timeout)
        return float(data["price"])


class SnapshotMarket:
    """Offline-Quelle aus einer JSON-Datei, z. B. für Tests oder die Cloud (Binance dort gesperrt).

    Format: {"tickers": [...], "klines": {"BTCUSDT:1h": [[...], ...]}, "prices": {"BTCUSDT": 1.0}}
    """

    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def from_file(cls, path: Path) -> "SnapshotMarket":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def tickers_24h(self) -> list[dict]:
        return list(self.data.get("tickers", []))

    def klines(self, symbol: str, interval: str, limit: int, start_ms: int | None = None) -> list[list]:
        rows = list(self.data.get("klines", {}).get(f"{symbol}:{interval}", []))
        if start_ms is not None:
            rows = [r for r in rows if int(r[0]) >= start_ms]
        return rows[-limit:] if start_ms is None else rows[:limit]

    def price(self, symbol: str) -> float:
        return float(self.data["prices"][symbol])
