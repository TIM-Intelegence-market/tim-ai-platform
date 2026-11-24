"""Gamma levels with an order-book wall nearby: display and shadow log, no signal, no order.

Uzi 21.11.2026: "die besonderen Gamma-Preiszonen einzeichnen mithilfe des Orderbuches". The options levels of
:mod:`src.dashboard.gamma_data` (Deribit) alone were hardly reliable as price levels (review of 17.11.2026). The
order book shows where large resting orders really stand right now. A gamma level is drawn as a zone when a
standing wall of our own Binance perpetual recording (:mod:`src.research_lab.orderbook.walls`, at least
30 minutes old) lies within ``TOLERANCE_PCT`` of it. That says a wall stands near the level, not that a gamma
effect is confirmed.

Both sources must be fresh and plausible before any zone is shown (1.2, 24.11.2026): the order book (``walls_as_of``)
and the gamma snapshot (``gamma_as_of``). Every view carries both times, so the UI and the API can show them.

Three parts:

* ``refresh`` follows the recorder's archive and stores walls and zones in ``state.gamma_zones``.
* ``chart_drawings`` draws each zone as a band (group "gamma_ob").
* ``track`` / ``update`` keep a shadow log of every visit to a zone: gehalten (price left on the side
  it came from) or gebrochen (price went through), and whether the wall was pulled during the visit.

The rule is frozen (``RULESET``) before any outcome was seen. Order-flow rules cannot be backtested here (no
order book history), so the shadow log is the only test: a verdict is due from ``VERDICT_FROM`` closed visits.
Only BTC (the only recorded book). Options from Deribit, book from Binance: two venues, said in the legend.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard import gamma_data
from src.research_lab.orderbook import walls as wall_rules

# 1.1 (22.11.2026): every standing wall counts, not only the 5 largest per side.
# 1.2 (24.11.2026): zones only when the gamma snapshot is fresh too (no old, missing or future ``as_of``) and the book
# time is not in the future. Point in time: a source time after now (even by a second) is not yet available, so no
# zone; a skew beyond ``FUTURE_SKEW`` is flagged apart as a probable clock error (diagnosis only, not a gate).
# Rollback-safe: 1.2 writes its own file (``log_path``), the 1.1 log stays byte for byte as it was, so a revert to 1.1
# sees only 1.1 visits and a return to 1.2 continues its own file. Visits beyond ``MAX_VISITS`` go to an archive
# file next to it (append only), never lost.
RULESET = "gamma-orderbuch/1.2"
SCHEMA = "tim_gamma_zone_watch/1"
LEVEL_KEYS = ("flip", "call_wall", "put_wall", "oi_call", "oi_put")  # expected move and max pain are no gamma levels
TOLERANCE_PCT = 0.003   # wall within 0.3 % of the gamma level
PAD_PCT = 0.001         # a visit ends when the price is 0.1 % outside the zone
STALE_AFTER = timedelta(minutes=10)  # walls older than this are not drawn (recorder or reader stands still)
GAMMA_STALE_AFTER = gamma_data.STALE_AFTER  # gamma snapshot older than this: no zones (same limit as the gamma lines)
FUTURE_SKEW = timedelta(seconds=60)  # diagnosis: a source time more than this ahead of now is a clock error
# Statuses with a fresh book: the price is known, so the runtime may advance the shadow log (open visits close by
# price). Only "OK" ever opens a visit (``track``).
WATCH_STATUSES = ("OK", "NO_GAMMA", "STALE_GAMMA", "FUTURE_GAMMA")
VERDICT_FROM = 30       # closed visits before the first verdict
MAX_VISITS = 500
DEFAULT_PATH = Path("data/journal/tim_gamma_zone_watch.json")
ROOT_ENV = "TIM_ORDERBOOK_ROOT"
DEFAULT_ROOT = Path("~/Documents/TIM/orderbook/binance")
COLOR = "#ffd24a"
SIDE_DE = {"bid": "Kaufmauer", "ask": "Verkaufsmauer"}

LOCAL = ZoneInfo("Europe/Berlin")

_TAILS: dict[tuple[str, str], wall_rules.Tail] = {}


def archive_root() -> Path:
    return Path(os.environ.get(ROOT_ENV) or DEFAULT_ROOT).expanduser()


def confirm(levels: Sequence[Mapping[str, Any]], walls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Gamma levels with a standing wall close by. One zone per level, with the largest wall in tolerance."""
    zones = []
    for level in levels:
        if level.get("key") not in LEVEL_KEYS:
            continue
        price = float(level["price"])
        tolerance = price * TOLERANCE_PCT
        near = [w for w in walls if w["low"] - tolerance <= price <= w["high"] + tolerance]
        if not near:
            continue
        wall = max(near, key=lambda w: w["qty"])
        zones.append({"key": level["key"], "name": level["name"], "level": price, "side": wall["side"],
                      "low": min(price, wall["low"]), "high": max(price, wall["high"]),
                      "wall_low": wall["low"], "wall_high": wall["high"], "wall_qty": wall["qty"],
                      "wall_usd": wall["notional_usd"], "wall_ratio": wall["ratio"], "wall_since_ms": wall["since_ms"]})
    merged: list[dict[str, Any]] = []
    for zone in sorted(zones, key=lambda z: (z["low"], z["level"])):   # two levels on the same wall are one zone
        last = merged[-1] if merged else None
        if last and zone["low"] <= last["high"] and zone["wall_low"] == last["wall_low"] and zone["side"] == last["side"]:
            last["high"] = max(last["high"], zone["high"])
            last["name"] = f"{last['name']} + {zone['name']}"
            last["key"] = f"{last['key']}+{zone['key']}"
        else:
            merged.append(dict(zone))
    return merged


