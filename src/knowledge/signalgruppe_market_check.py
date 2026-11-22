"""Market check and paper diary for Signalgruppe calls (paper only, no orders).

Per call the check answers one question: could TIM have taken this trade on Bitunix, and would it
have been worth it after costs? The answer is "tradable" or "not tradable" with one plain reason.

* Is the coin an open USDT futures contract at Bitunix?
* Is there enough trading (24 h turnover in USDT before the call)?
* Does the call name a stop (a trade without a stop is never entered)?
* Has the price already run away between the post and the moment TIM knew about it? TIM reads
  the channels a few times a day, so this lag is real; entry is the first bar at or after
  ``known_at``, never the posting time.
* Do round-trip costs stay small against the stop distance (and, with a target, is the net
  reward still at least as large as the net risk)?

Tradable calls go into the paper diary with entry, stop and target, kept per author. The thresholds
below are assumptions, not measurements; the Bitunix fee is the unverified VIP0 figure from
``src/research_lab/bitunix/contract.py``. Prices come from a snapshot file (see
``scripts/signalgruppe_paper_diary.py fetch``); without prices a call is reported as "no price data",
never guessed. Nothing here sends an order or posts anywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .signalgruppe_coin_analysis import analyse_coin
from .signalgruppe_channels import (
    PROFILES,
    STATUS_NOT_CHECKABLE,
    STATUS_OPEN,
    STATUS_STOPPED,
    STATUS_TARGET,
    PriceBar,
    TrackedCall,
    _author_key,
    check_outcome,
    has_chart_image,
)

__all__ = [
    "COST_PER_SIDE",
    "DiaryEntry",
    "Instrument",
    "MIN_QUOTE_VOLUME_24H",
    "MarketBar",
    "MarketSnapshot",
    "MarketVerdict",
    "author_scorecards",
    "build_diary",
    "check_market",
    "merge_diary",
    "render_diary_report",
]

# --- assumptions (documented in the module docstring and in every report) ---------------------
FEE_TAKER = Decimal("0.0006")  # Bitunix VIP0 taker, Uzi 10.11.2026, unverified (see contract.py)
SLIPPAGE_PER_SIDE = Decimal("0.0005")  # 0.05 % per fill, a flat guess; real spread/slippage not measured
COST_PER_SIDE = FEE_TAKER + SLIPPAGE_PER_SIDE
MIN_QUOTE_VOLUME_24H = Decimal("5000000")  # USDT turnover in the 24 h before the call
MAX_COST_SHARE_OF_RISK = Decimal("0.10")  # round-trip cost at most 10 % of the stop distance
# Small coins (Uzi 22.11.2026, "kleine Coins"): the group mostly calls coins far below the 5 Mio. line. They go into their
# own paper book: lower turnover floor, much higher assumed slippage, a quarter of the usual stake. All three numbers are
# settings, not measurements; real spread and depth of these coins are not recorded yet.
SMALL_MIN_QUOTE_VOLUME_24H = Decimal("100000")
SMALL_SLIPPAGE_PER_SIDE = Decimal("0.003")  # 0.3 % per fill
SMALL_MAX_COST_SHARE_OF_RISK = Decimal("0.25")
SMALL_STAKE_FACTOR = Decimal("0.25")
BOOK_NORMAL, BOOK_SMALL = "normal", "klein"
# A call read long after it was posted opens no paper trade: the entry would be at a price the author never meant.
# 12 h covers the three screen readings a day; a setting, not a measurement.
MAX_READ_DELAY = timedelta(hours=12)
# The same author naming the same coin and side again within this time, without new levels, is one call, not two.
REPEAT_WINDOW = timedelta(minutes=60)
MIN_NET_REWARD_TO_RISK = Decimal("1")  # with a target: net reward at least the net risk
RUNAWAY_SHARE = Decimal("0.5")  # price already covered half the way to the target
DRIFT_HOURS = (1, 4, 24, 72)  # control: plain price change after the entry, whatever stop or target does
MAX_STOP_DISTANCE = Decimal("0.30")  # a stop further than 30 % from the entry is a typo or another scale, not a trade
MIN_VOLUME_COVERAGE = Decimal("0.8")  # share of the 24 h window that must be covered by bars

CODE_TRADABLE = "tradable"
CODE_NO_DIRECTION = "no_direction"
CODE_NO_SYMBOL = "no_symbol"
CODE_NOT_LISTED = "not_listed"
CODE_NOT_OPEN = "not_open"
CODE_NO_PRICES = "no_prices"
CODE_THIN = "thin_volume"
CODE_READ_LATE = "read_too_late"
CODE_NO_STOP = "no_stop"
CODE_STOP_IN_IMAGE = "stop_maybe_in_image"
CODE_STOP_TOO_FAR = "stop_too_far"
CODE_TIM_NO_TRADE = "tim_no_trade"
CODE_STOP_HIT = "stop_hit_before_entry"
CODE_TARGET_REACHED = "target_reached_before_entry"
CODE_RAN_AWAY = "ran_away"
CODE_TOO_EXPENSIVE = "too_expensive"

_STATUS_DE = {"not_entered": "nicht eingestiegen", "open": "offen", "target_hit": "Ziel erreicht", "stopped": "Stop", "expired": "abgelaufen"}
_REASON_DE = {
    CODE_TRADABLE: "handelbar",
    CODE_NO_DIRECTION: "keine klare Richtung",
    CODE_NO_SYMBOL: "kein einzelner Coin genannt",
    CODE_NOT_LISTED: "Coin bei Bitunix nicht als Futures gelistet",
    CODE_NOT_OPEN: "Bitunix-Vertrag nicht offen",
    CODE_NO_PRICES: "keine Kursdaten",
    CODE_THIN: "zu wenig Handel",
    CODE_READ_LATE: "zu spät gelesen",
    CODE_NO_STOP: "kein Stop genannt",
    CODE_TIM_NO_TRADE: "TIM-Analyse: nicht handeln",
    CODE_STOP_TOO_FAR: "Stop unrealistisch weit weg",
    CODE_STOP_IN_IMAGE: "Stop evtl. nur im Chart-Bild, von Hand prüfen",
    CODE_STOP_HIT: "Stop schon vor unserem Einstieg erreicht",
    CODE_TARGET_REACHED: "Ziel schon vor unserem Einstieg erreicht",
    CODE_RAN_AWAY: "Preis seit dem Call weggelaufen",
    CODE_TOO_EXPENSIVE: "lohnt nach Gebühren nicht",
}


# --------------------------------------------------------------------------- snapshot

@dataclass(frozen=True, slots=True)
class MarketBar:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    quote_volume: Decimal

    def price_bar(self) -> PriceBar:
        return PriceBar(self.open_time, self.open, self.high, self.low, self.close)


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    status: str
    max_leverage: int = 0
    min_qty: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Bitunix contracts plus fixed-interval bars per pair (e.g. ``AKEUSDT``), as saved by the fetch command."""

    taken_at: datetime
    interval: timedelta
    instruments: Mapping[str, Instrument]
    bars: Mapping[str, Sequence[MarketBar]]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MarketSnapshot":
        taken_at = datetime.fromisoformat(str(payload["taken_at"]))
        if taken_at.tzinfo is None:
            raise ValueError("taken_at needs a time zone")
        instruments = {}
        for row in payload.get("instruments", ()):
            instruments[str(row["symbol"])] = Instrument(
                str(row["symbol"]), str(row.get("symbolStatus") or row.get("status") or ""),
                int(row.get("maxLeverage") or row.get("max_leverage") or 0), Decimal(str(row.get("minTradeVolume") or row.get("min_qty") or 0)))
        bars: dict[str, list[MarketBar]] = {}
        for symbol, rows in (payload.get("bars") or {}).items():
            parsed = [MarketBar(datetime.fromtimestamp(int(row["time"]) / 1000, tz=timezone.utc), Decimal(str(row["open"])), Decimal(str(row["high"])),
                                Decimal(str(row["low"])), Decimal(str(row["close"])), Decimal(str(row.get("quoteVol") or 0))) for row in rows]
            bars[str(symbol)] = sorted(parsed, key=lambda bar: bar.open_time)
        return cls(taken_at, timedelta(minutes=int(payload["interval_minutes"])), instruments, bars)

    @classmethod
    def load(cls, path: Path) -> "MarketSnapshot":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- market check

