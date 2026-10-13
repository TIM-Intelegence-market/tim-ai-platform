"""Study S1: BTC range in the CPI release hour vs matched hours without CPI.

Fixed by docs/research_lab/studien/S1_CPI_VOLATILITAET.md. Descriptive only: no direction,
no signal, no register entry. Reads no clock, network or randomness besides the seeded
bootstrap, so the same events and candles always give the same result.
"""
from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from src.research_lab.external.align import BtcSeries
from src.research_lab.external.events import EventStatus, ReleaseEvent
from src.research_lab.external.records import iso, ms_to_utc, utc_to_ms
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS, Split, split_of
from src.research_lab.stats.inference import holm

STUDY_ID = "S1"
STUDY_VERSION = "1.0"
HOUR_MS = 3_600_000
WEEK_MS = 7 * 24 * HOUR_MS
DAY_MS = 24 * HOUR_MS
START_MS = utc_to_ms(datetime(2017, 9, 1, tzinfo=timezone.utc))
WINDOWS_H = (1, 4, 24)
PRIMARY_H = 1
WEEK_OFFSETS = (-4, -3, -2, -1, 1, 2, 3, 4)
MIN_CONTROLS = 4
CALENDAR_GUARD_MS = DAY_MS
FAMILY_ALPHA = 0.05
MIN_MEDIAN_RATIO = 1.25
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20261013
CI_LEVEL = 0.95


def window_range(btc: BtcSeries, start_ms: int, hours: int) -> float | None:
    """ln(highest high / lowest low) over ``hours`` 1h candles from ``start_ms``; None if any candle is missing."""
    candles = [btc.by_open.get(start_ms + i * HOUR_MS) for i in range(hours)]
    if any(candle is None for candle in candles):
        return None
    high = max(candle.high for candle in candles)
    low = min(candle.low for candle in candles)
    if low <= 0 or high <= 0:
        return None
    return math.log(high / low)


def sign_test_p(positive: int, n: int) -> float:
    """Exact one-sided sign test: P(X >= positive) for X ~ Binomial(n, 1/2)."""
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(positive, n + 1)) / 2**n


def bootstrap_median_ci(values: Sequence[float], *, draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED, level: float = CI_LEVEL) -> tuple[float, float] | None:
    """Percentile interval of the median of ``values`` (sampled with replacement)."""
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    medians = sorted(statistics.median(rng.choices(values, k=n)) for _ in range(draws))
    tail = (1 - level) / 2
    return medians[int(tail * (draws - 1))], medians[int((1 - tail) * (draws - 1))]


def eligible_events(events: Sequence[ReleaseEvent]) -> list[ReleaseEvent]:
    return [
        event for event in events
        if event.status is EventStatus.OK and event.event_time is not None
        and START_MS <= utc_to_ms(event.event_time) < HOLDOUT_START_MS
    ]


def _blocked(start_ms: int, end_ms: int, calendar_ms: Sequence[int]) -> bool:
    return any(start_ms - CALENDAR_GUARD_MS <= t < end_ms + CALENDAR_GUARD_MS for t in calendar_ms)


def measure_event(event: ReleaseEvent, btc: BtcSeries, hours: int, calendar_ms: Sequence[int]) -> dict[str, Any]:
    release = utc_to_ms(event.event_time)
    start = release - release % HOUR_MS
    row: dict[str, Any] = {"event_id": event.event_id, "event_time": iso(event.event_time), "candle_open": iso(ms_to_utc(start)),
                           "split": split_of(release).value}
    event_range = window_range(btc, start, hours)
    controls = []
    for weeks in WEEK_OFFSETS:
        c_start = start + weeks * WEEK_MS
        c_end = c_start + hours * HOUR_MS
        if c_end > HOLDOUT_START_MS or _blocked(c_start, c_end, calendar_ms):
            continue
        value = window_range(btc, c_start, hours)
        if value is not None:
            controls.append(value)
    row["event_range"] = event_range
    row["controls"] = len(controls)
    if event_range is None:
        return {**row, "status": "EVENT_WINDOW_INCOMPLETE"}
    if len(controls) < MIN_CONTROLS:
        return {**row, "status": "TOO_FEW_CONTROLS"}
    baseline = statistics.median(controls)
    row["control_median"] = baseline
    if event_range <= 0 or baseline <= 0:
        return {**row, "status": "NON_POSITIVE_RANGE"}
    row["log_ratio"] = math.log(event_range / baseline)
    return {**row, "status": "OK"}


def _summary(log_ratios: Sequence[float]) -> dict[str, Any]:
    n = len(log_ratios)
    positive = sum(1 for value in log_ratios if value > 0)
    non_tied = sum(1 for value in log_ratios if value != 0)
    if not n:
        return {"n": 0, "positive": 0, "p_sign": 1.0, "median_log_ratio": None, "median_ratio": None, "ci_ratio": None, "share_ratio_ge_2": None}
    median = statistics.median(log_ratios)
    ci = bootstrap_median_ci(list(log_ratios))
    return {
        "n": n,
        "positive": positive,
        "p_sign": sign_test_p(positive, non_tied),
        "median_log_ratio": median,
        "median_ratio": math.exp(median),
        "ci_ratio": [math.exp(ci[0]), math.exp(ci[1])],
        "share_ratio_ge_2": sum(1 for value in log_ratios if value >= math.log(2)) / n,
    }


