"""USDT.D tab on the TIM chart: own candles from recorded CoinGecko samples, swing marks, EMA."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.dashboard import usdt_dominance as ud
from src.dashboard.chart_live import SYMBOLS, build_live_chart, tab_label
from src.dashboard.public_en import english_chart_model

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
START = int(datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc).timestamp())


def wave_samples(n: int = 800) -> list[dict]:
    # a slow wave between about 7.9 and 8.4 so that swing highs and lows exist
    import math

    return [{"t": START + i * 300, "usdt": 8.15 + 0.25 * math.sin(i / 40)} for i in range(n)]


def test_tab_and_symbol() -> None:
    assert "USDTD" in SYMBOLS and tab_label("USDTD") == "USDT.D"


def test_parse_global_reads_usdt_btc_total() -> None:
    raw = json.dumps({"data": {"market_cap_percentage": {"usdt": 8.2, "btc": 58.1}, "total_market_cap": {"usd": 3.1e12}}})
    assert ud.parse_global(raw) == (8.2, 58.1, 3.1e12)
    with pytest.raises(Exception):
        ud.parse_global(json.dumps({"data": {"market_cap_percentage": {"usdt": 0}}}))


def test_record_sample_skips_double_reads(tmp_path) -> None:
    path = tmp_path / "s.jsonl"
    assert ud.record_sample(path, 8.2, NOW) is True
    assert ud.record_sample(path, 8.3, NOW.replace(minute=2)) is False
    assert ud.record_sample(path, 8.3, NOW.replace(minute=6)) is True
    assert [s["usdt"] for s in ud.load_samples(path, NOW)] == [8.2, 8.3]


def test_recorder_failure_is_not_filled(tmp_path) -> None:
    def broken(url: str) -> bytes:
        raise OSError("down")

    rec = ud.Recorder(tmp_path / "s.jsonl", fetch=broken)
    assert rec.once(NOW) is False and rec.last_error == "OSError" and not (tmp_path / "s.jsonl").exists()


def test_hourly_candles_are_ohlc_of_samples() -> None:
    rows = ud.candle_rows({"samples": [{"t": START + 60, "usdt": 8.0}, {"t": START + 1200, "usdt": 8.3}, {"t": START + 2400, "usdt": 8.1}]},
                          "1h", 3600, NOW)
    assert len(rows) == 1
    r = rows[0]
    assert (r["open"], r["high"], r["low"], r["close"]) == (8.0, 8.3, 8.0, 8.1)


def test_daily_views_use_coin_metrics_for_days_before_recording() -> None:
    day = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp())
    daily = {"points": [[day + 86400, 58.0, 8.0], [day + 2 * 86400, 58.0, 8.1]]}
    rows = ud.candle_rows({"samples": [], "daily": daily}, "1d", 86400, NOW)
    assert [r["close"] for r in rows] == [8.0, 8.1]
    weeks = ud.candle_rows({"samples": [], "daily": daily}, "1w", 604800, NOW)
    assert len(weeks) == 1 and weeks[0]["high"] == 8.1 and weeks[0]["low"] == 8.0
    assert datetime.fromisoformat(weeks[0]["open_time"]).weekday() == 0


def test_ema_is_seeded_with_the_mean() -> None:
    line = ud.ema([1, 2, 3, 4, 5], 3)
    assert line[:2] == [None, None] and line[2] == 2.0 and line[4] > line[3] > line[2]


def test_chart_has_candles_swings_ema_and_no_trades() -> None:
    model = build_live_chart("USDTD", "30m", context={"usdtd": {"samples": wave_samples(), "daily": None, "error": None}}, now=NOW)
    assert model["symbol"] == "USDTD" and len(model["candles"]) > 30
    groups = {d["group"] for d in model["drawings"]}
    assert {"usdtd_swing", "usdtd_ema", "usdtd_sr"} <= groups
    swing = next(d for d in model["drawings"] if d["group"] == "usdtd_swing")
    assert "," in swing["label"] and swing["label"][-1] in "↑↓"
    assert model["footprint"]["bars"] == [] and model["plans"] == []
    assert any("kein Signal" in n for n in model["notes"])


def test_chart_without_samples_says_so_and_does_not_crash() -> None:
    model = build_live_chart("USDTD", "1h", context={"usdtd": {"samples": [], "daily": None, "error": "URLError"}}, now=NOW)
    assert model["candles"] == [] and any("CoinGecko nicht erreichbar" in n for n in model["notes"])


def test_unoffered_timeframe() -> None:
    model = build_live_chart("USDTD", "1m", context=None, now=NOW)
    assert model["candles"] == [] and any("gibt es nicht" in n for n in model["notes"])


def test_english_model_keeps_working() -> None:
    model = build_live_chart("USDTD", "30m", context={"usdtd": {"samples": wave_samples(), "daily": None, "error": None}}, now=NOW)
    assert english_chart_model(model)["symbol"] == "USDTD"


def test_recorder_starts_with_the_process_not_with_the_chart() -> None:
    """18.11.2026: the recorder only started on the first USDT.D chart call and left a 30-minute gap after a restart."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "usdt_dominance_recorder.start()" in source
    assert source.index("self.dashboard.start()") < source.index("usdt_dominance_recorder.start()")


def test_recorder_start_is_a_noop_in_tests_and_idempotent(tmp_path) -> None:
    rec = ud.Recorder(tmp_path / "s.jsonl", fetch=lambda url: (_ for _ in ()).throw(OSError("no network in tests")))
    rec.start()
    rec.start()
    assert rec._thread is None and not (tmp_path / "s.jsonl").exists()
