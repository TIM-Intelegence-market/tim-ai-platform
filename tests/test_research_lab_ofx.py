"""OFX: holdout release of the S8 store (Uzi 10.11.2026) and the search loop."""
from __future__ import annotations

from datetime import date

import pytest

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.orderflow_ml.store import OFX_RELEASE, MinuteBarStore, guard


def test_holdout_stays_locked_without_release():
    with pytest.raises(HoldoutLocked):
        guard(date(2025, 1, 1))
    with pytest.raises(HoldoutLocked):
        guard(date(2025, 6, 1), "irgendwas")
    guard(date(2024, 12, 31))


def test_release_opens_holdout_up_to_yesterday_only():
    guard(date(2025, 1, 1), OFX_RELEASE, today=date(2026, 11, 10))
    guard(date(2026, 11, 9), OFX_RELEASE, today=date(2026, 11, 10))
    with pytest.raises(HoldoutLocked):
        guard(date(2026, 11, 10), OFX_RELEASE, today=date(2026, 11, 10))


def test_store_rejects_unknown_release_and_plain_store_stays_locked(tmp_path):
    with pytest.raises(ValueError):
        MinuteBarStore(tmp_path, release="OFX")
    with pytest.raises(HoldoutLocked):
        MinuteBarStore(tmp_path).load(date(2025, 3, 1))
    with pytest.raises(FileNotFoundError):
        MinuteBarStore(tmp_path, release=OFX_RELEASE).load(date(2025, 3, 1))


# -- search loop ---------------------------------------------------------------------------------------------------
import json
import random
from datetime import datetime, timedelta, timezone

from src.research_lab.of2.backtest import Trade
from src.research_lab.of2.models import MARKET, Signal
from src.research_lab.ofx.loop import run_loop
from src.research_lab.ofx.sieve import (
    apply_filter,
    basic_pass,
    metrics,
    neighbours_pass,
    t_threshold,
)
from src.research_lab.ofx.space import (
    BASE_CONFIG,
    ENGINE_SPACE,
    TradeFilter,
    base_values,
    engine_config,
    neighbours,
    sample_filter,
)