def run_study(events: Sequence[ReleaseEvent], btc: BtcSeries) -> dict[str, Any]:
    if btc.interval != "1h":
        raise ValueError("study S1 is defined on 1h candles")
    if btc.cutoff_ms > HOLDOUT_START_MS:
        raise ValueError("study S1 never reads the holdout")
    calendar_ms = sorted(utc_to_ms(event.available_at) for event in events)
    used = eligible_events(events)
    windows: dict[str, Any] = {}
    for hours in WINDOWS_H:
        rows = [measure_event(event, btc, hours, calendar_ms) for event in used]
        ok = [row for row in rows if row["status"] == "OK"]
        overall = _summary([row["log_ratio"] for row in ok])
        by_split = {
            split.value: _summary([row["log_ratio"] for row in ok if row["split"] == split.value])
            for split in (Split.TRAIN, Split.VALIDATION)
        }
        status_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        windows[f"{hours}h"] = {"overall": overall, "by_split": by_split, "status_counts": dict(sorted(status_counts.items())), "rows": rows}
    pvalues = {name: window["overall"]["p_sign"] for name, window in windows.items()}
    rejected = holm(pvalues, m=len(pvalues), alpha=FAMILY_ALPHA)
    for name, window in windows.items():
        overall = window["overall"]
        splits_positive = all((window["by_split"][s]["median_log_ratio"] or 0) > 0 for s in (Split.TRAIN.value, Split.VALIDATION.value))
        window["holm_significant"] = name in rejected
        window["splits_positive"] = splits_positive
        window["verdict"] = (
            "BESTAETIGT"
            if name in rejected and overall["median_ratio"] is not None and overall["median_ratio"] >= MIN_MEDIAN_RATIO and splits_positive
            else "NICHT_BESTAETIGT"
        )
    return {
        "study": STUDY_ID,
        "study_version": STUDY_VERSION,
        "config": {
            "windows_h": list(WINDOWS_H), "primary_h": PRIMARY_H, "week_offsets": list(WEEK_OFFSETS), "min_controls": MIN_CONTROLS,
            "calendar_guard_h": CALENDAR_GUARD_MS // HOUR_MS, "family_alpha": FAMILY_ALPHA, "min_median_ratio": MIN_MEDIAN_RATIO,
            "bootstrap_draws": BOOTSTRAP_DRAWS, "bootstrap_seed": BOOTSTRAP_SEED, "start": iso(ms_to_utc(START_MS)),
            "validation_start": iso(ms_to_utc(VALIDATION_START_MS)), "holdout_start": iso(ms_to_utc(HOLDOUT_START_MS)),
        },
        "events_total": len(events),
        "events_eligible": len(used),
        "btc": {"candles": len(btc.klines), "excluded": len(btc.excluded), "completeness": btc.gaps()},
        "primary_verdict": windows[f"{PRIMARY_H}h"]["verdict"],
        "windows": windows,
    }


def render_markdown(result: dict[str, Any], provenance: dict[str, Any]) -> str:
    def pct(value: float | None) -> str:
        return "–" if value is None else f"{value:.2f}"

    lines = [
        "# Studie S1 – BTC-Schwankung an CPI-Terminen (Ergebnis)",
        "",
        "Vorregistrierung: `docs/research_lab/studien/S1_CPI_VOLATILITAET.md`. Beschreibende Messung, kein Signal, Holdout zu.",
        "",
        "| Feld | Wert |",
        "|---|---|",
    ]
    for key, value in provenance.items():
        lines.append(f"| {key} | `{value}` |")
    lines += [
        f"| Ereignisse gesamt / verwendbar | {result['events_total']} / {result['events_eligible']} |",
        f"| BTC-Kerzen 1h (ausgeschlossen) | {result['btc']['candles']} ({result['btc']['excluded']}) |",
        f"| **Primärurteil (1h)** | **{result['primary_verdict']}** |",
        "",
        "| Fenster | n | über Vergleich | p (Vorzeichen) | Holm | Median-Verhältnis | 95-%-Intervall | Anteil ≥ 2× | Training | Validierung | Urteil |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, window in result["windows"].items():
        o = window["overall"]
        ci = o["ci_ratio"]
        train, val = window["by_split"]["train"], window["by_split"]["validation"]
        share = "–" if o["share_ratio_ge_2"] is None else f"{o['share_ratio_ge_2']:.0%}"
        lines.append(
            f"| {name} | {o['n']} | {o['positive']} | {o['p_sign']:.2e} | {'ja' if window['holm_significant'] else 'nein'} | "
            f"{pct(o['median_ratio'])} | {'–' if ci is None else f'{ci[0]:.2f}–{ci[1]:.2f}'} | "
            f"{share} | "
            f"{pct(train['median_ratio'])} (n={train['n']}) | {pct(val['median_ratio'])} (n={val['n']}) | {window['verdict']} |"
        )
    lines += ["", "Ausgefallene Ereignisse je Fenster:", ""]
    for name, window in result["windows"].items():
        lines.append(f"- {name}: {window['status_counts']}")
    return "\n".join(lines) + "\n"


__all__ = ["bootstrap_median_ci", "eligible_events", "measure_event", "render_markdown", "run_study", "sign_test_p", "window_range"]
