"""S19: orderflow thresholds measured on BTC (15m candles from the S8 store, spot 2020-2024).

Rules: docs/research_lab/studien/S19_ORDERFLOW_SCHWELLEN_BTC_PRAEREGISTRIERUNG_ENTWURF.md (version 0.2,
sections 3 to 5). Observation study without trades; the holdout from 2025-01-01 is never loaded.

    python -m src.research_lab.studies.s19 count    --bars <orderflow_ml root> --out DIR [--workers N] [--cache DIR]
    python -m src.research_lab.studies.s19 evaluate --bars <root> --out DIR [--workers N] [--cache DIR]

``count`` is the results-blind feasibility gate (section 5.1): it writes event and week counts per family,
grid value, direction and section, never a hit rate. ``evaluate`` (section 5, only after the rules are
frozen as 1.0 on Uzi's word) adds outcomes, lift, block bootstrap, Holm and the verdict per family.

Flags come from the engine's own reader (``analyze_footprint``) on a footprint built from the S8 day
profile, and from the engine's effort rules (``effort_context`` thresholds) on 15m candles. Reading the
days is the slow part; ``--workers`` splits the day range into contiguous stretches, one process each, so
the PS5 (16 threads) finishes a count run in minutes. ``--cache`` keeps one JSON file per day with the
per-candle readings, so ``evaluate`` reads nothing twice.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from multiprocessing import Pool
from pathlib import Path

from src.orderflow_scenario.engines.orderflow_interpretation import (
    EFFORT_BASELINE_CANDLES,
    HEAVY_VOLUME_RATIO,
    SHRINKING_RANGE_RATIO,
    THIN_VOLUME_RATIO,
)
from src.orderflow_scenario.footprint import (
    CLUSTER_RATIO,
    IMBALANCE_RATIO,
    STACK_MIN,
    THIN_EXTREME_RATIO,
    FootprintBar,
    FootprintLevel,
    FootprintSeries,
    analyze_footprint,
)
from src.research_lab.of2.candles import Candle, candle_from_bars
from src.research_lab.of2.footprint import DayFootprints
from src.research_lab.orderflow_ml.bars import E8, MINUTE_MS, DayProfile, MinuteBar
from src.research_lab.orderflow_ml.store import MinuteBarStore
from src.research_lab.protocol import HOLDOUT_START_MS
from src.research_lab.stats.inference import holm

VERSION = "0.2"
SEED = 19
DRAWS = 9_999
BLOCK_WEEKS = 4
CANDLE_MINUTES = 15
CANDLES_PER_DAY = 1_440 // CANDLE_MINUTES
CANDLE_MS = CANDLE_MINUTES * MINUTE_MS
HORIZONS = (4, 16)
MOVE_LOOKBACK = 4  # move direction = sign(close - close four candles earlier)
DEBOUNCE = 3  # no event if today's value of the family fired in one of the three candles before
MIN_LEVELS = 20  # traded price steps a candle needs for F4/F5
FP_STEP_PCT = 0.001  # footprint step 0.1 % of the day's first price (S8 bins merged, as OF2 does)
FLAT_FRACTION = 0.001  # engine: a close-to-close move below 0.1 % is FLAT
MIN_EVENTS = 500
MIN_WEEKS = 100
MIN_LIFT_PP = 3.0
REPLACE_MARGIN_PP = 2.0
ALPHA = 0.05
HOUR = 3_600_000
DAY = 24 * HOUR
WEEK = 7 * DAY
MONDAY_OFFSET = 4 * DAY  # 1970-01-05 00:00 UTC is a Monday
FIRST_DAY = date(2020, 1, 1)
LAST_DAY = date(2024, 12, 31)
UP, DOWN = "up", "down"
DIRECTIONS = (UP, DOWN)
TIME_BLOCKS = 6  # six UTC blocks of four hours (S17)


def _ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


SECTIONS = {"training": (_ms(FIRST_DAY), _ms(date(2023, 1, 1))), "validierung": (_ms(date(2023, 1, 1)), _ms(date(2025, 1, 1)))}


def section_of(time_ms: int) -> str | None:
    return next((name for name, (lo, hi) in SECTIONS.items() if lo <= time_ms < hi), None)


def week_of(time_ms: int) -> int:
    """Calendar week index, Monday 00:00 UTC to Sunday 24:00 UTC."""
    return (time_ms - MONDAY_OFFSET) // WEEK


def year_of(time_ms: int) -> int:
    return datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc).year


def time_block_of(time_ms: int) -> int:
    return (time_ms // HOUR) % 24 // (24 // TIME_BLOCKS)


# -- grid (section 4) ------------------------------------------------------------------------------
FAMILIES = ("I", "A", "C", "T", "H", "E")
FAMILY_NAMES = {"I": "Imbalance (Faktor x Stapel)", "A": "Auktionsrand (finished auction)", "C": "Absorptions-Cluster (Faktor)",
                "T": "Dünnes Extrem (Anteil)", "H": "Absorption mit Anstrengung (schwer)", "E": "Exhaustion (dünn x schrumpfend)"}
GRID: dict[str, tuple[tuple[float, ...], ...]] = {
    "I": tuple((f, s) for f in (3, 4, 5) for s in (2, 3, 4)),
    "A": ((),),
    "C": ((2,), (3,), (4,)),
    "T": ((0.20,), (0.25,), (0.30,)),
    "H": ((1.0,), (1.2,), (1.5,)),
    "E": tuple((t, s) for t in (0.6, 0.7, 0.8) for s in (0.7, 0.8, 0.9)),
}
TODAY: dict[str, tuple[float, ...]] = {
    "I": (int(IMBALANCE_RATIO), STACK_MIN), "A": (), "C": (int(CLUSTER_RATIO),), "T": (float(THIN_EXTREME_RATIO),),
    "H": (float(HEAVY_VOLUME_RATIO),), "E": (float(THIN_VOLUME_RATIO), float(SHRINKING_RANGE_RATIO)),
}
# Expected direction R(K) in section 4: "continuation" follows the flag's side, "reversal" goes against it.
EXPECTATION = {"I": "Fortsetzung in Richtung der Imbalance", "A": "Umkehr gegen die Bewegung", "C": "Umkehr gegen den Aggressor",
               "T": "Umkehr gegen die Bewegung", "H": "Umkehr gegen den Aggressor", "E": "Umkehr gegen den Aggressor"}


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def flag_key(family: str, value: Sequence[float]) -> str:
    return f"{family}:{'x'.join(_fmt(v) for v in value) or '-'}"


FLAG_KEYS: tuple[str, ...] = tuple(flag_key(family, value) for family in FAMILIES for value in GRID[family])
TODAY_KEYS: dict[str, str] = {family: flag_key(family, TODAY[family]) for family in FAMILIES}
HYPOTHESES = len(FLAG_KEYS) * len(HORIZONS) * len(DIRECTIONS)  # 28 x 2 x 2 = 112


def family_of(key: str) -> str:
    return key.split(":", 1)[0]


# -- per-candle reading -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Reading:
    """One 15m candle: close and every flag (``key|direction``) that fired on it."""

    start: int
    close: float
    traded: bool
    levels: int  # traded price steps of the footprint (0 without trades)
    flags: tuple[str, ...]

    def as_row(self) -> list:
        return [self.start, self.close, int(self.traded), self.levels, list(self.flags)]

    @classmethod
    def from_row(cls, row: Sequence) -> Reading:
        return cls(int(row[0]), float(row[1]), bool(row[2]), int(row[3]), tuple(row[4]))


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def footprint_bar(fp, candle: Candle) -> FootprintBar | None:
    """Engine footprint bar from an OF2 footprint: price = bin lower edge, bid = aggressive sells, ask = aggressive buys."""
    if fp.empty:
        return None
    step = Decimal(str(fp.step))
    levels = tuple(FootprintLevel(Decimal(b) * step, Decimal(sell), Decimal(buy)) for b, buy, sell in fp.bins)
    return FootprintBar(levels=levels, open=Decimal(str(candle.open)), close=Decimal(str(candle.close)))


def effort(history: Sequence[Candle], candle: Candle) -> tuple[float | None, float | None]:
    """(volume ratio, range ratio) of the candle against the previous candles, as ``effort_context`` does."""
    if len(history) < 2:
        return None, None
    previous = [c for c in history[-EFFORT_BASELINE_CANDLES:] if c.volume > 0]
    if len(previous) < 2:
        return None, None
    mean_volume = sum(c.volume for c in previous) / len(previous)
    mean_range = sum(c.range for c in previous) / len(previous)
    volume_ratio = candle.volume / mean_volume
    range_ratio = candle.range / mean_range if mean_range > 0 else None
    return volume_ratio, range_ratio


def read_candle(history: Sequence[Candle], candle: Candle, bar: FootprintBar | None, step: float) -> Reading:
    """Every flag of the grid on one closed candle. ``history`` holds the earlier candles, oldest first."""
    if not candle.has_trades:
        return Reading(candle.start, 0.0, False, 0, ())
    flags: list[str] = []
    traded_levels = sum(1 for level in bar.levels if level.total > 0) if bar is not None else 0
    move = 0
    if len(history) >= MOVE_LOOKBACK and history[-MOVE_LOOKBACK].has_trades:
        move = _sign(candle.close - history[-MOVE_LOOKBACK].close)
    if bar is not None and traded_levels >= MIN_LEVELS:
        series = FootprintSeries(bars=(bar,), source="s19", tick_size=Decimal(str(step)))
        base = None
        for factor in (3, 4, 5):
            reading = analyze_footprint(series, imbalance_ratio=Decimal(factor), stack_min=2)
            for stack in (2, 3, 4):
                if reading.stacked_buy >= stack:
                    flags.append(f"{flag_key('I', (factor, stack))}|{UP}")
                if reading.stacked_sell >= stack:
                    flags.append(f"{flag_key('I', (factor, stack))}|{DOWN}")
            if factor == int(IMBALANCE_RATIO):
                base = reading
        assert base is not None
        if move > 0 and base.finished_high:
            flags.append(f"{TODAY_KEYS['A']}|{DOWN}")
        elif move < 0 and base.finished_low:
            flags.append(f"{TODAY_KEYS['A']}|{UP}")
        side, strength = base.summary.get("cluster_side"), base.summary.get("cluster_strength")
        if side and strength is not None:
            direction = DOWN if side == "PASSIVE_SELLERS" else UP
            for (ratio,) in GRID["C"]:
                if Decimal(strength) >= Decimal(str(ratio)):
                    flags.append(f"{flag_key('C', (ratio,))}|{direction}")
        extreme = base.summary.get("extreme_ratio")
        if extreme is not None and bar.direction in ("UP", "DOWN"):
            direction = DOWN if bar.direction == "UP" else UP
            for (share,) in GRID["T"]:
                if Decimal(extreme) <= Decimal(str(share)):
                    flags.append(f"{flag_key('T', (share,))}|{direction}")
    aggressor = _sign(candle.delta)
    volume_ratio, range_ratio = effort(history, candle)
    if aggressor and volume_ratio is not None and history and history[-1].has_trades and history[-1].close > 0:
        change = candle.close - history[-1].close
        response = "FLAT" if abs(change) / history[-1].close < FLAT_FRACTION else "UP" if change > 0 else "DOWN"
        against = response != "FLAT" and (aggressor > 0) != (response == "UP")
        with_price = response != "FLAT" and not against
        reversal = DOWN if aggressor > 0 else UP
        for (heavy,) in GRID["H"]:
            # R1 with effort / R2: aggression that does not move price (or leaves it flat) on heavy volume
            if volume_ratio >= heavy and (against or response == "FLAT"):
                flags.append(f"{flag_key('H', (heavy,))}|{reversal}")
        for thin, shrink in GRID["E"]:
            # R3: no progress on thin volume; R4: progress on thin volume and shrinking range
            if volume_ratio < thin and (against or (with_price and range_ratio is not None and range_ratio < shrink)):
                flags.append(f"{flag_key('E', (thin, shrink))}|{reversal}")
    return Reading(candle.start, candle.close, True, traded_levels, tuple(flags))


def read_day(bars: Sequence[MinuteBar], profile: DayProfile | None, history: list[Candle]) -> list[Reading]:
    """Readings of the 96 candles of one day; ``history`` is extended in place (keeps the last candles)."""
    day_start = bars[0].window_start_ms
    reference = next((b.first_price_e8 / E8 for b in bars if b.has_trades), 0.0)
    footprints = DayFootprints(profile, FP_STEP_PCT, reference) if profile is not None and reference > 0 else None
    out: list[Reading] = []
    for k in range(CANDLES_PER_DAY):
        start = day_start + k * CANDLE_MS
        candle = candle_from_bars(bars[k * CANDLE_MINUTES:(k + 1) * CANDLE_MINUTES], start, CANDLE_MINUTES)
        bar = footprint_bar(footprints.candle(start, CANDLE_MINUTES), candle) if footprints is not None and candle.has_trades else None
        out.append(read_candle(history, candle, bar, footprints.step if footprints is not None else 0.0))
        history.append(candle)
        del history[:-EFFORT_BASELINE_CANDLES - MOVE_LOOKBACK]
    return out


def _gap_day(day: date) -> list[Reading]:
    start = _ms(day)
    return [Reading(start + k * CANDLE_MS, 0.0, False, 0, ()) for k in range(CANDLES_PER_DAY)]


def _tail(history: Sequence[Candle]) -> list[list]:
    return [[c.start, c.minutes, c.trades, c.open, c.high, c.low, c.close, c.volume, c.delta] for c in history]


def read_days(root: Path | str, days: Sequence[date], warmup: int = 1, cache: Path | str | None = None) -> tuple[list[Reading], list[str]]:
    """Readings of ``days`` (contiguous, ascending); ``warmup`` earlier days only feed the candle history.

    A day the store refuses (missing, faulty, holdout) becomes 96 untraded candles and is listed as a gap.
    A cached day is not read again; its file carries the last candles so the next day starts from the
    same history as in a fresh run.
    """
    store = MinuteBarStore(root)
    cache_dir = Path(cache) if cache else None
    history: list[Candle] = []
    out: list[Reading] = []
    gaps: list[str] = []
    day = days[0] - timedelta(days=warmup)
    while day <= days[-1]:
        wanted = day >= days[0]
        cached = cache_dir / f"{day.isoformat()}.json" if cache_dir else None
        if cached is not None and cached.exists():
            payload = json.loads(cached.read_text())
            readings = [Reading.from_row(row) for row in payload["readings"]]
            gap = bool(payload.get("gap"))
            history[:] = [Candle(*row) for row in payload["tail"]]
        else:
            gap = False
            try:
                bars = store.load(day)
                profile = store.load_profile(day)
            except Exception:  # noqa: BLE001 - missing, faulty or holdout day: counted, never guessed
                gap = True
            if gap:
                readings = _gap_day(day)
                history.clear()
            else:
                readings = read_day(bars, profile, history)
            if cached is not None and not gap:  # a gap is cheap to detect again and may be filled later
                cache_dir.mkdir(parents=True, exist_ok=True)
                tmp = cached.with_suffix(".tmp")
                tmp.write_text(json.dumps({"day": day.isoformat(), "gap": gap, "tail": _tail(history), "readings": [r.as_row() for r in readings]}))
                tmp.replace(cached)
        if wanted:
            out.extend(readings)
            if gap:
                gaps.append(day.isoformat())
        day += timedelta(days=1)
    return out, gaps


def _read_chunk(args: tuple) -> tuple[list[list], list[str]]:
    root, first, last, cache = args
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    readings, gaps = read_days(root, days, cache=cache)
    return [r.as_row() for r in readings], gaps


def read_range(root: Path | str, first: date, last: date, *, workers: int = 1, cache: Path | str | None = None) -> tuple[list[Reading], list[str]]:
    """All readings of ``first..last`` in time order, read by ``workers`` processes on contiguous stretches."""
    if _ms(last) + DAY > HOLDOUT_START_MS or last > LAST_DAY:
        raise PermissionError("S19 reads no holdout day")
    if last < first:
        raise ValueError("last day before first day")
    total = (last - first).days + 1
    workers = max(1, min(workers, total))
    bounds = []
    for w in range(workers):
        a = first + timedelta(days=total * w // workers)
        b = first + timedelta(days=total * (w + 1) // workers - 1)
        bounds.append((str(root), a, b, str(cache) if cache else None))
    if workers == 1:
        parts = [_read_chunk(bounds[0])]
    else:
        with Pool(workers) as pool:
            parts = pool.map(_read_chunk, bounds)
    readings = [Reading.from_row(row) for rows, _ in parts for row in rows]
    gaps = [g for _, gs in parts for g in gs]
    return readings, gaps


# -- events and outcomes (section 4) -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Event:
    index: int
    start: int
    key: str
    direction: str


def events_of(readings: Sequence[Reading], *, debounce: int = DEBOUNCE) -> list[Event]:
    """One event per flag and candle, dropped when today's value of the family fired in the ``debounce`` candles before."""
    last_today: dict[tuple[str, str], int] = {}
    out: list[Event] = []
    for i, reading in enumerate(readings):
        fired_today = []
        for flag in reading.flags:
            key, direction = flag.split("|")
            family = family_of(key)
            if key == TODAY_KEYS[family]:
                fired_today.append((family, direction))
            last = last_today.get((family, direction))
            if last is not None and i - last <= debounce:
                continue
            out.append(Event(i, reading.start, key, direction))
        for family_direction in fired_today:
            last_today[family_direction] = i
    return out


