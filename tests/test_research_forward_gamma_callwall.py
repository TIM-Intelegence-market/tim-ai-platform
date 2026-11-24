import datetime as dt
import json

from src.research_lab.forward import gamma_callwall as g

H = 3_600_000
T0 = int(g.START.timestamp() * 1000)


def bars_from(closes_hl, start_ms=T0 + H):
    return [(start_ms + i * H, c, h, l, c) for i, (h, l, c) in enumerate(closes_hl)]


def flat(n, p=100.0):
    return [(p, p, p)] * n


def test_frozen():
    assert g.FROZEN and g.VERSION == "1.0"
    assert g.START.year == 2026 and g.START.tzinfo is not None


def test_judge_hold_break_untouched_pending():
    hold = bars_from([(101.0, 100.0, 100.5)] + [(100.0, 99.0, 99.0)] * 5 + flat(200, 99.0))
    assert g.judge(101.0, hold).result == "hold"
    brk = bars_from([(101.0, 100.0, 100.5), (103.0, 101.0, 102.5)] + flat(200, 102.5))
    assert g.judge(101.0, brk).result == "break"
    assert g.judge(110.0, bars_from(flat(g.LOOK_H + 10))).result == "untouched"
    assert g.judge(110.0, bars_from(flat(20))).result == "pending"
    assert g.judge(101.0, bars_from([(101.0, 100.6, 100.8)] + flat(5, 100.8))).result == "pending"


def test_sampling_ignores_before_start_and_off_hours():
    lines = [
        json.dumps({"as_of": "2026-11-24T20:00:10+00:00", "spot": 1, "call_wall": 2}),
        json.dumps({"as_of": "2026-11-25T00:00:10+00:00", "spot": 1, "call_wall": 2}),
        json.dumps({"as_of": "2026-11-25T00:05:10+00:00", "spot": 1, "call_wall": 3}),
        json.dumps({"as_of": "2026-11-25T01:00:10+00:00", "spot": 1, "call_wall": 2}),
        json.dumps({"as_of": "2026-11-25T04:00:10+00:00", "spot": 1, "call_wall": 2}),
        "kaputt",
    ]
    s = g.sample_snapshots(lines)
    assert [x["as_of"][:13] for x in s] == ["2026-11-25T00", "2026-11-25T04"]
    assert s[0]["call_wall"] == 2


def test_same_wall_counted_once():
    bars = bars_from([(100.0, 99.0, 99.5)] * 10 + [(102.0, 100.0, 101.0)] + [(100.0, 99.0, 99.0)] * 60 + flat(200, 99.0))
    snaps = [{"_t": g.START, "spot": 100.0, "call_wall": 102.0},
             {"_t": g.START + dt.timedelta(hours=4), "spot": 99.5, "call_wall": 102.0}]
    r = g.evaluate(snaps, bars)
    assert r["events"] == 1 and r["hold"] == 1


def test_distance_filter_and_verdicts():
    snaps = [{"_t": g.START, "spot": 100.0, "call_wall": 100.1}, {"_t": g.START, "spot": 100.0, "call_wall": 150.0}]
    assert g.evaluate(snaps, bars_from(flat(300)))["skipped"] == 2
    assert g.summarize(["hold"] * 10, [], 1, 0)["verdict"] == "ZU_WENIG_DATEN"
    assert g.summarize(["hold"] * 27 + ["break"] * 3, ["hold", "break"] * 15, 1, 0)["verdict"] == "BESTANDEN"
    assert g.summarize(["hold"] * 18 + ["break"] * 12, ["hold", "break"] * 15, 1, 0)["verdict"] == "NICHT_BESTANDEN"


def test_wilson_low():
    assert g.wilson_low(0, 0) == 0.0
    assert 0.5 < g.wilson_low(27, 30) < 0.9
