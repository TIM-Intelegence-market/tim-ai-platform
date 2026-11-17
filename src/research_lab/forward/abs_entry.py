"""R-ABS-2: absorption at an important zone as entry, exit at the next counter-absorption (paper only).

Uzi 17.11.2026 ("go"): trade WITH the absorbing side at an important zone (sell absorption at support -> LONG,
buy absorption at resistance -> SHORT), stop just behind the wick, and take the profit at the next absorption in the
other direction, so the move is ridden instead of cut at a fixed target. Draft rule:
docs/research_lab/studien/ABSORPTIONS_EINSTIEG_SCHATTEN_PRAEREGISTRIERUNG.md (not frozen until Uzi's "einfrieren").

Data: the same Binance spot minute bars and day profiles as the orderflow live journal (stage B, :mod:`.of_live`):
archive days, complete recorder days, and today's closed minutes. Everything is recomputed from the minute bars on
every step; each decision uses only bars closed at that moment (no look-ahead). Only events at or after
``started_at`` count; the days before only warm up medians and prior-day levels.

Nothing here sends an order, reads a key or touches another journal.

    python -m src.research_lab.forward abs-step   --trades <recorder root> [--folder data/research/forward/ABS_ENTRY]
    python -m src.research_lab.forward abs-status [--folder ...]
"""
from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

from src.research_lab.orderflow_ml.bars import (
    DAY_MS,
    E8,
    MINUTE_MS,
    DayProfile,
    MinuteBar,
)

RULE = "R-ABS-2/0.3-entwurf"
FOLDER = Path("data/research/forward/ABS_ENTRY")
WARMUP_DAYS = 2


@dataclass(frozen=True)
class Params:
    window_min: int = 5              # detection window (minutes)
    median_windows: int = 288        # 24 h of 5m windows for the volume / trade-count median
    min_history: int = 96            # no detection before 8 h of history
    vol_factor: float = 3.0          # window volume >= 3x median (as absorption_volume_factor of the live Lage)
    delta_share: float = 0.25        # |buy - sell| / volume: the absorbed side was clearly aggressive
    hold_share: float = 0.6          # close at least 60 % of the range away from the absorbed extreme
    zone_pct: float = 0.15           # extreme within +-0.15 % of a zone
    trigger_minutes: int = 15        # entry must trigger within 15 one-minute bars after the event
    stop_atr_mult: float = 0.1       # stop = extreme -/+ 0.1 x ATR(14) of the 5m windows
    atr_len: int = 14
    breakeven_r: float = 1.0         # from +1 R (closed minute) the stop moves to the fill
    exit_needs_zone: bool = False    # the counter-absorption that ends a trade needs no zone
    swing_side: int = 3              # 1h swing pivot: 3 hours left and right
    swing_keep_h: int = 72
    value_area: float = 0.70
    accu_hours: int = 8              # accumulation flag (context only)
    accu_atr_mult: float = 3.0
    accu_min_events: int = 2
    fee: float = 0.0006              # Bitunix taker per side (bitunix/contract.FEE_TAKER)
    slippage: float = 0.0003         # entry and counter-absorption exit (of2 config)
    stop_slippage: float = 0.0005    # stop exit (of2 config)
    max_cost_r: float = 0.15         # above: trade is kept but counted as "kostenblockiert"
    fix_r: float = 2.0               # reference variant only (not in the verdict)
    min_trades: int = 30
    min_mean_r: float = 0.10
    bootstrap_draws: int = 10_000
    bootstrap_seed: int = 17

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


PARAMS = Params()


@dataclass
class Window:
    start_ms: int
    end_ms: int
    open: float
    high: float
    low: float
    close: float
    buy: float
    sell: float
    trades: int
    large: int
    largest: float

    @property
    def volume(self) -> float:
        return self.buy + self.sell

    @property
    def delta(self) -> float:
        return self.buy - self.sell