@dataclass(frozen=True, slots=True)
class MarketVerdict:
    tradable: bool
    code: str
    entry_time: datetime | None = None
    entry: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    quote_volume_24h: Decimal | None = None
    risk_pct: Decimal | None = None
    cost_pct: Decimal = COST_PER_SIDE * 2
    detail: str = ""
    rule: str = "autor"  # "autor": levels as the author wrote them; "tim_analyse": TIM's own analysis of a coin call without levels
    analysis: str = ""
    book: str = BOOK_NORMAL  # BOOK_SMALL: turnover between the small floor and the normal line, higher cost, quarter stake

    @property
    def reason(self) -> str:
        text = _REASON_DE[self.code]
        return f"{text} ({self.detail})" if self.detail else text


def _pair(symbol: str) -> str:
    return f"{symbol}USDT"


def _bar_at_or_after(bars: Sequence[MarketBar], when: datetime) -> MarketBar | None:
    return next((bar for bar in bars if bar.open_time >= when.replace(second=0, microsecond=0)), None)


def _entry_time(tracked: TrackedCall) -> datetime:
    """The first moment TIM could act: when the message was posted AND received (a later screen read means a later entry)."""
    return tracked.call.message.known_at


def check_market(tracked: TrackedCall, snapshot: MarketSnapshot) -> MarketVerdict:
    """Tradable or not, with the first reason that stops the call. Checks run in a fixed order."""
    verdict = _check_market(tracked, snapshot)
    small = verdict.quote_volume_24h is not None and SMALL_MIN_QUOTE_VOLUME_24H <= verdict.quote_volume_24h < MIN_QUOTE_VOLUME_24H
    return replace(verdict, book=BOOK_SMALL) if small else verdict


