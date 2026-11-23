"""P4 (Weg H): reading historical public archives with the holdout lock applied **at load time**.

Uzi allowed historical tests of trade-based order flow and Deribit option trades on 23.11.2026 ("historisch ja").
Windows follow ``protocol.py``: training until 2022-12-31, validation 2023-2024. Anything from ``HOLDOUT_START_MS``
(2025-01-01) is dropped while reading and counted, so no later step can see it. Releasing the holdout needs Uzi's
explicit word and a new study version; this module has no switch for it.

Historical rows have no TIM receive time. Point-in-time rule for them: a row counts as known at
``ts_ms + LATENCY_MS`` (fixed before any result, plan section 3).

Binance USD-M aggTrades CSV columns: agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time,
is_buyer_maker (header row present in newer files, absent in older ones). ``is_buyer_maker = true`` means the seller
was the aggressor (side -1). Nothing is downloaded here.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS

LATENCY_MS = 2_000


class HoldoutCounter:
    def __init__(self) -> None:
        self.dropped = 0


def guard(rows: Iterable[Mapping[str, Any]], counter: HoldoutCounter, ts_key: str = "ts_ms") -> Iterator[dict]:
    """Pass rows before 2025-01-01 through, drop the rest and count them. Adds ``recv_ms`` if missing."""
    for r in rows:
        t = int(r[ts_key])
        if t >= HOLDOUT_START_MS:
            counter.dropped += 1
            continue
        out = dict(r)
        out.setdefault("recv_ms", t + LATENCY_MS)
        yield out


def split(ts_ms: int) -> str:
    if ts_ms >= HOLDOUT_START_MS:
        raise ValueError("holdout row reached a study step")
    return "train" if ts_ms < VALIDATION_START_MS else "validation"


def _truthy(v: str) -> bool:
    return v.strip().lower() in ("true", "1")


def parse_aggtrades_csv(text: str) -> Iterator[dict]:
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0].strip().lstrip("-").isdigit():
            continue  # header or empty line
        ts = int(row[5])
        if ts > 10**15:  # microseconds in some newer archives
            ts //= 1000
        yield {"id": int(row[0]), "price": float(row[1]), "qty": float(row[2]), "ts_ms": ts,
               "side": -1 if _truthy(row[6]) else 1}


def read_aggtrades_zip(path: Path, counter: HoldoutCounter) -> Iterator[dict]:
    """One Binance archive zip. Files whose name says 2025 or later are skipped unopened."""
    m = re.search(r"-(\d{4})-\d{2}", path.name)
    if m and int(m.group(1)) >= 2025:
        counter.dropped += 1
        return
    with zipfile.ZipFile(path) as zf:
        for member in zf.namelist():
            if member.endswith(".csv"):
                yield from guard(parse_aggtrades_csv(zf.read(member).decode("utf-8")), counter)


def deribit_history_rows(result: Mapping[str, Any], counter: HoldoutCounter) -> Iterator[dict]:
    """Rows of a ``history.deribit.com`` ``get_last_trades_by_currency_and_time`` result, holdout dropped.

    The raw trade dicts are returned with ``recv_ms = timestamp + LATENCY_MS`` so ``contract.normalize_trade`` can be
    applied by the caller."""
    trades = result.get("trades") if isinstance(result, Mapping) else None
    for t in trades or []:
        ts = t.get("timestamp")
        if not isinstance(ts, int) or isinstance(ts, bool):
            continue
        if ts >= HOLDOUT_START_MS:
            counter.dropped += 1
            continue
        yield {"raw": t, "recv_ms": ts + LATENCY_MS}
