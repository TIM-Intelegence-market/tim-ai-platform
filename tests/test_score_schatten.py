"""Schatten-Score (TIM-Gehirn, Uzi 12.11.2026): second pipeline run with trades, next to the unchanged live score."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.dashboard.chart_model import run_scenarios
from src.models.market_data import Trade

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _candles(count: int = 40) -> list[dict]:
    out, price = [], 100_000.0
    for i in range(count):
        opened = START + timedelta(minutes=30 * i)
        close = price + (80 if i % 2 else -60)
        out.append({"symbol": "BTCUSDT", "timeframe": "30m", "open_time": opened, "close_time": opened + timedelta(minutes=30) - timedelta(milliseconds=1),
                    "open": price, "high": max(price, close) + 30, "low": min(price, close) - 30, "close": close, "volume": 10.0, "closed": True})
        price = close
    return out


def _trades(candles: list[dict], after: datetime | None = None) -> list[Trade]:
    out, n = [], 1
    for c in candles[-6:]:
        for k in range(10):
            out.append(Trade("BTCUSDT", c["close"] + k, 0.5, c["open_time"] + timedelta(minutes=k), n, k % 3 == 0))
            n += 1
    if after is not None:
        out.append(Trade("BTCUSDT", 100_000.0, 1.0, after + timedelta(minutes=5), n, False))
    return out


def test_live_result_is_identical_with_and_without_trades() -> None:
    candles = _candles()
    now = candles[-1]["close_time"] + timedelta(seconds=1)
    plain = run_scenarios(candles, "30m", None, now)
    shaded = run_scenarios(candles, "30m", None, now, _trades(candles))
    strip = lambda a: [{k: v for k, v in s.items() if k != "score_schatten"} for s in a["scenarios"]]
    assert strip(plain) == strip(shaded) and plain["data_quality"] == shaded["data_quality"]
    assert all("score_schatten" not in s for s in plain["scenarios"])


def test_shadow_score_has_trades_and_better_data_quality() -> None:
    candles = _candles()
    now = candles[-1]["close_time"] + timedelta(seconds=1)
    shaded = run_scenarios(candles, "30m", None, now, _trades(candles))
    found = [s["score_schatten"] for s in shaded["scenarios"] if "score_schatten" in s]
    assert found and all("trades" in f["daten"] and f["n_trades"] > 0 for f in found)
    assert all("trades" not in f["datenqualitaet"]["missing"] for f in found)


def test_trades_after_the_plan_moment_are_ignored() -> None:
    candles = _candles()
    now = candles[-1]["close_time"] + timedelta(seconds=1)
    base = run_scenarios(candles, "30m", None, now, _trades(candles))
    future = run_scenarios(candles, "30m", None, now, _trades(candles, after=now))
    pick = lambda a: [s.get("score_schatten") for s in a["scenarios"]]
    assert pick(base) == pick(future)


def _series(count: int = 90) -> dict:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    rows, price = [], 100_000.0
    for i in range(count):
        opened = start + timedelta(minutes=30 * i)
        close = price + (400 if (i // 10) % 2 else -400)
        rows.append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                     "open": price, "high": max(price, close) + 50, "low": min(price, close) - 50, "close": close, "volume": 10.0})
        price = close
    return {"30m": rows, "1m": []}


def test_journal_step_survives_a_failing_trades_source(tmp_path) -> None:
    from src.dashboard import plan_journal as pj

    def broken(start, end):
        raise TimeoutError("db")

    series = _series()
    now = datetime(2026, 10, 22, tzinfo=timezone.utc) + timedelta(minutes=30 * 90)
    journal = pj.update(tmp_path / "j.json", series, now, trades_fn=broken)
    assert journal["last_plan_candle"] is not None
    assert all(e.get("score_schatten") is None for e in journal["entries"])


def test_journal_step_asks_for_trades_only_up_to_the_plan_moment(tmp_path) -> None:
    from src.dashboard import plan_journal as pj

    asked = []

    def source(start, end):
        asked.append((start, end))
        return []

    series = _series()
    now = datetime(2026, 10, 22, tzinfo=timezone.utc) + timedelta(minutes=30 * 90)
    pj.update(tmp_path / "j.json", series, now, trades_fn=source)
    assert len(asked) == 1 and asked[0][1] <= now and asked[0][1] - asked[0][0] <= timedelta(hours=2)
