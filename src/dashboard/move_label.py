"""Market-event label for closed paper trades (Bauplan "Preisbewegungen erklären", P4, Uzi 16.11.2026).

After a paper trade of a BTC plan journal has closed, TIM checks whether a large move recorded by
``move_context`` (data/journal/tim_move_events.jsonl) overlapped the time the trade was open, and labels
the trade once:

- ``liquidations_kaskade``: a move whose liquidations finding was BELEGT or WAHRSCHEINLICH,
- ``markt_druck``: a move explained by another cause (flow, open interest, premium, stocks),
- ``makro_termin``: a move without such a cause but with a CPI/FOMC date in its window (only the time fits),
- ``news_notiz``: a move without such a cause but with a matching headline in its window (only the time fits),
- ``unerklaert``: a move without any of these,
- ``ruhig``: no recorded move while the trade was open.

Evidence first: a cause (BELEGT/WAHRSCHEINLICH) beats a date or headline, which are only ever VERMUTUNG. Several
moves: the first of that order wins (``ORDER``). The label is set only ``WAIT`` after the close, so a move that
started during the trade and ended later is recorded too (``move_context`` records up to ``RECORD_UNTIL`` after a
move's end; the newest record of a grown move counts), and only when the recorder's hourly heartbeat
(``move_context.beat``, written only while the recorder sees fresh candles) has no gap longer than ``MAX_GAP`` from the fill to the due time: a longer gap could hide a
move, so no label. Trades filled before ``RECORDING_SINCE`` get no label: no recording means no evidence of calm.

The label is written after the trade and is never an input for an entry, a plan, a score or a risk limit
(look-ahead). The learning loop only counts results per label (``plan_journal.summary``); groups under
``MIN_GROUP`` trades are shown with their size and not judged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.dashboard import move_context

RULE = "market-event/1"
RECORDING_SINCE = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)  # move recorder live on the Mac after #277
WAIT = timedelta(hours=30)  # a move that started in the trade may last a day (4 h merge gap) plus RECORD_UNTIL
MAX_GAP = timedelta(hours=4)  # the recorder catches a move up to 6 h after its end; hourly beats, room for a late step
MIN_GROUP = 30
CALM = "ruhig"
ORDER = ("liquidations_kaskade", "markt_druck", "makro_termin", "news_notiz", "unerklaert")
LABELS = (*ORDER, CALM)
STRONG = ("BELEGT", "WAHRSCHEINLICH")


def _time(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def move_kind(row: Mapping[str, Any]) -> str:
    """One label for one recorded move (pure)."""
    findings = [f for f in row.get("findings") or [] if isinstance(f, Mapping)]
    keys = {f.get("key") for f in findings}
    if any(f.get("key") == "liq" and f.get("level") in STRONG for f in findings):
        return "liquidations_kaskade"
    if row.get("explained"):
        return "markt_druck"
    if "macro" in keys:
        return "makro_termin"
    if "news" in keys:
        return "news_notiz"
    return "unerklaert"


def label_trade(entry: Mapping[str, Any], moves: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Label of one closed, filled trade from the recorded moves, or None when it cannot have one (pure)."""
    if entry.get("status") != "CLOSED" or entry.get("market_event") or entry.get("excluded"):
        return None
    opened, closed = _time(entry.get("filled_at")), _time(entry.get("closed_at"))
    if opened is None or closed is None or opened < RECORDING_SINCE:
        return None
    hits = []
    for row in moves:
        start, end = _time(row.get("start")), _time(row.get("end"))
        if start is not None and end is not None and start < closed and end > opened:
            hits.append(row)
    kinds = {move_kind(row) for row in hits}
    label = next((k for k in ORDER if k in kinds), CALM)
    return {"id": entry["id"], "label": label, "moves": sorted(str(row.get("id")) for row in hits), "rule": RULE,
            "move_rules": sorted({str(row["rules"]) for row in hits if row.get("rules")})}


def covered(hours: list[datetime], first: datetime, last: datetime) -> bool:
    """The heartbeat has no gap longer than MAX_GAP from ``first`` to ``last`` (pure; ``hours`` sorted)."""
    inside = [h for h in hours if first - timedelta(hours=1) <= h <= last]
    if not inside:
        return False
    points = [first, *inside, last]
    return all(b - a <= MAX_GAP for a, b in zip(points, points[1:]))


def labels(journal: Mapping[str, Any], moves_path: Path, now: datetime) -> list[dict[str, Any]]:
    """Payloads for closed trades that can be labelled now (reads only ``moves_path``)."""
    due = []
    for entry in journal.get("entries") or []:
        closed = _time(entry.get("closed_at"))
        if closed is not None and closed + WAIT <= now and label_trade(entry, []) is not None:
            due.append(entry)
    if not due:
        return []  # nothing to label: the record is not read
    hours = move_context.beats(moves_path)
    moves = list(move_context.latest(moves_path).values())
    out = []
    for entry in due:
        opened, closed = _time(entry["filled_at"]), _time(entry["closed_at"])
        if opened is not None and closed is not None and covered(hours, opened, closed + WAIT):
            out.append(label_trade(entry, moves))
    return out


def by_label(closed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts per label for the learning loop: trades, net R, costs; no verdict under MIN_GROUP (pure)."""
    groups: dict[str, Any] = {}
    for label in LABELS:
        mine = [e for e in closed if (e.get("market_event") or {}).get("label") == label]
        if not mine:
            continue
        groups[label] = {"closed": len(mine), "sum_net_r": round(sum(e.get("net_r") or 0.0 for e in mine), 3),
                         "sum_cost_r": round(sum((e.get("fee_r") or 0.0) + (e.get("slippage_r") or 0.0) for e in mine), 3),
                         "enough": len(mine) >= MIN_GROUP}
    return {"rule": RULE, "min_group": MIN_GROUP, "unlabelled": sum(not e.get("market_event") for e in closed), "groups": groups}
