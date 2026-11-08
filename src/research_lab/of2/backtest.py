"""Follows OF2 signals on minute bars (streaming) and books results in R after protocol costs.

Rules (protocol 4.2/4.3/4.4, prereg section 6):
- A MARKET signal fills at the open of the minute after the signal; STOP/LIMIT orders fill at the trigger
  (or at the open when the minute already gaps through), and expire at ``valid_until``.
- From the fill minute on, stop before target when both are touched in the same minute (conservative).
- Time stop (R70): after ``time_stop_bars`` bars of the model's time frame without ``time_stop_mfe_r`` MFE,
  exit at that minute's last price. Hard limit ``max_hold_minutes``.
- Costs: fee and slippage per side on the fill prices, stop_slippage on stop exits; cost in R = cost / stop distance.
Nothing here reads a later minute than the one being pushed.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.research_lab.of2.candles import session_of
from src.research_lab.of2.config import MINUTE_MS, Config
from src.research_lab.of2.models import LIMIT, MARKET, STOP, Signal
from src.research_lab.orderflow_ml.bars import E8, MinuteBar
from src.research_lab.protocol import BASE_COSTS, CostModel


@dataclass(frozen=True, slots=True)
class Trade:
    signal: Signal
    fill_ms: int
    entry: float
    exit_ms: int
    exit: float
    reason: str          # STOP, TARGET, TIME_STOP, MAX_HOLD
    gross_r: float
    fee_r: float
    slippage_r: float
    mfe_r: float
    mae_r: float

    @property
    def net_r(self) -> float:
        return self.gross_r - self.fee_r - self.slippage_r

    def as_dict(self) -> dict:
        s = self.signal
        return {
            "model": s.model, "direction": s.direction, "session": s.session, "regime": s.regime, "confirmed": s.confirmed,
            "level": s.level_name, "level_price": s.level, "relvol": s.relvol, "signal_ms": s.signal_ms, "tf": s.tf,
            "fill_ms": self.fill_ms, "entry": self.entry, "stop": s.stop, "target": s.target, "exit_ms": self.exit_ms,
            "exit": self.exit, "reason": self.reason, "gross_r": self.gross_r, "fee_r": self.fee_r,
            "slippage_r": self.slippage_r, "net_r": self.net_r, "mfe_r": self.mfe_r, "mae_r": self.mae_r,
            "notes": list(s.notes),
        }


@dataclass
class _Open:
    signal: Signal
    fill_ms: int
    entry: float
    stop_dist: float
    mfe: float = 0.0
    mae: float = 0.0


def costs_r(entry: float, exit_: float, stop_dist: float, stopped: bool, costs: CostModel) -> tuple[float, float]:
    fee = costs.fee * (entry + exit_)
    slip = costs.slippage * entry + (costs.stop_slippage if stopped else costs.slippage) * exit_
    return fee / stop_dist, slip / stop_dist


class Tracker:
    """Holds pending signals and open paper trades; ``push`` consumes one minute bar and returns closed trades."""

    def __init__(self, cfg: Config, costs: CostModel = BASE_COSTS) -> None:
        self.cfg = cfg
        self.costs = costs
        self.pending: list[Signal] = []
        self.open: list[_Open] = []
        self.expired = 0
        self.cancelled = 0

    def add(self, signal: Signal) -> None:
        self.pending.append(signal)

    def cancel_on_close(self, close: float, tf: int) -> None:
        """A close of the signal's own time frame back beyond ``cancel_beyond`` withdraws the resting limit
        (M2: acceptance failed; M5: the stacked zone died)."""
        keep = []
        for s in self.pending:
            beyond = s.cancel_beyond
            if s.tf == tf and beyond is not None and (close < beyond if s.direction > 0 else close > beyond):
                self.cancelled += 1
            else:
                keep.append(s)
        self.pending = keep

    def push(self, bar: MinuteBar) -> list[Trade]:
        t = bar.window_start_ms
        closed: list[Trade] = []
        # 1. pending orders of earlier signals
        still: list[Signal] = []
        fills: list[_Open] = []
        for s in self.pending:
            if t < s.signal_ms:
                still.append(s)
                continue
            if t >= s.valid_until:
                self.expired += 1
                continue
            if not bar.has_trades:
                still.append(s)
                continue
            o, h, l = bar.first_price_e8 / E8, bar.high_price_e8 / E8, bar.low_price_e8 / E8
            price: float | None = None
            if s.kind == MARKET:
                price = o
            elif s.kind == STOP:
                assert s.trigger is not None
                if s.direction > 0 and h >= s.trigger:
                    price = max(o, s.trigger)
                elif s.direction < 0 and l <= s.trigger:
                    price = min(o, s.trigger)
            elif s.kind == LIMIT:
                assert s.trigger is not None
                if s.direction > 0 and l <= s.trigger:
                    price = min(o, s.trigger)
                elif s.direction < 0 and h >= s.trigger:
                    price = max(o, s.trigger)
            if price is None:
                still.append(s)
                continue
            dist = abs(price - s.stop)
            if dist <= 0 or (s.direction > 0 and price <= s.stop) or (s.direction < 0 and price >= s.stop):
                self.cancelled += 1  # filled beyond its own stop: no trade
                continue
            fills.append(_Open(s, t, price, dist))
        self.pending = still
        self.open.extend(fills)
        # 2. open trades, fill minute included
        if not bar.has_trades:
            return closed
        h, l, c = bar.high_price_e8 / E8, bar.low_price_e8 / E8, bar.last_price_e8 / E8
        remaining: list[_Open] = []
        for o in self.open:
            s, d = o.signal, o.signal.direction
            favourable = (h - o.entry) if d > 0 else (o.entry - l)
            adverse = (o.entry - l) if d > 0 else (h - o.entry)
            o.mfe, o.mae = max(o.mfe, favourable / o.stop_dist), max(o.mae, adverse / o.stop_dist)
            hit_stop = l <= s.stop if d > 0 else h >= s.stop
            hit_target = h >= s.target if d > 0 else l <= s.target
            held = t - o.fill_ms
            tf = s.tf
            exit_: float | None = None
            reason = ""
            if hit_stop:
                exit_, reason = s.stop, "STOP"
            elif hit_target:
                exit_, reason = s.target, "TARGET"
            elif held >= self.cfg.max_hold_minutes * MINUTE_MS:
                exit_, reason = c, "MAX_HOLD"
            elif held >= self.cfg.time_stop_bars * tf * MINUTE_MS and o.mfe < self.cfg.time_stop_mfe_r:
                exit_, reason = c, "TIME_STOP"
            if exit_ is None:
                remaining.append(o)
                continue
            gross = (exit_ - o.entry) * d / o.stop_dist
            fee_r, slip_r = costs_r(o.entry, exit_, o.stop_dist, reason == "STOP", self.costs)
            closed.append(Trade(s, o.fill_ms, o.entry, t, exit_, reason, gross, fee_r, slip_r, o.mfe, o.mae))
        self.open = remaining
        return closed


def cost_gate(signal: Signal, cfg: Config, costs: CostModel = BASE_COSTS) -> float | None:
    """Estimated round-trip cost in R at the reference price; None when it cannot be computed."""
    dist = signal.stop_distance
    if dist <= 0:
        return None
    price = signal.reference_price
    return (2 * costs.fee + costs.slippage + costs.stop_slippage) * price / dist


def summarize(trades: Iterable[Trade], cfg: Config) -> dict:
    """Net R by model × session × confirmation, plus by hour and exit reason."""
    out: dict = {"gesamt": _stats([]), "modell": {}, "modell_session": {}, "stunde": {}, "grund": {}}
    rows = list(trades)
    out["gesamt"] = _stats(rows)
    for key, pick in (("modell", lambda t: t.signal.model), ("stunde", lambda t: str((t.fill_ms % 86_400_000) // 3_600_000)),
                      ("grund", lambda t: t.reason)):
        groups: dict[str, list[Trade]] = {}
        for t in rows:
            groups.setdefault(pick(t), []).append(t)
        out[key] = {k: _stats(v) for k, v in sorted(groups.items())}
    for t in rows:
        k = f"{t.signal.model}|{t.signal.session or session_of(t.fill_ms, cfg)}|{'OF' if t.signal.confirmed else 'PREIS'}"
        out["modell_session"].setdefault(k, []).append(t)
    out["modell_session"] = {k: _stats(v) for k, v in sorted(out["modell_session"].items())}
    return out


def _stats(rows: Sequence[Trade]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    net = [t.net_r for t in rows]
    return {"n": n, "netto_r_summe": round(sum(net), 4), "netto_r_mittel": round(sum(net) / n, 4),
            "treffer": round(sum(1 for x in net if x > 0) / n, 4), "brutto_r_mittel": round(sum(t.gross_r for t in rows) / n, 4),
            "kosten_r_mittel": round(sum(t.fee_r + t.slippage_r for t in rows) / n, 4)}
