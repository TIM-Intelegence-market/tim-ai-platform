"""S37: Konfigurationen, Absorptions-/Eröffnungsregel auf synthetischen Minuten."""
from __future__ import annotations

from datetime import date

from src.research_lab.studies import s37


def test_configs_and_constants():
    assert s37.CONFIGS == ["F-5m-vaOn", "F-5m-vaOff", "F-15m-vaOn", "F-15m-vaOff"]
    assert s37.SIGMA == 2.0 and s37.TIME_STOP_MIN == 240


def test_signal_none_without_data():
    class M:
        first = date(2024, 1, 1)
        n = 1440
    assert s37.find_signals(M(), date(2024, 1, 1), date(2024, 1, 1), 5) == {"vaOn": [], "vaOff": []}


def test_no_validation_without_training(tmp_path):
    import json
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"configs": {c: {"training_passed": False} for c in s37.CONFIGS}}))
    assert s37.run("valid", {}, "x", tmp_path / "o.json", p) == 2


class _Syn:
    """Two synthetic UTC days: day 0 profile ~ 99..101, day 1 opens at 100, absorbs at the VAL, bounces."""

    def __init__(self):
        from array import array
        self.first, self.t0, self.n = date(2024, 1, 1), 0, 2880
        z = lambda: array("d", [0.0]) * self.n
        self.open, self.high, self.low, self.close, self.buy_q, self.sell_q, self.base = (z() for _ in range(7))
        self.valid = bytearray(b"\x01" * self.n)
        for i in range(self.n):
            p = 100 + (0.5 if i % 2 else -0.5) if i < 1440 else 100 + (0.3 if i % 2 else -0.3)
            self.open[i] = self.high[i] = self.low[i] = self.close[i] = p
            self.buy_q[i] = self.sell_q[i] = 50.0
            self.base[i] = 1.0
            self.high[i] += 0.05
            self.low[i] -= 0.05

    def day_profile(self, d):
        return [(0, 98.8 + 0.1 * k, 10.0 if 4 <= k <= 16 else 1.0) for k in range(25)]


def test_absorption_long_signal_and_vaon_filter():
    m = _Syn()
    lv = s37.profile_levels(m, date(2024, 1, 2))
    val = lv[2]
    # candle k = minutes 240..244 (5m): big volume, tiny range at VAL, sellers dominate; k+1 = 245..249: buyers, close >= open
    for i in range(1440 + 240, 1440 + 245):
        m.open[i] = m.close[i] = val
        m.high[i], m.low[i] = val + 0.01, val - 0.01
        m.sell_q[i], m.buy_q[i], m.base[i] = 400.0, 50.0, 4.0
    for i in range(1440 + 245, 1440 + 250):
        m.open[i], m.low[i] = val, val
        m.close[i] = m.high[i] = val + 0.05
        m.buy_q[i], m.sell_q[i], m.base[i] = 200.0, 20.0, 2.0
    out = s37.find_signals(m, date(2024, 1, 2), date(2024, 1, 2), 5)
    assert len(out["vaOff"]) == 1 and out["vaOff"][0]["direction"] == 1
    assert out["vaOn"] == out["vaOff"]            # open 100 inside the value area
    assert out["vaOff"][0]["i_entry"] == 1440 + 250
    m.open[1440] = 150.0                          # open outside the value area -> vaOn drops
    out2 = s37.find_signals(m, date(2024, 1, 2), date(2024, 1, 2), 5)
    assert out2["vaOn"] == [] and len(out2["vaOff"]) == 1
