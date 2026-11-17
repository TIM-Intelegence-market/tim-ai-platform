"""Futures recorder for R-ABS-2: closed minutes only, refill after a pause, context of a window."""
from __future__ import annotations

import json

from src.research_lab.forward import abs_entry
from src.research_lab.forward.futures_recorder import FuturesRecorder, context, read_rows
from src.research_lab.liquidations import store

T0 = 1_795_000_000_000 // 60_000 * 60_000   # a minute in Nov 2026


def kline(t: int, vol: float, buy: float) -> list:
    return [t, "1", "1", "1", "65000", str(vol), t + 59_999, "0", 10, str(buy), "0", "0"]


class Fake:
    def __init__(self) -> None:
        self.now = (T0 + 3 * 60_000 + 5_000) / 1000
        self.urls: list[str] = []

    def fetch(self, url: str):
        self.urls.append(url)
        if "openInterest" in url:
            return {"openInterest": "80000.5"}
        if "premiumIndex" in url:
            return {"lastFundingRate": "0.0001", "markPrice": "65000"}
        end = int(self.now * 1000)
        return [kline(t, 10.0, 7.0) for t in range(T0, end, 60_000)]   # includes the open minute


def test_poll_writes_closed_minutes_and_refills(tmp_path):
    fake = Fake()
    rec = FuturesRecorder(tmp_path, fetch=fake.fetch, clock=lambda: fake.now)
    assert rec.poll() == 3                                  # minute 3 is still open
    fake.now += 300                                         # five minutes offline
    assert rec.poll() == 5
    assert "startTime" in fake.urls[-3]
    rows = read_rows(tmp_path, T0, T0 + 20 * 60_000)
    assert [int(r["minute_ms"]) for r in rows] == [T0 + k * 60_000 for k in range(8)]
    assert sum(1 for r in rows if r["oi_btc"]) == 2         # OI only on minutes polled live


def test_context_perp_delta_oi_and_liquidations(tmp_path):
    fake = Fake()
    rec = FuturesRecorder(tmp_path / "fut", fetch=fake.fetch, clock=lambda: fake.now)
    rec.poll()
    liq = tmp_path / "liq"
    msg = {"e": "forceOrder", "o": {"s": "BTCUSDT", "S": "SELL", "X": "FILLED", "ap": "65000", "z": "2", "T": T0 + 1000}}
    store.append(liq, store.make_record("message", "binance", "s1", (T0 + 1000) * 1_000_000, 1, json.dumps(msg)))
    out = context(tmp_path / "fut", liq, T0, T0 + 3 * 60_000)
    assert out["perp_volumen_btc"] == 30.0 and out["perp_delta_btc"] == 12.0
    assert out["funding_rate"] == 0.0001
    assert out["liq_long_usd"] == 130_000 and out["liq_short_usd"] == 0 and out["liq_nachrichten"] is True
    assert context(tmp_path / "fut", None, T0 + 3_600_000, T0 + 3_660_000)["perp_fehlt"] is True


def test_abs_entry_attaches_futures_context_only_to_counted_events():
    from tests.test_research_forward_abs_entry import STARTED, days, scenario

    seen = []
    out = abs_entry.simulate(days(scenario()), STARTED,
                             futures=lambda a, b: seen.append((a, b)) or {"perp_delta_btc": 1.0})
    assert out["trades"][0]["futures"] == {"perp_delta_btc": 1.0}
    assert all(b > a and b >= STARTED for a, b in seen)
