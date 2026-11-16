"""Large BTC moves with context and explanation (src/dashboard/move_context.py, Bauplan P1+P2)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.dashboard import move_context as M
from src.research_lab.liquidations.events import LiquidationEvent

END = datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)
CRASH = END - timedelta(hours=3)  # open of the -3 % candle


def _candle(opened: datetime, o: float, c: float, volume: float = 100.0) -> dict:
    return {"symbol": "BTCUSDT", "timeframe": "1h", "open_time": opened.isoformat(), "close_time": (opened + timedelta(hours=1)).isoformat(),
            "open": o, "high": max(o, c) + 5, "low": min(o, c) - 5, "close": c, "volume": volume}


def _series(crash: float | None = -0.03, hours: int = 500, crash_volume: float = 600.0) -> dict:
    start = END - timedelta(hours=hours)
    rows, price = [], 90000.0
    for i in range(hours):
        opened = start + timedelta(hours=i)
        if crash is not None and opened == CRASH:
            close, vol = price * (1 + crash), crash_volume
        else:
            close, vol = price * (1 + 0.002 * math.sin(i * 1.7)), 100.0
        rows.append(_candle(opened, price, close, vol))
        price = close
    return {"1h": rows}


def _liq(side: str, usd: float, at: datetime) -> LiquidationEvent:
    return LiquidationEvent(venue="binance", symbol="BTCUSDT", side=side, raw_side="SELL" if side == "long" else "BUY",
                            price=Decimal(88000), quantity=Decimal(str(usd / 88000)), time_ms=int(at.timestamp() * 1000), status="FILLED")


def _store(start: datetime, end: datetime, bid: float, ask: float) -> dict:
    rows, t = [], int(start.timestamp())
    while t + 300 <= int(end.timestamp()):
        rows.append([t, 88000.0, bid, ask])
        t += 300
    return {"bucket_seconds": 300, "days": {"2026-11-13": rows}, "source": "test"}


def _oi(before: float, after: float) -> dict:
    t0 = int((CRASH - timedelta(hours=1)).timestamp())
    return {"points": [[t0, before, before * 90000], [t0 + 3600, before, before * 90000], [t0 + 7200, after, after * 88000]], "source": "OI test"}


def test_quiet_market_has_no_move():
    assert M.detect(_series(crash=None), END + timedelta(minutes=1)) == []


def test_crash_candle_is_detected_with_its_size_and_direction():
    events = M.detect(_series(), END + timedelta(minutes=1))
    assert len(events) == 1
    e = events[0]
    assert e["direction"] == "DOWN" and e["start"] == CRASH and e["change_pct"] == -3.0
    assert any(t["tf"] == "1h" and t["score"] >= 3 for t in e["triggers"])


def test_too_short_history_detects_nothing():
    assert M.detect(_series(hours=100), END + timedelta(minutes=1)) == []


def test_running_candle_is_not_used():
    # one minute before the crash candle closes it is not a closed candle yet
    assert M.detect(_series(), CRASH + timedelta(minutes=59)) == []


def test_no_sources_means_fehlt_and_unexplained():
    rows = M.build(_series(), {}, END + timedelta(minutes=1))
    row = rows[0]
    for key in ("liquidations", "open_interest", "funding", "premium", "perp_delta", "spot_delta", "macro", "gamma", "stocks", "news"):
        assert row["context"][key]["status"] == M.FEHLT, key
    assert row["context"]["volume"]["status"] == M.OK
    assert [f["key"] for f in row["findings"]] == ["volume"]
    assert row["explained"] is False
    assert "nicht erklärbar" in M.render_de(rows)


def test_full_context_gives_evidenced_findings():
    end = CRASH + timedelta(hours=1)
    sources = {
        "liquidations": {"binance": [_liq("long", 30e6, CRASH + timedelta(minutes=20)), _liq("short", 1e6, CRASH + timedelta(minutes=30)),
                                     _liq("long", 99e6, end + timedelta(minutes=5))]},  # after the move: never counted
        "open_interest": _oi(100000.0, 96000.0),
        "funding": {"points": [[int((CRASH - timedelta(hours=5)).timestamp()), 0.04]], "interval_hours": 8},
        "premium": {"points": [[int((CRASH - timedelta(hours=1)).timestamp()), 0.02, 18.0], [int(CRASH.timestamp()), -0.06, -50.0]]},
        "perp": _store(CRASH, end, bid=900.0, ask=600.0),
        "spot": _store(CRASH, end, bid=100.0, ask=60.0),
        "calendar": [{"kind": "CPI", "label": "US-CPI", "time": CRASH - timedelta(minutes=30)}],
    }
    row = M.build(_series(), sources, END + timedelta(minutes=1))[0]
    by_key = {f["key"]: f for f in row["findings"]}
    assert row["context"]["liquidations"]["long_usd"] == 30_000_000
    assert by_key["liq"]["level"] == "BELEGT" and "30,0 Mio" in by_key["liq"]["de"]
    assert by_key["oi"]["level"] == "WAHRSCHEINLICH" and "geschlossen" in by_key["oi"]["de"]
    assert by_key["flow"]["level"] == "BELEGT" and "Spot und Perp" in by_key["flow"]["de"]
    assert by_key["premium"]["level"] == "WAHRSCHEINLICH"
    assert by_key["funding"]["level"] == "WAHRSCHEINLICH"
    assert by_key["macro"]["level"] == "VERMUTUNG"
    assert row["explained"] is True
    html = M.render_de([row])
    assert "BELEGT" in html and "Beleg:" in html and "Fehlt: Gamma, Aktien, Schlagzeilen" in html
    en = M.render_en([row])
    assert "SHOWN" in en and "Evidence:" in en and "Berlin time" in en
    assert "30.0 M$" in en and "Liquidationen" not in en and "Mio." not in en


def test_premium_hour_counts_only_after_it_ended():
    # the hour that opens at the crash ends with the crash candle: known at the end, not before the start
    sources = {"premium": {"points": [[int((CRASH - timedelta(hours=2)).timestamp()), 0.0, 0.0], [int(CRASH.timestamp()), -0.1, -90.0]]}}
    ctx = M.build(_series(), sources, END + timedelta(minutes=1))[0]["context"]["premium"]
    assert ctx["status"] == M.OK and ctx["before_pct"] == 0.0 and ctx["after_pct"] == -0.1


def test_gappy_delta_record_is_fehlt():
    store = _store(CRASH, CRASH + timedelta(minutes=20), bid=900.0, ask=100.0)
    ctx = M.build(_series(), {"perp": store}, END + timedelta(minutes=1))[0]["context"]["perp_delta"]
    assert ctx["status"] == M.FEHLT and "lückenhaft" in ctx["note"]


def test_gamma_only_from_the_moves_last_hour():
    late = {"analysis_input": {"as_of": (END + timedelta(hours=2)).isoformat(), "gamma_flip": 95000.0}}
    fresh = {"analysis_input": {"as_of": (CRASH + timedelta(minutes=50)).isoformat(), "gamma_flip": 95000.0}}
    assert M.build(_series(), {"gamma": late}, END + timedelta(minutes=1))[0]["context"]["gamma"]["status"] == M.FEHLT
    row = M.build(_series(), {"gamma": fresh}, END + timedelta(minutes=1))[0]
    assert row["context"]["gamma"]["below_flip"] is True
    assert any(f["key"] == "gamma" and f["level"] == "VERMUTUNG" for f in row["findings"])


def test_macro_only_timing_is_a_guess():
    sources = {"calendar": [{"kind": "FOMC", "label": "FOMC", "time": CRASH + timedelta(minutes=10)}],
               "funding": {"points": [[int((CRASH - timedelta(hours=5)).timestamp()), 0.05]], "interval_hours": 8}}
    row = M.build(_series(), sources, END + timedelta(minutes=1))[0]
    assert [f["level"] for f in row["findings"] if f["key"] == "macro"] == ["VERMUTUNG"]
    assert any(f["key"] == "funding" for f in row["findings"])
    assert row["explained"] is False  # a date and high funding are context, not an explanation


def test_up_move_with_rising_oi_reads_as_new_longs():
    row = M.build(_series(crash=0.03), {"open_interest": _oi(100000.0, 103000.0)}, END + timedelta(minutes=1))[0]
    assert row["direction"] == "UP"
    assert any(f["key"] == "oi" and "Long-Positionen" in f["de"] for f in row["findings"])


def test_update_records_once_in_its_window(tmp_path):
    path = tmp_path / "moves.jsonl"
    series = _series()
    end = CRASH + timedelta(hours=1)
    assert M.update(path, series, {}, end + timedelta(minutes=5)) == []  # too early
    first = M.update(path, series, {}, end + timedelta(minutes=20))
    assert len(first) == 1 and first[0]["id"] == CRASH.isoformat()
    assert M.update(path, series, {}, end + timedelta(minutes=50)) == []  # already recorded
    lines = path.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["schema"] == M.SCHEMA
    shown = M.shown(series, {}, path, end + timedelta(hours=1))
    assert len(shown) == 1 and not shown[0].get("live") and shown[0]["recorded_at"]


def test_shown_marks_unrecorded_moves_live(tmp_path):
    rows = M.shown(_series(), {}, tmp_path / "none.jsonl", END + timedelta(minutes=1))
    assert rows[0]["live"] is True
    assert "vorläufig" in M.render_de(rows)


def test_empty_render_and_broken_file(tmp_path):
    path = tmp_path / "moves.jsonl"
    path.write_text("kaputt\n{\"schema\": \"other\"}\n")
    assert M.load(path) == []
    assert "Keine große Bewegung" in M.render_de([])


def test_sources_from_state_without_data(monkeypatch, tmp_path):
    import threading

    monkeypatch.setenv("TIM_RUNTIME_ENV", "test")
    monkeypatch.setenv("TIM_MACRO_CALENDAR", str(tmp_path / "missing.json"))

    class State:
        lock = threading.Lock()
        footprint = None
        gamma: dict = {}  # noqa: RUF012 - test stand-in for the dashboard state

    monkeypatch.setattr("src.dashboard.liquidation_events.default_root", lambda: tmp_path / "no-liquidations")
    sources = M.sources_from_state(State())
    assert sources["calendar"] is None and sources["perp"] is None and "funding" not in sources
    row = M.build(_series(), sources, END + timedelta(minutes=1))[0]
    assert row["context"]["liquidations"]["status"] == M.FEHLT


def test_text_is_escaped():
    row = M.build(_series(), {"calendar": [{"kind": "CPI", "label": "<script>", "time": CRASH}]}, END + timedelta(minutes=1))[0]
    assert "<script>" not in M.render_de([row])


def test_perp_pressure_without_spot_data_is_not_called_leverage_only():
    end = CRASH + timedelta(hours=1)
    row = M.build(_series(), {"perp": _store(CRASH, end, bid=900.0, ask=600.0)}, END + timedelta(minutes=1))[0]
    flow = [f for f in row["findings"] if f["key"] == "flow"]
    assert flow[0]["level"] == "WAHRSCHEINLICH" and "Spot unbekannt" in flow[0]["de"]
    both = M.build(_series(), {"perp": _store(CRASH, end, bid=900.0, ask=600.0), "spot": _store(CRASH, end, bid=50.0, ask=50.0)},
                   END + timedelta(minutes=1))[0]
    assert next(f for f in both["findings"] if f["key"] == "flow")["level"] == "BELEGT"


def test_move_that_grows_after_its_record_is_recorded_again(tmp_path):
    path = tmp_path / "moves.jsonl"
    first_end = CRASH + timedelta(hours=1)
    short = _series()
    assert len(M.update(path, short, {}, first_end + timedelta(minutes=20))) == 1
    # a second -3 % candle two hours later joins the same move
    longer = _series()
    rows = longer["1h"]
    second = CRASH + timedelta(hours=2)
    for i, c in enumerate(rows):
        if c["open_time"] == second.isoformat():
            rows[i] = _candle(second, c["open"], c["open"] * 0.97, 600.0)
            for j in range(i + 1, len(rows)):
                factor = rows[i]["close"] / rows[i + 1]["open"] if j == i + 1 else 1.0
                rows[j] = {**rows[j], "open": rows[j]["open"] * factor, "close": rows[j]["close"] * factor}
            break
    second_end = second + timedelta(hours=1)
    live = M.shown(longer, {}, path, second_end + timedelta(minutes=1))
    assert live[0]["live"] is True and live[0]["end"] == second_end.isoformat()
    again = M.update(path, longer, {}, second_end + timedelta(minutes=20))
    assert len(again) == 1 and again[0]["end"] == second_end.isoformat()
    assert len(path.read_text().splitlines()) == 2
    shown = M.shown(longer, {}, path, second_end + timedelta(minutes=30))
    assert not shown[0].get("live") and shown[0]["end"] == second_end.isoformat()


def test_broken_but_schema_valid_line_is_skipped(tmp_path):
    path = tmp_path / "moves.jsonl"
    path.write_text(json.dumps({"schema": M.SCHEMA, "id": "x"}) + "\n")
    assert M.load(path) == []
    assert M.shown(_series(), {}, path, END + timedelta(minutes=1))[0]["live"] is True


def test_four_hour_move_is_flagged_on_4h_too():
    # four hours of -0.8 % each: the 4h candle is flagged as well (window from the 1h candles)
    start = END - timedelta(hours=500)
    rows, price = [], 90000.0
    for i in range(500):
        opened = start + timedelta(hours=i)
        step = -0.008 if END - timedelta(hours=4) <= opened < END else 0.0015 * math.sin(i * 1.7)
        close = price * (1 + step)
        rows.append(_candle(opened, price, close))
        price = close
    events = M.detect({"1h": rows}, END + timedelta(minutes=1))
    assert events and any(t["tf"] == "4h" for t in events[-1]["triggers"])


# --- P3: stocks and headlines ------------------------------------------------------------------------------------


def _bars(changes: dict[datetime, float]) -> list[list[float]]:
    """Hourly bars from 10 h before the crash to 2 h after; ``changes`` sets a bar's return by its start."""
    out, price = [], 20000.0
    t = CRASH - timedelta(hours=10)
    while t <= CRASH + timedelta(hours=2):
        close = price * (1 + changes.get(t, 0.0))
        out.append([int(t.timestamp()), price, close])
        price, t = close, t + timedelta(hours=1)
    return out