def _check_market(tracked: TrackedCall, snapshot: MarketSnapshot) -> MarketVerdict:
    if tracked.bias not in ("LONG", "SHORT"):
        return MarketVerdict(False, CODE_NO_DIRECTION)
    if not tracked.symbol:
        return MarketVerdict(False, CODE_NO_SYMBOL)
    pair = _pair(tracked.symbol)
    instrument = snapshot.instruments.get(pair)
    if instrument is None:
        return MarketVerdict(False, CODE_NOT_LISTED, detail=pair)
    if instrument.status.upper() != "OPEN":
        return MarketVerdict(False, CODE_NOT_OPEN, detail=f"{pair}: {instrument.status or 'unbekannt'}")
    bars = snapshot.bars.get(pair, ())
    message = tracked.call.message
    known = _entry_time(tracked)
    entry_bar = _bar_at_or_after(bars, known)
    posted_bar = _bar_at_or_after(bars, message.posted_at)
    if entry_bar is None or posted_bar is None:
        return MarketVerdict(False, CODE_NO_PRICES, detail=pair)

    window = [bar for bar in bars if known - timedelta(hours=24) <= bar.open_time < known]
    needed = Decimal(timedelta(hours=24) / snapshot.interval) * MIN_VOLUME_COVERAGE
    if Decimal(len(window)) < needed:
        return MarketVerdict(False, CODE_NO_PRICES, detail=f"{pair}: Kurse der 24 h vor dem Call fehlen")
    volume = sum((bar.quote_volume for bar in window), Decimal(0))
    small = volume < MIN_QUOTE_VOLUME_24H
    if volume < SMALL_MIN_QUOTE_VOLUME_24H:
        return MarketVerdict(False, CODE_THIN, quote_volume_24h=volume, detail=f"{volume / 1_000_000:.1f} Mio. USDT in 24 h")

    delay = known - message.posted_at
    if delay > MAX_READ_DELAY:
        return MarketVerdict(False, CODE_READ_LATE, entry_bar.open_time, entry_bar.open, quote_volume_24h=volume,
                             detail=f"{delay / timedelta(hours=1):.0f} h nach dem Post")

    # Levels are read against the price at the posting (that is what the author saw), prices from the bars.
    outcome = check_outcome(tracked, [bar.price_bar() for bar in bars], observed_at=snapshot.taken_at)
    stop, target = outcome.stop, outcome.target
    long = tracked.bias == "LONG"
    entry = entry_bar.open
    rule = "autor"
    analysis_text = ""
    if stop is None:
        if PROFILES[tracked.profile].coin_calls and target is None and not has_chart_image(message):
            # Only a coin is named ("Short ake"): the call is the trigger, TIM analyses the coin itself and recommends or declines.
            analysis = analyse_coin(bars, at=entry_bar.open_time, side=tracked.bias, interval=snapshot.interval)
            if analysis is None:
                return MarketVerdict(False, CODE_NO_PRICES, detail=f"{pair}: zu wenig Kerzen für die Analyse")
            analysis_text = analysis.text(tracked.symbol)
            if not analysis.tradable:
                return MarketVerdict(False, CODE_TIM_NO_TRADE, entry_bar.open_time, entry, quote_volume_24h=volume, detail=analysis.reason,
                                     rule="tim_analyse", analysis=analysis_text)
            rule, stop, target = "tim_analyse", analysis.stop, analysis.target
            if (entry <= stop or entry >= target) if long else (entry >= stop or entry <= target):
                return MarketVerdict(False, CODE_TIM_NO_TRADE, entry_bar.open_time, entry, quote_volume_24h=volume,
                                     detail="Kurs sprang beim Einstieg über Stop oder Ziel", rule=rule, analysis=analysis_text)
        else:
            code = CODE_STOP_IN_IMAGE if has_chart_image(message) else CODE_NO_STOP
            return MarketVerdict(False, code, entry_time=entry_bar.open_time, entry=entry_bar.open, target=target, quote_volume_24h=volume)
    # What happened between the post and our entry bar: stop or target touched already?
    gap = [bar for bar in bars if posted_bar.open_time <= bar.open_time < entry_bar.open_time] if rule == "autor" else []
    if any((bar.low <= stop if long else bar.high >= stop) for bar in gap) or (entry <= stop if long else entry >= stop):
        return MarketVerdict(False, CODE_STOP_HIT, entry_bar.open_time, entry, stop, target, volume)
    if target is not None and (any((bar.high >= target if long else bar.low <= target) for bar in gap) or (entry >= target if long else entry <= target)):
        return MarketVerdict(False, CODE_TARGET_REACHED, entry_bar.open_time, entry, stop, target, volume)
    moved = (entry - posted_bar.open) if long else (posted_bar.open - entry)
    risk = abs(entry - stop)
    if rule == "tim_analyse":
        if moved >= risk / 2:  # already half a stop distance in the call's favour since the post
            return MarketVerdict(False, CODE_RAN_AWAY, entry_bar.open_time, entry, stop, target, volume, rule=rule,
                                 detail="schon die halbe Stop-Distanz gelaufen", analysis=analysis_text)
    elif target is not None:
        way = abs(target - posted_bar.open)
        if way > 0 and moved / way >= RUNAWAY_SHARE:
            return MarketVerdict(False, CODE_RAN_AWAY, entry_bar.open_time, entry, stop, target, volume,
                                 detail=f"{moved / way * 100:.0f} % des Wegs zum Ziel schon gelaufen")
    elif moved >= risk:
        return MarketVerdict(False, CODE_RAN_AWAY, entry_bar.open_time, entry, stop, None, volume,
                             detail="schon mehr als die Stop-Distanz gelaufen")

    risk_pct = risk / entry
    if risk_pct > MAX_STOP_DISTANCE:
        return MarketVerdict(False, CODE_STOP_TOO_FAR, entry_bar.open_time, entry, stop, target, volume, risk_pct,
                             detail=f"Stop {risk_pct * 100:.0f} % vom Einstieg entfernt")
    cost_pct = (FEE_TAKER + (SMALL_SLIPPAGE_PER_SIDE if small else SLIPPAGE_PER_SIDE)) * 2
    if cost_pct > risk_pct * (SMALL_MAX_COST_SHARE_OF_RISK if small else MAX_COST_SHARE_OF_RISK):
        return MarketVerdict(False, CODE_TOO_EXPENSIVE, entry_bar.open_time, entry, stop, target, volume, risk_pct,
                             detail=f"Kosten {cost_pct * 100:.2f} % bei Stop-Abstand {risk_pct * 100:.2f} %")
    if target is not None:
        reward_pct = abs(target - entry) / entry
        if (reward_pct - cost_pct) / (risk_pct + cost_pct) < MIN_NET_REWARD_TO_RISK:
            return MarketVerdict(False, CODE_TOO_EXPENSIVE, entry_bar.open_time, entry, stop, target, volume, risk_pct,
                                 detail="Gewinn nach Kosten kleiner als Risiko")
    return MarketVerdict(True, CODE_TRADABLE, entry_bar.open_time, entry, stop, target, volume, risk_pct, cost_pct, rule=rule, analysis=analysis_text)


