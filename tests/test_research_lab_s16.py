"""S16: past-only deciles, declustering, gaps, design effect and a reproducible bootstrap."""
from __future__ import annotations

from src.research_lab.studies import s16
from src.research_lab.studies.s16 import DAY, HOUR, Term

START = s16._ms(2021, 1)


def _candles(start: int, hours: int, price: float = 100.0) -> dict:
    return {start + h * HOUR: (price, price * 0.99, price) for h in range(hours)}


def _funding(days: int, spike_at: int | None = None) -> list[tuple[int, float]]:
    rows = [(START + i * 8 * HOUR, 0.0001 + (i % 7) * 1e-6) for i in range(days * 3)]
    if spike_at is not None:
        rows[spike_at] = (rows[spike_at][0], 0.01)
    return rows


def test_decile_uses_only_the_past_and_skips_warmup():
    funding = _funding(120, spike_at=300)
    terms, gaps = s16.build_terms("BTCUSDT", funding, _candles(START, 125 * 24))
    assert gaps == 0 and all(t.time >= START + s16.WARMUP for t in terms)
    spike = next(t for t in terms if t.time == funding[300][0])
    assert spike.group == "oben"
    after = next(t for t in terms if t.time == funding[301][0])
    assert after.group != "oben"  # the spike is in the past window now and raises the upper cut
    assert spike.ret == 0 and round(spike.dd, 6) == -0.01


def test_missing_candle_drops_the_term():
    candles = _candles(START, 125 * 24)
    del candles[START + 100 * DAY + 5 * HOUR]
    _, gaps = s16.build_terms("BTCUSDT", _funding(120), candles)
    assert gaps >= 1


def test_decluster_keeps_one_event_per_24h_per_instrument():
    terms = [Term(sym, START + h * 8 * HOUR, "training", 0, 0, "oben") for sym in ("BTCUSDT", "ETHUSDT") for h in range(6)]
    kept = s16.decluster(terms, "oben")
    assert len(kept) == 4 and {t.time for t in kept} == {START, START + DAY}


def test_design_effect_is_one_for_independent_singletons_and_grows_with_clusters():
    assert s16.design_effect([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
    assert s16.design_effect([1, 1, 5, 5], [1, 1, 2, 2]) == 1.5


def test_bootstrap_is_reproducible_with_the_fixed_seed():
    all_terms = [Term("BTCUSDT", START + i * 8 * HOUR, "training", (i % 5) / 100, -(i % 3) / 100, None) for i in range(300)]
    events = {"oben": all_terms[::7], "unten": all_terms[3::11]}
    a = s16.bootstrap(all_terms, events, draws=200)
    b = s16.bootstrap(all_terms, events, draws=200)
    assert a == b and set(a) == {"oben/rendite_24h", "oben/rueckschlag_max", "unten/rendite_24h", "unten/rueckschlag_max"}
    assert all(0 < v["p"] <= 1 for v in a.values())
