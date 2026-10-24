from __future__ import annotations

import ast
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.options_gamma import (
    GexObservationEngine,
    OptionQuote,
    bs_delta,
    bs_gamma,
    compute_gex_profile,
    load_chain_snapshot,
)
from src.options_gamma.gex import _total_gex

FIXTURE = Path(__file__).parent / "fixtures" / "options_gamma" / "btc_chain_sample.json"
NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def _sample():
    return load_chain_snapshot(json.loads(FIXTURE.read_text()))


def test_gamma_matches_closed_form_reference():
    # S=K=100, T=30d, vol=50 %: d1 = 0.5*vol*sqrt(T), gamma = pdf(d1)/(S*vol*sqrt(T))
    years = 30 / 365
    d1 = 0.5 * 0.5 * math.sqrt(years)
    expected = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (100 * 0.5 * math.sqrt(years))
    assert bs_gamma(100, 100, years, 0.5) == pytest.approx(expected, rel=1e-12)
    assert bs_gamma(100, 100, years, 0.5) == pytest.approx(0.027759, abs=1e-6)


def test_gamma_is_derivative_of_delta_and_same_for_puts():
    s, k, t, v, h = 67000.0, 70000.0, 14 / 365, 0.55, 1.0
    call_fd = (bs_delta(s + h, k, t, v, True) - bs_delta(s - h, k, t, v, True)) / (2 * h)
    put_fd = (bs_delta(s + h, k, t, v, False) - bs_delta(s - h, k, t, v, False)) / (2 * h)
    assert call_fd == pytest.approx(bs_gamma(s, k, t, v), rel=1e-5)
    assert put_fd == pytest.approx(bs_gamma(s, k, t, v), rel=1e-5)
    assert bs_delta(s, k, t, v, True) - bs_delta(s, k, t, v, False) == pytest.approx(1.0)


@pytest.mark.parametrize("args", [(0, 1, 1, 0.5), (1, 0, 1, 0.5), (1, 1, 0, 0.5), (1, 1, 1, 0)])
def test_gamma_rejects_invalid_inputs(args):
    with pytest.raises(ValueError):
        bs_gamma(*args)


def test_sample_profile_levels():
    symbol, spot, as_of, chain = _sample()
    profile = compute_gex_profile(symbol, spot, as_of, chain)
    assert profile.regime == "POSITIVE_GAMMA"
    assert profile.call_wall == 70000
    assert profile.put_wall == 65000
    assert profile.skipped_expired == 1
    assert profile.gamma_flip is not None and 60000 < profile.gamma_flip < spot
    live = [(q, (q.expiry - as_of).total_seconds() / (365 * 24 * 3600)) for q in chain if q.expiry > as_of]
    assert _total_gex(live, profile.gamma_flip - 50, 0.0) < 0 < _total_gex(live, profile.gamma_flip + 50, 0.0)
    assert profile.net_gex == pytest.approx(sum(s.call_gex + s.put_gex for s in profile.strikes))


def test_call_gex_positive_put_gex_negative_and_units():
    expiry = NOW + timedelta(days=30)
    call = OptionQuote(100, expiry, True, 10, 0.5)
    put = OptionQuote(100, expiry, False, 10, 0.5)
    profile = compute_gex_profile("X", 100, NOW, [call, put])
    (row,) = profile.strikes
    gamma = bs_gamma(100, 100, (expiry - NOW).total_seconds() / (365 * 24 * 3600), 0.5)
    assert row.call_gex == pytest.approx(gamma * 10 * 100 * 100 * 0.01)
    assert row.put_gex == pytest.approx(-row.call_gex)
    assert profile.regime == "NEUTRAL_GAMMA" or abs(profile.net_gex) < 1e-9


def test_only_puts_is_negative_regime_without_flip():
    expiry = NOW + timedelta(days=7)
    chain = [OptionQuote(k, expiry, False, 100, 0.6) for k in (90, 95, 100)]
    profile = compute_gex_profile("X", 100, NOW, chain)
    assert profile.regime == "NEGATIVE_GAMMA"
    assert profile.call_wall is None and profile.put_wall is not None
    assert profile.gamma_flip is None


def test_expired_only_chain_gives_empty_profile_and_no_observation():
    chain = [OptionQuote(100, NOW - timedelta(days=1), True, 10, 0.5)]
    profile = compute_gex_profile("X", 100, NOW, chain)
    assert profile.strikes == () and profile.gamma_flip is None
    assert GexObservationEngine().evaluate(profile) == []


def test_hash_is_order_independent_and_input_sensitive():
    symbol, spot, as_of, chain = _sample()
    a = compute_gex_profile(symbol, spot, as_of, chain)
    b = compute_gex_profile(symbol, spot, as_of, list(reversed(chain)))
    c = compute_gex_profile(symbol, spot + 1, as_of, chain)
    assert a.input_hash == b.input_hash != c.input_hash


def test_observation_is_observe_only_and_deduplicated():
    symbol, spot, as_of, chain = _sample()
    profile = compute_gex_profile(symbol, spot, as_of, chain)
    engine = GexObservationEngine()
    (obs,) = engine.evaluate(profile)
    assert obs.kind == "POSITIVE_GAMMA_REGIME"
    assert obs.mode == "OBSERVE" and obs.rule_id == "gex_regime"
    assert obs.input_hash == profile.input_hash
    fields = {e["field"]: e for e in obs.evidence}
    assert fields["call_wall"]["value"] == 70000
    assert fields["call_wall"]["distance_pct"] == pytest.approx((70000 - spot) / spot * 100, abs=1e-4)
    json.dumps(obs.to_dict())
    assert engine.evaluate(profile) == []
    assert GexObservationEngine().evaluate(profile)[0].observation_id == obs.observation_id


def test_rejects_naive_datetimes_and_bad_types():
    with pytest.raises(ValueError):
        OptionQuote(100, datetime(2026, 11, 1), True, 1, 0.5)
    with pytest.raises(ValueError):
        compute_gex_profile("X", 100, datetime(2026, 10, 21), [])
    with pytest.raises(ValueError):
        load_chain_snapshot({"symbol": "X", "spot": 1, "as_of": NOW.isoformat(), "chain": [
            {"strike": 1, "expiry": NOW.isoformat(), "type": "future", "open_interest": 1, "implied_vol": 0.5}]})


def test_package_has_no_network_or_execution_imports():
    forbidden = {"socket", "requests", "httpx", "urllib", "aiohttp", "websockets", "ccxt", "subprocess"}
    for path in (Path(__file__).parents[1] / "src" / "options_gamma").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in forbidden, f"{path.name} imports {name}"


def test_learning_doc_exercise_numbers():
    assert bs_gamma(100, 100, 30 / 365, 0.5) == pytest.approx(0.0278, abs=5e-5)
    gex = bs_gamma(67000, 70000, 30 / 365, 0.48) * 1000 * 67000**2 * 0.01
    assert gex == pytest.approx(1.88e6, rel=0.01)
    straddle_gamma = 2 * bs_gamma(100, 100, 30 / 365, 0.5)
    breakeven = 100 * 0.5 / math.sqrt(365)
    assert breakeven == pytest.approx(2.62, abs=0.01)
    assert 0.5 * straddle_gamma * breakeven**2 == pytest.approx(0.19, abs=0.005)
    assert 0.5 * straddle_gamma * 16 == pytest.approx(0.44, abs=0.005)
