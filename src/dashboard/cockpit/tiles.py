"""Tile contract and status rule of the new Control Center (Cockpit).

Every tile carries value, state, reason, source and as-of time. One rule here
decides the colour, so the same evidence looks the same on every page:

* ``ok``      green: validated healthy and fresh.
* ``warn``    yellow: needs a look (degraded, waiting, stale, partial).
* ``fail``    red: a measured fault.
* ``unknown`` grey: no data, or deliberately off. Never shown without a reason.

A tile that is not green always has a reason in plain words. A tile whose data
is older than its freshness limit is at least yellow and says how old it is.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.dashboard.design_system import severity
from src.dashboard.helpers import _parse_time

STATES = ("ok", "warn", "fail", "unknown")
STATE_LABELS = {"ok": "OK", "warn": "Prüfen", "fail": "Fehler", "unknown": "Keine Daten"}
# Severity keys of the old design system mapped onto the four cockpit states.
_FROM_SEVERITY = {
    "ok": "ok", "fail": "fail", "warn": "warn", "degraded": "warn", "blocked": "warn",
    "info": "warn", "unknown": "unknown", "disabled": "unknown",
}
_ORDER = {"fail": 0, "warn": 1, "unknown": 2, "ok": 3}
NO_REASON = "Kein Grund angegeben"


@dataclass(slots=True)
class Tile:
    id: str
    label: str
    value: str
    state: str = "unknown"
    reason: str = ""
    source: str = ""
    as_of: str | None = None
    max_age_seconds: int | None = None
    age_seconds: int | None = None
    detail: str = ""
    href: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def state_of(raw_status: Any) -> str:
    """Map any status word (PASS, RED, STALE, BLOCKED …) to one of the four states."""
    return _FROM_SEVERITY.get(severity(raw_status), "warn")


def age_seconds(as_of: Any, now: datetime | None = None) -> int | None:
    moment = _parse_time(as_of)
    if moment is None:
        return None
    now = now or datetime.now(timezone.utc)
    return int((now - moment).total_seconds())


def human_age(seconds: int | None) -> str:
    if seconds is None:
        return "Alter unbekannt"
    if seconds < -60:
        return "Zeitstempel in der Zukunft"
    seconds = max(0, seconds)
    if seconds < 90:
        return f"vor {seconds} s"
    if seconds < 90 * 60:
        return f"vor {round(seconds / 60)} min"
    if seconds < 36 * 3600:
        return f"vor {round(seconds / 3600)} h"
    return f"vor {round(seconds / 86400)} Tagen"


def make_tile(
    tile_id: str,
    label: str,
    value: Any,
    raw_status: Any = None,
    *,
    state: str | None = None,
    reason: str = "",
    source: str = "",
    as_of: Any = None,
    max_age_seconds: int | None = None,
    detail: str = "",
    href: str = "",
    now: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> Tile:
    """Build a tile and apply the status rule (freshness and reason)."""
    chosen = state if state in STATES else state_of(raw_status)
    text = "—" if value in (None, "") else str(value)
    age = age_seconds(as_of, now) if as_of else None
    why = reason.strip()
    if max_age_seconds is not None and chosen != "unknown":
        if age is None:
            # Only a green tile loses its colour; a red or yellow one keeps it.
            if chosen == "ok":
                chosen = "unknown"
            why = (why + " · " if why else "") + "Kein lesbarer Zeitstempel: Frische lässt sich nicht prüfen"
        elif age < -60:
            chosen = "warn" if chosen == "ok" else chosen
            why = (why + " · " if why else "") + "Zeitstempel liegt in der Zukunft (Uhr prüfen)"
        elif age > max_age_seconds:
            if chosen == "ok":
                chosen = "warn"
            why = (why + " · " if why else "") + f"Daten veraltet: {human_age(age)}, Grenze {human_age(max_age_seconds).removeprefix('vor ')}"
    if chosen != "ok" and not why:
        why = NO_REASON + (f" (Quelle: {source})" if source else "")
    return Tile(
        id=tile_id, label=label, value=text, state=chosen, reason=why, source=source,
        as_of=str(as_of) if as_of else None, max_age_seconds=max_age_seconds, age_seconds=age,
        detail=detail, href=href, extra=dict(extra or {}),
    )


def unavailable(tile_id: str, label: str, reason: str, source: str = "", href: str = "") -> Tile:
    """A grey tile for a source that could not be read; the reason is mandatory."""
    return make_tile(tile_id, label, "—", state="unknown", reason=reason or NO_REASON, source=source, href=href)


def worst(states: list[str]) -> str:
    if not states:
        return "unknown"
    return min(states, key=lambda item: _ORDER.get(item, 2))


def attention(tiles: list[Tile]) -> list[Tile]:
    """Tiles that need a look: red first, then yellow. Grey tiles stay on their card."""
    return sorted((tile for tile in tiles if tile.state in {"fail", "warn"}), key=lambda tile: _ORDER[tile.state])
