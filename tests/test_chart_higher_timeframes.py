from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from io import BytesIO
import json

from src.dashboard.chart_model import analytical_series, build_chart_model, clean_candles, structure_events, ny_open_windows
from src.dashboard.chart_history import TIMEFRAMES, fetch_history
from src.dashboard.pages.chart import _chart_svg, _time_label

UTC = timezone.utc


def bar(t, tf="1h", seconds=3600, high=110, low=90, close=100):
    return dict(timeframe=tf, open_time=t, close_time=t + timedelta(seconds=seconds),
                open=100, high=high, low=low, close=close, volume=10)


def test_calendar_month_and_monday_week_require_full_coverage():
    start = datetime(2024, 2, 1, tzinfo=UTC)
    end = datetime(2024, 3, 1, tzinfo=UTC)
    hours = [bar(start + timedelta(hours=i)) for i in range(29 * 24)]
    result = analytical_series({"1h": hours}, end)
    assert len(result["1M"]) == 1
    assert result["1M"][0]["close_time"] == end
    assert all(c["open_time"].weekday() == 0 for c in result["1w"])
    assert analytical_series({"1h": hours[1:]}, end)["1M"] == []
    assert analytical_series({"1h": hours}, end - timedelta(seconds=1))["1M"] == []


def test_chart_rejects_small_timeframes_and_running_bars():
    start = datetime(2026, 10, 20, tzinfo=UTC)
    rows = [bar(start + timedelta(minutes=30*i), "30m", 1800) for i in range(8)]
    for small in ("1m", "5m", "15m"):
        model = build_chart_model({"30m": rows}, small, now=start + timedelta(hours=3))
        assert model["timeframe"] == "30m"
        assert model["timeframes"] == list(TIMEFRAMES)
        assert len(model["candles"]) == 6


def test_structure_shift_is_causal_and_wick_is_not_a_break():
    start = datetime(2026, 10, 20, tzinfo=UTC)
    ranges = [(102,98,100), (110,99,105), (104,97,100), (106,98,103),
              (112,100,111), (108,99,103), (106,95,96), (107,97,100)]
    rows = [bar(start + timedelta(hours=i), high=h, low=l, close=c) for i,(h,l,c) in enumerate(ranges)]
    rows = clean_candles(rows)
    events = structure_events(rows, "1h", width=1)
    assert [(e["kind"], e["direction"], e["break_index"]) for e in events] == [("BOS","UP",4),("MSS","DOWN",6)]
    assert structure_events(rows[:6], "1h", width=1) == events[:1]
    rows[6]["close"] = 100
    assert not any(e["kind"] == "MSS" for e in structure_events(rows, "1h", width=1))


def test_ny_open_is_unique_per_date_with_date_axis_and_no_htf_bands():
    start = datetime(2026, 10, 19, tzinfo=UTC)
    windows = ny_open_windows(start, start + timedelta(days=7))
    assert len(windows) == len({w["open"][:10] for w in windows}) == 5
    assert "19.10." in _time_label(start.isoformat(), "30m")
    rows = [bar(start + timedelta(hours=4*i), "4h", 14400) for i in range(20)]
    model = build_chart_model({"4h":rows}, "4h", now=start + timedelta(days=4))
    assert model["events"] == []
    assert "tc-block-text" not in _chart_svg(model)


def test_exchange_history_excludes_running_month_and_has_context_provenance():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 10, 1, tzinfo=UTC)
    def raw(a,b):
        return [int(a.timestamp()*1000),"100","110","90","105","10",int(b.timestamp()*1000)-1]
    payload = [raw(start,end),raw(end,datetime(2026,11,1,tzinfo=UTC))]
    with patch("src.dashboard.chart_history.urlopen", return_value=BytesIO(json.dumps(payload).encode())):
        rows = fetch_history("BTCUSDT", "1M", datetime(2026,10,24,tzinfo=UTC))
    assert len(rows) == 1 and rows[0]["close_time"] == end.isoformat()
    assert rows[0]["provenance"] == "BINANCE_PUBLIC_KLINES_CHART_CONTEXT"


def test_legacy_journal_plan_keeps_its_own_invalidation_timeframe():
    from src.dashboard import plan_journal as pj
    from tests.test_plan_journal import _plan, T0
    journal = pj.empty_journal()
    pj.record_plans(journal, [_plan("SHORT", entry=103, stop=104, invalid=101)], T0, timeframe="15m")
    pj.record_plans(journal, [_plan("SHORT", entry=103, stop=104, invalid=101)], T0, timeframe="30m")
    legacy = bar(T0, "15m", 900, high=102, low=100, close=101.5)
    minute = bar(T0 + timedelta(minutes=15), "1m", 60, high=102, low=100, close=101.5)
    pj.evaluate(journal, [minute], [legacy], T0 + timedelta(minutes=16))
    assert [e["status"] for e in journal["entries"]] == ["INVALIDATED", "OPEN"]