def outcome(readings: Sequence[Reading], index: int, horizon: int) -> int | None:
    """+1 / -1 / 0 for the close ``horizon`` candles later, or None when a candle in between is missing."""
    end = index + horizon
    if end >= len(readings) or not readings[index].traded:
        return None
    for j in range(index + 1, end + 1):
        if not readings[j].traded or readings[j].start != readings[index].start + (j - index) * CANDLE_MS:
            return None
    return _sign(readings[end].close - readings[index].close)


def base_rates(readings: Sequence[Reading]) -> dict[tuple[int, int, str], float]:
    """Share of the week's candles whose close ``h`` later rose (UP) or fell (DOWN)."""
    counts: dict[tuple[int, int, str], list[int]] = {}
    for i, reading in enumerate(readings):
        for h in HORIZONS:
            result = outcome(readings, i, h)
            if result is None:
                continue
            week = week_of(reading.start)
            for direction, hit in ((UP, result > 0), (DOWN, result < 0)):
                cell = counts.setdefault((week, h, direction), [0, 0])
                cell[0] += int(hit)
                cell[1] += 1
    return {key: hits / n for key, (hits, n) in counts.items() if n}


# -- count (section 5.1) ------------------------------------------------------------------------------
def count(readings: Sequence[Reading], gaps: Sequence[str]) -> dict:
    """Results-blind counts: events and weeks per flag, direction and section; no outcome is looked at."""
    events = events_of(readings)
    cells: dict[tuple[str, str, str], dict] = {}
    for event in events:
        section = section_of(event.start)
        if section is None:
            continue
        cell = cells.setdefault((section, event.key, event.direction), {"events": 0, "weeks": set()})
        cell["events"] += 1
        cell["weeks"].add(week_of(event.start))
    flags: dict[str, dict] = {}
    for key in FLAG_KEYS:
        flags[key] = {}
        for section in SECTIONS:
            for direction in DIRECTIONS:
                cell = cells.get((section, key, direction), {"events": 0, "weeks": set()})
                flags[key][f"{section}/{direction}"] = {"events": cell["events"], "weeks": len(cell["weeks"])}
    gate = {}
    for family in FAMILIES:
        today = flags[TODAY_KEYS[family]]
        passed = all(today[f"{s}/{d}"]["events"] >= MIN_EVENTS and today[f"{s}/{d}"]["weeks"] >= MIN_WEEKS for s in SECTIONS for d in DIRECTIONS)
        gate[family] = {"today": TODAY_KEYS[family], "testable": passed}
    per_section = {}
    for section, (lo, hi) in SECTIONS.items():
        inside = [r for r in readings if lo <= r.start < hi]
        per_section[section] = {"candles": len(inside), "traded": sum(r.traded for r in inside),
                                "with_footprint": sum(r.levels >= MIN_LEVELS for r in inside),
                                "with_today_flag": sum(any(f.split("|")[0] in TODAY_KEYS.values() for f in r.flags) for r in inside),
                                "weeks": len({week_of(r.start) for r in inside})}
    return {"study": "S19", "version": VERSION, "mode": "count", "hypotheses": HYPOTHESES, "min_events": MIN_EVENTS, "min_weeks": MIN_WEEKS,
            "sections": per_section, "gap_days": list(gaps), "flags": flags, "gate": gate}


