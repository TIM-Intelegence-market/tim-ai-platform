"""Study S2 (docs/research_lab/studien/S2_ORDERFLOW_REGELN_PRAEREGISTRIERUNG.md): the
outcome-blind count run, section 3.

The live rules (``src/orderflow/observations.py``, RULE_VERSION 1.0.0) look at
two adjacent 60-second metric windows. Every rule reads only counts and
quantities of a window: trade count, buy and sell count, aggressive buy and
sell volume, largest trade. No rule reads a price. This module therefore
reduces each archive day to per-minute aggregates of exactly those fields and
feeds them, as ``OrderflowMetric`` objects, through the **unchanged**
``OrderflowObservationEngine``. Prices are never loaded here, so the count run
cannot see an outcome even by accident.

Exactness: quantities are kept as integers in 1e-8 BTC ("sats") and turned into
``Decimal`` without rounding, so every metric field the rules compare is
numerically identical to what ``OrderflowMetricsEngine.calculate`` produces
from the same trades (``tests/test_research_lab_s2.py`` checks that against the
live engine on random trade sets).

Counting follows the pre-registration: per directional kind the first
observation is kept and every further one strictly less than 30 minutes after
the kept one is dropped (greedy, anchored on the kept one); controls are all
evaluable 60-second windows of the same ISO week that do not carry that kind;
weeks are calendar positions of a section, and only weeks with all seven days
present and inside one section are complete.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Iterator, Sequence

from src.orderflow.metrics import METRIC_VERSION, SOURCE, OrderflowMetric
from src.orderflow.observations import RULE_VERSION, OrderflowObservationEngine
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS

STUDY = "S2"
STUDY_DRAFT_VERSION = "0.3"
SYMBOL = "BTCUSDT"
MINUTE_MS = 60_000
MINUTES_PER_DAY = 1_440
SATS = Decimal(10) ** 8
DEDUP_MS = 30 * MINUTE_MS
MIN_CASES = 200
MIN_WEEKS = 26
TRAIN_START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

# Section 1 of the study: direction claimed per kind; the two descriptive kinds carry none.
DIRECTIONAL: dict[str, str] = {
    "STRONG_BUYER_ACTIVITY": "up", "RISING_CVD_ACTIVITY": "up", "EXTREME_BUY_RATIO_ACTIVITY": "up",
    "STRONG_SELLER_ACTIVITY": "down", "FALLING_CVD_ACTIVITY": "down", "EXTREME_SELL_RATIO_ACTIVITY": "down",
}
DESCRIPTIVE: tuple[str, ...] = ("HIGH_TRADE_FREQUENCY", "LARGE_INDIVIDUAL_TRADE_ACTIVITY")
ALL_KINDS: tuple[str, ...] = tuple(DIRECTIONAL) + DESCRIPTIVE
SECTIONS: dict[str, tuple[int, int]] = {"train": (TRAIN_START_MS, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}


@dataclass(frozen=True, slots=True)
class MinuteAggregate:
    """Everything the rules need from one 60-second window; no price."""

    window_start_ms: int
    trade_count: int
    buy_count: int
    sell_count: int
    buy_sats: int
    sell_sats: int
    largest_sats: int

    def __post_init__(self) -> None:
        if self.trade_count != self.buy_count + self.sell_count:
            raise ValueError("trade_count must equal buy_count + sell_count")
        if min(self.buy_count, self.sell_count, self.buy_sats, self.sell_sats, self.largest_sats) < 0:
            raise ValueError("aggregates cannot be negative")
        if self.window_start_ms % MINUTE_MS:
            raise ValueError("window_start_ms must be minute aligned")

    @property
    def window_start(self) -> datetime:
        return datetime.fromtimestamp(self.window_start_ms / 1000, tz=timezone.utc)

    @property
    def window_end(self) -> datetime:
        return self.window_start + timedelta(minutes=1)

    def as_row(self) -> list[int]:
        return [self.window_start_ms, self.trade_count, self.buy_count, self.sell_count, self.buy_sats, self.sell_sats, self.largest_sats]

    @classmethod
    def from_row(cls, row: Sequence[int | str]) -> "MinuteAggregate":
        return cls(*(int(value) for value in row))


def quantity_to_sats(text: str) -> int:
    """Exact 1e-8 integer from an archive quantity string (at most eight decimals)."""
    value = Decimal(text.strip())
    sats = value * SATS
    if sats != sats.to_integral_value():
        raise ValueError(f"quantity has more than eight decimals: {text!r}")
    if sats < 0:
        raise ValueError("negative quantity")
    return int(sats)


def parse_is_buyer_maker(text: str) -> bool:
    flag = text.strip().lower()
    if flag in {"true", "1"}:
        return True
    if flag in {"false", "0"}:
        return False
    raise ValueError(f"unknown is_buyer_maker flag {text!r}")


def aggregate_rows(rows: Iterable[Sequence[str]], day_start_ms: int) -> list[MinuteAggregate]:
    """Reference aggregation of one archive day from raw aggTrades rows (pure Python).

    Row layout (spot aggTrades): agg_trade_id, price, quantity, first_trade_id,
    last_trade_id, transact_time, is_buyer_maker, is_best_match. Only columns
    2, 5 and 6 are read. Trades outside the day raise: an archive day is the unit.
    """
    if day_start_ms % 86_400_000:
        raise ValueError("day_start_ms must be a UTC midnight")
    trade_count = [0] * MINUTES_PER_DAY
    buy_count = [0] * MINUTES_PER_DAY
    buy_sats = [0] * MINUTES_PER_DAY
    sell_sats = [0] * MINUTES_PER_DAY
    largest = [0] * MINUTES_PER_DAY
    for row in rows:
        stamp = archive_ms(row[5])
        minute = (stamp - day_start_ms) // MINUTE_MS
        if not 0 <= minute < MINUTES_PER_DAY:
            raise ValueError(f"trade at {stamp} lies outside the archive day")
        sats = quantity_to_sats(row[2])
        if sats <= 0:
            raise ValueError("zero quantity trade")
        trade_count[minute] += 1
        if parse_is_buyer_maker(row[6]):
            sell_sats[minute] += sats  # buyer is maker: the aggressor sold
        else:
            buy_count[minute] += 1
            buy_sats[minute] += sats
        if sats > largest[minute]:
            largest[minute] = sats
    return [MinuteAggregate(day_start_ms + i * MINUTE_MS, trade_count[i], buy_count[i], trade_count[i] - buy_count[i], buy_sats[i], sell_sats[i], largest[i]) for i in range(MINUTES_PER_DAY)]


def archive_ms(value: str) -> int:
    stamp = int(value)
    return stamp // 1000 if stamp >= 10**14 else stamp  # microsecond archives (2025+, holdout anyway)


def _sats_decimal(sats: int) -> Decimal:
    return Decimal(sats).scaleb(-8)


def metric_from_aggregate(item: MinuteAggregate, *, opening_cvd: Decimal = Decimal(0), symbol: str = SYMBOL) -> OrderflowMetric:
    """Build the live ``OrderflowMetric`` from an aggregate, field for field as the live engine does.

    ``source_hash`` is a hash of the window identity, not of canonical trades:
    the count run does not carry trades. No rule reads the hash.
    """
    buy = _sats_decimal(item.buy_sats)
    sell = _sats_decimal(item.sell_sats)
    total = buy + sell
    delta = buy - sell
    duration = Decimal(60)
    count = item.trade_count
    digest = hashlib.sha256(f"{STUDY}:{METRIC_VERSION}:{symbol}:{item.window_start_ms}".encode()).hexdigest()
    return OrderflowMetric(
        symbol, item.window_start, item.window_end, count, item.buy_count, item.sell_count, buy, sell, total, delta,
        opening_cvd + delta, total / count if count else Decimal(0), _sats_decimal(item.largest_sats),
        Decimal(count) / duration, total / duration, buy / sell if sell else None, digest,
    )


def observe(minutes: Iterable[MinuteAggregate], engine: OrderflowObservationEngine | None = None) -> Iterator[tuple[MinuteAggregate, frozenset[str] | None]]:
    """Yield (window, kinds) for every window; kinds is None when the previous minute is missing.

    ``minutes`` must be sorted by time. A gap of more than one minute between
    two aggregates makes the later one non-evaluable, exactly like the live
    runtime, which needs the adjacent previous window.
    """
    engine = engine or OrderflowObservationEngine()
    previous: tuple[MinuteAggregate, OrderflowMetric] | None = None
    for item in minutes:
        if previous is not None and item.window_start_ms <= previous[0].window_start_ms:
            raise ValueError("minutes must be strictly increasing")
        metric = metric_from_aggregate(item)
        if previous is None or previous[0].window_start_ms + MINUTE_MS != item.window_start_ms:
            yield item, None
        else:
            prev_metric = previous[1]
            current = metric_from_aggregate(item, opening_cvd=prev_metric.cumulative_delta)
            yield item, frozenset(obs.kind for obs in engine.evaluate(prev_metric, current))
            metric = current
        previous = (item, metric)


def greedy_dedup(times_ms: Sequence[int], gap_ms: int = DEDUP_MS) -> list[int]:
    """Keep the first time, drop every later one strictly less than ``gap_ms`` after the kept one."""
    kept: list[int] = []
    anchor: int | None = None
    for stamp in times_ms:
        if anchor is not None and stamp < anchor:
            raise ValueError("times must be sorted")
        if anchor is None or stamp - anchor >= gap_ms:
            kept.append(stamp)
            anchor = stamp
    return kept


def iso_week_of(stamp_ms: int) -> tuple[int, int]:
    day = datetime.fromtimestamp(stamp_ms / 1000, tz=timezone.utc).date()
    year, week, _ = day.isocalendar()
    return year, week


def week_monday(year: int, week: int) -> date:
    return date.fromisocalendar(year, week, 1)


def week_id(year: int, week: int) -> str:
    return f"{year:04d}-W{week:02d}"


def section_of_week(year: int, week: int) -> str | None:
    """The section a calendar week lies in completely, or None when it straddles a boundary."""
    monday = week_monday(year, week)
    start_ms = int(datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = start_ms + 7 * 86_400_000
    for name, (lo, hi) in SECTIONS.items():
        if lo <= start_ms and end_ms <= hi:
            return name
    return None


def calendar_weeks(section: str) -> list[tuple[int, int]]:
    """All ISO weeks lying completely inside a section (its calendar positions)."""
    lo, hi = SECTIONS[section]
    first = datetime.fromtimestamp(lo / 1000, tz=timezone.utc).date()
    weeks: list[tuple[int, int]] = []
    monday = first - timedelta(days=first.isoweekday() - 1)
    while True:
        year, week, _ = monday.isocalendar()
        if section_of_week(year, week) == section:
            weeks.append((year, week))
        monday += timedelta(days=7)
        if int(datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc).timestamp() * 1000) >= hi:
            break
    return weeks


@dataclass(slots=True)
class WeekCount:
    year: int
    week: int
    section: str | None
    days_present: int = 0
    evaluable_windows: int = 0
    non_evaluable_windows: int = 0
    zero_trade_windows: int = 0
    raw: dict[str, int] = field(default_factory=lambda: {kind: 0 for kind in ALL_KINDS})
    kept: dict[str, int] = field(default_factory=lambda: {kind: 0 for kind in ALL_KINDS})

    @property
    def id(self) -> str:
        return week_id(self.year, self.week)

    @property
    def complete(self) -> bool:
        return self.section is not None and self.days_present == 7

    def controls(self, kind: str) -> int:
        """Evaluable windows of the week without this kind (raw, before dedup)."""
        return self.evaluable_windows - self.raw[kind]

    def to_dict(self) -> dict:
        row = {"week": self.id, "monday": week_monday(self.year, self.week).isoformat(), "section": self.section,
               "complete": self.complete, "days_present": self.days_present, "evaluable_windows": self.evaluable_windows,
               "non_evaluable_windows": self.non_evaluable_windows, "zero_trade_windows": self.zero_trade_windows,
               "kinds": {}}
        for kind in ALL_KINDS:
            row["kinds"][kind] = {"raw": self.raw[kind], "kept": self.kept[kind], "controls": self.controls(kind)}
        return row


def count_weeks(days: Iterable[tuple[date, Sequence[MinuteAggregate]]]) -> dict[tuple[int, int], WeekCount]:
    """Run the rules over consecutive archive days and count per ISO week.

    ``days`` is sorted by date; each entry holds the 1 440 aggregates of one
    archive day. Observations are dated by window end, like the live
    ``observed_at``. Dedup runs per kind over the whole stream, so a case kept
    at a week boundary anchors the exclusion into the next week.
    """
    weeks: dict[tuple[int, int], WeekCount] = {}
    pending: dict[str, list[int]] = {kind: [] for kind in ALL_KINDS}

    def week_for(stamp_ms: int) -> WeekCount:
        key = iso_week_of(stamp_ms)
        if key not in weeks:
            weeks[key] = WeekCount(key[0], key[1], section_of_week(*key))
        return weeks[key]

    def stream() -> Iterator[MinuteAggregate]:
        last_day: date | None = None
        for day, minutes in days:
            if last_day is not None and day <= last_day:
                raise ValueError("days must be strictly increasing")
            if len(minutes) != MINUTES_PER_DAY:
                raise ValueError(f"{day}: expected {MINUTES_PER_DAY} aggregates, got {len(minutes)}")
            if minutes[0].window_start_ms >= HOLDOUT_START_MS:
                raise PermissionError(f"{day} lies in the holdout; the count run must not read it")
            day_ms = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
            week_for(day_ms + MINUTE_MS).days_present += 1  # a day belongs to the week of its first window end
            last_day = day
            yield from minutes

    for item, kinds in observe(stream()):
        end_ms = item.window_start_ms + MINUTE_MS
        week = week_for(end_ms)
        if kinds is None:
            week.non_evaluable_windows += 1
            continue
        week.evaluable_windows += 1
        if item.trade_count == 0:
            week.zero_trade_windows += 1
        for kind in kinds:
            week.raw[kind] += 1
            pending[kind].append(end_ms)
    for kind, times in pending.items():
        for stamp in greedy_dedup(times):
            week_for(stamp).kept[kind] += 1
    return weeks


def section_summary(weeks: dict[tuple[int, int], WeekCount], section: str) -> dict:
    """Per kind: cases, controls, weeks with at least one case and one control, minimum check (not power)."""
    positions = calendar_weeks(section)
    rows = {}
    for kind in ALL_KINDS:
        cases = controls = usable = 0
        for key in positions:
            week = weeks.get(key)
            if week is None or not week.complete:
                continue
            if week.kept[kind] >= 1 and week.controls(kind) >= 1:
                usable += 1
                cases += week.kept[kind]
                controls += week.controls(kind)
        rows[kind] = {"directional": kind in DIRECTIONAL, "cases": cases, "controls": controls, "usable_weeks": usable,
                      "minimum_met": cases >= MIN_CASES and usable >= MIN_WEEKS}
    complete = sum(1 for key in positions if key in weeks and weeks[key].complete)
    return {"calendar_weeks": len(positions), "complete_weeks": complete,
            "incomplete_weeks": [week_id(*key) for key in positions if key not in weeks or not weeks[key].complete], "kinds": rows}


def weekly_series(weeks: dict[tuple[int, int], WeekCount], section: str, kind: str) -> list[tuple[int, int]]:
    """(cases, controls) per calendar position of the section; excluded weeks are (0, 0)."""
    out = []
    for key in calendar_weeks(section):
        week = weeks.get(key)
        if week is None or not week.complete or week.kept[kind] < 1 or week.controls(kind) < 1:
            out.append((0, 0))
        else:
            out.append((week.kept[kind], week.controls(kind)))
    return out


def build_count_report(weeks: dict[tuple[int, int], WeekCount], *, commit: str, dataset_hash: str, days: int, missing_days: Sequence[str], created: datetime | None = None) -> dict:
    created = created or datetime.now(timezone.utc)
    report = {
        "study": STUDY, "draft_version": STUDY_DRAFT_VERSION, "rule_version": RULE_VERSION, "metric_version": METRIC_VERSION,
        "source": SOURCE, "symbol": SYMBOL, "outcome_blind": True, "prices_read": False, "commit": commit,
        "dataset_hash": dataset_hash, "archive_days": days, "missing_days": list(missing_days),
        "created": created.isoformat(timespec="seconds"), "dedup_minutes": DEDUP_MS // MINUTE_MS,
        "minimums": {"cases": MIN_CASES, "weeks": MIN_WEEKS},
        "sections": {name: section_summary(weeks, name) for name in SECTIONS},
        "boundary_weeks": sorted(week.id for week in weeks.values() if week.section is None),
        "weeks": [weeks[key].to_dict() for key in sorted(weeks)],
    }
    return report


def render_count_markdown(report: dict) -> str:
    lines = [f"# S2 Zähllauf (ergebnisblind), Stand {report['created']}", "",
             f"Regelversion {report['rule_version']}, Metrikversion {report['metric_version']}, Commit `{report['commit'][:12]}`,",
             f"Datensatz-Hash `{report['dataset_hash'][:16]}…`, {report['archive_days']} Archivtage, fehlende Tage: {len(report['missing_days'])}.",
             "", "Es wurden keine Preise gelesen; der Lauf zählt Fälle und Kontrollfenster, keine Treffer.", ""]
    for name, section in report["sections"].items():
        lines += [f"## Abschnitt {name}: {section['complete_weeks']} von {section['calendar_weeks']} Kalenderwochen vollständig", "",
                  "| Art | gerichtet | Fälle (nach Dedup) | Kontrollfenster | auswertbare Wochen | Mindestzahlen (200 / 26) |", "|---|---|---|---|---|---|"]
        for kind, row in section["kinds"].items():
            lines.append(f"| {kind} | {'ja' if row['directional'] else 'nein (deskriptiv)'} | {row['cases']} | {row['controls']} | {row['usable_weeks']} | {'erfüllt' if row['minimum_met'] else 'nicht erfüllt'} |")
        if section["incomplete_weeks"]:
            lines += ["", f"Unvollständige Wochen ({len(section['incomplete_weeks'])}): " + ", ".join(section["incomplete_weeks"][:20]) + (" …" if len(section["incomplete_weeks"]) > 20 else "")]
        lines.append("")
    if report["boundary_weeks"]:
        lines += ["Wochen über einer Abschnittsgrenze (ausgeschlossen): " + ", ".join(report["boundary_weeks"]), ""]
    lines += ["Mindestzahlen sind kein Power-Nachweis (Studie Abschnitt 3). Die Power-Simulation liest diese Datei.", ""]
    return "\n".join(lines)