def _stock_source(ndx: float, nvda: float) -> dict:
    return {"source": "test", "series": {"^NDX": {"name": "Nasdaq-100", "bars": _bars({CRASH: ndx})},
                                         "NVDA": {"name": "NVIDIA", "bars": _bars({CRASH: nvda})}}}


def test_stocks_falling_together_explain_the_move():
    row = M.build(_series(), {"stocks": _stock_source(-0.015, -0.05)}, END + timedelta(minutes=1))[0]
    keys = {f["key"]: f for f in row["findings"]}
    assert keys["stocks"]["level"] == "WAHRSCHEINLICH" and "Risiko-Aus" in keys["stocks"]["de"]
    assert keys["nvda"]["level"] == "VERMUTUNG" and "-5,00 %" in keys["nvda"]["evidence"]
    assert row["explained"] is True


def test_calm_stocks_say_crypto_own_move_but_do_not_explain_it():
    row = M.build(_series(), {"stocks": _stock_source(0.001, 0.0)}, END + timedelta(minutes=1))[0]
    assert any(f["key"] == "stocks_calm" for f in row["findings"])
    assert row["explained"] is False


def test_stock_bar_counts_only_after_its_hour():
    # the bar that opens at the end of the move is not used, even if it crashes
    late = {"source": "t", "series": {"^NDX": {"name": "Nasdaq-100", "bars": _bars({CRASH + timedelta(hours=1): -0.05})}}}
    row = M.build(_series(), {"stocks": late}, END + timedelta(minutes=1))[0]
    assert row["context"]["stocks"]["moves"]["^NDX"]["change_pct"] == 0.0


