"""Live-Orderflow-Lage: TIM folgt dem laufenden Trade-Strom und beschreibt die Welle (Paket 1, 08.11.2026).

Bisher landen Spot-Trades in PostgreSQL, Delta und Footprint entstehen daraus nur für den Chart; die
Plan-Entscheidung sieht davon nichts. Dieses Modul hält die letzten Minuten der Spot-aggTrades im
Speicher (``LiveOrderflowTracker.ingest``) und beschreibt daraus alle paar Sekunden den Zustand
(``snapshot``):

- Fenster 1m/5m/15m: Volumen, Delta, Käufer-/Verkäuferanteil, Tempo gegenüber den letzten 20 Minuten,
- Tages-CVD, Tages-Hoch/-Tief (UTC-Tag),
- die Welle: Richtung, Stärke 0-3, Phase (aufbauend / läuft / ebbt ab) und Exhaustion,
- Orderflow an den nahen Leveln (Vortages-VAH/VAL/POC, Tages-POC, Tages-Hoch/-Tief): Bid x Ask,
  Imbalance, Absorption (viel Volumen am Level, Preis kommt nicht durch),
- Perp-Delta der letzten 5 und 15 Minuten aus dem Perp-Store (5-Minuten-Körbe, grober als Spot).

Alle Schwellen stehen in ``THRESHOLDS`` und sind unkalibrierte Startwerte (Präreg OF2 entscheidet
später). Nichts hier handelt, schreibt einen Plan oder ändert einen Score: reine Beschreibung, als
Datei ``data/orderflow/orderflow_lage.json`` für Chart, Control Center und den Hermes-Leser.
"""

from __future__ import annotations

import json
import os
from bisect import bisect_left
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from src.models.market_data import Trade

SCHEMA_VERSION = "orderflow-lage/1"
DEFAULT_PATH = Path("data/orderflow/orderflow_lage.json")
WINDOWS = {"1m": 60, "5m": 300, "15m": 900}
KEEP_SECONDS = 1800  # 15m window plus 20 one-minute baseline buckets, with reserve
BASELINE_MINUTES = 20
LEVEL_RANGE_PCT = 0.6  # levels farther away than this share of the price are not reported
THRESHOLDS = {
    "direction_share": 0.15,  # |delta| / volume of the 5m window needed for a direction
    "tempo_strength": (1.0, 1.6, 2.5),  # tempo ratio bounds for strength 1, 2, 3
    "fade_ratio": 0.5,  # last minute below this share of the 3-minute peak = fading
    "stall_range_share": 0.3,  # 1m range below this share of the 5m range = price stalls
    "imbalance_ratio": 3.0,  # ask/bid (or bid/ask) at a level
    "absorption_volume_factor": 3.0,  # level volume vs. the median level volume in the 15m window
}


def _epoch(moment: datetime) -> float:
    return moment.astimezone(timezone.utc).timestamp()


def _day_start(moment: datetime) -> float:
    utc = moment.astimezone(timezone.utc)
    return _epoch(utc.replace(hour=0, minute=0, second=0, microsecond=0))


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


