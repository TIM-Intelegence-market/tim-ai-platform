"""R-KI-1: zone strength, trigger, answer check, paper play and the append-only log."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.research_lab.ki_entry import decide, zones
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
        {"group": "structure", "label": "30m BOS ↓", "price": 60700.0, "finished": True, "start": "2026-11-20T18:15:00+00:00"},
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
    assert decide.trigger(model(c), [], now_after(c) + 3600)["why"] == "Kerzen veraltet"
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
    assert decide.play(d, [candle(1, 60100, 60150, 60050, 60100)]) is None                  # not filled yet, window open
    unfilled = [candle(i, 60100, 60150, 60050, 60100) for i in range(1, 5)]
    assert decide.play(d, unfilled)["outcome"] == "nicht gefüllt"
    both = [candle(1, 60100, 60150, 59990, 60050), candle(2, 60050, 60450, 59750, 60100)]
    assert decide.play(d, both)["outcome"] == "Stop"                                         # both in one candle: stop
    win = [candle(1, 60100, 60150, 59990, 60050), candle(2, 60050, 60450, 59950, 60400)]
    result = decide.play(d, win)
    assert result["outcome"] == "Ziel" and result["r_gross"] == pytest.approx(2.0)
    assert result["r"] == pytest.approx(2.0 - 60000 * decide.COST_PCT / 100 / 200, abs=1e-3)
    gap = [candle(1, 59900, 59950, 59850, 59900), candle(2, 59900, 60450, 59850, 60400)]
    assert decide.play(d, gap)["fill"] == 59900.0                                          # opened below the limit
    short = {"action": "SHORT", "candle": T0, "plan": {"entry": 60000.0, "stop": 60200.0, "target": 59600.0}}
    assert decide.play(short, [candle(1, 59950, 60010, 59900, 59950), candle(2, 59950, 60000, 59550, 59600)])["outcome"] == "Ziel"


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
    later = c + [candle(30, 60100, 60120, 60080, 60100), candle(31, 60100, 60600, 60090, 60550)]
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
