"""Signal rules of study S7b (docs/research_lab/studien/S7B_EINE_POSITION_PRAEREGISTRIERUNG.md).

S7b is S7 with one portfolio rule added: at most one open or pending position over
BTCUSDT, ETHUSDT and SOLUSDT together. The per-instrument rule (Donchian breakout in
the SMA-200 direction, stop max(1.5 x ATR14, 1 %), fixed target T in R, time stop 30
bars) is `s7.breakout` unchanged; the cap lives in `engine.run_portfolio`. Signals that
arrive while the slot is taken lapse, nothing is queued; two signals on the same bar
are resolved in the fixed order BTC > ETH > SOL.

Nothing here computes outcomes. `count_signals_locked` is the outcome-blind lower
bound for the feasibility gate: every taken signal is assumed to occupy the single slot
for the full time stop (30 bars) across all instruments.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.research_lab.backtest.engine import History
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s7

HYPOTHESIS = "S7b"
PARENT = "S7"
PRIORITY: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")  # tie-break on the same bar, liquidity order
MAX_POSITIONS = 1
REGISTERED_CHANNELS = (20,)  # N = 55 only as neighbour: never registered in S7, its gate failed there
LOCK_MS = s7.TIME_STOP_BARS * s7.INTERVAL_MS  # outcome-blind slot occupation per taken signal

S7B_VARIANTS: tuple[s7.S7Variant, ...] = tuple(
    s7.S7Variant(f"S7b-D{n}-T{int(t)}", n, t, hypothesis=HYPOTHESIS) for n in s7.CHANNELS for t in s7.TARGETS
)
GATE_VARIANTS: tuple[s7.S7Variant, ...] = tuple(v for v in S7B_VARIANTS if v.channel in REGISTERED_CHANNELS)


def params(variant: s7.S7Variant) -> dict[str, float | int | str]:
    """Register parameters: the S7 geometry plus the portfolio rule and the parent study."""
    return {**variant.params, "max_positions": MAX_POSITIONS, "priority": ">".join(PRIORITY), "parent": PARENT}


@dataclass(frozen=True, slots=True)
class LockedCount:
    upper: int  # every emitted signal over all instruments
    lower: int  # signals at least 30 bars (in time) after the last counted one, over all instruments
    skipped_gap: int
    lower_times: tuple[tuple[int, str], ...]  # (open time, symbol) of the lower-bound signals


def count_signals_locked(bars_by_symbol: Mapping[str, Sequence[Kline]], variant: s7.S7Variant,
                         windows: Mapping[str, tuple[int, int]], priority: Sequence[str] = PRIORITY) -> LockedCount:
    """Outcome-blind count for the feasibility gate. No exits, no R, no prices after a signal.

    `windows` gives [start, end) per instrument. Signals of all instruments are merged in
    time order (ties by `priority`); a signal counts for the lower bound when it comes at
    least `LOCK_MS` after the last counted signal of any instrument."""
    rank = {sym: i for i, sym in enumerate(priority)}
    emitted: list[tuple[int, int, str]] = []
    skipped_gap = 0
    for symbol, bars in bars_by_symbol.items():
        if symbol not in rank:
            raise ValueError(f"{symbol} missing from priority")
        start_ms, end_ms = windows[symbol]
        counts = s7.Counts()
        strategy = s7.breakout(variant, counts)
        for t, bar in enumerate(bars):
            if bar.open_time < start_ms:
                continue
            if bar.open_time >= end_ms:
                break
            if strategy(History(bars, t)) is not None:
                emitted.append((bar.open_time, rank[symbol], symbol))
        skipped_gap += counts.skipped_gap
    emitted.sort()
    lower: list[tuple[int, str]] = []
    last: int | None = None
    for time, _, symbol in emitted:
        if last is None or time - last >= LOCK_MS:
            lower.append((time, symbol))
            last = time
    return LockedCount(len(emitted), len(lower), skipped_gap, tuple(lower))
