"""F10 Regel-Anfrage: rule building blocks, causality, random twin, exploration log, translation, CLI."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_lab.backtest.engine import History
from src.research_lab.data.parse import Kline
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.synthetic import synthetic_series
from src.research_lab.workshop import rules
from src.research_lab.workshop.__main__ import _rule_command, main
from src.research_lab.workshop.generator import validate as validate_spec
from src.research_lab.workshop.ideas import IdeaQueue

H = 3_600_000
START_2020 = 1_577_836_800_000


def rule(**over):
    base = {"schema": "tim_rule/1", "title": "POC-Retest", "symbol": "BTCUSDT", "timeframe": "1h", "side": "long",
            "entry": {"type": "prev_day_level", "level": "poc", "mode": "retest"},
            "filters": [{"type": "hours", "from": 9, "to": 13}], "stop": {"type": "signal_bar", "buffer_atr": 0.1},
            "target": {"r": 2}, "time_stop_bars": 24}
    base.update(over)
    return base


def bar(t, o, h, l, c, v=100.0, step=H):
    return Kline(t, o, h, l, c, v, t + step - 1, v / 2)


# --- validation and preview ----------------------------------------------------------------------

def test_valid_rule_has_no_problems_and_reads_back_in_words():
    assert rules.validate(rule()) == []
    text = rules.describe(rule())
    assert "Vortages-POC" in text and "9:00 und 13:00 Ortszeit" in text and "Ziel 2 R" in text
    assert "Holdout 2025 bleibt zu" in text


@pytest.mark.parametrize("change, word", [
    ({"period": ["2020-01-01", "2025-03-01"]}, "Holdout"),
    ({"symbol": "DOGEUSDT"}, "symbol"),
    ({"timeframe": "1d"}, "POC/VAH/VAL"),
    ({"target": None, "time_stop_bars": None}, "Zeitstopp"),
    ({"entry": {"type": "rsi"}}, "entry.type"),
    ({"leverage": 10}, "unbekanntes Feld"),
    ({"stop": {"type": "atr", "k": 50}}, "stop atr"),
    ({"period": ["2020-01-01", "2022-12-31"]}, "Validierung"),
])
def test_invalid_rules_are_refused(change, word):
    problems = rules.validate(rule(**change))
    assert any(word in p for p in problems), problems


def test_sol_default_period_starts_with_its_archive():
    assert rules.period_of(rule(symbol="SOLUSDT")) == ("2020-09-01", "2024-12-31")
    assert rules.validate(rule(symbol="SOLUSDT")) == []
    assert any("Archivdaten" in p for p in rules.validate(rule(symbol="SOLUSDT", period=["2020-01-01", "2024-12-31"])))


# --- building blocks -----------------------------------------------------------------------------

def test_volume_profile_finds_the_heavy_price():
    bars = [bar(i * H, 100, 101, 99, 100, v=10) for i in range(23)] + [bar(23 * H, 109.5, 110, 109, 109.5, v=10_000)]
    poc, vah, val = rules.volume_profile(bars)
    assert 109 <= poc <= 110
    assert val <= poc <= vah


def _day_then(level_bar_low, close_after, *, prev_close=None):
    """24 bars of day 0 around 100, then day 1 bars; the last bar tests the previous-day low (99)."""
    day0 = [bar(i * H, 100, 100.5, 99.0 if i == 5 else 99.5, 100) for i in range(24)]
    day1 = [bar((24 + i) * H, 100, 100.5, 99.8, prev_close or 100) for i in range(9)]
    last = bar(33 * H, 100, 100.4, level_bar_low, close_after)
    return day0 + day1 + [last]


def test_prev_day_low_retest_triggers_only_on_touch_and_close_back_above():
    r = rule(entry={"type": "prev_day_level", "level": "low", "mode": "retest"}, filters=[],
             stop={"type": "percent", "pct": 1})
    hit = _day_then(98.9, 99.5)
    assert rules._triggered(r, History(hit, len(hit) - 1), 1, {})
    no_touch = _day_then(99.2, 99.5)
    assert not rules._triggered(r, History(no_touch, len(no_touch) - 1), 1, {})
    closed_below = _day_then(98.5, 98.8)
    assert not rules._triggered(r, History(closed_below, len(closed_below) - 1), 1, {})


def test_signals_never_depend_on_future_bars():
    bars = synthetic_series(24 * 60, seed=3, start_ms=START_2020, volatility=0.006)
    for entry in ({"type": "prev_day_level", "level": "vah", "mode": "break"}, {"type": "vwap_cross"},
                  {"type": "sma_cross", "n": 30}, {"type": "breakout", "n": 20}):
        r = rule(entry=entry, side="both", filters=[{"type": "trend", "n": 50}])
        full = rules.compile_rule(r)
        cut = 24 * 40
        early = [full(History(bars, t)) for t in range(cut)]
        fresh = rules.compile_rule(r)
        alone = [fresh(History(bars[: t + 1], t)) for t in range(cut)]
        assert early == alone
        assert any(s is not None for s in early), entry


def test_hours_filter_uses_local_time():
    winter_9_local = 1_604_217_600_000  # 2020-11-01 08:00 UTC = 09:00 in Germany
    bars = [bar(winter_9_local + (i - 30) * H, 100, 101, 99, 100) for i in range(31)]
    r = rule(filters=[{"type": "hours", "from": 9, "to": 10}])
    assert rules._passes_filters(r, History(bars, 30), 1)
    assert not rules._passes_filters(r, History(bars, 29), 1)


def test_aggregate_builds_complete_bars_and_drops_partial_ones():
    five = [bar(i * 300_000, 100 + i, 101 + i, 99 + i, 100.5 + i, v=1, step=300_000) for i in range(13)]
    out = rules.aggregate(five, 1_800_000)
    assert len(out) == 2
    assert out[0].open == 100 and out[0].close == 105.5 and out[0].high == 106 and out[0].volume == 6
    assert out[0].close_time == 1_800_000 - 1


# --- evaluation ----------------------------------------------------------------------------------

def _walk(seed):
    bars = synthetic_series(43_800, seed=seed, start_ms=START_2020, volatility=0.006)
    return [b for b in bars if b.open_time < HOLDOUT_START_MS]


def test_random_walk_gives_no_candidate_and_follows_the_result_contract():
    r = rule(entry={"type": "breakout", "n": 20}, side="both", filters=[])
    out = rules.evaluate(r, _walk(1), random_runs=19)
    assert out["status"] in {"failed", "not_testable"}
    assert out["edge"] is False and out["lesson"].startswith("Erkundung, kein Beleg")
    m = out["metrics"]
    assert m["base_costs"]["train"]["trades"] > 0 and m["base_costs"]["validation"]["trades"] > 0
    assert m["stress_costs"]["validation"]["expectancy_r"] < m["base_costs"]["validation"]["expectancy_r"]
    assert m["random"]["validation"]["runs"] == 19 and 0 < m["random"]["validation"]["p_value"] <= 1


def test_random_twin_copies_the_risk_of_the_rule():
    bars = _walk(2)
    r = rule(entry={"type": "breakout", "n": 20}, side="long", filters=[])
    from src.research_lab.backtest.engine import run_backtest
    base = run_backtest(bars, rules.compile_rule(r), H, end_ms=HOLDOUT_START_MS)
    distances = rules.stop_distances(bars, base.signals)
    assert len(distances) == len(base.signals) and min(distances) > 0


def test_evaluate_refuses_holdout_bars():
    bars = [bar(HOLDOUT_START_MS - H, 1, 1, 1, 1), bar(HOLDOUT_START_MS, 1, 1, 1, 1)]
    with pytest.raises(rules.RuleError, match="Holdout"):
        rules.evaluate(rule(), bars, random_runs=0)


def test_split_boundaries_are_the_protocol_ones():
    assert rules.SPLITS["validation"] == (VALIDATION_START_MS, HOLDOUT_START_MS)


# --- data loading --------------------------------------------------------------------------------

class FakeStore:
    def __init__(self, native: bool):
        self.native = native
        self.asked = []

    def load_klines(self, refs):
        refs = list(refs)
        self.asked.append(refs[0].interval)
        if refs[0].interval != "5m" and not self.native:
            raise FileNotFoundError("not fetched")
        step = rules.TIMEFRAMES.get(refs[0].interval, 300_000) if refs[0].interval != "5m" else 300_000
        start = refs[0].start_ms
        return [bar(start + i * step, 100, 101, 99, 100, step=step) for i in range(48 * 3_600_000 // step)]

    def load_funding(self, refs):
        raise FileNotFoundError("no funding")

    def dataset_hash(self, refs):
        return "h" * 64


def test_load_data_falls_back_to_5m_and_says_so():
    store = FakeStore(native=False)
    bars, funding, notes, _ = rules.load_data(store, rule(period=["2020-01-01", "2024-06-30"]))
    assert store.asked == ["1h", "5m"] and len(bars) == 48 and bars[1].open_time - bars[0].open_time == H
    assert any("5m" in n for n in notes) and any("Funding" in n for n in notes) and funding == []


def test_load_data_uses_native_bars_when_present():
    store = FakeStore(native=True)
    bars, _, notes, _ = rules.load_data(store, rule(timeframe="4h", entry={"type": "breakout", "n": 5}, filters=[]))
    assert store.asked == ["4h"] and not any("5m" in n for n in notes)


# --- exploration log and study spec --------------------------------------------------------------

def test_exploration_log_counts_every_run_and_detects_tampering(tmp_path):
    log = rules.ExplorationLog(tmp_path / "log.jsonl")
    outcome = {"status": "failed", "result": "nichts"}
    first = log.append(rule(), outcome, at="2026-10-31T18:00:00Z", requested_by="uzi", data_hash=None)
    second = log.append(rule(title="B"), outcome, at="2026-10-31T18:05:00Z", requested_by="uzi", data_hash=None)
    assert (first["run"], second["run"]) == ("R-0001", "R-0002") and second["prev"] == first["hash"]
    assert "2 Regeln erkundet" in rules.exploration_note(log.records())
    assert rules.exploration_note([]) == "Noch keine Regel erkundet."
    text = (tmp_path / "log.jsonl").read_text().replace('"failed"', '"candidate"', 1)
    (tmp_path / "log.jsonl").write_text(text)
    with pytest.raises(rules.RuleError, match="Hash-Kette"):
        log.records()


def test_explore_writes_bundle_files(tmp_path):
    fake = lambda r, b, f, **kw: {"status": "failed", "result": "x", "lesson": "y", "edge": False,  # noqa: E731
                                  "metrics": rules.evaluate(r, _walk(4)[:24 * 400], random_runs=0)["metrics"]}
    entry, path = rules.explore(rule(period=["2020-01-01", "2024-06-30"]), store=FakeStore(native=True),
                                log=rules.ExplorationLog(tmp_path / "log.jsonl"), runs_dir=tmp_path / "runs",
                                at="2026-10-31T18:00:00Z", requested_by="uzi", evaluate_fn=fake)
    folder = tmp_path / "runs" / entry["run"]
    assert json.loads((folder / "result.json").read_text())["metrics"]["data_hash"] == "h" * 64
    assert path.read_text().startswith("# R-0001: POC-Retest (Erkundung)")


def test_study_spec_passes_the_generator_and_names_the_prior_burden():
    spec = rules.study_spec(rule(), exploration="R-0003")
    idea = {"template": "regel_backtest", "derived_from": None, "data": ["archive_usdm_klines"]}
    assert validate_spec(idea, spec) == []
    assert "R-0003" in spec["prior_burden"] and spec["variants"][0]["params"]["title"] == "POC-Retest"


# --- translation ---------------------------------------------------------------------------------

def test_translation_accepts_only_valid_rules():
    answer = "Hier die Regel:\n```json\n" + json.dumps({k: v for k, v in rule().items() if k != "schema"}) + "\n```"
    assert rules.parse_translation(answer)["schema"] == "tim_rule/1"
    with pytest.raises(rules.RuleError, match="kein JSON"):
        rules.parse_translation("geht nicht")
    with pytest.raises(rules.RuleError, match="Holdout"):
        rules.parse_translation(json.dumps(rule(period=["2021-01-01", "2025-06-30"])))
    prompt = rules.translate_prompt("Long am POC" + "x" * 5000)
    assert "2025 ist gesperrt" in prompt and len(prompt) < 4000


# --- command line --------------------------------------------------------------------------------

def test_cli_preview_and_from_text(tmp_path, capsys):
    spec = tmp_path / "r.json"
    spec.write_text(json.dumps(rule()))
    assert main(["--queue", str(tmp_path / "q.jsonl"), "rule-preview", "--spec", str(spec)]) == 0
    assert "Vortages-POC" in capsys.readouterr().out

    class Args:
        command, text, save_dir = "rule-from-text", "Long am POC-Retest", tmp_path / "specs"
    answer = json.dumps(rule(note="Absorption nicht abbildbar"))
    assert _rule_command(Args, IdeaQueue(tmp_path / "q.jsonl"), ask=lambda prompt: answer) == 0
    out = capsys.readouterr().out
    assert "Nicht abbildbar: Absorption" in out and len(list((tmp_path / "specs").glob("*.json"))) == 1


def test_cli_rule_study_adds_idea_once(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec = tmp_path / "r.json"
    spec.write_text(json.dumps(rule()))
    queue = tmp_path / "q.jsonl"
    assert main(["--queue", str(queue), "rule-study", "--spec", str(spec)]) == 0
    assert "I-0001 angelegt" in capsys.readouterr().out
    assert (tmp_path / "data/research/rules/studies/I-0001.json").exists()
    assert main(["--queue", str(queue), "rule-study", "--spec", str(spec)]) == 2
    assert main(["--queue", str(queue), "rule-study", "--spec", str(spec), "--run", "R-0009"]) == 2


def test_cli_refuses_invalid_rule(tmp_path, capsys):
    spec = tmp_path / "r.json"
    spec.write_text(json.dumps(rule(period=["2020-01-01", "2025-02-01"])))
    assert main(["--queue", str(tmp_path / "q.jsonl"), "rule-test", "--spec", str(spec)]) == 2
    assert "Holdout" in capsys.readouterr().err


def test_a_planted_edge_is_found_and_plain_noise_is_not():
    import math
    import random

    def series(edge):
        rng, price, out, left = random.Random(5), 10_000.0, [], 0
        for i in range(43_848):
            mu = edge * 0.006 if left > 0 else 0.0
            left = max(left - 1, 0)
            o = price
            c = o * math.exp(rng.gauss(mu, 0.006))
            t = START_2020 + i * H
            out.append(Kline(t, o, max(o, c) * (1 + abs(rng.gauss(0, 0.003))), min(o, c) * (1 - abs(rng.gauss(0, 0.003))),
                             c, 100.0, t + H - 1, 50.0))
            price = c
            if len(out) > 21 and c > max(b.high for b in out[-21:-1]):
                left = 6  # after a 20-bar breakout the price drifts up for six bars
        return [b for b in out if b.open_time < HOLDOUT_START_MS]

    r = rule(entry={"type": "breakout", "n": 20}, filters=[], stop={"type": "atr", "k": 1.5},
             target={"r": 1.5}, time_stop_bars=6)
    assert rules.evaluate(r, series(0.6), random_runs=39)["status"] == "candidate"
    assert rules.evaluate(r, series(0.0), random_runs=39)["status"] == "failed"


def test_cli_rule_test_names_a_missing_archive(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec = tmp_path / "r.json"
    spec.write_text(json.dumps(rule()))
    assert main(["--queue", str(tmp_path / "q.jsonl"), "rule-test", "--spec", str(spec), "--archive", str(tmp_path / "leer")]) == 2
    assert "Archivdaten fehlen" in capsys.readouterr().err
    assert not (tmp_path / "data/research/rules/log.jsonl").exists()


def test_short_retest_reads_the_right_way_round():
    text = rules.describe(rule(side="short", entry={"type": "prev_day_level", "level": "high", "mode": "retest"}))
    assert "Docht darüber, Schluss darunter" in text and "Long:" not in text