def _parse_time(value: Any) -> datetime | None:
    """ISO time with a zone, else None (a naive or unparsable time cannot be compared with now)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def gamma_check(gamma: Mapping[str, Any] | None, now: datetime) -> tuple[str, str | None, dict[str, Any]]:
    """Status of the gamma snapshot for the zones: OK, NO_GAMMA, STALE_GAMMA or FUTURE_GAMMA, a note and its times."""
    times: dict[str, Any] = {"gamma_as_of": None, "gamma_age_seconds": None, "gamma_clock_skew_suspect": False}
    if not gamma or not gamma.get("levels"):
        return "NO_GAMMA", "kein Gamma-Stand", times
    moment = _parse_time(gamma.get("as_of"))
    if moment is None:
        return "NO_GAMMA", "Gamma-Stand ohne gültige Zeit, Zonen ausgeblendet", times
    age = now - moment
    times = {"gamma_as_of": moment.isoformat(), "gamma_age_seconds": int(age.total_seconds()),
             "gamma_clock_skew_suspect": age < -FUTURE_SKEW}
    if age < timedelta(0):                       # not yet available at ``now``: never a zone, whatever the cause
        return "FUTURE_GAMMA", "Gamma-Stand liegt in der Zukunft, Zonen ausgeblendet", times
    if age > GAMMA_STALE_AFTER:
        return "STALE_GAMMA", "Gamma-Stand ist alt, Zonen ausgeblendet", times
    return "OK", None, times


def build(gamma: Mapping[str, Any] | None, walls_view: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """View for state, API and chart from a gamma snapshot and the walls view of :class:`walls.Tail`.

    Only status OK carries zones. Every view carries ``gamma_as_of``, ``gamma_age_seconds`` and ``walls_as_of``
    (None when unknown). Book checks come first (without a fresh book nothing is known), then the gamma checks.
    """
    now = now or datetime.now(timezone.utc)
    gamma_status, gamma_note, gamma_times = gamma_check(gamma, now)
    out: dict[str, Any] = {"ruleset": RULESET, "walls_ruleset": wall_rules.RULESET, "as_of": now.isoformat(),
                           "status": "OK", "note": None, "walls": [], "zones": [], "mid": None,
                           "walls_as_of": None, "walls_clock_skew_suspect": False, **gamma_times}
    if not walls_view or walls_view.get("last_event_ms") is None:
        return {**out, "status": "MISSING", "note": "kein Orderbuch-Archiv gefunden oder noch kein Stand"}
    out["mid"] = walls_view.get("mid")
    walls_at = datetime.fromtimestamp(walls_view["last_event_ms"] / 1000, timezone.utc)
    out["walls_as_of"] = walls_at.isoformat()
    out["walls_clock_skew_suspect"] = walls_at - now > FUTURE_SKEW
    if walls_at > now:
        return {**out, "status": "FUTURE_BOOK", "note": "Orderbuch-Zeit liegt in der Zukunft, Zonen ausgeblendet"}
    if not walls_view.get("caught_up"):
        return {**out, "status": "CATCHING_UP", "note": "Orderbuch-Archiv wird noch eingelesen"}
    if now - walls_at > STALE_AFTER or not walls_view.get("synced"):
        return {**out, "status": "STALE", "note": "Orderbuch-Stand ist alt oder ohne Anschluss, Zonen ausgeblendet"}
    out["walls"] = [dict(w) for w in walls_view.get("walls") or []]   # the largest per side, for the display
    if gamma_status != "OK":
        return {**out, "status": gamma_status, "note": gamma_note}
    # Offline check 22.11.2026 (5 h real book): with only the 5 largest walls per side a smaller wall right at the
    # put wall dropped out, zones were missing in 130 of 319 minutes and flickered. Zones look at every standing wall.
    every = walls_view.get("walls_all")
    out["zones"] = confirm(gamma["levels"], [dict(w) for w in (every if every is not None else out["walls"])])
    return out


def refresh(state: Any, symbol: str, root: Path | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Advance the archive reader and store the view in ``state.gamma_zones``; None for symbols without a book."""
    if symbol not in wall_rules.BUCKET_USD:
        return None
    root = Path(root) if root is not None else archive_root()
    key = (str(root), symbol)
    tail = _TAILS.get(key)
    if tail is None:
        moment = now or datetime.now(timezone.utc)
        tail = _TAILS[key] = wall_rules.Tail(root, symbol, int(moment.timestamp() * 1000) - wall_rules.LOOKBACK_SECONDS * 1000)
    tail.advance()
    with state.lock:
        gamma = state.gamma.get(symbol)
    view = build(gamma, tail.view(), now)
    with state.lock:
        state.gamma_zones = {**getattr(state, "gamma_zones", {}), symbol: view}
    return view