def count_report(result: Mapping, *, stamp: str) -> str:
    lines = [f"# S19 Zähllauf {stamp} (ergebnisblind, Abschnitt 5.1)", "",
             f"Version {result['version']}, {result['hypotheses']} Hypothesen, Gate: ≥ {result['min_events']} Ereignisse und ≥ {result['min_weeks']} Wochen je Richtung und Zeitraum.",
             f"Lückentage: {len(result['gap_days'])}", ""]
    lines.append("| Zeitraum | Kerzen | gehandelt | mit Footprint (≥ 20 Stufen) | mit heutigem Flag | Wochen |")
    lines.append("|---|---|---|---|---|---|")
    for section, s in result["sections"].items():
        lines.append(f"| {section} | {s['candles']} | {s['traded']} | {s['with_footprint']} | {s['with_today_flag']} | {s['weeks']} |")
    lines += ["", "## Gate je Familie", "", "| Familie | heutiger Wert | testbar |", "|---|---|---|"]
    for family, g in result["gate"].items():
        lines.append(f"| {family} {FAMILY_NAMES[family]} | `{g['today']}` | {'ja' if g['testable'] else 'nein'} |")
    lines += ["", "## Ereignisse und Wochen je Flag", "",
              "| Flag | Training up | Training down | Validierung up | Validierung down |", "|---|---|---|---|---|"]
    for key, cells in result["flags"].items():
        mark = " (heute)" if key in TODAY_KEYS.values() else ""
        row = [f"`{key}`{mark}"]
        for section in SECTIONS:
            for direction in DIRECTIONS:
                c = cells[f"{section}/{direction}"]
                row.append(f"{c['events']} / {c['weeks']} W")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "Keine Trefferquote, kein Folgeschluss wurde berechnet oder angesehen."]
    return "\n".join(lines) + "\n"


