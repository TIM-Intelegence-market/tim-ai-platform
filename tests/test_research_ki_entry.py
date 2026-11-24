"""R-KI-1: zone strength, trigger, answer check, paper play and the append-only log."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.research_lab.ki_entry import decide, deepseek, zones
from src.research_lab.ki_filter.decide import LogError, read_log

T0 = 1_795_400_000 - 1_795_400_000 % 900


def candle(i: int, o: float, h: float, low: float, c: float, closed: bool = True) -> dict:
    return {"time": T0 + i * 900, "open": o, "high": h, "low": low, "close": c, "volume": 100.0, "closed": closed}


def model(candles: list[dict], extra: list[dict] | None = None) -> dict:
    drawings = [
        {"group": "gamma", "label": "Opt Put Wall", "price": 60000.0},
        {"group": "gamma", "label": "Opt Put-OI-Wand", "price": 60000.0},
        {"group": "gamma_ob", "label": "Gamma-Zone Put Wall", "price": 60000.0, "band": [59950.0, 60050.0]},
        {"group": "week", "label": "1W VAL", "price": 59980.0},
        {"group": "day", "label": "1D VAH", "price": 61500.0},
        {"group": "trend", "label": "30m Trend", "price": 60500.0},
        {"group": "day", "label": "alt", "price": 60400.0, "finished": True},
        {"group": "structure", "label": "30m BOS ↓", "price": 60700.0, "finished": True, "start": "2026-11-20T18:15:00+00:00", "end": "2026-11-20T19:00:00+00:00"},
    ] + (extra or [])
    bars = [{"time": c["time"], "delta": -20.0, "levels": [[60600.0, 5.0, 5.0], [60700.0, 1.0, 1.0]]} for c in candles]
    return {"candles": candles, "drawings": drawings, "footprint": {"step": 10.0, "bars": bars},
            "bubbles": {"items": [{"time": candles[-1]["time"] + 60, "price": 60010.0, "quantity": 210.0, "side": -1, "venue": "binance"},
                                  {"time": candles[-1]["time"] + 60, "price": 60010.0, "quantity": 5.0, "side": 1, "venue": "binance"}]},
            "funding": {"points": [[T0, 0.01, 0.01]]}, "oi": {"points": []}}


def falling_into_zone(n: int = 30) -> list[dict]:
    out = [candle(i, 60800 - i * 20, 60810 - i * 20, 60770 - i * 20, 60780 - i * 20) for i in range(n - 1)]
    out.append(candle(n - 1, 60230, 60240, 60020, 60100))   # wick into the 60k zone
    return out


def now_after(candles: list[dict]) -> float:
    return candles[-1]["time"] + 900 + 60


def test_overlapping_marks_make_one_strong_zone():
    c = falling_into_zone()
    found = zones.build(model(c), 60100.0, c[:-1])
    top = found[0]
    assert top["low"] <= 59950 and top["high"] >= 60050
    assert top["strength"] == pytest.approx(3 + 2 + 4 + 2)       # Put Wall, OI wall, gamma zone, week VAL
    assert "Opt Put Wall" in top["sources"] and top["strength"] >= zones.STRONG
    assert all("Trend" not in s and s != "alt" for z in found for s in z["sources"])   # trend lines and history left out
    assert any("meistgehandelter Preis" in z["sources"] for z in found)


def test_rejections_add_strength():
    c = falling_into_zone()
    c[5] = candle(5, 60200, 60210, 60030, 60150)     # earlier wick into the zone, closed above
    found = zones.build(model(c), 60100.0, c[:-1])
    assert found[0]["rejections"] == 1 and found[0]["strength"] == pytest.approx(11.5)


def test_trigger_needs_touch_fresh_candle_and_no_open_trade():
    c = falling_into_zone()
    hit = decide.trigger(model(c), [], now_after(c))
    assert hit["zone"]["strength"] >= zones.STRONG
    assert decide.trigger(model(c), [], now_after(c) + 600)["why"] == "Kerzen veraltet"
    running = c[:-1] + [dict(c[-1], closed=False)]
    assert decide.trigger(model(running), [], now_after(c))["why"] != "Kerze schon gefragt"   # running candle never used
    away = c[:-1] + [candle(29, 60300, 60320, 60250, 60280)]
    assert decide.trigger(model(away), [], now_after(away))["why"] == "keine starke Zone berührt"
    busy = [{"kind": "decision", "id": "x", "action": "LONG", "candle": 1}]
    assert decide.trigger(model(c), busy, now_after(c))["why"] == "Papier-Trade offen"


def test_check_answer_rejects_impossible_plans():
    ok = {"aktion": "LONG", "einstieg": 60100, "stop": 59900, "ziel": 60500, "vertrauen": 0.6, "grund": "hält"}
    assert decide.check_answer(ok, 60100)[4] is None
    assert "falschen Seite" in decide.check_answer({**ok, "stop": 60200}, 60100)[4]
    assert "Ziel kleiner" in decide.check_answer({**ok, "ziel": 60300}, 60100)[4]
    assert "Einstieg" in decide.check_answer({**ok, "einstieg": 60500, "stop": 60300, "ziel": 61000}, 60100)[4]
    assert "Stop" in decide.check_answer({**ok, "stop": 60090, "ziel": 60200}, 60100)[4]
    assert decide.check_answer({"aktion": "NICHTS", "einstieg": 0, "stop": 0, "ziel": 0, "vertrauen": 0.2, "grund": "unklar"}, 60100)[0] == "NICHTS"
    with pytest.raises(ValueError):
        decide.check_answer({"aktion": "KAUFEN", "vertrauen": 0.5}, 60100)


def test_play_limit_fill_stop_first_target_and_costs():
    d = {"action": "LONG", "candle": T0, "plan": {"entry": 60000.0, "stop": 59800.0, "target": 60400.0}}
    asked = candle(1, 60100, 60150, 59000, 60100)          # the AI answered during this candle: never used
    assert decide.play(d, [asked, candle(2, 60100, 60150, 60050, 60100)]) is None          # window still open
    unfilled = [asked] + [candle(i, 60100, 60150, 60050, 60100) for i in range(2, 6)]
    assert decide.play(d, unfilled)["outcome"] == "nicht gefüllt"
    both = [asked, candle(2, 60100, 60150, 59990, 60050), candle(3, 60050, 60450, 59750, 60100)]
    assert decide.play(d, both)["outcome"] == "Stop"                                         # both in one candle: stop
    win = [asked, candle(2, 60100, 60150, 59990, 60050), candle(3, 60050, 60450, 59950, 60400)]
    result = decide.play(d, win)
    assert result["outcome"] == "Ziel" and result["r_gross"] == pytest.approx(2.0)
    assert result["r"] == pytest.approx(2.0 - 60000 * decide.COST_PCT / 100 / 200, abs=1e-3)
    gap = [asked, candle(2, 59900, 59950, 59850, 59900), candle(3, 59900, 60450, 59850, 60400)]
    assert decide.play(d, gap)["fill"] == 59900.0                                          # opened below the limit
    short = {"action": "SHORT", "candle": T0, "plan": {"entry": 60000.0, "stop": 60200.0, "target": 59600.0}}
    assert decide.play(short, [asked, candle(2, 59950, 60010, 59900, 59950), candle(3, 59950, 60000, 59550, 59600)])["outcome"] == "Ziel"


def test_gap_beyond_stop_is_a_loss_never_a_gain():
    d = {"action": "LONG", "candle": T0, "plan": {"entry": 60000.0, "stop": 59800.0, "target": 60400.0}}
    asked = candle(1, 60100, 60150, 60050, 60100)
    opened_below_stop = decide.play(d, [asked, candle(2, 59700, 59750, 59600, 59650)])
    assert opened_below_stop["outcome"] == "Stop" and opened_below_stop["r"] < 0
    later_gap = decide.play(d, [asked, candle(2, 60050, 60100, 59990, 60000), candle(3, 59600, 59650, 59500, 59550)])
    assert later_gap["outcome"] == "Stop" and later_gap["exit"] == 59600.0 and later_gap["r_gross"] == pytest.approx(-2.0)
    at_stop = decide.play(d, [asked, candle(2, 59800, 59850, 59790, 59800)])                 # fill exactly at the stop
    assert at_stop["outcome"] == "Stop"
    s = {"action": "SHORT", "candle": T0, "plan": {"entry": 60000.0, "stop": 60200.0, "target": 59600.0}}
    up = decide.play(s, [asked, candle(2, 60050, 60100, 59990, 60000), candle(3, 60400, 60450, 60350, 60400)])
    assert up["outcome"] == "Stop" and up["fill"] == 60050.0 and up["r_gross"] == pytest.approx(-1.75)


def test_time_exit_after_hold_bars():
    d = {"action": "LONG", "candle": T0, "plan": {"entry": 60000.0, "stop": 59800.0, "target": 60400.0}}
    bars = [candle(1, 60100, 60150, 60050, 60100), candle(2, 60050, 60100, 59990, 60000)]
    bars += [candle(i, 60050, 60100, 60000, 60050) for i in range(3, 2 + decide.HOLD_BARS)]
    assert decide.play(d, bars[:-1]) is None
    result = decide.play(d, bars)
    assert result["outcome"] == "Zeit" and result["exit"] == 60050.0


def test_open_trade_without_candles_is_given_up(tmp_path: Path):
    log = tmp_path / "ki.jsonl"
    c = falling_into_zone()
    decide.run(model(c), log, lambda p: {"aktion": "LONG", "einstieg": 60100, "stop": 59880, "ziel": 60560,
                                          "vertrauen": 0.6, "grund": "x"}, "test", now=now_after(c))
    later = now_after(c) + decide.GIVE_UP_S + 60
    out = decide.run(model(c), log, lambda p: None, "test", now=later)
    assert out["results"][0]["outcome"] == "Daten fehlen"
    assert decide.open_trade(read_log(log)) is None and decide.report(read_log(log))["trades"] == 0


def test_only_local_dashboard():
    from src.research_lab.ki_entry.__main__ import main
    with pytest.raises(SystemExit):
        main(["run", "--api", "http://example.com/api/chart/live"])


def test_run_writes_decision_before_result_and_never_twice(tmp_path: Path):
    log = tmp_path / "ki.jsonl"
    c = falling_into_zone()
    prompts: list[str] = []

    def ask(prompt: str):
        prompts.append(prompt)
        return {"aktion": "LONG", "einstieg": 60100, "stop": 59880, "ziel": 60560, "vertrauen": 0.6, "grund": "Verkäufer absorbiert"}

    out = decide.run(model(c), log, ask, "test", now=now_after(c))
    assert out["decision"]["action"] == "LONG" and len(prompts) == 1
    assert "Opt Put Wall" in prompts[0] and "210.0" in prompts[0] and "von oben" in prompts[0] and "BOS" in prompts[0]
    again = decide.run(model(c), log, ask, "test", now=now_after(c) + 60)
    assert again["decision"] is None and len(prompts) == 1
    later = c + [candle(30, 60100, 60120, 60080, 60100), candle(31, 60100, 60200, 60090, 60150), candle(32, 60150, 60600, 60140, 60550)]
    done = decide.run(model(later), log, ask, "test", now=now_after(later))
    assert done["results"][0]["outcome"] == "Ziel"
    records = read_log(log)
    assert [r["kind"] for r in records][:2] == ["decision", "result"]
    report = decide.report(records)
    assert report["trades"] == 1 and report["sum_r"] > 0


def test_failed_ai_writes_nothing_and_bad_plan_is_ungueltig(tmp_path: Path):
    log = tmp_path / "ki.jsonl"
    c = falling_into_zone()

    def down(prompt: str):
        raise TimeoutError

    assert decide.run(model(c), log, down, "test", now=now_after(c))["failed"] == "TimeoutError"
    assert read_log(log) == []
    bad = decide.run(model(c), log, lambda p: {"aktion": "SHORT", "einstieg": 60100, "stop": 59900, "ziel": 59000,
                                                 "vertrauen": 0.5, "grund": "x"}, "test", now=now_after(c))
    assert bad["decision"]["action"] == "UNGUELTIG" and decide.open_trade(read_log(log)) is None


def test_log_tampering_is_detected(tmp_path: Path):
    log = tmp_path / "ki.jsonl"
    c = falling_into_zone()
    decide.run(model(c), log, lambda p: {"aktion": "NICHTS", "einstieg": 0, "stop": 0, "ziel": 0, "vertrauen": 0.3, "grund": "unklar"},
               "test", now=now_after(c))
    log.write_text(log.read_text().replace("unklar", "klar"))
    with pytest.raises(LogError):
        read_log(log)


def test_zone_cooldown(tmp_path: Path):
    log = tmp_path / "ki.jsonl"
    c = falling_into_zone()
    nothing = lambda p: {"aktion": "NICHTS", "einstieg": 0, "stop": 0, "ziel": 0, "vertrauen": 0.3, "grund": "unklar"}
    decide.run(model(c), log, nothing, "test", now=now_after(c))
    nxt = c + [candle(30, 60100, 60120, 60010, 60050)]
    assert decide.run(model(nxt), log, nothing, "test", now=now_after(nxt))["waiting"] == "Zone kürzlich gefragt"


def test_hermes_opinion_once_public_numbers_only(tmp_path: Path):
    from src.research_lab.ki_entry import hermes
    log = tmp_path / "ki.jsonl"
    c = falling_into_zone()
    decide.run(model(c), log, lambda p: {"aktion": "LONG", "einstieg": 60100, "stop": 59880, "ziel": 60560,
                                          "vertrauen": 0.6, "grund": "Verkäufer absorbiert"}, "test", now=now_after(c))
    asked: list[str] = []

    def ask(text: str):
        asked.append(text)
        return {"ok": True, "answer": "DAFÜR: Zone hält.\nDAGEGEN: Trend fällt.\nURTEIL: DAFÜR", "seconds": 9.0}

    out = hermes.opinions(read_log(log), log, ask, now_after(c) + 30, "t")
    assert out[0]["verdict"] == "DAFÜR" and "LONG, Einstieg 60100" in asked[0] and "Opt Put Wall" in asked[0]
    assert "hash" not in asked[0] and "key" not in asked[0].lower()
    assert hermes.opinions(read_log(log), log, ask, now_after(c) + 60, "t") == [] and len(asked) == 1   # only once
    assert hermes.hermes_summary(read_log(log))["by_verdict"]["DAFÜR"]["n"] == 1


def test_hermes_failure_writes_nothing_and_window_ends(tmp_path: Path):
    from src.research_lab.ki_entry import hermes
    log = tmp_path / "ki.jsonl"
    c = falling_into_zone()
    decide.run(model(c), log, lambda p: {"aktion": "NICHTS", "einstieg": 0, "stop": 0, "ziel": 0, "vertrauen": 0.2, "grund": "unklar"},
               "test", now=now_after(c))
    down = lambda t: {"ok": False, "error": "Keine Antwort"}
    assert hermes.opinions(read_log(log), log, down, now_after(c) + 30, "t")[0]["failed"]
    assert all(r["kind"] != "hermes" for r in read_log(log))
    late = now_after(c) + hermes.OPINION_WINDOW_S + 120
    assert hermes.opinions(read_log(log), log, lambda t: {"ok": True, "answer": "URTEIL: NEUTRAL"}, late, "t") == []


def test_bitunix_paper_account():
    from src.research_lab.ki_entry import hermes
    d = {"id": "a", "kind": "decision", "action": "LONG", "plan": {"entry": 60000.0, "stop": 59800.0, "target": 60400.0}}
    win = {"kind": "result", "decision_id": "a", "outcome": "Ziel", "fill": 60000.0, "exit": 60400.0, "r": 1.9}
    row = hermes.bitunix_fill(d, win)
    assert row["qty_btc"] == pytest.approx(0.05)                         # 10 USDT risk / 200 USD stop
    assert row["notional_usdt"] == pytest.approx(3000.0) and row["leverage"] == 60 and row["allowed"]
    fees = 3000 * 0.0002 + 0.05 * 60400 * 0.0006
    assert row["pnl_usdt"] == pytest.approx(20.0 - fees, abs=1e-3)
    loss = hermes.bitunix_fill(d, {**win, "outcome": "Stop", "exit": 59800.0})
    assert loss["pnl_usdt"] < -10.0                                       # stop slippage and fees on top of 1 %
    assert hermes.bitunix_fill(d, {"outcome": "nicht gefüllt", "r": 0.0}) is None
    account = hermes.bitunix([d, win])
    assert account["trades"] == 1 and account["balance_usdt"] == pytest.approx(1000 + row["pnl_usdt"], abs=1e-3)


def test_session_names_follow_london_and_new_york_clocks():
    day = 1_795_478_400   # 24.11.2026 00:00 UTC (Tuesday, winter time)
    assert decide.session(day + 7 * 3600) == "Asia"
    assert decide.session(day + 8 * 3600) == "London"
    assert decide.session(day + 15 * 3600) == "London+New York"
    assert decide.session(day + 17 * 3600) == "New York"
    assert decide.session(day + 22 * 3600) == "nach New York"


def test_context_shows_london_selloff_and_smart_money():
    day = 1_795_478_400
    asia = [{"time": day + i * 900, "open": 60500, "high": 60600, "low": 60400, "close": 60500, "volume": 10, "closed": True} for i in range(32)]
    london = [{"time": day + 8 * 3600 + i * 900, "open": 60450 - i * 100, "high": 60460 - i * 100, "low": 60300 - i * 100,
               "close": 60350 - i * 100, "volume": 30, "closed": True} for i in range(4)]
    running = {"time": day + 9 * 3600, "open": 60050, "high": 60060, "low": 59000, "close": 59100, "volume": 5, "closed": False}
    cs = asia + london + [running]
    end = day + 9 * 3600
    m = model(cs)
    m["cvd"] = {"spot": [[end - 5 * 3600, 0.0], [end - 4500, -50.0], [end - 900, -150.0], [end, -999.0]],
                "perp": [[end - 5 * 3600, 0.0], [end - 4500, -100.0], [end - 900, -400.0], [end, -9999.0]]}
    m["oi"] = {"points": [[end - 5 * 3600, 100.0], [end - 2 * 3600, 101.0], [end - 3600, 102.0], [end, 500.0]]}
    m["liquidations"] = {"items": [{"time": end - 600, "side": "long", "usd": 2_000_000}, {"time": end + 60, "side": "long", "usd": 9e9}]}
    m["liquidation"] = {"cells": [{"side": "long", "price": 59500.0, "usd": 30e6, "start": end - 86400},
                                  {"side": "short", "price": 61000.0, "usd": 20e6, "start": end - 86400},
                                  {"side": "short", "price": 70000.0, "usd": 90e6, "start": end - 86400}]}
    zone = {"low": 59950.0, "high": 60050.0, "center": 60000.0, "strength": 9.0, "sources": ["Put Wall"], "rejections": 0}
    ctx = decide.build_context(m, zone, end + 60)
    assert ctx["zone"]["schluss"] == "in der Zone"   # close 60050 = zone top
    above = {**zone, "low": 60100.0, "high": 60200.0, "center": 60150.0}
    assert decide.build_context(m, above, end + 60)["zone"]["schluss"] == "unter der Zone (Bruch nach unten)"
    s = ctx["sitzung"]
    assert s["jetzt"] == "London" and s["asia_tief"] == 60400 and s["asia_hoch"] == 60600
    assert s["london"]["eroeffnung"] == 60450 and s["london"]["asia_tief_genommen"] is True and s["london"]["aenderung_pct"] < 0
    assert s["london"]["tief"] == 60000   # the running candle (low 59000) is not seen
    sm = ctx["smart_money"]
    assert sm["cvd_spot_btc"]["1h"] == -100.0 and sm["cvd_perp_btc"]["1h"] == -300.0 and sm["cvd_spot_btc"]["4h"] == -150.0   # last point at ``end`` is the running bar
    assert sm["oi_aenderung_pct"]["1h"] == 0.99 and sm["liquidiert_3h_mio_usd"]["long"] == 2.0
    assert sm["liq_cluster_darunter"] == [{"preis": 59500.0, "mio_usd": 30.0}]
    assert sm["liq_cluster_darueber"] == [{"preis": 61000.0, "mio_usd": 20.0}]   # 70k is more than 3 % away
    assert "Asia-Tief" in decide.build_prompt(ctx) and "Smart Money" in decide.INSTRUCTIONS and "BRICHT" in decide.INSTRUCTIONS
    assert decide.ANSWER_SCHEMA["properties"]["lesart"]["enum"] == ["HAELT", "BRICHT", "UNKLAR"]


def test_new_session_asks_again_at_the_same_zone(tmp_path: Path):
    day = 1_795_478_400
    log = tmp_path / "ki.jsonl"
    nothing = lambda p: {"aktion": "NICHTS", "einstieg": 0, "stop": 0, "ziel": 0, "vertrauen": 0.3, "grund": "unklar"}
    cs = [{"time": day + i * 900, "open": 60800 - i * 20, "high": 60810 - i * 20, "low": 60770 - i * 20, "close": 60780 - i * 20,
           "volume": 100.0, "closed": True} for i in range(30)]
    cs.append({"time": day + 30 * 900, "open": 60230, "high": 60240, "low": 60020, "close": 60100, "volume": 100.0, "closed": True})   # 07:30 UTC Asia
    assert decide.run(model(cs), log, nothing, "test", now=cs[-1]["time"] + 960)["decision"]["action"] == "NICHTS"
    cs.append({"time": day + 31 * 900, "open": 60100, "high": 60120, "low": 60010, "close": 60050, "volume": 100.0, "closed": True})  # still Asia
    assert decide.run(model(cs), log, nothing, "test", now=cs[-1]["time"] + 960)["waiting"] == "Zone kürzlich gefragt"
    cs.append({"time": day + 32 * 900, "open": 60050, "high": 60080, "low": 59990, "close": 60000, "volume": 100.0, "closed": True})  # 08:00 UTC London
    out = decide.run(model(cs), log, lambda p: {**nothing(p), "lesart": "UNKLAR"}, "test", now=cs[-1]["time"] + 960)
    assert out["decision"]["action"] == "NICHTS" and out["decision"]["reading"] == "UNKLAR"
    rep = decide.report(read_log(log))
    assert rep["by_prompt"] == {"ki-einstieg/3": 2} and rep["rule"] == "R-KI-1/0.3-entwurf"


def _reply(action: str, entry: float = 60100.0, stop: float = 59700.0, target: float = 61000.0, key: str = "aktion") -> dict:
    body = f'{{"lesart": "HAELT", "{key}": "{action}", "einstieg": {entry}, "stop": {stop}, "ziel": {target}, "grund": "Zone hält."}}'
    return {"ok": True, "answer": "```json\n" + body + "\n```"}


def test_deepseek_trades_only_when_both_answers_agree(tmp_path: Path):
    c = falling_into_zone()
    replies = iter([_reply("LONG"), _reply("LONG", key="richtung")])
    prompts: list[str] = []

    def ask(text: str) -> dict:
        prompts.append(text)
        return next(replies)

    log = tmp_path / "ds.jsonl"
    out = decide.run(model(c), log, deepseek.decider(ask), deepseek.MODEL_NAME, now=now_after(c), profile=decide.DEEPSEEK_PROFILE)
    assert out["decision"]["action"] == "LONG" and len(prompts) == 2 and "keine Werkzeuge" in prompts[0]
    assert "mindestens 0.5 %" in prompts[0] and "mindestens 2.0-mal" in prompts[0]
    rec = read_log(log)[0]
    assert rec["rule"] == "R-KI-2/0.2-entwurf" and rec["asked"] == ["LONG", "LONG"] and rec["model"] == "deepseek (Hermes)"
    assert "at most 3 trades per day" in rec["rules"]

    swing = iter([_reply("SHORT", 60100, 60500, 59000), _reply("LONG")])
    log2 = tmp_path / "ds2.jsonl"
    out = decide.run(model(c), log2, deepseek.decider(lambda t: next(swing)), "ds", now=now_after(c), profile=decide.DEEPSEEK_PROFILE)
    assert out["decision"]["action"] == "NICHTS" and "uneinig" in out["decision"]["reason"]

    log3 = tmp_path / "ds3.jsonl"
    out = decide.run(model(c), log3, deepseek.decider(lambda t: {"ok": False, "error": "Zeit"}), "ds", now=now_after(c),
                     profile=decide.DEEPSEEK_PROFILE)
    assert out["failed"] == "RuntimeError" and not log3.exists()
    with pytest.raises(ValueError):
        deepseek.parse("kein JSON")


def test_deepseek_guards_stop_target_day_limit_and_pause():
    p = decide.DEEPSEEK_PROFILE
    ok = {"aktion": "LONG", "einstieg": 60000.0, "stop": 59700.0, "ziel": 60600.0, "vertrauen": 0.6, "grund": "x"}
    assert decide.check_answer(ok, 60000.0, p)[4] is None
    assert "Stop" in decide.check_answer({**ok, "stop": 59800.0, "ziel": 61000.0}, 60000.0, p)[4]      # 0.33 % < 0.5 %
    assert "Ziel" in decide.check_answer({**ok, "ziel": 60500.0}, 60000.0, p)[4]                        # 1.67 x < 2 x
    assert decide.check_answer({**ok, "stop": 59800.0, "ziel": 60400.0}, 60000.0)[4] is None            # local profile unchanged
    now = 1_795_478_400 + 12 * 3600

    def dec(i: int, action: str = "LONG") -> dict:
        return {"kind": "decision", "id": f"d{i}", "action": action, "candle_epoch": now - 3600 * (5 - i)}

    def res(i: int, r: float) -> dict:
        return {"kind": "result", "decision_id": f"d{i}", "outcome": "Stop" if r < 0 else "Ziel", "r": r}

    assert decide.day_guard([dec(1), res(1, 2.0), dec(2), res(2, -1.0)], now, p) is None
    assert decide.day_guard([dec(1), res(1, -1.0), dec(2), res(2, -1.0)], now, p) == "Pause nach Verlusten"
    assert decide.day_guard([dec(1), res(1, 1.0), dec(2), res(2, 1.0), dec(3), res(3, 1.0)], now, p) == "Tageslimit erreicht"
    assert decide.day_guard([dec(1, "NICHTS"), dec(2, "NICHTS"), dec(3, "NICHTS")], now, p) is None
    old = [{**dec(1), "candle_epoch": now - 30 * 3600}, res(1, -1.0), {**dec(2), "candle_epoch": now - 29 * 3600}, res(2, -1.0)]
    assert decide.day_guard(old, now, p) is None                                                       # yesterday does not count
    assert decide.day_guard([dec(1), res(1, -1.0), dec(2), res(2, -1.0)], now, decide.LOCAL_PROFILE) is None


def test_both_ais_judge_the_candle_by_the_same_clock(tmp_path: Path, monkeypatch):
    """The local AI needs minutes; DeepSeek, asked after it, must not find the candle stale (24.11.2026: 0 DeepSeek decisions)."""
    import io

    from src.research_lab.ki_entry import __main__ as cli
    clocks: list[float] = []

    def fake_run(model, log_path, ask, model_name, now=None, profile=decide.LOCAL_PROFILE):
        clocks.append(now)
        cli.time.sleep(0.01)
        return {"results": [], "decision": None}

    monkeypatch.setattr(cli, "urlopen", lambda *a, **k: io.BytesIO(b"{}"))
    monkeypatch.setattr(cli.decide, "run", fake_run)
    assert cli.main(["run", "--log", str(tmp_path / "ki.jsonl"), "--no-hermes"]) == 0
    assert len(clocks) == 2 and clocks[0] is not None and clocks[0] == clocks[1]


def test_stop_lies_behind_zone_and_recent_extreme_with_buffer():
    """Uzi 24.11.2026: the stop is calculated as carefully as the entry."""
    c = [candle(i, 60500, 60600, 60400, 60500) for i in range(20)]   # ATR 200, buffer 100
    c.append(candle(20, 60500, 60550, 60180, 60300))
    help_ = decide.stop_help(c, {"low": 60250.0, "high": 60350.0})
    assert help_["long"]["struktur_tief"] == 60180.0
    assert help_["long"]["stop_spaetestens"] < 60180 - 90
    assert help_["short"]["struktur_hoch"] == 60600.0 and help_["short"]["stop_spaetestens"] > 60690
    answer = {"aktion": "LONG", "einstieg": 60300, "stop": 60150, "ziel": 61200, "vertrauen": 0.6, "grund": "x"}
    assert "Stop vor der Struktur" in decide.check_answer(answer, 60300.0, stops=help_)[4]
    assert decide.check_answer({**answer, "stop": 59850}, 60300.0, stops=help_)[4] is None
    assert decide.check_answer({"aktion": "SHORT", "einstieg": 60300, "stop": 60650, "ziel": 59000, "vertrauen": 0.6, "grund": "x"},
                               60300.0, stops=help_)[4].startswith("Stop vor der Struktur")


def test_stop_keeps_the_buffer_from_a_round_number():
    c = [candle(i, 60300, 60400, 60200, 60300) for i in range(20)]   # ATR 200, buffer 100
    c.append(candle(20, 60300, 60350, 60110, 60250))                 # low 60110: minus buffer = 60010, right on 60,000
    help_ = decide.stop_help(c, {"low": 60150.0, "high": 60250.0})
    assert help_["long"]["stop_spaetestens"] <= 59900.5
    assert "stop_hilfe" in decide.build_context(model(falling_into_zone()), zones.build(model(falling_into_zone()), 60100.0,
                                                                                        falling_into_zone()[:-1])[0], 0.0)
