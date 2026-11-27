"""Producer -> consumer for the known-side policy (Codex P2 #376, 27.11.2026).

The Lage is built by the real tracker (``live_state``) and judged by the real shadow (``orderflow_shadow``): no window
dicts are written by hand here, so a loss of precision between the two would show. The seeded sweep always runs; the
Hypothesis variant runs where Hypothesis is installed.
"""
from __future__ import annotations

import inspect
import json
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


@pytest.mark.parametrize("evidence_patch, status", [
    ({"known": 0.95}, "INVALID"), ({"unknown": 0.05}, "INVALID"), ({"known": "9.5e-1"}, "INVALID"),
    ({"unknown": "-0.05"}, "INVALID"), ({"known": "nan"}, "INVALID"), ({"unknown": "inf"}, "INVALID"),
    ({"known": True}, "INVALID"), ({"known": " 0.95"}, "INVALID"), ({"schema": "side-evidence/0"}, "INVALID"),
    ({"known": None}, "MISSING"), ({"unknown": None}, "MISSING"),
])
def test_invalid_evidence_written_into_a_produced_lage_fails_closed(evidence_patch, status):
    lage = _lage([(0.95, False), (0.05, None)])
    assert _judge(lage)[0]["side_status"] == "OK"
    lage["windows"]["5m"]["side_evidence"].update(evidence_patch)
    view, gate, exit_long, _ = _judge(lage)
    assert view["side_ok"] is False and view["side_status"] == status
    assert gate == shadow.UNBEKANNT and exit_long is None


@pytest.mark.parametrize("drop", ["known", "unknown", "block"])
def test_evidence_taken_out_of_a_produced_lage_is_missing(drop):
    lage = _lage([(0.95, False), (0.05, None)])
    if drop == "block":
        del lage["windows"]["15m"]["side_evidence"]
    else:
        del lage["windows"]["15m"]["side_evidence"][drop]
    view, gate, exit_long, exit_short = _judge(lage)
    assert (view["side_ok"], view["side_status"]) == (False, "MISSING") and gate == shadow.UNBEKANNT
    assert exit_long is None and exit_short is None


@pytest.mark.parametrize("display", [{"volume": "0.0006"}, {"unknown_volume": None}, {"volume": float("nan")},
                                     {"volume": 1e9, "unknown_volume": 0.0}])
def test_display_numbers_do_not_feed_the_policy(display):
    """volume/unknown_volume are display only since round 2: changing them leaves the verdict as the evidence says."""
    for parts, status in (([(0.95, False), (0.05, None)], "OK"), ([(0.56, False), (0.04, None)], "BELOW")):
        lage = _lage(parts)
        lage["windows"]["5m"].update(display)
        assert _judge(lage)[0]["side_status"] == status


# Codex #376 (27.11.): two tracker trades, exact sum 0.000140273908193734948 < 20 * unknown 0.000140273908193734960;
# float(volume) is 0.00014027390819373496 and used to give OK/0.95, LONG confirmed and a SHORT exit.
CODEX_KNOWN, CODEX_UNKNOWN = 0.0001332602127840482, 0.000007013695409686748


def test_codex_case_is_below_through_json_and_the_view():
    lage = json.loads(json.dumps(_lage([(CODEX_KNOWN, False), (CODEX_UNKNOWN, None)])))
    for window in lage["windows"].values():
        assert window["side_evidence"] == {"schema": "side-evidence/1", "known": "0.0001332602127840482",
                                           "unknown": "0.000007013695409686748"}
        assert 20 * Decimal(window["side_evidence"]["unknown"]) > Decimal("0.000140273908193734948")
    view, gate, exit_long, exit_short = _judge(lage)
    assert (view["side_ok"], view["side_status"]) == (False, "BELOW")
    assert gate == shadow.UNBEKANNT and exit_long is None and exit_short is None
    stored = json.loads(json.dumps(view))                       # the view kept on a plan survives JSON as well
    assert shadow.gate("LONG", stored) == shadow.UNBEKANNT and shadow.should_exit("SHORT", stored) is None


def test_codex_case_mirror_on_the_other_side_of_the_boundary():
    """One unit more known in the last written digit (…482 -> …483) brings 20 * unknown <= total: OK."""
    known = 0.0001332602127840483
    assert Decimal(repr(known)) + Decimal(repr(CODEX_UNKNOWN)) >= 20 * Decimal(repr(CODEX_UNKNOWN))
    lage = json.loads(json.dumps(_lage([(known, False), (CODEX_UNKNOWN, None)])))
    assert _judge(lage)[0]["side_status"] == "OK"


def test_evidence_sums_are_exact_over_many_trades_and_survive_json():
    parts = [(0.1, False)] * 190 + [(0.1, None)] * 10   # float sum of 0.1s is not 19; the evidence is
    lage = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    trades = [Trade(SYMBOL, 75000.0, q, T0 + timedelta(seconds=10 + k * 0.2), k + 1, buyer_is_maker=m)  # type: ignore[arg-type]
              for k, (q, m) in enumerate(parts)]
    if "available_at" in inspect.signature(lage.ingest).parameters:
        lage.ingest(trades, available_at=T0 + timedelta(seconds=50))
    else:
        lage.ingest(trades)
    state = json.loads(json.dumps(lage.snapshot(NOW + timedelta(seconds=1))))
    assert state["windows"]["1m"]["side_evidence"]["known"] == "19"
    assert state["windows"]["1m"]["side_evidence"]["unknown"] == "1"
    assert _judge(state)[0]["side_status"] == "OK"


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