# --------------------------------------------------------------------------- paper diary

@dataclass(frozen=True, slots=True)
class DiaryEntry:
    message_id: str
    profile: str
    author: str
    channel: str
    symbol: str | None
    side: str
    posted_at: datetime
    verdict: str
    reason: str
    entry_time: datetime | None = None
    entry: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    status: str = "not_entered"  # not_entered | open | target_hit | stopped | expired
    exit_time: datetime | None = None
    exit_price: Decimal | None = None
    net_r: Decimal | None = None  # result in multiples of the risk, after costs
    text: str = ""
    rule: str = "autor"  # "autor" or "tim_analyse" (TIM's own analysis and levels, reported apart)
    analysis: str = ""  # TIM's short coin analysis, when it wrote one
    book: str = BOOK_NORMAL  # "klein": small-coin book (higher assumed cost, quarter stake), reported apart
    drift: dict | None = None  # control: price change in % in the call's direction 1/4/24/72 h after entry

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in self.__slots__:  # type: ignore[attr-defined]
            value = getattr(self, key)
            out[key] = value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, Decimal) else value
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DiaryEntry":
        values: dict[str, Any] = {}
        for key in cls.__slots__:  # type: ignore[attr-defined]
            value = payload.get(key)
            if value is not None and key in ("posted_at", "entry_time", "exit_time"):
                value = datetime.fromisoformat(value)
            elif value is not None and key in ("entry", "stop", "target", "exit_price", "net_r"):
                value = Decimal(value)
            values[key] = value
        return cls(**values)

    @property
    def entered(self) -> bool:
        return self.status != "not_entered"