def _px(value_e8: int) -> float:
    return value_e8 / E8


def window_of(bars: Sequence[MinuteBar]) -> Window | None:
    live = [b for b in bars if b.has_trades]
    if not live:
        return None
    return Window(bars[0].window_start_ms, bars[-1].window_start_ms + MINUTE_MS, _px(live[0].first_price_e8),
                  max(_px(b.high_price_e8) for b in live), min(_px(b.low_price_e8) for b in live),
                  _px(live[-1].last_price_e8), sum(b.buy_sats for b in live) / E8, sum(b.sell_sats for b in live) / E8,
                  sum(b.trade_count for b in live), sum(b.large_count for b in live), max(b.largest_sats for b in live) / E8)


# -- zones --------------------------------------------------------------------------------------------------------
def profile_levels(profile: DayProfile, value_area: float = 0.70) -> dict[str, float]:
    """POC, VAH and VAL of a finished day from its aggressive volume per price bin."""
    volume: dict[int, int] = {}
    for _minute, bin_, buy, sell in profile.entries:
        volume[bin_] = volume.get(bin_, 0) + buy + sell
    if not volume:
        return {}
    width = profile.width_e8 / E8
    bins = sorted(volume)
    poc = max(bins, key=lambda b: (volume[b], -b))
    total, inside, lo, hi = sum(volume.values()), volume[poc], poc, poc
    while inside < value_area * total and (lo > bins[0] or hi < bins[-1]):
        down = volume.get(lo - 1, 0) if lo > bins[0] else -1
        up = volume.get(hi + 1, 0) if hi < bins[-1] else -1
        if up >= down:
            hi += 1
            inside += max(up, 0)
        else:
            lo -= 1
            inside += max(down, 0)
    return {"VT POC": (poc + 0.5) * width, "VT VAH": (hi + 1) * width, "VT VAL": lo * width}


@dataclass
class Zones:
    day: dict[str, float] = field(default_factory=dict)
    swings: list[tuple[int, str, float]] = field(default_factory=list)   # (confirmed_ms, name, price)

    def all(self, now_ms: int, keep_h: int) -> list[tuple[str, float]]:
        out = list(self.day.items())
        out += [(name, price) for at, name, price in self.swings if now_ms - at <= keep_h * 3_600_000]
        return out

    def near(self, price: float, now_ms: int, p: Params) -> tuple[str, float] | None:
        best = None
        for name, level in self.all(now_ms, p.swing_keep_h):
            dist = abs(price - level) / level * 100
            if dist <= p.zone_pct and (best is None or dist < best[0]):
                best = (dist, name, level)
        return (best[1], best[2]) if best else None


# -- detection ----------------------------------------------------------------------------------------------------
def detect(win: Window, history: Sequence[Window], p: Params) -> dict[str, Any] | None:
    """Absorption in one closed window against the windows before it, or None."""
    if len(history) < p.min_history or win.volume <= 0 or win.high <= win.low:
        return None
    recent = history[-p.median_windows:]
    med = median(w.volume for w in recent)
    if med <= 0 or win.volume < p.vol_factor * med:
        return None
    share = win.delta / win.volume
    rng = win.high - win.low
    if share <= -p.delta_share and (win.close - win.low) / rng >= p.hold_share:
        side, direction, extreme = "VERKAUF", "LONG", win.low
    elif share >= p.delta_share and (win.high - win.close) / rng >= p.hold_share:
        side, direction, extreme = "KAUF", "SHORT", win.high
    else:
        return None
    med_trades = median(w.trades for w in recent) or 1
    last_hour = list(history[-11:]) + [win]
    cvd = sum(w.delta for w in last_hour)
    move = last_hour[-1].close - last_hour[0].open
    return {"side": side, "direction": direction, "extreme": extreme, "close": win.close,
            "vol_ratio": round(win.volume / med, 2), "delta_btc": round(win.delta, 4), "delta_share": round(share, 3),
            "large_trades": win.large, "largest_btc": round(win.largest, 4),
            "tempo": round(win.trades / med_trades, 2),
            "cvd_60m_btc": round(cvd, 4), "cvd_divergenz": bool(cvd and move and (cvd > 0) != (move > 0))}