def test_closed_market_is_not_missing():
    bars = [[int((CRASH - timedelta(days=2)).timestamp()), 1.0, 1.0], [int((CRASH + timedelta(hours=20)).timestamp()), 1.0, 1.0]]
    closed = {"source": "t", "series": {"^NDX": {"name": "Nasdaq-100", "bars": bars}}}
    row = M.build(_series(), {"stocks": closed}, END + timedelta(minutes=1))[0]
    assert row["context"]["stocks"]["status"] == "geschlossen"
    html = M.render_de([row])
    assert "US-Börse geschlossen" in html and "Aktien," not in html.split("Fehlt:")[1].split("</p>")[0]


def test_headlines_in_window_are_only_a_guess_and_relevant_first():
    def h(minutes: int, title: str) -> dict:
        t = CRASH + timedelta(minutes=minutes)
        return {"id": title, "feed": "CoinDesk", "title": title, "link": "", "time": t.isoformat()}
    items = [h(-600, "old"), h(-30, "Weather report"), h(10, "Nvidia CEO scandal hits stocks"), h(20, "Bitcoin slides"), h(200, "later")]
    row = M.build(_series(), {"headlines": items}, END + timedelta(minutes=1))[0]
    news = row["context"]["news"]
    assert news["count"] == 3 and news["items"][0]["title"] == "Nvidia CEO scandal hits stocks"
    finding = next(f for f in row["findings"] if f["key"] == "news")
    assert finding["level"] == "VERMUTUNG" and "Bitcoin slides" in finding["evidence"]
    assert row["explained"] is False


def test_headline_log_younger_than_window_is_missing():
    items = [{"id": "a", "feed": "x", "title": "t", "link": "", "time": (CRASH + timedelta(minutes=5)).isoformat()}]
    assert M.build(_series(), {"headlines": items}, END + timedelta(minutes=1))[0]["context"]["news"]["status"] == M.FEHLT


def test_stale_stock_feed_is_missing_not_closed():
    stale = {"source": "t", "series": {"^NDX": {"name": "Nasdaq-100", "bars": [[int((CRASH - timedelta(days=2)).timestamp()), 1.0, 1.0]]}}}
    row = M.build(_series(), {"stocks": stale}, END + timedelta(minutes=1))[0]
    assert row["context"]["stocks"]["status"] == M.FEHLT


def test_relevance_matches_word_starts_only():
    assert M._relevant("Bitcoin liquidations spike") and M._relevant("SEC sues exchange")
    assert not M._relevant("A second warning on whether federal rates separate")
