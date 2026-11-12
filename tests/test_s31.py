"""S31: Metrics-Fenster (nur Vergangenheit) und B6/B7-Detektoren."""
import math

from src.research_lab.of2.candles import Candle
from src.research_lab.of2.config import DEFAULT_CONFIG
from src.research_lab.s31.metrics import Metrics
from src.research_lab.s31.models import b6_divergence, b7_oi_sweep

T0 = 1_600_000_200_000  # multiple of 5 min
M15 = 15 * 60_000


def metrics(n=40, oi0=1000.0, oi_step=1.0, ratio=1.0):
    times = [T0 + i * 300_000 for i in range(n)]
    return Metrics(times, [oi0 + i * oi_step for i in range(n)], [ratio] * n)


def test_window_is_past_only_and_needs_coverage():
    m = metrics()
    end = T0 + 20 * 300_000
    oi, tk = m.window(end, 60)
    assert oi > 0 and tk == 0.0
    assert m.window(T0 - 1, 60) is None            # before any snapshot
    assert m.window(T0 + 200 * 300_000, 60) is None  # stale
    m2 = metrics(ratio=2.0)
    assert math.isclose(m2.window(end, 60)[1], math.log(2.0))


def candle(i, o, h, l, c, delta=0):
    return Candle(T0 + i * M15, 15, 100, o, h, l, c, 1000, delta)


def test_b6_short_confirmed_and_twin(monkeypatch):
    import src.research_lab.s31.models as mod
    monkeypatch.setattr(mod, "_targets", lambda lv, d, e, st, cfg: ("POC", e + d * 3 * abs(e - st)))
    hist = [candle(i, 100, 101 + i * 0.1, 99, 100.5, delta=-5) for i in range(8)]
    hist.append(candle(8, 102, 105, 101, 101.5, delta=-5))   # new high, red close
    m = metrics(ratio=0.9)
    sig = b6_divergence(m, hist, None, DEFAULT_CONFIG)
    assert sig is not None and sig.model == "B6" and sig.direction == -1 and sig.confirmed
    m_up = metrics(ratio=1.2)                                   # perp confirms the run -> twin only
    twin = b6_divergence(m_up, hist, None, DEFAULT_CONFIG)
    assert twin is not None and not twin.confirmed