class LiveOrderflowTracker:
    """Rolling store of the last ``keep_seconds`` of trades for one spot symbol."""

    def __init__(self, symbol: str, tick: float, keep_seconds: int = KEEP_SECONDS) -> None:
        if tick <= 0 or keep_seconds <= WINDOWS["15m"]:
            raise ValueError("tick must be > 0 and keep_seconds longer than the 15m window")
        self.symbol = symbol
        self.tick = float(tick)
        self.keep_seconds = int(keep_seconds)
        self._trades: deque[tuple[float, float, float, bool]] = deque()  # (time, price, qty, buyer aggressive)
        self.last_trade_id: int | None = None
        self.last_trade_time: datetime | None = None
        self.day_key: float | None = None
        self.day_cvd = 0.0
        self.day_high: float | None = None
        self.day_low: float | None = None
        self.last_price: float | None = None
        self.ingested = 0

    def ingest(self, trades: Iterable[Trade]) -> int:
        """Add new trades; a trade with an id not above the last seen one is skipped (replay-safe)."""
        added = 0
        for trade in trades:
            if trade.symbol != self.symbol:
                continue
            if trade.trade_id is not None and self.last_trade_id is not None and trade.trade_id <= self.last_trade_id:
                continue
            moment = _epoch(trade.event_time)
            if self._trades and moment < self._trades[-1][0]:
                continue  # out of order: the durable store already has it in order; ignore here
            buy = not bool(trade.buyer_is_maker) if trade.buyer_is_maker is not None else True
            day = _day_start(trade.event_time)
            if self.day_key != day:
                self.day_key, self.day_cvd, self.day_high, self.day_low = day, 0.0, None, None
            self.day_cvd += trade.quantity if buy else -trade.quantity
            self.day_high = trade.price if self.day_high is None else max(self.day_high, trade.price)
            self.day_low = trade.price if self.day_low is None else min(self.day_low, trade.price)
            self._trades.append((moment, float(trade.price), float(trade.quantity), buy))
            if trade.trade_id is not None:
                self.last_trade_id = trade.trade_id
            self.last_trade_time = trade.event_time
            self.last_price = float(trade.price)
            added += 1
        self.ingested += added
        return added

    def _prune(self, now: float) -> None:
        limit = now - self.keep_seconds
        while self._trades and self._trades[0][0] < limit:
            self._trades.popleft()

    def _since(self, start: float) -> Sequence[tuple[float, float, float, bool]]:
        times = [t[0] for t in self._trades]
        index = bisect_left(times, start)
        return list(self._trades)[index:]

    @staticmethod
    def _window(trades: Sequence[tuple[float, float, float, bool]]) -> dict[str, Any]:
        buy = sum(q for _, _, q, b in trades if b)
        sell = sum(q for _, _, q, b in trades if not b)
        volume = buy + sell
        prices = [p for _, p, _, _ in trades]
        return {"trades": len(trades), "volume": _round(volume), "delta": _round(buy - sell),
                "buy_share": _round(buy / volume, 3) if volume else None,
                "high": max(prices) if prices else None, "low": min(prices) if prices else None,
                "range": _round(max(prices) - min(prices), 2) if prices else 0.0}

    def _minutes(self, now: float, count: int) -> list[dict[str, Any]]:
        """Per-minute windows, oldest first, the last one ending at ``now``."""
        trades = self._since(now - 60 * count)
        buckets: list[list[tuple[float, float, float, bool]]] = [[] for _ in range(count)]
        for item in trades:
            index = int((item[0] - (now - 60 * count)) // 60)
            if 0 <= index < count:
                buckets[index].append(item)
        return [self._window(bucket) for bucket in buckets]

    def snapshot(self, now: datetime, levels: Sequence[Mapping[str, Any]] = (),
                 perp_store: Mapping[str, Any] | None = None,
                 day_profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Describe the orderflow at ``now``.

        ``levels`` are ``{"name", "price"}``; ``perp_store`` is the perp footprint store; ``day_profile`` is the
        running day's volume profile from the spot store (``footprint_data.volume_profiles``), which carries the whole
        UTC day while the tracker itself only holds the last ``keep_seconds`` (the tracker's own day values start at
        the runtime start, 1b fix 08.11.2026).
        """
        moment = _epoch(now)
        self._prune(moment)
        windows = {name: self._window(self._since(moment - seconds)) for name, seconds in WINDOWS.items()}
        minutes = self._minutes(moment, BASELINE_MINUTES + 3)
        baseline = [m["volume"] for m in minutes[:BASELINE_MINUTES] if m["volume"] > 0]
        last_three = minutes[-3:]
        tempo = (last_three[-1]["volume"] / median(baseline)) if baseline and last_three else None
        price = self.last_price
        wave = _wave(windows, last_three, tempo)
        day = _day_values(self, day_profile)
        own_levels = list(levels)
        if day["high"] is not None:
            own_levels += [{"name": "Tages-Hoch", "price": day["high"]}, {"name": "Tages-Tief", "price": day["low"]}]
        level_rows = _levels(self._since(moment - WINDOWS["15m"]), own_levels, price, self.tick) if price else []
        perp = _perp(perp_store, moment)
        stale = self.last_trade_time is None or moment - _epoch(self.last_trade_time) > 120
        state = {
            "schema": SCHEMA_VERSION, "symbol": self.symbol, "as_of": now.astimezone(timezone.utc).isoformat(),
            "price": price, "last_trade_at": self.last_trade_time.astimezone(timezone.utc).isoformat() if self.last_trade_time else None,
            "stale": stale, "windows": windows, "tempo": _round(tempo, 2) if tempo is not None else None,
            "day": day,
            "wave": wave, "levels": level_rows, "perp": perp, "thresholds": THRESHOLDS,
        }
        state["text"] = describe(state)
        return state


def _day_values(tracker: LiveOrderflowTracker, profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """Whole-day CVD/high/low from the running day profile when there is one, else the tracker's own since start."""
    own = {"cvd": _round(tracker.day_cvd), "high": tracker.day_high, "low": tracker.day_low, "source": "seit Start der Runtime"}
    if not profile or not profile.get("rows"):
        return own
    prices = [float(r["price"]) for r in profile["rows"] if r.get("volume")]
    if not prices:
        return own
    step = float(profile.get("step") or 0.0)
    high, low = max(prices) + step, min(prices)
    if tracker.day_high is not None:
        high, low = max(high, tracker.day_high), min(low, tracker.day_low)
    return {"cvd": _round(float(profile.get("delta") or 0.0)), "high": high, "low": low,
            "source": "Tagesprofil des Spot-Stores (bis 2 min alt) plus Trades seit Start"}


def _wave(windows: Mapping[str, Mapping[str, Any]], last_three: Sequence[Mapping[str, Any]], tempo: float | None) -> dict[str, Any]:
    five = windows["5m"]
    direction = "keine"
    if five["volume"] and abs(five["delta"]) / five["volume"] >= THRESHOLDS["direction_share"]:
        direction = "auf" if five["delta"] > 0 else "ab"
    strength = 0
    if tempo is not None and direction != "keine":
        strength = sum(1 for bound in THRESHOLDS["tempo_strength"] if tempo >= bound)
    sign = 1 if direction == "auf" else -1
    deltas = [m["delta"] * sign for m in last_three]  # positive = with the wave
    volumes = [m["volume"] for m in last_three]
    phase = "keine"
    exhaustion = False
    if direction != "keine" and len(last_three) == 3 and volumes[-1] > 0:
        peak = max(volumes)
        stalled = bool(five["range"]) and windows["1m"]["range"] < THRESHOLDS["stall_range_share"] * five["range"]
        if deltas[0] < deltas[1] < deltas[2] and volumes[2] >= volumes[1]:
            phase = "aufbauend"
        elif volumes[-1] < THRESHOLDS["fade_ratio"] * peak or deltas[-1] <= 0:
            phase = "ebbt ab"
            exhaustion = stalled or deltas[-1] <= 0
        else:
            phase = "läuft"
    return {"direction": direction, "strength": strength, "phase": phase, "exhaustion": exhaustion,
            "delta_per_minute": [_round(m["delta"]) for m in last_three]}


def _levels(trades: Sequence[tuple[float, float, float, bool]], levels: Sequence[Mapping[str, Any]],
            price: float, tick: float) -> list[dict[str, Any]]:
    by_level: dict[float, list[float]] = {}
    for _, p, q, b in trades:
        row = by_level.setdefault(round(p // tick * tick, 8), [0.0, 0.0])
        row[1 if b else 0] += q
    volumes = [a + b for a, b in by_level.values()]
    typical = median(volumes) if volumes else 0.0
    out = []
    for level in levels:
        try:
            target = float(level["price"])
        except (KeyError, TypeError, ValueError):
            continue
        distance_pct = (target - price) / price * 100
        if abs(distance_pct) > LEVEL_RANGE_PCT:
            continue
        tolerance = 2 * tick
        bid = ask = 0.0
        for key, (b, a) in by_level.items():
            if abs(key - target) <= tolerance:
                bid += b
                ask += a
        volume = bid + ask
        touched = any(abs(p - target) <= tolerance for _, p, _, _ in trades)
        side_now = "über" if price > target else "unter"
        broke = any((p - target) * (price - target) < -tolerance for _, p, _, _ in trades)  # traded on the far side
        ratio = (ask / bid) if bid else (float("inf") if ask else 0.0)
        imbalance = None
        if bid and ratio >= THRESHOLDS["imbalance_ratio"]:
            imbalance = "Käufer"
        elif ask and (1 / ratio if ratio else 0) >= THRESHOLDS["imbalance_ratio"]:
            imbalance = "Verkäufer"
        absorption = touched and not broke and typical > 0 and volume >= THRESHOLDS["absorption_volume_factor"] * typical
        out.append({"name": str(level.get("name", "Level")), "price": target, "distance_pct": _round(distance_pct, 3),
                    "side": side_now, "tested_15m": touched, "broke_through": broke, "bid": _round(bid), "ask": _round(ask),
                    "delta": _round(ask - bid), "imbalance": imbalance, "absorption": bool(absorption)})
    out.sort(key=lambda row: abs(row["distance_pct"]))
    return out


def _perp(store: Mapping[str, Any] | None, now: float) -> dict[str, Any] | None:
    if not store or not store.get("days"):
        return None
    bucket = int(store.get("bucket_seconds") or 300)
    delta5 = delta15 = volume15 = 0.0
    seen = False
    for rows in store["days"].values():
        for bucket_time, _level, bid, ask in rows:
            if bucket_time < now - 900 - bucket:
                continue
            seen = True
            delta15 += ask - bid
            volume15 += ask + bid
            if bucket_time >= now - 300 - bucket:
                delta5 += ask - bid
    if not seen:
        return {"status": "keine Daten in den letzten 15 Minuten"}
    return {"symbol": store.get("symbol"), "bucket_seconds": bucket, "delta_5m": _round(delta5), "delta_15m": _round(delta15),
            "volume_15m": _round(volume15), "updated_at": store.get("updated_at")}


def describe(state: Mapping[str, Any]) -> str:
    """Short German summary for the Control Center and the Hermes reader; every number comes from ``state``."""
    if state.get("stale") or state.get("price") is None:
        return "Orderflow-Lage: keine frischen Trades (Datenstrom prüfen)."
    wave = state["wave"]
    five = state["windows"]["5m"]
    parts = [f"Preis {state['price']:.0f}."]
    if wave["direction"] == "keine":
        parts.append(f"Keine klare Welle: Delta 5m {five['delta']:+.2f} bei {five['volume']:.1f} Volumen.")
    else:
        word = {"auf": "Käuferwelle", "ab": "Verkäuferwelle"}[wave["direction"]]
        parts.append(f"{word} Stärke {wave['strength']}/3, Phase {wave['phase']}; Delta 5m {five['delta']:+.2f}.")
        if wave["exhaustion"]:
            parts.append("Exhaustion: Tempo fällt, Preis stockt.")
    if state.get("tempo") is not None:
        parts.append(f"Tempo {state['tempo']:.1f}x der letzten 20 Minuten.")
    parts.append(f"Tages-CVD {state['day']['cvd']:+.1f}.")
    for level in state.get("levels", [])[:2]:
        flags = [f for f, on in (("Absorption", level["absorption"]), (f"Imbalance {level['imbalance']}", level["imbalance"])) if on]
        tag = f" ({', '.join(flags)})" if flags else ""
        parts.append(f"{level['name']} {level['price']:.0f} {level['distance_pct']:+.2f} %{tag}.")
    perp = state.get("perp") or {}
    if perp.get("delta_5m") is not None:
        parts.append(f"Perp-Delta 5m {perp['delta_5m']:+.1f}, 15m {perp['delta_15m']:+.1f}.")
    return " ".join(parts)


def levels_from_profiles(profiles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Prior-day VAH/VAL/POC and the running day's POC from ``footprint_data.volume_profiles``."""
    finished = [p for p in profiles if not p.get("running")]
    running = [p for p in profiles if p.get("running")]
    out: list[dict[str, Any]] = []
    if finished:
        prev = finished[-1]
        out += [{"name": "Vortag VAH", "price": prev["vah"]}, {"name": "Vortag VAL", "price": prev["val"]},
                {"name": "Vortag POC", "price": prev.get("poc_mid", prev["poc"])}]
    if running:
        out.append({"name": "Tages-POC", "price": running[-1].get("poc_mid", running[-1]["poc"])})
    return [row for row in out if row["price"] is not None]


def save(state: Mapping[str, Any], path: Path | str = DEFAULT_PATH) -> Path:
    """Write the state atomically (temp file + replace) so readers never see a half file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load(path: Path | str = DEFAULT_PATH) -> dict[str, Any] | None:
    target = Path(path)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None