def extreme_imbalance(profile: DayProfile | None, win: Window, extreme: float) -> dict[str, float] | None:
    """Aggressive buy and sell volume in the price bin of the extreme during the window (footprint at the wick)."""
    if profile is None or not profile.entries:
        return None
    first = (win.start_ms - profile.day_start_ms) // MINUTE_MS
    last = (win.end_ms - profile.day_start_ms) // MINUTE_MS
    target = int(extreme * E8) // profile.width_e8
    buy = sum(e[2] for e in profile.entries if first <= e[0] < last and e[1] == target) / E8
    sell = sum(e[3] for e in profile.entries if first <= e[0] < last and e[1] == target) / E8
    return {"kauf_btc": round(buy, 4), "verkauf_btc": round(sell, 4)}


def _atr(windows: Sequence[Window], n: int) -> float | None:
    if len(windows) < n + 1:
        return None
    tr = [max(w.high - w.low, abs(w.high - prev.close), abs(w.low - prev.close))
          for prev, w in zip(windows[-n - 1:-1], windows[-n:])]
    return sum(tr) / n


def _hours(bars: Sequence[MinuteBar]) -> list[Window]:
    """Closed 1h windows of a run of minute bars (hour aligned)."""
    out, bucket, hour = [], [], None
    for bar in bars:
        h = bar.window_start_ms // 3_600_000
        if hour is not None and h != hour:
            win = window_of(bucket)
            if win and len(bucket) == 60:
                out.append(win)
            bucket = []
        hour = h
        bucket.append(bar)
    if bucket and len(bucket) == 60:
        win = window_of(bucket)
        if win:
            out.append(win)
    return out


def accumulation(hours: Sequence[Window], events: Sequence[dict[str, Any]], now_ms: int, p: Params) -> str | None:
    """Context flag: tight range over the last ``accu_hours`` with repeated absorption at its floor (or roof)."""
    if len(hours) < max(p.accu_hours, p.atr_len + 1):
        return None
    span = hours[-p.accu_hours:]
    top, bottom = max(w.high for w in span), min(w.low for w in span)
    atr = _atr(hours, p.atr_len)
    width = top - bottom
    if not atr or width > p.accu_atr_mult * atr:
        return None
    since = span[0].start_ms
    recent = [e for e in events if since <= e["at_ms"] <= now_ms]
    cvd = sum(w.delta for w in span)
    floor = sum(1 for e in recent if e["side"] == "VERKAUF" and e["extreme"] <= bottom + 0.25 * width)
    roof = sum(1 for e in recent if e["side"] == "KAUF" and e["extreme"] >= top - 0.25 * width)
    if floor >= p.accu_min_events and cvd >= 0:
        return "AKKUMULATION"
    if roof >= p.accu_min_events and cvd <= 0:
        return "DISTRIBUTION"
    return None


# -- simulation ---------------------------------------------------------------------------------------------------
def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _swings(hours: Sequence[Window], side: int) -> list[tuple[int, str, float]]:
    out = []
    for i in range(side, len(hours) - side):
        mid = hours[i]
        around = hours[i - side:i] + hours[i + 1:i + side + 1]
        if all(mid.high > w.high for w in around):
            out.append((hours[i + side].end_ms, "Swing-Hoch 1h", mid.high))
        if all(mid.low < w.low for w in around):
            out.append((hours[i + side].end_ms, "Swing-Tief 1h", mid.low))
    return out