# -- evaluation (section 5) ---------------------------------------------------------------------------
def _week_cells(events: Sequence[Event], readings: Sequence[Reading], rates: Mapping, horizon: int) -> dict[int, list[float]]:
    """Per week: [events, hits, sum of base rates] for the events of one flag/direction."""
    cells: dict[int, list[float]] = {}
    for event in events:
        result = outcome(readings, event.index, horizon)
        if result is None:
            continue
        week = week_of(event.start)
        base = rates.get((week, horizon, event.direction))
        if base is None:
            continue
        hit = (result > 0) if event.direction == UP else (result < 0)
        cell = cells.setdefault(week, [0.0, 0.0, 0.0])
        cell[0] += 1
        cell[1] += float(hit)
        cell[2] += base
    return cells


def lift_of(cells: Iterable[Sequence[float]]) -> float | None:
    n = hits = base = 0.0
    for events, h, b in cells:
        n += events
        hits += h
        base += b
    return (hits - base) / n * 100.0 if n else None


def block_bootstrap_p(cells: Mapping[int, Sequence[float]], *, seed: str, draws: int = DRAWS, block: int = BLOCK_WEEKS) -> float | None:
    """One-sided p for H0 lift <= 0: moving blocks of ``block`` consecutive weeks, resampled to the number of weeks."""
    weeks = sorted(cells)
    if len(weeks) < 2:
        return None
    rows = [cells[w] for w in weeks]
    rng = random.Random(f"{SEED}:{seed}")
    starts = len(rows) - min(block, len(rows)) + 1
    width = min(block, len(rows))
    at_or_below = 0
    for _ in range(draws):
        n = hits = base = 0.0
        covered = 0
        while covered < len(rows):
            s = rng.randrange(starts)
            for events, h, b in rows[s:s + width]:
                n += events
                hits += h
                base += b
            covered += width
        if n == 0 or hits - base <= 0:
            at_or_below += 1
    return (at_or_below + 1) / (draws + 1)