def _ms(y, m, d, h=8, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def _trade(sig_ms, net, *, model="M1", session="LONDON", regime="NEUTRAL", confirmed=True, hold=60):
    s = Signal(model, 1, sig_ms, MARKET, None, sig_ms + 60_000, 99.0, 102.0, "VAL", 100.0, confirmed, session, regime, tf=30)
    fill = sig_ms + 60_000
    return Trade(s, fill, 100.0, fill + hold * 60_000, 100.0 + net, "X", net, 0.0, 0.0, 0.0, 0.0)


def test_base_values_are_of2_one_and_in_the_space():
    vals = base_values()
    for name, value in vals.items():
        assert value in ENGINE_SPACE[name], name
    assert BASE_CONFIG.training_end == "2023-12-31" and BASE_CONFIG.last_day == "2024-12-31"
    assert engine_config(vals) == BASE_CONFIG
    with pytest.raises(KeyError):
        engine_config({"fee": 0.0})
    for n in neighbours(vals):
        assert sum(n[k] != vals[k] for k in vals) == 1


def test_filter_only_confirmed_and_selected():
    t = [_trade(_ms(2021, 3, 1), 1.0), _trade(_ms(2021, 3, 2), 1.0, confirmed=False),
         _trade(_ms(2021, 3, 3), 1.0, model="M2"), _trade(_ms(2021, 3, 4), 1.0, session="NY"),
         _trade(_ms(2021, 3, 6), 1.0)]  # Saturday
    assert len(apply_filter(t, TradeFilter())) == 4
    assert len(apply_filter(t, TradeFilter(models=("M1",)))) == 3
    assert len(apply_filter(t, TradeFilter(sessions=("LONDON",)))) == 3
    assert len(apply_filter(t, TradeFilter(skip_weekend=True))) == 3


def test_day_rules_have_no_look_ahead():
    day = (2021, 3, 1)
    a = _trade(_ms(*day, 8, 0), -1.0, hold=30)        # loses, exit 08:31
    b = _trade(_ms(*day, 8, 10), 2.0, hold=5)         # fills 08:11, before the loss is known
    c = _trade(_ms(*day, 9, 0), 2.0, hold=5)          # fills after the loss
    kept = apply_filter([c, b, a], TradeFilter(stop_after_losses_day=1))
    assert [t.signal.signal_ms for t in kept] == [a.signal.signal_ms, b.signal.signal_ms]
    assert len(apply_filter([a, b, c], TradeFilter(max_trades_day=2))) == 2


def test_metrics_and_sieve():
    trades = [_trade(_ms(y, m, 1), x) for y in (2020, 2021, 2022, 2023) for m, x in zip(range(1, 13), [1.0, -0.5] * 6)] * 3
    m = metrics(trades)
    assert m["n"] == 144 and m["mean"] == 0.25 and m["max_dd"] == 0.5 and set(m["years"]) == {"2020", "2021", "2022", "2023"}
    ok, why = basic_pass(m, 1)
    assert ok, why
    ok, why = basic_pass(m, 10**9)  # with enough configurations tried the same result no longer counts
    assert not ok and why == ["mehrfachtest"]
    m2 = metrics([t for t in trades if datetime.fromtimestamp(t.signal.signal_ms / 1000, tz=timezone.utc).year != 2022])
    assert "jahr_nicht_im_plus" in basic_pass(m2, 1)[1] and "zu_wenig_trades" in basic_pass(m2, 1)[1]
    assert t_threshold(1, 0.05) < t_threshold(1000, 0.05)
    assert neighbours_pass(0.2, [0.1, 0.15]) and not neighbours_pass(0.2, [0.09]) and not neighbours_pass(0.2, [])


def test_noise_never_passes_the_sieve():
    rng = random.Random(7)
    passed = 0
    for k in range(200):
        trades = [_trade(_ms(2020 + i % 4, 1 + i % 12, 1 + i % 28, i % 24), rng.choice([2.0, -1.0, -1.0]))
                  for i in range(300)]
        passed += basic_pass(metrics(trades), k + 1)[0]
    assert passed == 0


def _edge_trades(values):
    """Fake engine: a real edge that shrinks smoothly with relvol, so neighbours stay stable."""
    rng = random.Random(values["relvol_min"])
    edge = 0.6 - 0.05 * values["relvol_min"]
    return [_trade(_ms(2020 + i % 4, 1 + i % 12, 1 + i % 28, i % 24), rng.gauss(edge, 1.0)) for i in range(800)]


def test_loop_finds_a_stable_edge_resumes_and_stops(tmp_path):
    calls = []

    def engine(values):
        calls.append(values)
        return _edge_trades(values)

    state = run_loop(tmp_path, engine, lambda trades, cfg: 0.001, configs=2, filters_per_config=5, log=lambda s: None)
    assert state["configs_tried"] == 2 and state["kandidaten"] >= 1
    rows = [json.loads(x) for x in (tmp_path / "kandidaten.jsonl").read_text().splitlines()]
    assert any(r["status"] == "KANDIDAT" and r["nachbarn_ok"] for r in rows)
    assert calls[0] == base_values()
    state = run_loop(tmp_path, engine, lambda trades, cfg: 0.5, configs=1, filters_per_config=5, log=lambda s: None)
    assert state["configs_tried"] == 3
    (tmp_path / "STOP").write_text("")
    assert run_loop(tmp_path, engine, lambda t, c: 0.5, configs=5, log=lambda s: None)["configs_tried"] == 3
    with pytest.raises(SystemExit):
        run_loop(tmp_path, engine, lambda t, c: 0.5, configs=1, seed=1, log=lambda s: None)


def test_random_p_too_high_blocks_the_candidate(tmp_path):
    state = run_loop(tmp_path, _edge_trades, lambda trades, cfg: 0.2, configs=1, filters_per_config=3, log=lambda s: None)
    assert state["kandidaten"] == 0


# -- direction filter: day / week / month (Uzi 10.11.) ----------------------------------------------
def _closes(first: date, values: list[float]) -> dict:
    return {first + timedelta(days=i): v for i, v in enumerate(values)}


def test_trend_reads_completed_periods_only():
    from src.research_lab.ofx.trend import Trend
    first = date(2020, 1, 1)
    rising = Trend(_closes(first, [100.0 + i for i in range(200)]))
    assert rising.state(first + timedelta(days=19), "d") == 0      # 19 completed days: too short
    assert rising.state(first + timedelta(days=20), "d") == 1
    assert rising.state(date(2020, 3, 31), "m") == 0                # Jan, Feb complete, March still running
    assert rising.state(date(2020, 4, 1), "m") == 1
    assert rising.state(date(2020, 3, 16), "w") == 1                # 10 full weeks after the partial first one
    # the future does not matter: change every close from the signal day on, the state stays
    day = date(2020, 5, 13)
    crash = {d: (v if d < day else 1.0) for d, v in _closes(first, [100.0 + i for i in range(200)]).items()}
    for frame in ("d", "w", "m"):
        assert Trend(crash).state(day, frame) == rising.state(day, frame) == 1
    # the running week does not count before it is over: a crash on Monday and Tuesday is invisible on Wednesday
    falling_week = Trend({d: (v if d < date(2020, 5, 11) else 1.0) for d, v in crash.items()})
    assert falling_week.state(day, "w") == 1 and falling_week.state(day, "d") == -1
    assert falling_week.state(date(2020, 5, 18), "w") == -1


def test_direction_filter_with_and_against_and_unknown():
    from src.research_lab.ofx.trend import Trend
    trend = Trend(_closes(date(2020, 1, 1), [100.0 + i for i in range(200)]))
    long_late = _trade(_ms(2020, 5, 13), 1.0)
    long_early = _trade(_ms(2020, 1, 5), 1.0)   # no history yet: unknown, dropped by every direction rule
    trades = [long_late, long_early]
    assert len(apply_filter(trades, TradeFilter(), trend)) == 2
    assert apply_filter(trades, TradeFilter(trend_d="MIT", trend_w="MIT", trend_m="MIT"), trend) == [long_late]
    assert apply_filter(trades, TradeFilter(trend_w="GEGEN"), trend) == []
    with pytest.raises(ValueError):
        apply_filter(trades, TradeFilter(trend_d="MIT"))
    assert TradeFilter(trend_w="MIT").key().endswith("|None|MIT|None")


def test_sample_filter_draws_directions_only_with_closes():
    rng_a, rng_b = random.Random(5), random.Random(5)
    plain = [sample_filter(rng_a) for _ in range(50)]
    assert all(f.trend_d is f.trend_w is f.trend_m is None for f in plain)
    with_trend = [sample_filter(rng_b, trend=True) for _ in range(200)]
    assert {f.trend_w for f in with_trend} == {None, "MIT", "GEGEN"}


def test_loop_passes_the_direction_rule_to_the_random_comparator(tmp_path):
    from src.research_lab.ofx.trend import Trend
    trend = Trend(_closes(date(2019, 6, 1), [100.0 + i for i in range(1700)]))
    seen = []

    def rp(trades, cfg, allowed=None):
        seen.append(allowed)
        return 0.001

    run_loop(tmp_path, _edge_trades, rp, configs=3, filters_per_config=40, log=lambda s: None, trend=trend)
    rows = [json.loads(x) for x in (tmp_path / "kandidaten.jsonl").read_text().splitlines()]
    with_rule = [r for r in rows if any(x in ("MIT", "GEGEN") for x in r["filter"].split("|")[-3:])]
    assert len(seen) == len(rows) and sum(a is not None for a in seen) == len(with_rule)
    for a in seen:
        if a is not None:
            assert isinstance(a(_ms(2021, 5, 13), 1), bool)


def test_random_signals_obey_the_selection_rule():
    from src.research_lab.of2.compare import random_signals
    trades = [_trade(_ms(2021, 3, 1 + i), 1.0) for i in range(5)]
    even = lambda ms, direction: (ms // 86_400_000) % 2 == 0
    pseudo = random_signals(trades, date(2021, 1, 1), date(2021, 12, 31), BASE_CONFIG, 20, 7, even)
    assert len(pseudo) == 100 and all((s.signal_ms // 86_400_000) % 2 == 0 for s in pseudo)
    assert random_signals(trades, date(2021, 1, 1), date(2021, 12, 31), BASE_CONFIG, 3, 7) == \
        random_signals(trades, date(2021, 1, 1), date(2021, 12, 31), BASE_CONFIG, 3, 7, None)
