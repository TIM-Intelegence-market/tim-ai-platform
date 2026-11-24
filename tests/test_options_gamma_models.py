"""P1 gamma models: M0 equals gex.py, sign assumptions, forward variant, vanna/charm, flip only where it can exist."""
from __future__ import annotations

import itertools
import json
from datetime import timedelta
from pathlib import Path

import pytest

from src.options_gamma import models as m
from src.options_gamma.gex import compute_gex_profile, load_chain_snapshot
from src.options_gamma.greeks import bs_delta, bs_gamma

FIXTURE = Path(__file__).parent / "fixtures" / "options_gamma" / "btc_chain_sample.json"


@pytest.fixture()
def chain():
    return load_chain_snapshot(json.loads(FIXTURE.read_text()))


def test_m0_spot_reproduces_gex_py(chain):
    sym, spot, as_of, quotes = chain
    ref = compute_gex_profile(sym, spot, as_of, quotes)
    p = m.model_profile(quotes, spot, as_of, m.DealerModel.M0)
    assert p.net_gex == pytest.approx(ref.net_gex, rel=1e-12)
    assert p.call_wall == ref.call_wall and p.put_wall == ref.put_wall
    assert p.regime == ref.regime
    assert p.gamma_flip == pytest.approx(ref.gamma_flip, rel=0.002)  # different grid, same crossing


def test_forward_variant_equals_spot_when_forward_is_spot(chain):
    _, spot, as_of, quotes = chain
    fw = {q.expiry: spot for q in quotes}
    a = m.model_profile(quotes, spot, as_of, m.DealerModel.M0)
    b = m.model_profile(quotes, spot, as_of, m.DealerModel.M0, variant="forward", forwards=fw)
    assert b.net_gex == pytest.approx(a.net_gex, rel=1e-9)
    assert m.b76_gamma(spot, 70000, 0.1, 0.5) == pytest.approx(bs_gamma(spot, 70000, 0.1, 0.5), rel=1e-12)


def test_forward_variant_moves_with_basis(chain):
    _, spot, as_of, quotes = chain
    fw = {q.expiry: spot * 1.01 for q in quotes}
    a = m.model_profile(quotes, spot, as_of, m.DealerModel.M0)
    b = m.model_profile(quotes, spot, as_of, m.DealerModel.M0, variant="forward", forwards=fw)
    assert b.net_gex != pytest.approx(a.net_gex, rel=1e-6)
    with pytest.raises(KeyError):
        m.model_profile(quotes, spot, as_of, m.DealerModel.M0, variant="forward", forwards={})


def test_all_short_and_all_long_have_no_regime_and_no_flip(chain):
    _, spot, as_of, quotes = chain
    short = m.model_profile(quotes, spot, as_of, m.DealerModel.M1)
    long = m.model_profile(quotes, spot, as_of, m.DealerModel.M2)
    assert short.net_gex < 0 < long.net_gex
    assert short.abs_gex == pytest.approx(long.abs_gex) == pytest.approx(-short.net_gex)
    for p in (short, long):
        assert p.regime is None and p.gamma_flip is None


def test_m3_uses_only_complete_contracts_and_flips_taker_sign(chain):
    _, spot, as_of, quotes = chain
    q0, q1 = quotes[0], quotes[1]
    k0, k1 = m.quote_key(q0), m.quote_key(q1)
    pos = m.Positioning(taker_net={k0: 10.0, k1: -4.0}, complete=frozenset({k0, k1}))
    p = m.model_profile(quotes, spot, as_of, m.DealerModel.M3, positioning=pos)
    assert p.used == 2 and p.skipped == len(quotes) - 2
    years = (q0.expiry - as_of).total_seconds() / (365 * 24 * 3600)
    g = lambda q: bs_gamma(spot, q.strike, years, q.implied_vol) * spot * spot * 0.01
    assert p.net_gex == pytest.approx(-10 * g(q0) + 4 * g(q1))
    none = m.model_profile(quotes, spot, as_of, m.DealerModel.M3)
    assert none.used == 0 and none.net_gex == 0 and none.gamma_flip is None


def test_m4_sign_from_oi_side(chain):
    _, spot, as_of, quotes = chain
    k = m.quote_key(quotes[2])
    buy = m.model_profile(quotes, spot, as_of, m.DealerModel.M4, positioning=m.Positioning(oi_side={k: 5}))
    sell = m.model_profile(quotes, spot, as_of, m.DealerModel.M4, positioning=m.Positioning(oi_side={k: -5}))
    assert buy.used == 1 and buy.net_gex < 0 < sell.net_gex and buy.net_gex == pytest.approx(-sell.net_gex)


