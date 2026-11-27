"""Producer -> consumer for the known-side policy (Codex P2 #376, 27.11.2026).

The Lage is built by the real tracker (``live_state``) and judged by the real shadow (``orderflow_shadow``): no window
dicts are written by hand here, so a loss of precision between the two would show. The seeded sweep always runs; the
Hypothesis variant runs where Hypothesis is installed.
"""
from __future__ import annotations

import inspect
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

import pytest

from src.dashboard import orderflow_shadow as shadow
from src.models.market_data import Trade
from src.orderflow import live_state as ls

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"
NOW = T0 + timedelta(seconds=50)


def _lage(parts, order=None):
    """``parts`` = [(qty, maker)] all inside the last minute (at most 120 trades, all available before ``NOW``); maker True = sell, False = buy, None = unknown side."""
    items = list(enumerate(parts))
    if order is not None:
        items = [items[i] for i in order]
    trades = [Trade(SYMBOL, 75000.0, qty, T0 + timedelta(seconds=10 + k * 0.25), k + 1, buyer_is_maker=maker)  # type: ignore[arg-type]
              for k, (_, (qty, maker)) in enumerate(items)]
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    if "available_at" in inspect.signature(tracker.ingest).parameters:   # Paket A: availability is evidence too
        tracker.ingest(trades, available_at=T0 + timedelta(seconds=40))
    else:
        tracker.ingest(trades)
    return tracker.snapshot(NOW)


def _expected(parts) -> bool:
    known = sum((Decimal(repr(q)) for q, m in parts if m is not None), Decimal(0))
    unknown = sum((Decimal(repr(q)) for q, m in parts if m is None), Decimal(0))
    volume = known + unknown
    return volume > 0 and Fraction(known) / Fraction(volume) >= Fraction(95, 100)


def _judge(lage):
    view = shadow.lage_view(lage)
    return view, shadow.gate("LONG", view), shadow.should_exit("LONG", view), shadow.should_exit("SHORT", view)


def test_p2_case_small_unknown_share_is_not_lost_by_rounding():
    lage = _lage([(0.00056, False), (0.00004, None)])
    assert lage["windows"]["1m"]["unknown_volume"] == pytest.approx(0.00004, abs=0)   # not rounded away
    view, gate, exit_long, exit_short = _judge(lage)
    assert view["side_ok"] is False and view["side_status"] == "BELOW"
    assert view["known_share"] == pytest.approx(0.9333333, rel=1e-6)
    assert gate == shadow.UNBEKANNT and exit_long is None and exit_short is None


@pytest.mark.parametrize("scale", ["0.00001", "0.001", "1", "1000", "100000"])
@pytest.mark.parametrize("known, unknown, ok", [
    ("95", "5", True),          # exactly 95 %: still judged
    ("9499", "501", False),     # 94.99 %: just below
    ("9501", "499", True),      # 95.01 %: just above
    ("56", "4", False),         # the P2 ratio, 93.33 %
])
def test_boundary_on_small_and_large_scales(scale, known, unknown, ok):
    unit = Decimal(scale) / (100 if len(known) <= 2 else 10000)
    parts = [(float(Decimal(known) * unit), False), (float(Decimal(unknown) * unit), None)]
    view, gate, exit_long, _ = _judge(_lage(parts))
    assert view["side_ok"] is ok, (scale, known, unknown, view)
    assert view["side_status"] == ("OK" if ok else "BELOW")
    if not ok:
        assert gate == shadow.UNBEKANNT and exit_long is None
    else:
        assert gate != shadow.UNBEKANNT


def test_known_volume_split_over_many_trades_keeps_the_exact_boundary():
    parts = [(0.01, False)] * 95 + [(0.01, None)] * 5       # 95 % in 100 trades of 0.01; a float sum is not 0.95
    view, *_ = _judge(_lage(parts))
    assert view["side_ok"] is True and view["side_status"] == "OK"
    parts = [(0.01, False)] * 94 + [(0.01, None)] * 6
    assert _judge(_lage(parts))[0]["side_ok"] is False


@pytest.mark.parametrize("lage_patch, status", [
    ({"volume": "0.0006"}, "INVALID"), ({"unknown_volume": None}, "MISSING"), ({"unknown_volume": -0.00004}, "INVALID"),
    ({"volume": float("nan")}, "INVALID"), ({"unknown_volume": float("inf")}, "INVALID"), ({"volume": True}, "INVALID"),
])
def test_invalid_values_written_into_a_produced_lage_fail_closed(lage_patch, status):
    lage = _lage([(0.95, False), (0.05, None)])
    lage["windows"]["5m"].update(lage_patch)
    view, gate, exit_long, _ = _judge(lage)
    assert view["side_ok"] is False and view["side_status"] == status
    assert gate == shadow.UNBEKANNT and exit_long is None


def test_display_text_stays_rounded():
    lage = _lage([(0.000561234, False), (0.00004, None)])
    assert "0.000561234" not in lage["text"]


def _random_parts(rng: random.Random):
    scale = Decimal(10) ** rng.randint(-5, 4)
    parts = []
    for _ in range(rng.randint(1, 12)):
        qty = float(Decimal(rng.randint(1, 10_000)) * scale / 1000)
        parts.append((qty, rng.choice((False, True, None)) if rng.random() < 0.3 else rng.choice((False, True))))
    return parts


def test_seeded_sweep_producer_consumer_agree_and_order_does_not_matter():
    rng = random.Random(20261127)
    outcomes = set()
    for _ in range(400):
        parts = _random_parts(rng)
        expected = _expected(parts)
        view, gate, exit_long, _ = _judge(_lage(parts))
        assert view["side_ok"] is expected, (parts, view)
        outcomes.add(expected)
        # Metamorphic: the order of arrival of the same trades changes nothing about the side.
        order = list(range(len(parts)))
        rng.shuffle(order)
        assert _judge(_lage(parts, order))[0]["side_ok"] is expected
        # Metamorphic: scaling every quantity by a power of ten changes nothing about the side.
        factor = Decimal(10) ** rng.randint(-2, 2)
        scaled = [(float(Decimal(repr(q)) * factor), m) for q, m in parts]
        assert _judge(_lage(scaled))[0]["side_ok"] is _expected(scaled) is expected
        if not expected:
            assert gate == shadow.UNBEKANNT and exit_long is None
    assert outcomes == {True, False}


def test_hypothesis_producer_consumer_agree():
    hypothesis = pytest.importorskip("hypothesis")
    st = hypothesis.strategies

    part = st.tuples(st.integers(1, 10_000), st.integers(-5, 4), st.sampled_from([False, True, None]))

    @hypothesis.settings(max_examples=150, deadline=None, derandomize=True)
    @hypothesis.given(st.lists(part, min_size=1, max_size=10))
    def run(raw):
        parts = [(float(Decimal(n) * Decimal(10) ** e / 1000), m) for n, e, m in raw]
        assert _judge(_lage(parts))[0]["side_ok"] is _expected(parts)

    run()