def _evaluate_cell(args: tuple) -> tuple[str, dict]:
    name, cells = args
    rows = {int(w): v for w, v in cells.items()}
    n = int(sum(v[0] for v in rows.values()))
    lift = lift_of(rows.values())
    p = block_bootstrap_p(rows, seed=name) if lift is not None else None
    return name, {"events": n, "weeks": len(rows), "hit_rate": (sum(v[1] for v in rows.values()) / n) if n else None, "lift_pp": lift, "p": p}


def evaluate(readings: Sequence[Reading], gaps: Sequence[str], *, workers: int = 1) -> dict:
    """Section 5: lift, block-bootstrap p, Holm over all 112 hypotheses per section, verdict per family."""
    counted = count(readings, gaps)
    events = events_of(readings)
    rates = base_rates(readings)
    jobs: list[tuple[str, dict]] = []
    for section, (lo, hi) in SECTIONS.items():
        inside = [e for e in events if lo <= e.start < hi]
        by_flag: dict[tuple[str, str], list[Event]] = {}
        for event in inside:
            by_flag.setdefault((event.key, event.direction), []).append(event)
        for key in FLAG_KEYS:
            for direction in DIRECTIONS:
                for h in HORIZONS:
                    cells = _week_cells(by_flag.get((key, direction), []), readings, rates, h)
                    jobs.append((f"{section}/{key}/{direction}/h{h}", {str(w): v for w, v in cells.items()}))
    if workers > 1:
        with Pool(workers) as pool:
            results = dict(pool.map(_evaluate_cell, jobs))
    else:
        results = dict(map(_evaluate_cell, jobs))
    for section in SECTIONS:
        pvalues = {name: r["p"] for name, r in results.items() if name.startswith(f"{section}/") and r["p"] is not None}
        rejected = holm(pvalues, HYPOTHESES, ALPHA)
        for name, r in results.items():
            if name.startswith(f"{section}/"):
                r["holm_significant"] = name in rejected
    verdicts = {family: verdict(family, results, counted["gate"][family]["testable"]) for family in FAMILIES}
    described = describe(readings, events, rates)
    return {**counted, "mode": "evaluate", "draws": DRAWS, "block_weeks": BLOCK_WEEKS, "seed": SEED, "alpha": ALPHA,
            "results": results, "verdicts": verdicts, "descriptive": described}


