"""S7b forward journal (src/research_lab/forward/s7b.py): prospective, append-only, same engine as the study."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.research_lab.backtest.engine import run_portfolio
from src.research_lab.forward import s7b as fwd
from src.research_lab.hypotheses import s7
from src.research_lab.protocol import BASE_COSTS
from src.research_lab.stats.random_entry import atr_at_signal

H4 = fwd.INTERVAL_MS
T0 = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000) - 300 * 4 * 3_600_000  # warm-up ends before the start


def _price(sym: str, i: int) -> float:
    base = {"BTCUSDT": 60000.0, "ETHUSDT": 3000.0, "SOLUSDT": 150.0}[sym]
    phase = {"BTCUSDT": 0.0, "ETHUSDT": 1.3, "SOLUSDT": 2.1}[sym]
    # slow trend with waves, so that Donchian breakouts in both directions occur
    return base * math.exp(0.0009 * i + 0.06 * math.sin(i / 23 + phase) + 0.02 * math.sin(i / 5.3 + 2 * phase))


def _rows(sym: str, count: int) -> list[list]:
    rows = []
    for i in range(count):
        o, c = _price(sym, i), _price(sym, i + 1)
        rows.append([T0 + i * H4, str(o), str(max(o, c) * 1.004), str(min(o, c) * 0.996), str(c), "100", T0 + (i + 1) * H4 - 1,
                     "0", 10, "55", "0", "0"])
    return rows


class FakeExchange:
    def __init__(self, count: int = 900) -> None:
        self.rows = {sym: _rows(sym, count) for sym in fwd.SYMBOLS}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, params: dict) -> list:
        self.calls.append((path, dict(params)))
        start, sym = int(params["startTime"]), params["symbol"]
        if path == "/fapi/v1/klines":
            # like Binance: the bar that is still open is part of the answer
            return [r for r in self.rows[sym] if r[0] >= start and r[0] <= self.now_ms][: int(params["limit"])]
        if path == "/fapi/v1/fundingRate":
            times = range(T0 + 3_600_007, self.now_ms, 8 * 3_600_000)  # settlement stamps a few ms off the hour
            return [{"fundingTime": t, "fundingRate": "0.0001"} for t in times if t >= start][: int(params["limit"])]
        raise AssertionError(path)

    now_ms = 0


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def _journal(tmp_path: Path, start_bar: int = 400) -> tuple[fwd.ForwardJournal, FakeExchange, Clock]:
    exchange = FakeExchange()
    clock = Clock(datetime.fromtimestamp((T0 + start_bar * H4 - 30 * 60_000) / 1000, tz=timezone.utc))
    exchange.now_ms = int(clock().timestamp() * 1000)
    journal = fwd.ForwardJournal(tmp_path / "S7b", fetch=exchange, clock=clock)
    return journal, exchange, clock


def _advance(exchange: FakeExchange, clock: Clock, bars: int) -> None:
    clock.moment += timedelta(milliseconds=bars * H4)
    exchange.now_ms = int(clock().timestamp() * 1000)


def test_start_is_the_next_4h_open_and_written_once(tmp_path: Path) -> None:
    journal, _, clock = _journal(tmp_path)
    start = journal.start(code_commit="abc")
    assert start["start_ms"] == T0 + 400 * H4  # 30 minutes before that open
    assert start["start_ms"] > int(clock().timestamp() * 1000)
    assert start["variants"] == ["S7b-D20-T3", "S7b-D20-T4"]
    clock.moment += timedelta(days=3)
    assert journal.start()["start_ms"] == start["start_ms"]  # a later call never moves the start
    assert [e["kind"] for e in journal.events()] == ["start"]
    assert fwd.first_open_at_or_after(T0) == T0 and fwd.first_open_at_or_after(T0 + 1) == T0 + H4


def test_step_logs_only_signals_after_the_start_and_is_idempotent(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    _advance(exchange, clock, 400)
    status = journal.step()
    events = journal.events()
    start_ms = events[0]["start_ms"]
    signals = [e for e in events if e["kind"] == "signal"]
    trades = [e for e in events if e["kind"] == "trade"]
    assert signals and trades, "the synthetic trend must produce signals and closed trades"
    assert all(e["signal_time"] >= start_ms for e in signals + trades)
    assert all(e["counts_in_net_r"] is False for e in events)
    assert status["new_events"] > 0
    again = journal.step()  # same data: nothing new, nothing rewritten
    assert again["new_events"] == 0
    assert len(journal.events()) == len(events)
    t3 = again["variants"]["S7b-D20-T3"]
    assert t3["trades"] == sum(1 for e in trades if e["variant"] == "S7b-D20-T3")
    assert t3["net_r"] == pytest.approx(sum(e["r"] for e in trades if e["variant"] == "S7b-D20-T3"), abs=1e-3)
    assert t3["min_trades"] == 100


def test_trades_equal_the_study_engine_on_the_same_bars(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    _advance(exchange, clock, 400)
    journal.step()
    start_ms = journal.events()[0]["start_ms"]
    bars = {sym: journal.load_bars(sym) for sym in fwd.SYMBOLS}
    funding = {sym: journal.load_funding(sym) for sym in fwd.SYMBOLS}
    variant = fwd.VARIANTS[0]
    direct = run_portfolio(bars, {sym: s7.breakout(variant) for sym in fwd.SYMBOLS}, H4, priority=fwd.SYMBOLS,
                           costs=BASE_COSTS, funding_by_symbol=funding, start_ms_by_symbol={s: start_ms for s in fwd.SYMBOLS},
                           atr_at_signal=atr_at_signal, gap_entry_as_loss=True, max_positions=1)
    expected = sorted((sym, t.signal_time, round(t.r, 6)) for sym, r in direct.items() for t in r.trades if t.reason != "end")
    logged = sorted((e["symbol"], e["signal_time"], e["r"]) for e in journal.events()
                    if e["kind"] == "trade" and e["variant"] == variant.variant_id)
    assert logged == expected
    assert any(f.rate for f in funding["BTCUSDT"])


def test_open_bar_is_never_cached(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    now_ms = int(clock().timestamp() * 1000)
    for sym in fwd.SYMBOLS:
        bars = journal.load_bars(sym)
        assert bars[-1].close_time < now_ms
        assert bars[0].open_time >= T0 + (400 - fwd.WARMUP_BARS) * H4
        assert all(b.open_time - a.open_time == H4 for a, b in zip(bars, bars[1:]))


def test_changed_history_is_reported_not_rewritten(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    _advance(exchange, clock, 400)
    journal.step()
    trade = next(e for e in journal.events() if e["kind"] == "trade")
    path = journal.folder / f"bars_{trade['symbol']}.json"
    rows = json.loads(path.read_text())
    index = next(i for i, r in enumerate(rows) if r[0] == trade["entry_time"])
    rows[index][1] *= 1.001  # the entry bar's open moves: the recomputed trade differs
    path.write_text(json.dumps(rows))
    journal.step()
    events = journal.events()
    mismatches = [e for e in events if e["kind"] == "mismatch"]
    assert mismatches and mismatches[0]["logged"]["entry_price"] == trade["entry_price"]
    assert [e for e in events if e["kind"] == "trade" and e["signal_time"] == trade["signal_time"]
            and e["variant"] == trade["variant"] and e["symbol"] == trade["symbol"]] == [trade]
    count = len(events)
    journal.step()
    assert len(journal.events()) == count  # the same mismatch is written once
    assert journal.status()["variants"][trade["variant"]]["mismatches"] == 1


def test_broken_chain_and_missing_start_are_refused(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    lines = journal.journal_path.read_text().splitlines()
    event = json.loads(lines[0])
    event["start_ms"] -= H4  # back-dating the start
    journal.journal_path.write_text(json.dumps(event) + "\n")
    with pytest.raises(fwd.ForwardError, match="hash chain"):
        journal.step()


def test_late_signal_is_flagged(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    _advance(exchange, clock, 400)  # the Mac "slept" through 400 bars
    journal.step()
    signals = [e for e in journal.events() if e["kind"] == "signal"]
    assert any(e["late"] for e in signals)
    assert journal.status()["variants"]["S7b-D20-T3"]["late_signals"] > 0


def test_pending_and_open_are_exclusive(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    for _ in range(300):
        _advance(exchange, clock, 1)
        status = journal.step()
        for row in status["variants"].values():
            assert len(row["open"]) + len(row["pending"]) <= 1


def test_bad_kline_rows_are_refused() -> None:
    good = _rows("BTCUSDT", 1)[0]
    assert fwd.parse_kline(good).open_time == T0
    with pytest.raises(fwd.ForwardError):
        fwd.parse_kline(good[:5])
    off_grid = list(good)
    off_grid[0] += 1
    with pytest.raises(fwd.ForwardError):
        fwd.parse_kline(off_grid)
    bad_price = list(good)
    bad_price[2] = "1"  # high below open
    with pytest.raises(fwd.ForwardError):
        fwd.parse_kline(bad_price)
    nan = list(good)
    nan[4] = "nan"
    with pytest.raises(fwd.ForwardError):
        fwd.parse_kline(nan)


def test_start_inside_the_holdout_window_is_refused(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
    journal = fwd.ForwardJournal(tmp_path, fetch=FakeExchange(), clock=clock)
    with pytest.raises(fwd.ForwardError, match="holdout"):
        journal.start()
    assert not journal.journal_path.exists()


def test_drawdown() -> None:
    assert fwd.max_drawdown([]) == 0
    assert fwd.max_drawdown([1, -1, -1, 3, -2]) == 2


def test_workshop_steps_forward_and_survives_its_failure(tmp_path: Path) -> None:
    from src.research_lab.workshop.schedule import Workshop
    seen = []

    def forward(root: Path) -> dict:
        seen.append(root)
        return {"new_events": 2}

    now = datetime(2026, 11, 1, 2, 30, tzinfo=timezone.utc)
    workshop = Workshop(tmp_path, ask=None, ps=lambda: "", forward=forward)
    summary = workshop.run_once(now)
    assert summary["forward"]["ok"] is True and summary["forward"]["new_events"] == 2
    assert seen == [tmp_path]
    assert workshop.read_state()["forward"]["last_result"]["ok"] is True
    assert "forward" not in workshop.run_once(now, dry_run=True)
    assert "forward" not in workshop.run_once(now, only="trades")
    quiet = Workshop(tmp_path, ps=lambda: "", forward=lambda root: {"new_events": 0})
    lines = len((tmp_path / "data/research/schedule/history.jsonl").read_text().splitlines())
    quiet.run_once(now + timedelta(minutes=15))  # nothing due, nothing new: no history line
    assert len((tmp_path / "data/research/schedule/history.jsonl").read_text().splitlines()) == lines

    def broken(root: Path) -> dict:
        raise OSError("network down")

    failing = Workshop(tmp_path, ask=None, ps=lambda: "", forward=broken).run_once(now + timedelta(hours=2))
    assert failing["forward"]["ok"] is False and "network down" in failing["forward"]["error"]
    assert failing["ran"]["trades"]["ok"] is True
    (tmp_path / "data/research/schedule/PAUSE").touch()
    assert "forward" not in Workshop(tmp_path, ps=lambda: "", forward=forward).run_once(now + timedelta(hours=4))
    assert Workshop(tmp_path, ps=lambda: "").forward is None  # tests and other callers: no network unless asked


def test_forschung_screen_shows_the_forward_card(tmp_path: Path) -> None:
    from src.dashboard.screens import _forward_card
    from src.research_lab.workshop.overview import overview
    journal, exchange, clock = _journal(tmp_path / "data/research/forward")
    journal.folder = tmp_path / fwd.FOLDER
    journal.step()
    _advance(exchange, clock, 400)
    journal.step()
    data = overview(tmp_path)
    assert data["forward"]["variants"]["S7b-D20-T4"]["target_r"] == 4.0
    html = _forward_card(data["forward"])
    assert "S7b-Vorwärtstest" in html and "S7b-D20-T3" in html and "von 100 Trades" in html
    assert "Noch kein Lauf" in _forward_card(None)
    assert overview(tmp_path / "empty")["forward"] is None


class LaggingExchange(FakeExchange):
    """ETH answers up to ``lag`` bars late, as an exchange hiccup would."""

    lag = 2

    def __call__(self, path: str, params: dict) -> list:
        rows = super().__call__(path, params)
        if path == "/fapi/v1/klines" and params["symbol"] == "ETHUSDT":
            return [r for r in rows if r[6] + self.lag * H4 < self.now_ms]
        return rows


def test_lagging_coin_never_changes_logged_trades(tmp_path: Path) -> None:
    exchange = LaggingExchange()
    clock = Clock(datetime.fromtimestamp((T0 + 400 * H4 - 30 * 60_000) / 1000, tz=timezone.utc))
    exchange.now_ms = int(clock().timestamp() * 1000)
    journal = fwd.ForwardJournal(tmp_path / "S7b", fetch=exchange, clock=clock)
    journal.step()
    for _ in range(300):
        _advance(exchange, clock, 1)
        status = journal.step()
        # the slot is shared, so all coins are simulated only up to the newest bar every coin has
        assert status["simulated_through"] == status["last_closed_bar"]["ETHUSDT"] < status["last_closed_bar"]["BTCUSDT"]
    exchange.lag = 0
    _advance(exchange, clock, 1)
    journal.step()
    events = journal.events()
    assert not [e for e in events if e["kind"] == "mismatch"]
    # what was logged step by step equals one fresh run over all bars
    full = FakeExchange()
    fresh_clock = Clock(datetime.fromtimestamp((T0 + 400 * H4 - 30 * 60_000) / 1000, tz=timezone.utc))
    fresh = fwd.ForwardJournal(tmp_path / "fresh", fetch=full, clock=fresh_clock)
    assert fresh.start()["start_ms"] == events[0]["start_ms"]
    fresh_clock.moment, full.now_ms = clock.moment, exchange.now_ms
    fresh.step()
    fresh_events = [e for e in fresh.events() if e["kind"] == "trade"]
    key = lambda e: (e["variant"], e["symbol"], e["signal_time"], e["r"])  # noqa: E731
    assert sorted(map(key, (e for e in events if e["kind"] == "trade"))) == sorted(map(key, fresh_events))


def test_pending_signal_gets_its_final_status(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    for _ in range(300):
        _advance(exchange, clock, 1)
        journal.step()
    events = journal.events()
    final: dict = {}
    for e in events:
        if e["kind"] in ("signal", "signal_status"):
            final[(e["variant"], e["symbol"], e["signal_time"])] = e["status"]
    assert any(e["kind"] == "signal_status" for e in events)
    last = max(t for _, _, t in final)
    assert all(status != "pending" for (_, _, t), status in final.items() if t < last)
    taken = {k for k, v in final.items() if v == "taken"}
    traded = {(e["variant"], e["symbol"], e["signal_time"]) for e in events if e["kind"] == "trade"}
    assert traded <= taken
    t3 = journal.status()["variants"]["S7b-D20-T3"]
    assert t3["signals"] == t3["signal_status"]["taken"] + t3["signal_status"]["pending"]
    assert t3["invalid_signals"] >= 0


def test_torn_last_line_is_dropped_and_logged_trade_that_vanishes_is_reported(tmp_path: Path) -> None:
    journal, exchange, clock = _journal(tmp_path)
    journal.step()
    _advance(exchange, clock, 400)
    journal.step()
    with journal.journal_path.open("a") as handle:
        handle.write('{"kind": "trade", "half')  # crash while writing
    count = len(journal.events())
    trade = next(e for e in journal.events() if e["kind"] == "trade")
    # forge nothing: append a valid fake trade through the journal itself, then let the recompute miss it
    journal._append([{**{k: trade[k] for k in trade if k not in ("hash", "previous", "schema", "study", "counts_in_net_r")},
                      "signal_time": trade["signal_time"] + 1}])
    assert len(journal.events()) == count + 1  # torn line gone, chain intact
    journal.step()
    missing = [e for e in journal.events() if e["kind"] == "mismatch" and e["key"].endswith("|missing")]
    assert len(missing) == 1 and missing[0]["recomputed"] is None
