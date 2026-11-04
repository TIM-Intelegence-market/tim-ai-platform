"""Shadow journal next to the MID plan journal: the same trades, the last third as a runner (paper only).

Uzi, 04.11.2026 ("go" after the first evaluation, docs/research_lab/berichte/ausstieg_laeufer_2026-11-04.md):
the MID long of that day closed at TP3 78,517 while the price ran on to about 81,000. The shadow follows,
for every MID trade that reaches TP2 after the shadow started, the last third under each exit variant of
``src.research_lab.exit_variants`` (FEST = the journal's own rule, LAEUFER, LAEUFER_WEIT, OF_LAEUFER):

- Prospective: only trades whose TP2 hit lies at or after ``started_at`` (written once, on the first run).
- Resumable: each run keeps its stop and the last minute it saw, so the runtime's short 1m window is
  enough. A minute that is missing is noted as ``data_gap`` on the run.
- No look-ahead: plan closes and delta buckets count only once they are closed.
- Orderflow: spot taker delta from TIM's own trade store (perp collected only since 30.10.2026).
- Costs: Kraken as measured 04.11.2026 (5 bps taker per side).

It reads the MID journal and never writes it. Nothing here trades or changes a rule; a rule change stays
Uzi's decision after 30 trades with TP2.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.research_lab import exit_variants as ev

SCHEMA = "tim_exit_shadow/1"
DEFAULT_PATH = Path("data/journal/tim_exit_shadow_mid.json")
TARGET_TRADES = 30  # trades with TP2 before the shadow is judged
THIRD = ev.THIRD


def load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _save(state: Mapping[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=1))
    os.replace(temporary, path)


def _candles(series: Mapping[str, Sequence[Mapping[str, Any]]], timeframe: str) -> list[dict[str, Any]]:
    from src.dashboard.chart_model import clean_candles

    return [c for c in clean_candles(series.get(timeframe) or [], timeframe) if c.get("closed", True)]


def _net(entry: Mapping[str, Any], run: Mapping[str, Any]) -> tuple[float, float]:
    legs = [(THIRD, float(entry["targets"][0]), "TP"), (THIRD, float(entry["targets"][1]), "TP"),
            (THIRD, float(run["exit_price"]), str(run["exit_reason"]))]
    return ev.net_r(entry, legs, ev.KRAKEN)


def summary(state: Mapping[str, Any]) -> dict[str, Any]:
    """Per variant: closed trades and net R; ``vs_fest`` = net R minus FEST on the trades closed in both."""
    runs = list((state.get("runs") or {}).values())
    out: dict[str, Any] = {"trades": len(runs), "target": TARGET_TRADES}
    for name in ev.VARIANTS:
        done = [r for r in runs if r["variants"][name].get("status") == "CLOSED"]
        both = [r for r in done if r["variants"]["FEST"].get("status") == "CLOSED"]
        out[name] = {"closed": len(done), "sum_r": round(sum(r["variants"][name]["net_r"] for r in done), 3),
                     "vs_fest": round(sum(r["variants"][name]["net_r"] - r["variants"]["FEST"]["net_r"] for r in both), 3),
                     "open": len(runs) - len(done)}
    return out


def update(path: Path, journal_path: Path, series: Mapping[str, Sequence[Mapping[str, Any]]],
           spot: Mapping[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """One step: start runs for new TP2 hits of the journal, follow every open run, save the view."""
    from src.dashboard.plan_journal import load_view

    now = now or datetime.now(timezone.utc)
    state = load(path) or {"schema": SCHEMA, "started_at": ev._iso(now), "source": Path(journal_path).name,
                           "variants": list(ev.VARIANTS), "costs": ev.KRAKEN.name, "orderflow": "spot taker delta",
                           "runs": {}}
    journal = load_view(Path(journal_path))
    if journal.get("blocked"):
        return state
    started = ev._time(state["started_at"])
    minutes = _candles(series, "1m")
    frames: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    delta_cache: dict[tuple[str, str], dict[int, float]] = {}
    for entry in journal.get("entries") or []:
        hits = entry.get("tp_hits") or []
        if entry.get("excluded") or not entry.get("filled_at") or len(hits) < 2 or ev._time(hits[1]) < started:
            continue
        key = str(entry["id"])
        journal_view = {"status": entry.get("status"), "exit_reason": entry.get("exit_reason"),
                        "exit_price": entry.get("exit_price"), "net_r": entry.get("net_r")}
        if key in state["runs"] and all(r.get("status") == "CLOSED" for r in state["runs"][key]["variants"].values()):
            state["runs"][key]["journal"] = journal_view
            continue
        timeframe = str(entry.get("timeframe") or "1h")
        if timeframe not in frames:
            frames[timeframe] = (_candles(series, timeframe), _candles(series, ev.HIGHER.get(timeframe, timeframe)))
        plan, higher = frames[timeframe]
        record = state["runs"].setdefault(key, {
            "id": entry["id"], "direction": entry["direction"], "timeframe": timeframe, "filled_at": entry["filled_at"],
            "fill_price": entry.get("fill_price") or entry["entry"], "entry": entry["entry"], "stop": entry["stop"],
            "targets": entry["targets"], "tp2_at": hits[1],
            "variants": {name: ev.start_run(entry, name) for name in ev.VARIANTS}})
        record["journal"] = journal_view
        for run in record["variants"].values():
            if run.get("status") == "OFFEN":
                deltas: dict[int, float] = {}
                if run["variant"] == "OF_LAEUFER" and not run.get("of_checked"):
                    # Built only while the orderflow question is still open (the spot store is large).
                    same = spot and str(spot.get("symbol") or "") == str(entry.get("symbol") or "BTCUSDT")
                    seconds = ev.TIMEFRAME_MINUTES[timeframe] * 60
                    first_day = (ev._time(entry["filled_at"]) - timedelta(days=1)).date().isoformat()
                    cache_key = (timeframe, first_day)
                    if cache_key not in delta_cache:
                        days = {day: rows for day, rows in (spot.get("days") or {}).items() if day >= first_day} if same else None
                        delta_cache[cache_key] = ev.store_deltas(days, seconds)
                    deltas = delta_cache[cache_key]
                ev.advance(entry, run, minutes, plan, higher, deltas)
            if run.get("status") == "CLOSED" and "net_r" not in run:
                run["gross_r"], run["net_r"] = _net(entry, run)
    state["checked_at"] = ev._iso(now)
    state["summary"] = summary(state)
    _save(state, Path(path))
    return state