def _confirmed(key: str, direction: str, results: Mapping[str, Mapping]) -> bool:
    for section in SECTIONS:
        short = results[f"{section}/{key}/{direction}/h4"]
        long = results[f"{section}/{key}/{direction}/h16"]
        if short["events"] < MIN_EVENTS or short["weeks"] < MIN_WEEKS:
            return False
        if short["lift_pp"] is None or short["lift_pp"] < MIN_LIFT_PP or not short["holm_significant"]:
            return False
        if long["lift_pp"] is None or long["lift_pp"] < 0:
            return False
    return True


def _grid_distance(family: str, key: str) -> float:
    today, value = TODAY[family], GRID[family][[flag_key(family, v) for v in GRID[family]].index(key)]
    return sum(abs(a - b) for a, b in zip(today, value))


def verdict(family: str, results: Mapping[str, Mapping], testable: bool) -> dict:
    """"bestätigt", "bestätigt, Nachbarwert besser", "ohne Nachweis" or "nicht testbar" per family and direction."""
    today = TODAY_KEYS[family]
    if not testable:
        return {"status": "nicht testbar", "today": today}
    out: dict = {"today": today, "directions": {}}
    statuses = []
    for direction in DIRECTIONS:
        confirmed = _confirmed(today, direction, results)
        better = []
        for value in GRID[family]:
            key = flag_key(family, value)
            if key == today or not _confirmed(key, direction, results):
                continue
            if all(results[f"{s}/{key}/{direction}/h4"]["lift_pp"] >= results[f"{s}/{today}/{direction}/h4"]["lift_pp"] + REPLACE_MARGIN_PP for s in SECTIONS):
                better.append(key)
        better.sort(key=lambda k: (_grid_distance(family, k), k))
        if better and confirmed:
            status, chosen = "bestätigt, Nachbarwert besser", better[0]
        elif confirmed:
            status, chosen = "bestätigt", None
        else:
            status, chosen = "ohne Nachweis", None
        out["directions"][direction] = {"status": status, "replacement": chosen}
        statuses.append(status)
    out["status"] = statuses[0] if len(set(statuses)) == 1 else "gemischt: " + " / ".join(statuses)
    return out