def simulate(days: Sequence[tuple[date, Sequence[MinuteBar], DayProfile | None]], started_ms: int,
             p: Params = PARAMS) -> dict[str, Any]:
    """Run the rule over consecutive days (oldest first; the last may be today's closed minutes)."""
    bars: list[MinuteBar] = []
    profiles: dict[int, DayProfile | None] = {}
    for day, day_bars, profile in days:
        bars.extend(day_bars)
        profiles[int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)] = profile
    events: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    windows: list[Window] = []
    zones = Zones()
    pending: dict[str, Any] | None = None
    pos: dict[str, Any] | None = None
    exit_next: str | None = None
    current_day = None
    for idx, bar in enumerate(bars):
        day_start = bar.window_start_ms // DAY_MS * DAY_MS
        if day_start != current_day:
            current_day = day_start
            prev = profiles.get(day_start - DAY_MS)
            prev_bars = [b for b in bars[max(0, idx - 1440):idx] if b.has_trades and b.window_start_ms >= day_start - DAY_MS]
            zones.day = profile_levels(prev, p.value_area) if prev is not None else {}
            if prev_bars:
                zones.day["VT Hoch"] = max(_px(b.high_price_e8) for b in prev_bars)
                zones.day["VT Tief"] = min(_px(b.low_price_e8) for b in prev_bars)
        if not bar.has_trades:
            continue
        o, h, l, c = (_px(bar.first_price_e8), _px(bar.high_price_e8), _px(bar.low_price_e8), _px(bar.last_price_e8))
        # 1) a pending exit (decided on the last window close) or entry fills at this minute's open
        if pos is not None and exit_next:
            _close(pos, o * (1 - p.slippage if pos["direction"] == "LONG" else 1 + p.slippage), bar.window_start_ms, exit_next, p)
            trades.append(pos)
            pos, exit_next = None, None
        if pending is not None and pending.get("fill_next") and pos is None:
            pos = _open(pending, o, bar.window_start_ms, p)
            pending = None
        # 2) the open position against this minute
        if pos is not None:
            _manage(pos, h, l, bar.window_start_ms, p)
            if pos.get("closed_at"):
                trades.append(pos)
                pos = None
        # 3) a waiting event: invalidated, or triggered (fill at the next minute's open)
        if pending is not None and not pending.get("fill_next"):
            pending["waited"] += 1
            long = pending["direction"] == "LONG"
            if (long and l < pending["extreme"]) or (not long and h > pending["extreme"]):
                pending["event"]["ergebnis"] = "Extrem gebrochen vor Einstieg"
                pending = None
            elif (long and c > pending["close"]) or (not long and c < pending["close"]):
                pending["fill_next"] = True
            elif pending["waited"] >= p.trigger_minutes:
                pending["event"]["ergebnis"] = "kein Auslöser in 15 Minuten"
                pending = None
        # 4) window close: detect
        end_ms = bar.window_start_ms + MINUTE_MS
        if end_ms % (p.window_min * MINUTE_MS):
            continue
        start = bar.window_start_ms - (p.window_min - 1) * MINUTE_MS
        chunk = [b for b in bars[max(0, idx - p.window_min + 1):idx + 1] if b.window_start_ms >= start]
        win = window_of(chunk)
        if win is None:
            continue
        hit = detect(win, windows, p)
        if hit is not None:
            hours = _hours([b for b in bars[max(0, idx - p.swing_keep_h * 60 - 60):idx + 1]])
            zones.swings = _swings(hours, p.swing_side)
            zone = zones.near(hit["extreme"], end_ms, p)
            event = {"at_ms": end_ms, "at": _iso(end_ms), **hit,
                     "zone": {"name": zone[0], "price": round(zone[1], 2)} if zone else None,
                     "footprint_extrem": extreme_imbalance(profiles.get(win.start_ms // DAY_MS * DAY_MS), win, hit["extreme"]),
                     "kontext": accumulation(hours, events, end_ms, p), "zaehlt": end_ms >= started_ms}
            atr = _atr(windows + [win], p.atr_len)
            # counter-absorption ends the open trade (fill at the next minute's open)
            if pos is not None and hit["direction"] != pos["direction"] and (zone or not p.exit_needs_zone):
                exit_next = "Gegen-Absorption"
                event["ergebnis"] = f"Ausstieg Trade {pos['id']}"
            elif zone and pos is None and pending is None and atr and event["zaehlt"]:
                pending = {"event": event, "direction": hit["direction"], "extreme": hit["extreme"], "close": hit["close"],
                           "atr": atr, "waited": 0, "zone": event["zone"], "kontext": event["kontext"]}
                event["ergebnis"] = "wartet auf Auslöser"
            else:
                event["ergebnis"] = ("ohne Zone" if not zone else "Position offen" if pos is not None
                                     else "vor Start" if not event["zaehlt"] else "kein ATR")
            events.append(event)
        windows.append(win)
    if pending is not None and pending["event"].get("ergebnis") == "wartet auf Auslöser" and pending.get("fill_next"):
        pending["event"]["ergebnis"] = "ausgelöst, Fill zur nächsten Minute"
    return {"events": [e for e in events if e["zaehlt"]], "trades": trades, "open": pos,
            "last_minute": _iso(bars[-1].window_start_ms + MINUTE_MS) if bars else None}


def _open(pending: dict[str, Any], open_price: float, at_ms: int, p: Params) -> dict[str, Any] | None:
    long = pending["direction"] == "LONG"
    fill = open_price * (1 + p.slippage if long else 1 - p.slippage)
    stop = pending["extreme"] - p.stop_atr_mult * pending["atr"] if long else pending["extreme"] + p.stop_atr_mult * pending["atr"]
    risk = (fill - stop) if long else (stop - fill)
    event = pending["event"]
    if risk <= 0:
        event["ergebnis"] = "Fill schon hinter dem Stop"
        return None
    cost_r = (2 * p.fee * fill + p.slippage * fill + p.stop_slippage * stop) / risk
    event["ergebnis"] = "Einstieg"
    trade = {"id": f"{pending['direction'][0]}-{_iso(at_ms)}", "direction": pending["direction"],
             "event_at": event["at"], "zone": pending["zone"], "kontext": pending["kontext"],
             "filled_at": _iso(at_ms), "fill": round(fill, 2), "stop": round(stop, 2), "stop_start": round(stop, 2),
             "risk_pct": round(risk / fill * 100, 4), "cost_r": round(cost_r, 4),
             "kostenblockiert": cost_r > p.max_cost_r, "breakeven": False,
             "event": {k: event[k] for k in ("vol_ratio", "delta_btc", "delta_share", "large_trades", "largest_btc",
                                             "tempo", "cvd_60m_btc", "cvd_divergenz", "footprint_extrem")},
             "ref_fix": {"target": round(fill + p.fix_r * risk if pending["direction"] == "LONG" else fill - p.fix_r * risk, 2)}}
    event["trade"] = trade["id"]
    return trade


def _manage(pos: dict[str, Any], high: float, low: float, at_ms: int, p: Params) -> None:
    long = pos["direction"] == "LONG"
    fill, start = pos["fill"], pos["stop_start"]
    risk = (fill - start) if long else (start - fill)
    ref = pos["ref_fix"]
    if "net_r" not in ref:   # reference: original stop and fixed target, stop first when both lie in one minute
        if (long and low <= start) or (not long and high >= start):
            ref["net_r"] = _net(long, fill, start * (1 - p.stop_slippage if long else 1 + p.stop_slippage), risk, p)
        elif (long and high >= ref["target"]) or (not long and low <= ref["target"]):
            ref["net_r"] = _net(long, fill, ref["target"], risk, p)
    stop = pos["stop"]
    if (long and low <= stop) or (not long and high >= stop):
        price = stop * (1 - p.stop_slippage if long else 1 + p.stop_slippage)
        _close(pos, price, at_ms, "Einstand" if pos["breakeven"] else "Stop", p)
        return
    best = high if long else low
    if not pos["breakeven"] and ((best - fill) if long else (fill - best)) >= p.breakeven_r * risk:
        pos["breakeven"] = True
        pos["stop"] = fill   # active from the next minute on


def _net(long: bool, fill: float, exit_price: float, risk: float, p: Params) -> float:
    gross = ((exit_price - fill) if long else (fill - exit_price)) / risk
    return round(gross - p.fee * (fill + exit_price) / risk, 4)


def _close(pos: dict[str, Any], price: float, at_ms: int, reason: str, p: Params) -> None:
    long = pos["direction"] == "LONG"
    risk = (pos["fill"] - pos["stop_start"]) if long else (pos["stop_start"] - pos["fill"])
    pos.update(closed_at=_iso(at_ms), exit=round(price, 2), exit_reason=reason, net_r=_net(long, pos["fill"], price, risk, p))
    filled = datetime.fromisoformat(pos["filled_at"])
    closed = datetime.fromisoformat(pos["closed_at"])
    pos["funding_intervalle"] = sum(1 for k in range(int((closed - filled).total_seconds() // 3600) + 2)
                                    if (t := filled.replace(minute=0, second=0, microsecond=0) + timedelta(hours=k)) > filled
                                    and t <= closed and t.hour % 8 == 0)


# -- verdict ------------------------------------------------------------------------------------------------------
def evaluate(trades: Iterable[dict[str, Any]], p: Params = PARAMS) -> dict[str, Any]:
    closed = [t for t in trades if t.get("closed_at")]
    counted = [float(t["net_r"]) for t in closed if not t.get("kostenblockiert")]
    blocked = [float(t["net_r"]) for t in closed if t.get("kostenblockiert")]
    ref = [float(t["ref_fix"]["net_r"]) for t in closed if not t.get("kostenblockiert") and "net_r" in t.get("ref_fix", {})]
    verdict, lower = "NOCH_NICHT_BEURTEILBAR", None
    if len(counted) >= p.min_trades:
        rng = random.Random(p.bootstrap_seed)
        means = sorted(mean(rng.choices(counted, k=len(counted))) for _ in range(p.bootstrap_draws))
        lower = round(means[int(0.05 * p.bootstrap_draws)], 4)
        verdict = "BESTANDEN" if mean(counted) >= p.min_mean_r and lower > 0 else "NICHT_BESTANDEN"
    reasons: dict[str, int] = {}
    for t in closed:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    def row(values: list[float]) -> dict[str, Any]:
        return {"n": len(values), "mittel_r": round(mean(values), 4) if values else None, "summe_r": round(sum(values), 4)}
    return {"rule": RULE, "gezaehlt": row(counted), "kostenblockiert": row(blocked), "referenz_fix_2r": row(ref),
            "ausstiege": reasons, "mit_kontext": row([float(t["net_r"]) for t in closed if t.get("kontext") and not t.get("kostenblockiert")]),
            "noetig": p.min_trades, "untere_grenze_r": lower, "urteil": verdict,
            "hinweis": "Papier, Spot-Daten, Funding nicht eingerechnet (nur Intervalle gezählt). Kein Filter aktiv."}


# -- journal ------------------------------------------------------------------------------------------------------
def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def chain(previous: Sequence[dict[str, Any]], fresh: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Closed trades already written never change; new closed trades are appended with a hash chain."""
    kept = list(previous)
    known = {t["id"]: t for t in kept}
    deviations = []
    last = kept[-1]["hash"] if kept else ""
    for trade in fresh:
        if not trade.get("closed_at"):
            continue
        body = {k: v for k, v in trade.items() if k != "hash"}
        if trade["id"] in known:
            old = {k: v for k, v in known[trade["id"]].items() if k != "hash"}
            if json.dumps(old, sort_keys=True, default=str) != json.dumps(body, sort_keys=True, default=str):
                deviations.append(trade["id"])
            continue
        last = hashlib.sha256((last + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()
        kept.append({**body, "hash": last})
    return kept, deviations


Loader = Callable[[date], tuple[Sequence[MinuteBar], DayProfile | None] | None]


def step(folder: Path | str, load_day: Loader, today: date, *, now: datetime | None = None,
         partial: Callable[[date], tuple[Sequence[MinuteBar], DayProfile | None] | None] | None = None,
         p: Params = PARAMS) -> dict[str, Any]:
    """One run: load warm-up days, all days since the start and today's closed minutes; recompute; append."""
    folder = Path(folder)
    now = now or datetime.now(timezone.utc)
    start_path = folder / "start.json"
    if start_path.exists():
        start = json.loads(start_path.read_text(encoding="utf-8"))
        if start.get("digest") != p.digest():
            raise RuntimeError("Regel-Parameter geändert: neuer Ordner nötig, alte Trades zählen nicht für die neue Version")
    else:
        start = {"rule": RULE, "digest": p.digest(), "started_at": now.isoformat(), "params": asdict(p),
                 "status": "ENTWURF (nicht eingefroren)"}
        _write(start_path, start)
    started = datetime.fromisoformat(start["started_at"])
    first = started.date() - timedelta(days=WARMUP_DAYS)
    days, missing = [], None
    day = first
    while day < today:
        got = load_day(day)
        if got is None:
            missing = day.isoformat()
            break
        days.append((day, got[0], got[1]))
        day += timedelta(days=1)
    if missing is None and partial is not None:
        part = partial(today)
        if part is not None:
            days.append((today, part[0], part[1]))
    result = simulate(days, int(started.timestamp() * 1000), p)
    journal_path = folder / "journal.json"
    old = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}
    closed, deviations = chain(old.get("trades", []), result["trades"])
    journal = {"rule": RULE, "digest": p.digest(), "started_at": start["started_at"], "checked_at": now.isoformat(),
               "letzte_minute": result["last_minute"], "fehlender_tag": missing, "trades": closed,
               "offen": result["open"], "ereignisse": result["events"][-500:],
               "abweichungen": sorted(set(old.get("abweichungen", [])) | set(deviations)),
               "auswertung": evaluate(closed, p)}
    _write(journal_path, journal)
    return {"checked_at": journal["checked_at"], "letzte_minute": journal["letzte_minute"],
            "fehlender_tag": missing, "trades": len(closed), "offen": bool(result["open"]),
            "ereignisse": len(result["events"]), "urteil": journal["auswertung"]["urteil"],
            "abweichungen": len(journal["abweichungen"])}


def live_loaders(folder: Path | str, trades_root: Path | str):
    """Day and partial loaders on the stage-B data (own archive cache, the recorder is only read)."""
    from src.research_lab.forward.live_recorder import TradeRecorder
    from src.research_lab.forward.of_live import LiveStore
    from src.research_lab.orderflow_ml.store import PAPER_RELEASE, MinuteBarStore

    store = LiveStore(MinuteBarStore(Path(folder) / "store", release=PAPER_RELEASE), TradeRecorder(trades_root))

    def load_day(day: date):
        try:
            if store.cached(day) is None:
                store.fetch(day)
            return store.load(day), store.load_profile(day)
        except Exception:  # noqa: BLE001 - missing day: the run stops there, as stage B
            return None

    def partial(day: date):
        part = store.partial(day)
        return (part[0], part[1]) if part else None

    return load_day, partial


def status(folder: Path | str) -> dict[str, Any] | None:
    path = Path(folder) / "journal.json"
    if not path.exists():
        return None
    journal = json.loads(path.read_text(encoding="utf-8"))
    return {k: journal.get(k) for k in ("rule", "started_at", "checked_at", "letzte_minute", "fehlender_tag",
                                        "offen", "abweichungen", "auswertung")}