def _de(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _usd(value: float) -> str:
    return f"{value / 1e6:.1f} Mio $".replace(".", ",")


def chart_drawings(view: Mapping[str, Any] | None, watch: Mapping[str, Any] | None = None,
                   now: datetime | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Chart drawings (group "gamma_ob": a line at the level with ``band`` [low, high]) and notes."""
    if not view:
        return [], []
    now = now or datetime.now(timezone.utc)
    if now - datetime.fromisoformat(str(view["as_of"])) > STALE_AFTER:
        return [], []
    drawings = []
    for zone in view.get("zones") or []:
        since = datetime.fromtimestamp(zone["wall_since_ms"] / 1000, timezone.utc)
        note = (f"Gamma-Level {zone['name']} bei {_de(zone['level'])} mit {SIDE_DE[zone['side']]} im Orderbuch: "
                f"{_de(zone['wall_qty'])} BTC ({_usd(zone['wall_usd'])}), {_de(zone['wall_ratio'], 1)}-fach über üblich, "
                f"steht seit {since.astimezone(LOCAL).strftime('%d.%m. %H:%M')} Uhr. Aufträge können jederzeit zurückgezogen werden.")
        drawings.append({"group": "gamma_ob", "tf": "Opt", "name": f"Zone {zone['name']}", "label": f"Gamma-Zone {zone['name']}",
                         "price": float(zone["level"]), "band": [float(zone["low"]), float(zone["high"])],
                         "start": since.isoformat(), "note": note, "color": COLOR, "style": "solid"})
    notes = []
    counts = summary(watch) if watch else None
    if view.get("status") == "OK":
        text = f"Gamma-Level mit Orderbuch-Mauer: {len(drawings)}"
        if counts and counts["closed"]:
            text += f", Berührungen {counts['closed']} ({counts['held']} gehalten, {counts['broken']} gebrochen), Urteil ab {VERDICT_FROM}"
        notes.append(text + ".")
    elif view.get("note"):
        notes.append(f"Gamma-Zonen: {view['note']}.")
    return drawings, notes


# --- shadow log ---------------------------------------------------------------------------------------------------

def log_path(path: Path = DEFAULT_PATH) -> Path:
    """The file of the current ruleset next to ``path`` (``path`` itself holds the 1.1 log and is never written)."""
    path = Path(path)
    return path.with_name(f"{path.stem}.{RULESET.replace('/', '-')}{path.suffix}")


def archive_path(path: Path = DEFAULT_PATH) -> Path:
    target = log_path(path)
    return target.with_name(target.stem + ".archive.jsonl")


def load(path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    """The shadow log of the current ruleset (see :func:`log_path`)."""
    target = log_path(path)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _save(state: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def summary(state: Mapping[str, Any] | None) -> dict[str, int]:
    """Counts of the current ``RULESET`` only. Visits of an earlier ruleset (1.1 visits carry no ``ruleset``) are
    never counted in; should a log hold some, they show in ``earlier_open`` / ``earlier_closed``."""
    every = (state or {}).get("visits") or []
    every_open = (state or {}).get("open") or []
    visits = [v for v in every if v.get("ruleset") == RULESET]
    opened = [v for v in every_open if v.get("ruleset") == RULESET]
    return {"open": len(opened), "closed": len(visits),
            "held": sum(1 for v in visits if v["outcome"] == "gehalten"),
            "broken": sum(1 for v in visits if v["outcome"] == "gebrochen"),
            "pulled": sum(1 for v in visits if v.get("wall_pulled")),
            "earlier_open": len(every_open) - len(opened), "earlier_closed": len(every) - len(visits)}


def track(state: Mapping[str, Any] | None, view: Mapping[str, Any], price: float, at: str) -> dict[str, Any]:
    """One step of the shadow log, pure.

    A visit opens when the price stands in a confirmed zone and the price of the step before lay outside it (so
    the side it came from is known). The zone is frozen at that moment. The visit closes when the price is more
    than the pad outside: on the side it came from = gehalten, on the other side = gebrochen. If the zone is no
    longer shown while the visit runs, ``wall_pulled`` is set; the visit still ends by price.

    Invalid states (any status but OK: book missing, old or in the future, gamma missing, old or in the future)
    never open a visit. Open visits go on: they still close by price, and ``wall_pulled`` is not set, because the
    zones are unknown then (not gone). New visits carry ``ruleset``; visits of earlier rulesets are kept as they are.
    """
    previous = state or {}
    out = {"schema": SCHEMA, "ruleset": RULESET, "started_at": previous.get("started_at") or at, "open": [],
           "archived": int(previous.get("archived") or 0),
           "visits": list(previous.get("visits") or []), "last_price": price, "updated_at": at}
    zones = (view.get("zones") or []) if view.get("status") == "OK" else None   # None: nothing known about the book now
    for visit in previous.get("open") or []:
        pad = visit["pad"]
        if zones is not None and not any(z["wall_low"] == visit["wall_low"] and z["side"] == visit["side"] for z in zones):
            visit = {**visit, "wall_pulled": True}
        if price < visit["low"] - pad or price > visit["high"] + pad:
            left = "unten" if price < visit["low"] else "oben"
            out["visits"].append({**visit, "closed_at": at, "exit_price": price, "left": left,
                                  "outcome": "gehalten" if left == visit["from"] else "gebrochen"})
        else:
            out["open"].append(visit)
    last = previous.get("last_price")
    if last is not None and previous.get("updated_at"):
        if datetime.fromisoformat(at) - datetime.fromisoformat(str(previous["updated_at"])) > STALE_AFTER:
            last = None   # after a pause the side the price came from is not known
    for zone in zones or []:
        if not zone["low"] <= price <= zone["high"] or last is None or zone["low"] <= last <= zone["high"]:
            continue
        if any(v["low"] <= zone["high"] and zone["low"] <= v["high"] for v in out["open"]):
            continue
        out["open"].append({"opened_at": at, "key": zone["key"], "name": zone["name"], "level": zone["level"],
                            "low": zone["low"], "high": zone["high"], "side": zone["side"], "wall_low": zone["wall_low"],
                            "wall_qty": zone["wall_qty"], "wall_usd": zone["wall_usd"], "wall_ratio": zone["wall_ratio"],
                            "pad": price * PAD_PCT, "entry_price": price, "from": "unten" if last < zone["low"] else "oben",
                            "wall_pulled": False, "ruleset": RULESET})
    return out


def update(path: Path, view: Mapping[str, Any] | None, price: float | None, now: datetime | None = None) -> dict[str, Any] | None:
    """Runtime hook: advance the shadow log with the current price and save it. Writes only its own file."""
    if not view or price is None:
        return None
    at = (now or datetime.now(timezone.utc)).isoformat()
    state = track(load(path), view, float(price), at)
    overflow = state["visits"][:-MAX_VISITS]
    if overflow:                                   # retention: keep the newest in the log, the rest appended, not lost
        archive = archive_path(path)
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("a", encoding="utf-8") as fh:
            for visit in overflow:
                fh.write(json.dumps(visit, ensure_ascii=False, default=str) + "\n")
        state = {**state, "visits": state["visits"][-MAX_VISITS:], "archived": int(state.get("archived") or 0) + len(overflow)}
    _save(state, log_path(path))
    return state