def describe(readings: Sequence[Reading], events: Sequence[Event], rates: Mapping) -> dict:
    """Section 5.2: mean log return in bps, lift per year and UTC block (today's values, h = 4), flag share."""
    log_return: dict[str, list[float]] = {}
    undebounced: dict[str, list[float]] = {}
    per_year: dict[str, dict[int, list[float]]] = {}
    per_block: dict[str, dict[int, list[float]]] = {}
    for event in events:
        for h in HORIZONS:
            end = event.index + h
            if outcome(readings, event.index, h) is None or readings[end].close <= 0 or readings[event.index].close <= 0:
                continue
            signed = math.log(readings[end].close / readings[event.index].close) * (1 if event.direction == UP else -1)
            log_return.setdefault(f"{event.key}/{event.direction}/h{h}", []).append(signed * 10_000)
        if event.key in TODAY_KEYS.values():
            result = outcome(readings, event.index, 4)
            base = rates.get((week_of(event.start), 4, event.direction))
            if result is None or base is None:
                continue
            hit = float((result > 0) if event.direction == UP else (result < 0)) - base
            per_year.setdefault(f"{event.key}/{event.direction}", {}).setdefault(year_of(event.start), []).append(hit)
            per_block.setdefault(f"{event.key}/{event.direction}", {}).setdefault(time_block_of(event.start), []).append(hit)
    for i, reading in enumerate(readings):
        for flag in reading.flags:
            key, direction = flag.split("|")
            for h in HORIZONS:
                end = i + h
                if outcome(readings, i, h) is None or reading.close <= 0 or readings[end].close <= 0:
                    continue
                signed = math.log(readings[end].close / reading.close) * (1 if direction == UP else -1)
                undebounced.setdefault(f"{key}/{direction}/h{h}", []).append(signed * 10_000)
    def mean(values):
        return (sum(values) / len(values)) if values else None

    traded = [r for r in readings if r.traded]
    return {
        "mean_log_return_bps": {k: {"debounced": mean(v), "n": len(v), "undebounced": mean(undebounced.get(k, [])), "n_undebounced": len(undebounced.get(k, []))}
                                for k, v in sorted(log_return.items())},
        "lift_pp_per_year": {k: {str(y): {"lift_pp": mean(v) * 100 if v else None, "n": len(v)} for y, v in sorted(years.items())} for k, years in sorted(per_year.items())},
        "lift_pp_per_utc_block": {k: {str(b): {"lift_pp": mean(v) * 100 if v else None, "n": len(v)} for b, v in sorted(blocks.items())} for k, blocks in sorted(per_block.items())},
        "share_of_candles_with_today_flag": (sum(any(f.split("|")[0] in TODAY_KEYS.values() for f in r.flags) for r in traded) / len(traded)) if traded else None,
        "perp": "nicht geladen (Abschnitt 3)", "kline_deviation": "nicht gemessen: der S8-Store hält keine Klines",
    }


