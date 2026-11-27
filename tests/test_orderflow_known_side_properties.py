"""Properties of the known-side check (Mission 07-FINAL, #372): nothing but written, valid numbers confirms a side.

The seeded sweep always runs; the Hypothesis variant runs where Hypothesis is installed (not in the CI image).
"""
from __future__ import annotations

import math
import random
from decimal import Decimal
from fractions import Fraction

import pytest

from src.dashboard import orderflow_shadow as shadow

NAMES = ("1m", "5m", "15m")
JUNK = (None, "0", "x", True, False, float("nan"), float("inf"), -1.0, [], {})
ABSENT = object()


def _valid(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _q(value) -> Fraction:
    """A float as the decimal it is written as (#376, 27.11.: 0.95 is 19/20 exactly, like producer and consumer)."""
    return Fraction(Decimal(repr(value))) if isinstance(value, float) else Fraction(value)


def _oracle(windows) -> bool:
    """Independent restatement of the rule: OK only with every needed window, both numbers valid, share >= 95 %."""
    if not isinstance(windows, dict) or any(name not in windows for name in NAMES):
        return False
    lowest = None
    for window in windows.values():
        if not isinstance(window, dict) or "volume" not in window or "unknown_volume" not in window:
            return False
        volume, unknown = window["volume"], window["unknown_volume"]
        if not _valid(volume) or not _valid(unknown) or _q(unknown) > _q(volume):
            return False
        if volume > 0:
            share = (_q(volume) - _q(unknown)) / _q(volume)
            lowest = share if lowest is None else min(lowest, share)
    return lowest is not None and lowest >= Fraction(95, 100)


def _check(windows) -> None:
    lage = {"price": 100.0, "wave": {"direction": "auf", "strength": 3}}
    if windows is not ABSENT:
        lage["windows"] = windows
    view = shadow.lage_view(lage)
    expected = _oracle(None if windows is ABSENT else windows)
    assert view["side_ok"] is expected, (windows, view)
    assert (view["side_status"] == "OK") is expected
    if expected:
        assert shadow.gate("LONG", view) == shadow.BESTAETIGT and shadow.gate("SHORT", view) == shadow.GEGEN
    else:
        assert shadow.gate("LONG", view) == shadow.UNBEKANNT == shadow.gate("SHORT", view)
        assert shadow.should_exit("LONG", view) is None and shadow.should_exit("SHORT", view) is None


def _random_windows(rng: random.Random):
    if rng.random() < 0.03:
        return rng.choice((ABSENT, None, [], "1m", {}))
    windows = {}
    for name in NAMES + ("1h",):
        if rng.random() < (0.08 if name != "1h" else 0.85):
            continue
        if rng.random() < 0.04:
            windows[name] = rng.choice((None, [], "x"))
            continue
        volume = rng.choice((0, 0.0, 1.0, 100.0, 100000.0, rng.uniform(0, 1e6)))
        unknown = rng.choice((0, 0.0, volume * 0.05, volume * 0.0501, volume * 0.04, rng.uniform(0, max(volume, 1.0))))
        window = {"volume": volume, "unknown_volume": unknown, "delta": 1.0}
        for field in ("volume", "unknown_volume"):
            roll = rng.random()
            if roll < 0.06:
                del window[field]
            elif roll < 0.12:
                window[field] = rng.choice(JUNK)
        windows[name] = window
    return windows


def test_seeded_sweep_agrees_with_the_rule_and_hits_both_outcomes():
    rng = random.Random(20261124)
    outcomes = set()
    for _ in range(20000):
        windows = _random_windows(rng)
        _check(windows)
        outcomes.add(_oracle(None if windows is ABSENT else windows))
    assert outcomes == {True, False}


def test_taking_any_single_piece_of_evidence_away_from_a_confirmed_lage_never_keeps_it_confirmed():
    """Metamorphic: from an OK Lage, drop / null / corrupt one field or one needed window: never OK again."""
    rng = random.Random(7)
    for _ in range(300):
        base = {name: {"volume": rng.uniform(1, 1e5), "unknown_volume": 0.0} for name in NAMES}
        assert shadow.known_side({"windows": base})["status"] == "OK"
        for name in NAMES:
            assert shadow.known_side({"windows": {k: v for k, v in base.items() if k != name}})["ok"] is False
            for field in ("volume", "unknown_volume"):
                without = {**base, name: {k: v for k, v in base[name].items() if k != field}}
                assert shadow.known_side({"windows": without})["status"] == "MISSING"
                for junk in JUNK:
                    broken = {**base, name: {**base[name], field: junk}}
                    assert shadow.known_side({"windows": broken})["ok"] is False


def test_hypothesis_generated_windows_agree_with_the_rule():
    hypothesis = pytest.importorskip("hypothesis")
    st = hypothesis.strategies
    number = st.one_of(st.integers(-2, 10**6), st.floats(allow_nan=True, allow_infinity=True, width=64),
                       st.sampled_from(JUNK[:5]))
    window = st.one_of(st.none(), st.dictionaries(st.sampled_from(("volume", "unknown_volume", "delta")), number, max_size=3))
    windows = st.one_of(st.none(), st.dictionaries(st.sampled_from(NAMES + ("1h",)), window, max_size=4))

    @hypothesis.settings(max_examples=600, deadline=None)
    @hypothesis.given(windows)
    def run(value):
        _check(value)

    run()