def _price_at(bars: Sequence[MarketBar], when: datetime) -> Decimal | None:
    bar = _bar_at_or_after(bars, when)
    return bar.open if bar is not None else (bars[-1].close if bars else None)


def _drift(bars: Sequence[MarketBar], entry: Decimal, entry_time: datetime, long: bool, taken_at: datetime) -> dict:
    """Control without stop or target: how far the price moved in the call's direction after 1/4/24/72 h (only what already happened)."""
    result = {}
    for hours in DRIFT_HOURS:
        when = entry_time + timedelta(hours=hours)
        if when > taken_at:
            continue
        price = _price_at(bars, when)
        if price is not None:
            move = (price - entry) / entry * 100 * (1 if long else -1)
            result[f"{hours}h"] = f"{move:.2f}"
    return result


def _settle(tracked: TrackedCall, verdict: MarketVerdict, snapshot: MarketSnapshot) -> DiaryEntry:
    message = tracked.call.message
    base = dict(message_id=message.message_id, profile=tracked.profile, author=message.author_label, channel=message.channel_name or message.channel_id,
                symbol=tracked.symbol, side=tracked.bias, posted_at=message.posted_at, verdict=verdict.code, reason=verdict.reason,
                text=message.content)
    base.update(rule=verdict.rule, analysis=verdict.analysis, book=verdict.book)
    long = tracked.bias == "LONG"
    bars = snapshot.bars.get(_pair(tracked.symbol or ""), ())
    if verdict.entry is not None and verdict.entry_time is not None and bars:
        # control for every call with prices: did the coin move the author's way after TIM read it, whatever TIM decided?
        base["drift"] = _drift(bars, verdict.entry, verdict.entry_time, long, snapshot.taken_at)
    if not verdict.tradable or verdict.entry is None or verdict.stop is None or verdict.entry_time is None:
        return DiaryEntry(**base)
    risk = abs(verdict.entry - verdict.stop)
    cost_r = (verdict.cost_pct * verdict.entry) / risk
    deadline = verdict.entry_time + PROFILES[tracked.profile].horizon
    status, exit_time, exit_price = STATUS_OPEN, None, None
    for bar in (b for b in bars if verdict.entry_time <= b.open_time <= snapshot.taken_at):
        if bar.open_time > deadline:
            status, exit_time = "expired", deadline
            break
        hit_stop = bar.low <= verdict.stop if long else bar.high >= verdict.stop
        hit_target = verdict.target is not None and (bar.high >= verdict.target if long else bar.low <= verdict.target)
        if hit_stop:  # a bar that touches both counts as stopped: it does not say which came first
            status, exit_time = STATUS_STOPPED, bar.open_time
            break
        if hit_target:
            status, exit_time = STATUS_TARGET, bar.open_time
            break
    else:
        if snapshot.taken_at > deadline:
            status, exit_time = "expired", deadline
    if status == STATUS_STOPPED:
        exit_price = verdict.stop
    elif status == STATUS_TARGET:
        exit_price = verdict.target
    else:
        # marked at the deadline (expired) or at the latest bar (open)
        exit_price = _price_at(bars, exit_time) if exit_time is not None else bars[-1].close
    gross = ((exit_price - verdict.entry) if long else (verdict.entry - exit_price)) / risk if exit_price is not None else None
    net = None if gross is None else gross - cost_r
    return DiaryEntry(**base, entry_time=verdict.entry_time, entry=verdict.entry, stop=verdict.stop, target=verdict.target, status=status,
                      exit_time=exit_time, exit_price=exit_price, net_r=None if net is None else net.quantize(Decimal("0.01")))