def evaluate_report(result: Mapping, *, stamp: str) -> str:
    lines = [f"# S19 Auswertung {stamp} (Abschnitt 5)", "",
             f"Version {result['version']}, {result['hypotheses']} Hypothesen, Holm je Zeitraum, Block-Bootstrap {result['block_weeks']} Wochen, {result['draws']} Ziehungen, Seed {result['seed']}.", "",
             "## Urteil je Familie", "", "| Familie | heutiger Wert | Urteil | up | down |", "|---|---|---|---|---|"]
    def cell(dirs: Mapping, d: str) -> str:
        if d not in dirs:
            return "-"
        replacement = dirs[d].get("replacement")
        return dirs[d]["status"] + (f" → `{replacement}`" if replacement else "")

    def fmt(r: Mapping) -> str:
        return "-" if r["lift_pp"] is None else f"{r['lift_pp']:+.1f}{'*' if r.get('holm_significant') else ''}"

    for family, v in result["verdicts"].items():
        dirs = v.get("directions", {})
        lines.append(f"| {family} {FAMILY_NAMES[family]} | `{v['today']}` | {v['status']} | {cell(dirs, UP)} | {cell(dirs, DOWN)} |")
    lines += ["", "## Lift je Flag (Prozentpunkte, h = 4 / h = 16; Holm-signifikant mit *)", "",
              "| Flag | Richtung | Training n | Training Lift | Validierung n | Validierung Lift |", "|---|---|---|---|---|---|"]
    for key in FLAG_KEYS:
        for direction in DIRECTIONS:
            row = [f"`{key}`", direction]
            for section in SECTIONS:
                short = result["results"][f"{section}/{key}/{direction}/h4"]
                long = result["results"][f"{section}/{key}/{direction}/h16"]
                row += [str(short["events"]), f"{fmt(short)} / {fmt(long)}"]
            lines.append("| " + " | ".join(row) + " |")
    share = result["descriptive"]["share_of_candles_with_today_flag"]
    lines += ["", f"Anteil der Kerzen mit mindestens einem heutigen Flag: {share:.1%}" if share is not None else "", ""]
    return "\n".join(lines) + "\n"


# -- CLI -----------------------------------------------------------------------------------------------
def _dataset_hash(root: Path, first: date, last: date) -> str:
    manifest = json.loads((root / "bars_manifest.json").read_text()) if (root / "bars_manifest.json").exists() else {}
    keys = [k for k in sorted(manifest) if first.isoformat() <= k <= last.isoformat()]
    return hashlib.sha256(json.dumps([(k, manifest[k]) for k in keys], sort_keys=True).encode()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("count", "evaluate"):
        p = sub.add_parser(mode)
        p.add_argument("--bars", required=True, type=Path, help="S8 store root (bars/, profile/, bars_manifest.json)")
        p.add_argument("--out", required=True, type=Path, help="directory for the JSON and Markdown report")
        p.add_argument("--first", type=date.fromisoformat, default=FIRST_DAY)
        p.add_argument("--last", type=date.fromisoformat, default=LAST_DAY)
        p.add_argument("--workers", type=int, default=1)
        p.add_argument("--cache", type=Path, default=None, help="per-day reading cache (reused by later runs)")
    args = parser.parse_args(argv)
    started = time.time()
    readings, gaps = read_range(args.bars, args.first, args.last, workers=args.workers, cache=args.cache)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    if args.mode == "count":
        result = count(readings, gaps)
        report = count_report(result, stamp=stamp)
    else:
        result = evaluate(readings, gaps, workers=args.workers)
        report = evaluate_report(result, stamp=stamp)
    result["dataset_hash"] = _dataset_hash(args.bars, args.first, args.last)
    result["range"] = [args.first.isoformat(), args.last.isoformat()]
    result["seconds"] = round(time.time() - started, 1)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"s19_{args.mode}_{stamp}.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (args.out / f"s19_{args.mode}_{stamp}.md").write_text(report)
    print(json.dumps({"mode": args.mode, "candles": len(readings), "gap_days": len(gaps), "seconds": result["seconds"],
                      "report": str(args.out / f"s19_{args.mode}_{stamp}.md")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
