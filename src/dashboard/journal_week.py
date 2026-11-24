"""Wochenzahlen der Papier-Journale für den Subagenten ``journal-auswerter`` (docs/SUBAGENTEN_PLAN.md).

Nur lesend: lädt Journale über ``plan_journal.load_view`` und rechnet. Der Agent bewertet diese Ausgabe und
rechnet nichts selbst. Aufruf: ``python -m src.dashboard.journal_week JOURNAL [JOURNAL ...] [--shadow DATEI]
[--until ISO] [--days 7]``. Ausgabe ist JSON auf stdout; nichts wird geschrieben.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.dashboard.daily_report import LOCAL
from src.dashboard.orderflow_shadow import TARGET_TRADES, _time, current_path, load as load_shadow, summary as shadow_summary

MIN_TRADES = TARGET_TRADES  # below this a week (or a journal) gets no verdict


def _closed(entries: Sequence[Mapping[str, Any]], since: datetime, until: datetime) -> list[Mapping[str, Any]]:
    rows = [e for e in entries if not e.get("excluded") and e.get("status") == "CLOSED" and e.get("net_r") is not None
            and e.get("closed_at") and since <= _time(e["closed_at"]) < until]
    return sorted(rows, key=lambda e: _time(e["closed_at"]))


def max_drawdown(values: Sequence[float]) -> float:
    """Largest fall of the running sum from an earlier high (starting at 0), as a positive number of R."""
    total = peak = worst = 0.0
    for value in values:
        total += value
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return round(worst, 4)


def window_stats(entries: Sequence[Mapping[str, Any]], since: datetime, until: datetime) -> dict[str, Any]:
    closed = _closed(entries, since, until)
    values = [float(e["net_r"]) for e in closed]
    days = {(since + timedelta(days=i)).astimezone(LOCAL).date() for i in range(max((until - since).days, 0))}
    traded = {_time(e["closed_at"]).astimezone(LOCAL).date() for e in closed}
    return {"closed": len(values), "wins": sum(v > 0 for v in values), "sum_net_r": round(sum(values), 4),
            "mean_net_r": round(sum(values) / len(values), 4) if values else None,
            "hit_rate": round(sum(v > 0 for v in values) / len(values), 4) if values else None,
            "max_drawdown_r": max_drawdown(values), "days_without_close": len(days - traded),
            "judgeable": len(values) >= MIN_TRADES}


def journal_report(journal: Mapping[str, Any], until: datetime, days: int = 7) -> dict[str, Any]:
    if journal.get("blocked"):
        return {"readable": False, "integrity": journal.get("integrity")}
    entries = journal.get("entries") or []
    since = until - timedelta(days=days)
    week, before = window_stats(entries, since, until), window_stats(entries, since - timedelta(days=days), since)
    created = [_time(e["created_at"]) for e in entries if e.get("created_at")]
    return {"readable": True, "integrity": journal.get("integrity", "OK"), "entries": len(entries),
            "last_entry_at": max(created).isoformat() if created else None,
            "new_plans": sum(since <= moment < until for moment in created),
            "week": week, "previous_week": before,
            "change_sum_net_r": round(week["sum_net_r"] - before["sum_net_r"], 4),
            "all_time": window_stats(entries, datetime.min.replace(tzinfo=timezone.utc), until) | {"days_without_close": None}}


def _one_journal(path: Path, until: datetime, days: int) -> dict[str, Any]:
    """A present but broken journal (no valid document, no event log) is named, never shown as healthy and empty."""
    from src.dashboard.plan_journal import SCHEMA, events_path_for, load_view

    if not path.exists():
        return {"readable": False, "integrity": "FILE_MISSING"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    valid = isinstance(data, dict) and data.get("schema") == SCHEMA and isinstance(data.get("entries"), list)
    if not valid and not events_path_for(path).exists():
        return {"readable": False, "integrity": "UNREADABLE_OR_WRONG_SCHEMA"}
    return journal_report(load_view(path), until, days)


def report(journal_paths: Sequence[Path], shadow_path: Path | None, until: datetime, days: int = 7) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": "TIM_JOURNAL_WEEK_V1", "until": until.isoformat(), "days": days,
                           "min_trades_for_verdict": MIN_TRADES, "journals": {}, "shadow": None}
    for path in journal_paths:
        out["journals"][str(path)] = _one_journal(Path(path), until, days)
    if shadow_path is not None:
        state = load_shadow(current_path(Path(shadow_path)))   # E1: the pit/1 file
        out["shadow"] = {"readable": False} if state is None else {"readable": True, **shadow_summary(state)}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("journals", nargs="+", type=Path)
    parser.add_argument("--shadow", type=Path, help="orderflow shadow state file")
    parser.add_argument("--until", help="timezone-aware ISO-8601 end of the window (default: now)")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    until = datetime.fromisoformat(args.until) if args.until else datetime.now(timezone.utc)
    if until.tzinfo is None or args.days < 1:
        print("--until needs a timezone and --days must be at least 1", file=sys.stderr)
        return 2
    json.dump(report(args.journals, args.shadow, until, args.days), sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
