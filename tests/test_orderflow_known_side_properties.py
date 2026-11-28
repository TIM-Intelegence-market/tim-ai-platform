"""Properties of the known-side check (Mission 07-FINAL, #372; reference semantics round 2, 27.11.).

The policy reads only each window's ``side_evidence`` (``{"schema": "side-evidence/1", "known": str, "unknown": str}``,
plain decimal strings). The oracle here is written independently of the code: its own string parser (digits and at
most one point, nothing else) and integer arithmetic for the rule ``20 * unknown <= known + unknown``. The seeded sweep
always runs; the Hypothesis variant runs where Hypothesis is installed.
"""
from __future__ import annotations

import random
from fractions import Fraction

import pytest

from src.dashboard import orderflow_shadow as shadow

NAMES = ("1m", "5m", "15m")
SCHEMA = "side-evidence/1"
JUNK = (None, 0, 0.0, 1.5, True, False, float("nan"), float("inf"), [], {}, "", ".", "1.", ".5", "-1", "+1", "1e-5",
        "1E3", " 1", "1 ", "1\n", "nan", "inf", "1_000", "0x10", "１", "1,5", "1.2.3")
ABSENT = object()


def _parse(raw):
    """Oracle parser: 'VALUE' with an exact Fraction, 'MISSING' or 'INVALID' (no Decimal, no float, no regex)."""
    if raw is ABSENT or raw is None:
        return "MISSING", None
    if type(raw) is not str or raw.count(".") > 1:
        return "INVALID", None
    whole, _, frac = raw.partition(".")
    if not whole or ("." in raw and not frac) or any(c not in "0123456789" for c in whole + frac):
        return "INVALID", None
    return "VALUE", Fraction(int(whole + frac), 10 ** len(frac))


def _oracle(windows) -> bool:
    if not isinstance(windows, dict) or any(name not in windows for name in NAMES):
        return False
    seen_volume = False
    for window in windows.values():
        if not isinstance(window, dict):
            return False
        block = window.get("side_evidence", ABSENT)
        if not isinstance(block, dict) or block.get("schema") != SCHEMA:
            return False
        (ks, k), (us, u) = _parse(block.get("known", ABSENT)), _parse(block.get("unknown", ABSENT))
        if ks != "VALUE" or us != "VALUE":
            return False
        if k + u > 0:
            seen_volume = True
            if 20 * u > k + u:
                return False
    return seen_volume


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


def _amount(rng: random.Random) -> str:
    whole = str(rng.choice((0, 0, 1, 5, 19, 95, 100, rng.randint(0, 10**9))))
    if rng.random() < 0.5:
        return whole
    return whole + "." + "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 24)))


def _pair(rng: random.Random) -> tuple[str, str]:
    """Known/unknown, often exactly at, just below or just above 20 * unknown == total."""
    roll = rng.random()
    if roll < 0.5:
        return _amount(rng), _amount(rng)
    scale = 10 ** rng.randint(0, 30)
    u = rng.randint(0, 10**6)
    k = 19 * u + rng.choice((-1, 0, 1, 0))             # equality, one unit below, one unit above
    return _scaled(max(k, 0), scale), _scaled(u, scale)


def _scaled(n: int, scale: int) -> str:
    digits = len(str(scale)) - 1
    if digits == 0:
        return str(n)
    text = str(n).rjust(digits + 1, "0")
    return text[:-digits] + "." + text[-digits:]


def _random_windows(rng: random.Random):
    if rng.random() < 0.03:
        return rng.choice((ABSENT, None, [], "1m", {}))
    windows = {}
    for name in NAMES + ("1h",):
        if rng.random() < (0.08 if name != "1h" else 0.85):
            continue
        if rng.random() < 0.04:
            windows[name] = rng.choice((None, [], "x", {}))
            continue
        known, unknown = _pair(rng)
        block = {"schema": SCHEMA, "known": known, "unknown": unknown}
        roll = rng.random()
        if roll < 0.03:
            block["schema"] = rng.choice(("side-evidence/2", None, 1))
        elif roll < 0.05:
            block = rng.choice((None, [], "x"))
        else:
            for field in ("known", "unknown"):
                roll = rng.random()
                if roll < 0.06:
                    del block[field]
                elif roll < 0.14:
                    block[field] = rng.choice(JUNK)
        window = {"volume": rng.choice((0.0, 1.0, 1e9)), "unknown_volume": rng.choice((0.0, 1e9)), "delta": 1.0}
        if rng.random() > 0.03:
            window["side_evidence"] = block
        windows[name] = window
    return windows