def build_diary(calls: Mapping[str, Iterable[TrackedCall]], snapshot: MarketSnapshot, *, min_grade: Sequence[str] = ("A", "B")) -> list[DiaryEntry]:
    """One diary row per call of grade A/B (the others name no coin with a level or stop), oldest first.

    Channels whose calls come without levels (chart calls) list every directional call with a coin."""
    entries = []
    for tracked_calls in calls.values():
        last_seen: dict[tuple[str, str | None, str], datetime] = {}
        for tracked in sorted(tracked_calls, key=lambda item: item.call.message.posted_at):
            listed = PROFILES[tracked.profile].coin_calls and tracked.symbol and tracked.bias in ("LONG", "SHORT")
            if (tracked.call.grade not in min_grade and not listed) or tracked.call.message.known_at > snapshot.taken_at:
                continue
            message = tracked.call.message
            key = (_author_key(message.author_name), tracked.symbol, tracked.bias)
            earlier = last_seen.get(key)
            last_seen[key] = message.posted_at
            if tracked.symbol and earlier is not None and message.posted_at - earlier <= REPEAT_WINDOW and not tracked.call.guidance.levels:
                continue  # the same tip said again
            entries.append(_settle(tracked, check_market(tracked, snapshot), snapshot))
    return sorted(entries, key=lambda item: (item.posted_at, item.message_id))


def merge_diary(existing: Sequence[DiaryEntry], fresh: Sequence[DiaryEntry]) -> list[DiaryEntry]:
    """Keep what the diary decided at first sight, update only how the trade went on.

    An entered trade keeps its entry, stop and target forever; a row that was judged "no price data" is
    judged again. Rows that are no longer produced stay (a diary is never rewritten backwards).
    """
    merged = {item.message_id: item for item in existing}
    for item in fresh:
        old = merged.get(item.message_id)
        if old is None or old.verdict == CODE_NO_PRICES:
            merged[item.message_id] = item
        elif old.entered and item.entered and (old.entry, old.stop, old.target) == (item.entry, item.stop, item.target):
            merged[item.message_id] = item
    return sorted(merged.values(), key=lambda item: (item.posted_at, item.message_id))


def author_scorecards(entries: Sequence[DiaryEntry]) -> dict[str, dict[str, Any]]:
    """Per author: how many calls, how many were tradable and what the entered trades earned (in R, after costs)."""
    cards: dict[str, dict[str, Any]] = {}
    for entry in entries:
        own = entry.rule == "tim_analyse"
        small = entry.book == BOOK_SMALL and entry.entered
        card = cards.setdefault(f"{_author_key(entry.author)}{'|tim_analyse' if own else ''}{'|klein' if small else ''}", {
            "author": entry.author + (" (nur Coin genannt, TIM analysiert selbst)" if own else "") + (", kleine Coins" if small else ""), "direction": {}, "calls": 0, "tradable": 0, "target_hit": 0, "stopped": 0, "open": 0, "expired": 0,
            "net_r_closed": Decimal(0), "net_r_open": Decimal(0), "not_tradable_reasons": {}})
        card["calls"] += 1
        for horizon, move in (entry.drift or {}).items():
            seen = card["direction"].setdefault(horizon, {"calls": 0, "right": 0})
            seen["calls"] += 1
            seen["right"] += Decimal(move) > 0
        if entry.entered:
            card["tradable"] += 1
            card[entry.status] += 1
            card["net_r_open" if entry.status == STATUS_OPEN else "net_r_closed"] += entry.net_r or Decimal(0)
        else:
            card["not_tradable_reasons"][entry.verdict] = card["not_tradable_reasons"].get(entry.verdict, 0) + 1
    for card in cards.values():
        closed = card["target_hit"] + card["stopped"] + card["expired"]
        card["closed"] = closed
        card["avg_net_r_closed"] = None if closed == 0 else (card["net_r_closed"] / closed).quantize(Decimal("0.01"))
        card["net_r_closed"] = card["net_r_closed"].quantize(Decimal("0.01"))
        card["net_r_open"] = card["net_r_open"].quantize(Decimal("0.01"))
    return cards


