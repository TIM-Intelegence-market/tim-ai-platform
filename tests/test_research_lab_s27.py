"""S27 larger trades: fixed geometry, S24 costs, purge per section, one trade at a time, draft guard."""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from src.research_lab.bitunix.contract import FEE_TAKER
from src.research_lab.bitunix.leverage import SLIPPAGE, STOP_SLIPPAGE
from src.research_lab.data.parse import Kline
from src.research_lab.protocol import VALIDATION_START_MS
from src.research_lab.studies import s22, s24, s27
from src.research_lab.studies.s20 import HOUR

START = int(datetime(2022, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
NO_RATES = ([], [])


def _flat(n: int, start: int = START, price: float = 100.0) -> list[Kline]:
    return [Kline(start + i * HOUR, price, price + 0.5, price - 0.5, price, 1.0, start + (i + 1) * HOUR - 1, 0.5) for i in range(n)]


def _set(bars: list[Kline], k: int, *, high: float | None = None, low: float | None = None) -> None:
    b = bars[k]
    bars[k] = Kline(b.open_time, b.open, b.high if high is None else high, b.low if low is None else low, b.close,
                    b.volume, b.close_time, b.taker_buy_volume)


def test_geometry_and_costs():
    assert (s27.STOP_ATR, s27.TARGET_ATR, s27.HORIZON) == (3.0, 6.0, 168)
    bars = _flat(200)
    _set(bars, 100, high=106.5)  # target 6 ATR = 106 at atr 1.0, reached after 100 h (inside 168)
    net, exit_t = s27.outcome(bars, 0, "LONG", 1.0, NO_RATES)
    side = FEE_TAKER + SLIPPAGE
    assert net == pytest.approx(2.0 - (100 * side + 106 * side) / 3.0)
    assert exit_t == bars[100].open_time + HOUR
    bars = _flat(200)
    _set(bars, 5, low=96.5)  # stop at 97
    net, _ = s27.outcome(bars, 0, "LONG", 1.0, NO_RATES)
    assert net == pytest.approx(-1.0 - (100 * side + 97 * (side + STOP_SLIPPAGE)) / 3.0)
    # the cost per trade in R is a third of S24's for the same price and ATR
    flat = _flat(200)
    assert s27.outcome(flat, 0, "LONG", 1.0, NO_RATES)[0] == pytest.approx(-(200 * side) / 3.0)
    assert s27.outcome(flat, 40, "LONG", 1.0, NO_RATES) is None  # 168 candles not there
    # funding over the whole holding time, also after S24's 48 h
    rates = ([START + 100 * HOUR], [0.001])
    assert s27.outcome(flat, 0, "LONG", 1.0, rates)[0] == pytest.approx(s27.outcome(flat, 0, "LONG", 1.0, NO_RATES)[0] - 0.1 / 3.0)


def test_window_must_end_inside_the_section():
    end_of_training = VALIDATION_START_MS
    bars = _flat(400, start=end_of_training - 300 * HOUR)
    inside = [i for i in range(len(bars)) if s27.window_inside(bars, i)]
    last_close = bars[max(inside)].open_time + HOUR
    assert last_close + s27.HORIZON * HOUR <= end_of_training < last_close + (s27.HORIZON + 1) * HOUR
    assert not any(s27.window_inside(bars, i) for i in range(len(bars)) if bars[i].open_time + HOUR >= end_of_training)


def test_sequence_takes_one_trade_at_a_time():
    from src.dashboard.chart_verdict import SKIP, TAKE

    rows = [s24.Row(START + k * HOUR, "validierung", d, {}, float(k)) for k in range(10) for d in s22.DIRECTIONS]
    exits = {(r.time, r.direction): r.time + 4 * HOUR for r in rows}
    taken = s27.sequence(rows, lambda r: TAKE if r.direction == "LONG" else SKIP, exits)
    assert taken == [0.0, 4.0, 8.0]  # entries at hours 0, 4, 8: each waits for the previous exit
    assert s27.sequence(rows, lambda r: SKIP, exits) == []


def _planted(effect: float, seed: int) -> tuple[list[s24.Row], dict]:
    rng = random.Random(seed)
    rows, exits = [], {}
    for section, start in (("training", START), ("validierung", VALIDATION_START_MS)):
        for j in range(60 * 14):
            t = start + j * 12 * HOUR
            for direction in s22.DIRECTIONS:
                c = rng.choice((-1.0, 0.0, 1.0))
                feats = {"C": (c,) * 5, "K": tuple(rng.gauss(0, 1) for _ in range(3)), "F": tuple(rng.gauss(0, 0.2) for _ in range(6)),
                         "G": (rng.gauss(0, 1), rng.gauss(0, 1)), "T": tuple(rng.choice((-1.0, 1.0)) for _ in range(3)),
                         "V": (rng.gauss(0, 1), rng.gauss(0, 1))}
                rows.append(s24.Row(t, section, direction, feats, effect * c + rng.gauss(0, 1.0)))
                exits[(t, direction)] = t + 36 * HOUR
    return rows, exits


def test_planted_effect_passes_and_noise_fails(monkeypatch):
    monkeypatch.setattr(s27, "VERSION", "1.0")
    monkeypatch.setattr(s24, "MIN_TRADES", 50)
    monkeypatch.setattr(s24, "MIN_WEEKS", 20)
    rows, exits = _planted(0.5, 1)
    good = s27.evaluate(rows, list(s24.FAMILIES), exits, boot_draws=199, shift_draws=49)
    assert good["urteil"].startswith("BESTANDEN")
    assert good["modelle"]["M1"]["folge"]["n"] >= s27.MIN_SEQUENCE
    assert good["modelle"]["M1"]["kriterien"]["folge_positiv_nach_kosten"]
    rows, exits = _planted(0.0, 2)
    noise = s27.evaluate(rows, list(s24.FAMILIES), exits, boot_draws=199, shift_draws=49)
    assert noise["urteil"] == "NO ROBUST EDGE PROVEN"


def test_draft_refuses_to_evaluate():
    with pytest.raises(SystemExit):
        s27.evaluate([], list(s24.FAMILIES), {})


def test_build_rows_purges_and_scores_only_with_rates():
    from tests.test_research_lab_s24 import _series

    bars, half = _series(s22.WINDOW_1H + 400)
    blind, no_exits = s27.build_rows(bars, half)
    assert blind and all(r.net_r is None for r in blind) and no_exits == {}
    scored, exits = s27.build_rows(bars, half, rates=[])
    assert len(scored) == len(blind) and all(r.net_r is not None for r in scored)
    assert all(exits[(r.time, r.direction)] > r.time for r in scored)
    assert len(blind) < len(s24.build_rows(bars, half))  # the last 120 h of S24's moments do not fit 168 h
