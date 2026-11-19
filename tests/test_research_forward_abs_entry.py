"""R-ABS-2: sell absorption at a zone -> LONG, held until the next buy absorption; causal and append-only."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.research_lab.forward import abs_entry
from src.research_lab.orderflow_ml.bars import E8, MINUTE_MS, DayProfile, MinuteBar

DAY1 = date(2026, 11, 20)


def ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def bar(t: int, o: float, h: float, l: float, c: float, buy: float = 0.5, sell: float = 0.5) -> MinuteBar:
    e = lambda x: round(x * E8)
    return MinuteBar(t, 10, 5, e(buy), e(sell), e(0.1), 0, 0, 0, e(o), e(c), e(h), e(l), t + 30_000)


def flat_day(day: date, price: float = 64_500.0, low: float | None = None) -> list[MinuteBar]:
    start = ms(day)
    out = []
    for m in range(1440):
        p = price + (5 if m % 2 else -5)
        out.append(bar(start + m * MINUTE_MS, p, p + 10, (low if (low and m == 600) else p - 10), p))
    return out


def scenario(exit_absorption: bool = True) -> list[MinuteBar]:
    """Day 3: drop into the prior-day low 64 000 with heavy selling that is absorbed, then a run up."""
    start = ms(DAY1 + timedelta(days=2))
    bars = flat_day(DAY1 + timedelta(days=2))[:600]
    t = start + 600 * MINUTE_MS
    # absorption window 10:00-10:05: sells hammer 64 000, price closes back at 64 120
    prices = [(64_050, 64_060, 64_001, 64_020), (64_020, 64_040, 64_002, 64_030), (64_030, 64_080, 64_010, 64_070),
              (64_070, 64_110, 64_050, 64_100), (64_100, 64_130, 64_080, 64_120)]
    for k, (o, h, l, c) in enumerate(prices):
        bars.append(bar(t + k * MINUTE_MS, o, h, l, c, buy=1.0, sell=6.0))
    t += 5 * MINUTE_MS
    # trigger: close above 64 120; then a steady climb to ~65 000
    price = 64_120.0
    for k in range(120):
        price += 7.5
        low = 64_100.0 if k == 1 else price - 10   # minute 2: retest of the trigger level fills the limit
        bars.append(bar(t + k * MINUTE_MS, price - 7.5, price + 3, low, price))
    t += 120 * MINUTE_MS
    if exit_absorption:
        # buy absorption at the top (aligned window): buyers hammer, price closes lower
        top = [(price, price + 120, price - 5, price + 100), (price + 100, price + 150, price + 60, price + 80),
               (price + 80, price + 140, price + 20, price + 30), (price + 30, price + 60, price - 5, price + 10),
               (price + 10, price + 30, price - 10, price)]
        for k, (o, h, l, c) in enumerate(top):
            bars.append(bar(t + k * MINUTE_MS, o, h, l, c, buy=6.0, sell=1.0))
        t += 5 * MINUTE_MS
    for k in range(30):
        bars.append(bar(t + k * MINUTE_MS, price, price + 5, price - 5, price))
    return bars


def days(today_bars: list[MinuteBar]):
    return [(DAY1, flat_day(DAY1), None), (DAY1 + timedelta(days=1), flat_day(DAY1 + timedelta(days=1), low=64_000.0), None),
            (DAY1 + timedelta(days=2), today_bars, None)]


STARTED = ms(DAY1 + timedelta(days=2))


def test_long_on_sell_absorption_exits_on_counter_absorption():
    out = abs_entry.simulate(days(scenario()), STARTED)
    assert len(out["trades"]) == 1 and out["open"] is None
    trade = out["trades"][0]
    assert trade["direction"] == "LONG"
    assert trade["zone"]["name"] == "VT Tief"
    assert trade["ziel_1_erreicht"] is True and trade["exit_reason"] == "Ziel 3R"   # Uzi 19.11.: 2-3 R
    assert 2.3 < trade["net_r"] < 2.5    # half at +2 R, half at +3 R, minus costs
    assert trade["breakeven"] is True
    assert trade["stop_start"] < 64_001  # behind the wick ...
    assert trade["stop_start"] <= trade["fill"] * 0.995 + 0.01   # ... and at least 0.5 % away (Uzi "go Stop")
    assert trade["fill"] == 64_120.0 and trade["entry_fee"] == 0.0002   # limit at the trigger level, maker
    assert trade["kostenblockiert"] is False
    absorbed = [e for e in out["events"] if e["side"] == "VERKAUF"]
    assert absorbed and absorbed[0]["vol_ratio"] >= 3 and absorbed[0]["delta_share"] <= -0.25


def test_without_counter_absorption_the_trade_stays_open():
    out = abs_entry.simulate(days(scenario(exit_absorption=False)), STARTED)
    assert out["trades"] == [] and out["open"]["direction"] == "LONG"


def test_no_look_ahead_cutting_the_future_does_not_change_the_past():
    full = scenario()
    cut = full[: 600 + 5 + 3]   # three minutes after the absorption window
    early = abs_entry.simulate(days(cut), STARTED)
    late = abs_entry.simulate(days(full), STARTED)
    assert early["events"][0] == {**late["events"][0], "ergebnis": early["events"][0]["ergebnis"],
                                  "nachlauf": early["events"][0]["nachlauf"]}   # the follow-up is measured later
    assert early["open"]["fill"] == late["trades"][0]["fill"]


def test_events_before_start_do_not_count():
    out = abs_entry.simulate(days(scenario()), STARTED + 86_400_000)
    assert out["trades"] == [] and out["events"] == []


def test_without_zone_no_entry():
    bars = scenario()
    far = [(d, b, p) for d, b, p in days(bars)]
    far[1] = (far[1][0], flat_day(far[1][0]), None)   # prior day never touched 64 000
    far[0] = (far[0][0], flat_day(far[0][0]), None)
    out = abs_entry.simulate(far, STARTED)
    assert out["trades"] == []
    assert any(e["ergebnis"] == "ohne Zone" for e in out["events"])


def test_profile_levels_value_area():
    width = 100 * E8
    entries = tuple((0, b, v * E8, 0) for b, v in ((640, 1), (641, 5), (642, 10), (643, 4), (644, 1)))
    lv = abs_entry.profile_levels(DayProfile(0, width, entries))
    assert lv["VT POC"] == pytest.approx(64_250)
    assert lv["VT VAL"] == pytest.approx(64_100) and lv["VT VAH"] == pytest.approx(64_300)


def test_step_appends_and_keeps_closed_trades(tmp_path):
    data = {d: (b, p) for d, b, p in days(scenario())}
    today = DAY1 + timedelta(days=3)
    now = datetime.fromtimestamp(STARTED / 1000, tz=timezone.utc)
    out = abs_entry.step(tmp_path, lambda d: data.get(d), today, now=now)
    assert out["trades"] == 1 and out["fehlender_tag"] is None
    first = abs_entry.status(tmp_path)
    again = abs_entry.step(tmp_path, lambda d: data.get(d), today, now=now + timedelta(minutes=5))
    assert again["trades"] == 1 and again["abweichungen"] == 0
    assert first["auswertung"]["urteil"] == "NOCH_NICHT_BEURTEILBAR"


def test_step_refuses_changed_parameters(tmp_path):
    data = {d: (b, p) for d, b, p in days(scenario())}
    now = datetime.fromtimestamp(STARTED / 1000, tz=timezone.utc)
    abs_entry.step(tmp_path, lambda d: data.get(d), DAY1 + timedelta(days=3), now=now)
    with pytest.raises(RuntimeError):
        abs_entry.step(tmp_path, lambda d: data.get(d), DAY1 + timedelta(days=3), now=now,
                       p=abs_entry.Params(vol_factor=4.0))


def test_limit_not_filled_without_retest():
    bars = scenario()
    for i, b in enumerate(bars):   # remove the retest minute
        if b.low_price_e8 == round(64_100.0 * E8):
            bars[i] = bar(b.window_start_ms, b.first_price_e8 / E8, b.high_price_e8 / E8, b.last_price_e8 / E8 - 10, b.last_price_e8 / E8)
    out = abs_entry.simulate(days(bars), STARTED)
    assert out["trades"] == [] and out["open"] is None
    assert any(e["ergebnis"] == "Limit nicht gefüllt" for e in out["events"])


def test_verdict_rule():
    win = [{"closed_at": "x", "net_r": 0.5, "exit_reason": "Gegen-Absorption", "ref_fix": {"net_r": 1.0}}] * 30
    assert abs_entry.evaluate(win)["urteil"] == "BESTANDEN"
    flat = [{"closed_at": "x", "net_r": v, "exit_reason": "Stop", "ref_fix": {}} for v in [1.0, -1.0] * 15]
    assert abs_entry.evaluate(flat)["urteil"] == "NICHT_BESTANDEN"
    costly = [{"closed_at": "x", "net_r": 0.5, "exit_reason": "Stop", "kostenblockiert": True, "ref_fix": {}}] * 30
    assert abs_entry.evaluate(costly)["urteil"] == "NOCH_NICHT_BEURTEILBAR"


def test_comparison_next_level_is_recorded_but_not_the_rule():
    out = abs_entry.simulate(days(scenario()), STARTED)
    trade = out["trades"][0]
    assert "ref_level" in trade and trade["exit_reason"] == "Ziel 3R"
    lvl = trade["ref_level"]
    assert lvl["target"] is None or lvl["target"] > trade["fill"]


def test_ref_level_picks_nearest_zone_in_trade_direction():
    assert abs_entry._ref_level(True, 100.0, 2.0, [95.0, 104.0, 110.0]) == {"target": 104.0, "target_r": 2.0}
    assert abs_entry._ref_level(False, 100.0, 2.0, [95.0, 97.0, 104.0]) == {"target": 97.0, "target_r": 1.5}
    assert abs_entry._ref_level(True, 100.0, 2.0, [90.0]) == {"target": None, "target_r": None}


def test_comparison_rows_in_verdict_and_old_trades_unchanged():
    t = {"closed_at": "x", "net_r": 0.5, "exit_reason": "Stop", "ref_fix": {},
         "ref_level": {"target": 1.0, "target_r": 2.5, "net_r": 1.2}}
    short = {**t, "ref_level": {"target": 1.0, "target_r": 0.8, "net_r": 0.6}}
    out = abs_entry.evaluate([t, short])
    assert out["vergleich_naechstes_level"]["n"] == 2
    assert out["vergleich_naechstes_level_ab_2r"]["n"] == 1
    assert out["urteil"] == "NOCH_NICHT_BEURTEILBAR"
    old = {"id": "L-1", "closed_at": "x", "net_r": 0.5, "hash": "h"}
    kept, dev = abs_entry.chain([old], [{"id": "L-1", "closed_at": "x", "net_r": 0.5, "ref_level": {"target": None}}])
    assert dev == [] and kept == [old]


def test_counter_absorption_before_the_target_still_ends_the_trade():
    out = abs_entry.simulate(days(scenario()), STARTED, abs_entry.Params(target_r_1=5.0, target_r_2=6.0))
    trade = out["trades"][0]
    assert trade["exit_reason"] == "Gegen-Absorption" and trade["ziel_1_erreicht"] is False and trade["net_r"] > 1.0


def test_chart_zone_decides_when_a_snapshot_exists():
    zone = {"low": 63_950.0, "high": 64_020.0, "mid": 63_985.0, "weight": 5, "labels": ["1W Tief", "1D VAL"]}
    weak = {**zone, "weight": 2}
    seen = []
    out = abs_entry.simulate(days(scenario()), STARTED, chart=lambda at: seen.append(at) or [zone])
    assert out["trades"][0]["zone"]["quelle"] == "chart" and out["trades"][0]["zone"]["name"].startswith("TIM-Chart: 1W Tief")
    assert seen and all(at % (5 * MINUTE_MS) == 0 for at in seen)
    assert abs_entry.simulate(days(scenario()), STARTED, chart=lambda at: [weak])["trades"] == []   # own zone does not rescue
    assert abs_entry.simulate(days(scenario()), STARTED, chart=lambda at: None)["trades"][0]["zone"]["quelle"] == "eigen"


def test_follow_up_measures_piercing_and_second_test():
    bars = scenario(exit_absorption=False)
    t = bars[-1].window_start_ms + MINUTE_MS
    for k in range(10):   # back to the absorbed low with little volume, 4 dollars through it, closing above
        bars.append(bar(t + k * MINUTE_MS, 64_010, 64_030, 63_997 if k == 7 else 64_005, 64_020, buy=0.2, sell=0.2))
    for k in range(10, 260):
        bars.append(bar(t + k * MINUTE_MS, 64_020, 64_030, 64_010, 64_020))
    out = abs_entry.simulate(days(bars), STARTED)
    follow = out["events"][0]["nachlauf"]
    assert follow["fertig"] is True and follow["ueber_extrem_pct"] == pytest.approx(4 / 64_001 * 100, abs=1e-3)
    assert follow["zweiter_test"]["weniger_volumen"] is True and follow["zweiter_test"]["gehalten"] is True
    stats = abs_entry.stop_messung(out["events"])
    assert stats["ereignisse"] == 1 and stats["zweiter_test_weniger_volumen"] == 1