def render_diary_report(entries: Sequence[DiaryEntry], generated_at: datetime) -> str:
    """Short German report, plain words: per author what was tradable and what the paper trades did."""
    cards = author_scorecards(entries)
    lines = [
        "# Signalgruppe-Calls: Papier-Tagebuch",
        "",
        f"Stand: {generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. Nur Papier, keine Orders. "
        "Annahmen: Gebühr 0,06 % je Seite (nicht bestätigt), Rutschen 0,05 % je Seite (Schätzung), mind. 5 Mio. USDT Handel in 24 h.",
        "Kleine Coins (0,1 bis 5 Mio. USDT Handel) laufen in einem eigenen Buch: Rutschen 0,3 % je Seite (Annahme), Viertel-Einsatz.",
        "Einstieg ist erst dann, wenn TIM den Beitrag gelesen hat, nicht beim Posten.",
        "Calls mit Stop vom Autor und Calls, bei denen nur ein Coin genannt wird (TIM analysiert dann selbst, Regeln coin-analyse/1.0), stehen getrennt.",
    ]
    for card in cards.values():
        reasons = ", ".join(f"{_REASON_DE[code]} {count}x" for code, count in sorted(card["not_tradable_reasons"].items(), key=lambda item: -item[1])) or "-"
        small = " (zu wenige Trades für ein Urteil)" if card["closed"] < 30 else ""
        average = "-" if card["avg_net_r_closed"] is None else f"{card['avg_net_r_closed']:+} R"
        lines += [
            "", f"## {card['author']}",
            f"- {card['calls']} Calls gelesen, {card['tradable']} handelbar, {card['calls'] - card['tradable']} nicht handelbar.",
            f"- Papier-Trades: {card['target_hit']} Ziel, {card['stopped']} Stop, {card['expired']} abgelaufen, {card['open']} offen. "
+ ("Noch nichts abgeschlossen." if card["closed"] == 0 else f"Abgeschlossen im Schnitt {average} je Trade nach Kosten{small}."),
            f"- Nicht handelbar wegen: {reasons}.",
        ]
        if card["direction"]:
            lines.append("- Lief der Kurs danach in Richtung des Calls? " + ", ".join(
                f"nach {horizon.replace('h', ' h')}: {seen['right']} von {seen['calls']}" for horizon, seen in card["direction"].items()) + ".")
    lines += ["", "## Einzelne Calls", "", "| Zeit (UTC) | Autor | Coin | Seite | Urteil | Einstieg | Stop | Ziel | Stand | Ergebnis (R) |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for item in entries:
        def fmt(value: Decimal | None) -> str:
            return "-" if value is None else f"{value.normalize():f}"
        lines.append(f"| {item.posted_at.astimezone(timezone.utc).strftime('%m-%d %H:%M')} | {item.author} | {item.symbol or '?'} | {item.side} | "
                     f"{item.reason} | {fmt(item.entry)} | {fmt(item.stop)} | {fmt(item.target)} | {_STATUS_DE[item.status]} | {fmt(item.net_r)} |")
    written = [item for item in entries if item.analysis]
    if written:
        lines += ["", "## TIM-Analysen", ""] + [f"- {item.posted_at.astimezone(timezone.utc).strftime('%m-%d %H:%M')} {item.author}: {item.analysis}" for item in written]
    return "\n".join(lines) + "\n"