def test_vanna_and_charm_match_finite_differences():
    s, k, t, v = 67000.0, 70000.0, 0.05, 0.55
    h = 1e-5
    dv = (bs_delta(s, k, t, v + h, True) - bs_delta(s, k, t, v - h, True)) / (2 * h)
    assert m.vanna(s, k, t, v) == pytest.approx(dv, rel=1e-5)
    dt = (bs_delta(s, k, t - h, v, True) - bs_delta(s, k, t + h, v, True)) / (2 * h)  # passage of time
    assert m.charm(s, k, t, v) == pytest.approx(dt, rel=1e-4)
    # put delta = call delta - 1, so the same greeks
    dvp = (bs_delta(s, k, t, v + h, False) - bs_delta(s, k, t, v - h, False)) / (2 * h)
    assert dvp == pytest.approx(dv, rel=1e-6)


def test_sensitivity_grid_and_time_decay(chain):
    _, spot, as_of, quotes = chain
    rows = m.sensitivity(quotes, spot, as_of, m.DealerModel.M0)
    assert len(rows) == 2 * len(m.DEFAULT_SHIFTS)
    base = next(r for r in rows if r["days"] == 0 and r["shift"] == 0)
    assert base["net_gex"] == pytest.approx(m.model_profile(quotes, spot, as_of, m.DealerModel.M0).net_gex)
    later = m.model_profile(quotes, spot, as_of + timedelta(days=30), m.DealerModel.M0)
    assert later.used < len(quotes)  # expired contracts drop out


def test_flip_nearest_to_spot_is_reported(chain):
    _, spot, as_of, quotes = chain
    p = m.model_profile(quotes, spot, as_of, m.DealerModel.M0)
    grid = [spot * (1 + m.FLIP_STEP * i) for i in range(-40, 41)]
    vals = [m.model_profile(quotes, s, as_of, m.DealerModel.M0).net_gex for s in grid]
    crossings = [a for a, (v0, v1) in zip(grid, itertools.pairwise(vals), strict=False) if (v0 < 0) != (v1 < 0)]
    assert crossings and abs(p.gamma_flip - spot) <= min(abs(c - spot) for c in crossings) + spot * m.FLIP_STEP


def test_m3_zero_net_flow_is_skipped(chain):
    _, spot, as_of, quotes = chain
    k = m.quote_key(quotes[0])
    p = m.model_profile(quotes, spot, as_of, m.DealerModel.M3,
                        positioning=m.Positioning(taker_net={k: 0.0}, complete=frozenset({k})))
    assert p.used == 0


def test_forward_vanna_uses_forward_dollars(chain):
    _, spot, as_of, quotes = chain
    fw = {q.expiry: spot * 1.05 for q in quotes}
    a = m.model_profile(quotes, spot, as_of, m.DealerModel.M2, variant="forward", forwards=fw)
    q0 = [q for q in quotes if (q.expiry - as_of).total_seconds() > 0]
    yrs = lambda q: (q.expiry - as_of).total_seconds() / m.SECONDS_PER_YEAR
    want = sum(q.open_interest * m.vanna(fw[q.expiry], q.strike, yrs(q), q.implied_vol) * fw[q.expiry] * 0.01 for q in q0)
    assert a.vanna_exposure == pytest.approx(want)


def test_assumption_independent_rule():
    D = m.DealerModel
    ok = {D.M0: 0.3, D.M3: 0.1, D.M4: 0.2}
    assert m.assumption_independent(ok, {D.M1: 0.5, D.M2: 0.4})
    assert not m.assumption_independent({**ok, D.M4: -0.2}, {D.M1: 0.5, D.M2: 0.4})
    assert not m.assumption_independent(ok, {D.M1: 0.5, D.M2: -0.4})
    assert not m.assumption_independent({D.M0: 0.3, D.M3: 0.1}, {D.M1: 0.5, D.M2: 0.4})  # M4 missing


def test_input_checks(chain):
    _, spot, as_of, quotes = chain
    with pytest.raises(ValueError):
        m.model_profile(quotes, -1, as_of, m.DealerModel.M0)
    with pytest.raises(ValueError):
        m.model_profile(quotes, spot, as_of.replace(tzinfo=None), m.DealerModel.M0)
    with pytest.raises(ValueError):
        m.model_profile(quotes, spot, as_of, m.DealerModel.M0, variant="other")
