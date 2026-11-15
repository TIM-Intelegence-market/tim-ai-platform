"""S38: Engtag-Erkennung und Ausbruchssignal auf synthetischen Minuten."""
from __future__ import annotations

from array import array
from datetime import date

from src.research_lab.studies import s38


class _Syn:
    def __init__(self, days_n=24):
        self.first, self.t0, self.n = date(2024, 1, 1), 0, days_n * 1440
        z = lambda v: array("d", [v]) * self.n
        self.open, self.high, self.low, self.close = z(100.0), z(100.0), z(100.0), z(100.0)
        self.valid = bytearray(b"\x01" * self.n)

    def set_day(self, k, hi, lo):
        a = k * 1440
        for i in range(a, a + 1440):
            self.open[i] = self.close[i] = (hi + lo) / 2
            self.high[i], self.low[i] = hi, lo


def test_configs_and_reference():
    assert s38.CONFIGS == ["T-045", "T-060", "T-075"] and s38.REF == "T-alle" and s38.HOLD_MIN == 1440


def test_tight_day_ratio():
    m = _Syn()
    for k in range(22):
        m.set_day(k, 102.0, 98.0)       # range ~4 %
    m.set_day(22, 100.5, 99.5)           # tight day ~1 %
    r = s38.tight_days(m, date(2024, 1, 24), date(2024, 1, 24))
    assert date(2024, 1, 24) in r and r[date(2024, 1, 24)] < 0.45


def test_breakout_up_and_both():
    m = _Syn(3)
    m.set_day(0, 100.5, 99.5)
    m.set_day(1, 100.0, 100.0)
    i = 1440 + 600
    m.high[i] = 101.0                      # breaks above 100.5 * 1.0005
    s = s38.breakout_signal(m, date(2024, 1, 2))
    assert s["direction"] == 1 and s["i_entry"] == i and abs(s["entry"] - 100.5 * 1.0005) < 1e-9
    m.low[i] = 99.0                        # both sides in one minute
    assert s38.breakout_signal(m, date(2024, 1, 2)) == "both"


def test_valid_locked_without_training(tmp_path):
    import json
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"configs": {c: {"training_passed": False} for c in s38.CONFIGS}}))
    assert s38.run("valid", {}, "x", tmp_path / "o.json", p) == 2