def test_seeded_sweep_agrees_with_the_rule_and_hits_both_outcomes():
    rng = random.Random(20261127)
    outcomes = set()
    for _ in range(20000):
        windows = _random_windows(rng)
        _check(windows)
        outcomes.add(_oracle(None if windows is ABSENT else windows))
    assert outcomes == {True, False}


@pytest.mark.parametrize("digits", [0, 1, 6, 18, 30])
@pytest.mark.parametrize("delta, ok", [(0, True), (-1, False), (1, True)])
def test_boundary_one_unit_in_the_last_digit(digits, delta, ok):
    """known = 19 * unknown + delta units of 10**-digits; 20 * unknown <= total exactly at delta 0."""
    unknown = 7 * 10**digits + 13
    windows = {name: {"side_evidence": {"schema": SCHEMA, "known": _scaled(19 * unknown + delta, 10**digits),
                                        "unknown": _scaled(unknown, 10**digits)}} for name in NAMES}
    assert shadow.known_side({"windows": windows})["ok"] is ok
    _check(windows)


def test_taking_any_single_piece_of_evidence_away_from_a_confirmed_lage_never_keeps_it_confirmed():
    """Metamorphic: from an OK Lage, drop / null / corrupt one amount, the block or one needed window: never OK."""
    rng = random.Random(7)
    for _ in range(200):
        base = {name: {"side_evidence": {"schema": SCHEMA, "known": _amount(rng), "unknown": "0"}} for name in NAMES}
        base["1m"]["side_evidence"]["known"] = "1" + base["1m"]["side_evidence"]["known"]   # at least one window has volume
        assert shadow.known_side({"windows": base})["status"] == "OK"
        for name in NAMES:
            assert shadow.known_side({"windows": {k: v for k, v in base.items() if k != name}})["ok"] is False
            assert shadow.known_side({"windows": {**base, name: {}}})["status"] == "MISSING"
            for field in ("known", "unknown"):
                block = base[name]["side_evidence"]
                without = {**base, name: {"side_evidence": {k: v for k, v in block.items() if k != field}}}
                assert shadow.known_side({"windows": without})["status"] == "MISSING"
                for junk in JUNK:
                    broken = {**base, name: {"side_evidence": {**block, field: junk}}}
                    assert shadow.known_side({"windows": broken})["ok"] is False


def test_display_floats_never_change_the_verdict():
    """The policy ignores volume/unknown_volume: the same evidence with any display numbers gives the same verdict."""
    evidence = {"schema": SCHEMA, "known": "0.0001332602127840482", "unknown": "0.000007013695409686748"}
    for display in ({}, {"volume": 1.0, "unknown_volume": 0.0}, {"volume": 0.00014027390819373496,
                                                                 "unknown_volume": 0.000007013695409686748},
                    {"volume": float("nan"), "unknown_volume": "x"}):
        windows = {name: {**display, "side_evidence": dict(evidence)} for name in NAMES}
        assert shadow.known_side({"windows": windows})["status"] == "BELOW"


def test_hypothesis_generated_evidence_agrees_with_the_rule():
    hypothesis = pytest.importorskip("hypothesis")
    st = hypothesis.strategies
    decimal_text = st.builds(lambda w, f: str(w) + ("." + f if f else ""), st.integers(0, 10**12),
                             st.text("0123456789", max_size=25))
    amount = st.one_of(decimal_text, st.text(max_size=6), st.sampled_from(JUNK), st.floats(), st.integers(-2, 10))
    block = st.one_of(st.none(), st.fixed_dictionaries({"schema": st.sampled_from((SCHEMA, SCHEMA, "x"))},
                                                       optional={"known": amount, "unknown": amount}))
    window = st.one_of(st.none(), st.fixed_dictionaries({}, optional={"side_evidence": block,
                                                                     "volume": st.floats(), "unknown_volume": st.floats()}))
    windows = st.one_of(st.none(), st.dictionaries(st.sampled_from(NAMES + ("1h",)), window, max_size=4))

    @hypothesis.settings(max_examples=600, deadline=None, derandomize=True)
    @hypothesis.given(windows)
    def run(value):
        _check(value)

    run()

    @hypothesis.settings(max_examples=400, deadline=None, derandomize=True)
    @hypothesis.given(st.integers(0, 10**15), st.integers(-3, 3), st.integers(0, 30))
    def boundary(unknown, delta, digits):
        known = max(19 * unknown + delta, 0)
        windows = {name: {"side_evidence": {"schema": SCHEMA, "known": _scaled(known, 10**digits),
                                            "unknown": _scaled(unknown, 10**digits)}} for name in NAMES}
        _check(windows)

    boundary()
