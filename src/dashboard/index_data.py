"""Nasdaq-100 candles for the chart from Twelve Data with TIM's own API key (Uzi 16.11.2026: "per api key").

Key handling follows the FRED key (``research_lab.external.fred_secret``): exactly one provider,
selected by ``TIM_TWELVEDATA_SECRET_PROVIDER`` (``keychain``, ``file`` or ``env``); on the Mac without
that variable the macOS Keychain entry ``com.tim.twelvedata`` / ``tim`` is read. The key only lives in a
``SecretValue``, never in a log, a note, an error text or the chart JSON. Without a key the chart falls back
to the public Yahoo endpoint (``chart_live.fetch_yahoo_index``) and says so.

Twelve Data's free plan allows 8 requests a minute and 800 a day, so the chart keeps index candles longer
(``INDEX_TTL``). Display only: nothing here feeds a plan, a score or an order.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.secrets import SecretProviderError, SecretValue, _require_private_regular_file, _safe_identifier

PROVIDER_ENV = "TIM_TWELVEDATA_SECRET_PROVIDER"
KEY_ENV = "TIM_TWELVEDATA_API_KEY"
FILE_ENV = "TIM_TWELVEDATA_SECRET_FILE"
SYMBOL_ENV = "TIM_NASDAQ_SYMBOL"  # NDX (index) by default; QQQ if the plan has no indices
DEFAULT_SECRET_FILE = "~/Library/Application Support/TIM/twelvedata-api-key"
KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT = "com.tim.twelvedata", "tim"
KEYCHAIN_SERVICES = (KEYCHAIN_SERVICE, "twelvedata")  # Uzi stored the key as "twelvedata" (16.11.2026): both count
KEY_SHAPE = re.compile(r"[A-Za-z0-9]{16,64}")
DEFAULT_SYMBOL = "NDX"
ALLOWED_SYMBOLS = ("NDX", "QQQ")
URL = "https://api.twelvedata.com/time_series?"
SOURCE = "Twelve Data (API-Key)"
PROVENANCE = "TWELVEDATA_API_CHART_DISPLAY"
TIMEOUT_SECONDS = 10
MAX_BYTES = 3_000_000
MAX_OUTPUT = 1000
# view timeframe -> Twelve Data interval (3m, 6h, 12h and 3d do not exist there)
INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h",
             "1d": "1day", "1w": "1week", "1M": "1month"}
# seconds a cached answer is kept: 800 requests a day, the chart asks up to 7 frames per page
INDEX_TTL = {"1m": 120.0, "5m": 300.0, "15m": 600.0, "30m": 600.0, "1h": 900.0, "2h": 1800.0, "4h": 1800.0,
             "1d": 3600.0, "1w": 3600.0, "1M": 3600.0}


class IndexSecretError(RuntimeError):
    """No usable Twelve Data key. Messages never contain the key."""


def _keychain(env: Mapping[str, str]) -> str:
    chosen = env.get("TIM_TWELVEDATA_KEYCHAIN_SERVICE")
    for service in ((chosen,) if chosen else KEYCHAIN_SERVICES):
        try:
            return _keychain_item(env, service)
        except SecretProviderError:
            continue
    raise SecretProviderError("macOS Keychain Twelve Data secret is unavailable")


def _keychain_item(env: Mapping[str, str], service: str) -> str:
    service = _safe_identifier(service, label="Keychain service")
    account = _safe_identifier(env.get("TIM_TWELVEDATA_KEYCHAIN_ACCOUNT", KEYCHAIN_ACCOUNT), label="Keychain account")
    completed = None
    try:
        completed = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                                   check=False, capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass  # TimeoutExpired.output may hold the value: never chain it
    if completed is None or completed.returncode != 0:
        raise SecretProviderError("macOS Keychain Twelve Data secret is unavailable")
    text = None
    try:
        text = completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        pass  # the error holds the value: never chain it
    if text is None:
        raise SecretProviderError("macOS Keychain Twelve Data secret is not valid UTF-8")
    return text.strip()


def api_key(env: Mapping[str, str] | None = None) -> SecretValue:
    env = dict(os.environ if env is None else env)
    provider = env.get(PROVIDER_ENV, "").strip().lower() or ("keychain" if sys.platform == "darwin" else "")
    if provider not in ("keychain", "file", "env"):
        raise IndexSecretError(f"{PROVIDER_ENV} is not set or names an unsupported provider")
    failure, raw = None, ""
    try:
        if provider == "keychain":
            raw = _keychain(env)
        elif provider == "file":
            path = Path(env.get(FILE_ENV, DEFAULT_SECRET_FILE)).expanduser()
            _require_private_regular_file(path)
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        else:
            raw = env.get(KEY_ENV, "").strip()
    except SecretProviderError as exc:
        failure = f"{provider} provider: {exc}"
    except OSError as exc:
        failure = f"{provider} provider: {exc.__class__.__name__}"
    if failure is not None:
        raise IndexSecretError(failure)  # outside the except block: no chain that may hold the value
    if not KEY_SHAPE.fullmatch(raw):
        raise IndexSecretError(f"Twelve Data key has an invalid shape ({provider}: length={len(raw)})")
    return SecretValue(raw)


def has_key(env: Mapping[str, str] | None = None) -> bool:
    if (os.environ if env is None else env).get("TIM_RUNTIME_ENV") == "test":
        return False  # tests never reach the network
    try:
        api_key(env)
    except Exception:  # noqa: BLE001 - no key = Yahoo fallback
        return False
    return True


def symbol(env: Mapping[str, str] | None = None) -> str:
    value = (os.environ if env is None else env).get(SYMBOL_ENV, DEFAULT_SYMBOL).strip().upper()
    return value if value in ALLOWED_SYMBOLS else DEFAULT_SYMBOL


def parse(payload: Any, chart_symbol: str, interval: str, limit: int, now: datetime | None = None) -> list[dict[str, Any]]:
    """Twelve Data ``time_series`` answer (times in UTC) as chart rows in the Binance row format.

    An error answer raises with Twelve Data's code only (its message can echo the request)."""
    from src.dashboard.chart_live import INTERVAL_SECONDS

    if not isinstance(payload, Mapping) or payload.get("status") == "error" or not isinstance(payload.get("values"), list):
        code = payload.get("code") if isinstance(payload, Mapping) else None
        raise ValueError(f"Twelve Data error {code if isinstance(code, int) else '?'}")
    now = now or datetime.now(timezone.utc)
    rows = []
    for item in payload["values"]:
        try:
            text = str(item["datetime"])
            opened = datetime.fromisoformat(text if " " in text else text + " 00:00:00").replace(tzinfo=timezone.utc)
            o, h, lo, c = (float(item[k]) for k in ("open", "high", "low", "close"))
            vol = float(item.get("volume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if min(o, h, lo, c) <= 0:
            continue
        if interval == "1M":
            end = (opened.replace(year=opened.year + 1, month=1) if opened.month == 12 else opened.replace(month=opened.month + 1))
        else:
            end = opened + timedelta(seconds=INTERVAL_SECONDS[interval])
        rows.append(dict(symbol=chart_symbol, timeframe=interval, open_time=opened.isoformat(), close_time=end.isoformat(),
                         open=o, high=max(h, o, c), low=min(lo, o, c), close=c, volume=vol, provenance=PROVENANCE,
                         closed=end <= now))
    rows.sort(key=lambda r: r["open_time"])
    if len(rows) < 2:
        raise ValueError("Twelve Data: fewer than two candles")
    return rows[-max(1, min(int(limit), MAX_OUTPUT)):]


def fetch(chart_symbol: str, interval: str, limit: int, key: Callable[[], SecretValue] = api_key,
          opener: Callable[..., Any] = urlopen) -> list[dict[str, Any]]:
    if interval not in INTERVALS:
        raise ValueError("Timeframe not offered for the index")
    query = {"symbol": symbol(), "interval": INTERVALS[interval], "outputsize": max(2, min(int(limit), MAX_OUTPUT)),
             "timezone": "UTC", "order": "asc", "format": "JSON", "apikey": key().reveal()}
    request = Request(URL + urlencode(query), headers={"Accept": "application/json", "User-Agent": "TIM-dashboard/1.0"})
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - the URL carries the key: re-raise by type only, no chain
        name = type(exc).__name__
        raw = None
    if raw is None:
        raise ConnectionError(f"Twelve Data not reachable ({name})")
    if len(raw) > MAX_BYTES:
        raise ValueError("answer too large")
    return parse(json.loads(raw), chart_symbol, interval, limit)
