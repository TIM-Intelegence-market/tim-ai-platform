"""Gamma zones confirmed by the order book: display and shadow log, no signal, no order.

Uzi 21.11.2026: "die besonderen Gamma-Preiszonen einzeichnen mithilfe des Orderbuches". The options levels of
:mod:`src.dashboard.gamma_data` (Deribit) alone were hardly reliable as price levels (review of 17.11.2026). The
order book shows where large resting orders really stand right now. A gamma level counts as a confirmed zone
when a standing wall of our own Binance perpetual recording (:mod:`src.research_lab.orderbook.walls`, at least
30 minutes old) lies within ``TOLERANCE_PCT`` of it.

Three parts:

* ``refresh`` follows the recorder's archive and stores walls and confirmed zones in ``state.gamma_zones``.
* ``chart_drawings`` draws each confirmed zone as a band (group "gamma_ob").
* ``track`` / ``update`` keep a shadow log of every visit to a confirmed zone: gehalten (price left on the side
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

from src.research_lab.orderbook import walls as wall_rules

RULESET = "gamma-orderbuch/1.1"  # 1.1 (22.11.2026): every standing wall counts, not only the 5 largest per side
SCHEMA = "tim_gamma_zone_watch/1"
LEVEL_KEYS = ("flip", "call_wall", "put_wall", "oi_call", "oi_put")  # expected move and max pain are no gamma levels
TOLERANCE_PCT = 0.003   # wall within 0.3 % of the gamma level
PAD_PCT = 0.001         # a visit ends when the price is 0.1 % outside the zone
STALE_AFTER = timedelta(minutes=10)  # walls older than this are not drawn (recorder or reader stands still)
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


def build(gamma: Mapping[str, Any] | None, walls_view: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """View for state, API and chart from a gamma snapshot and the walls view of :class:`walls.Tail`."""
    now = now or datetime.now(timezone.utc)
    out: dict[str, Any] = {"ruleset": RULESET, "walls_ruleset": wall_rules.RULESET, "as_of": now.isoformat(),
                           "status": "OK", "note": None, "walls": [], "zones": [], "mid": None}
    if not walls_view or walls_view.get("last_event_ms") is None:
        return {**out, "status": "MISSING", "note": "kein Orderbuch-Archiv gefunden oder noch kein Stand"}
    out["mid"] = walls_view.get("mid")
    out["walls_as_of"] = datetime.fromtimestamp(walls_view["last_event_ms"] / 1000, timezone.utc).isoformat()
    if not walls_view.get("caught_up"):
        return {**out, "status": "CATCHING_UP", "note": "Orderbuch-Archiv wird noch eingelesen"}
    if now - datetime.fromisoformat(out["walls_as_of"]) > STALE_AFTER or not walls_view.get("synced"):
        return {**out, "status": "STALE", "note": "Orderbuch-Stand ist alt oder ohne Anschluss, Zonen ausgeblendet"}
    out["walls"] = [dict(w) for w in walls_view.get("walls") or []]   # the largest per side, for the display
    if not gamma or not gamma.get("levels"):
        return {**out, "status": "NO_GAMMA", "note": "kein Gamma-Stand"}
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
        text = f"Gamma-Zonen mit Orderbuch: {len(drawings)} bestätigt"
        if counts and counts["closed"]:
            text += f", Berührungen {counts['closed']} ({counts['held']} gehalten, {counts['broken']} gebrochen), Urteil ab {VERDICT_FROM}"
        notes.append(text + ".")
    elif view.get("note"):
        notes.append(f"Gamma-Zonen: {view['note']}.")
    return drawings, notes


# --- shadow log ---------------------------------------------------------------------------------------------------

def load(path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    target = Path(path)
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
    visits = (state or {}).get("visits") or []
    return {"open": len((state or {}).get("open") or []), "closed": len(visits),
            "held": sum(1 for v in visits if v["outcome"] == "gehalten"),
            "broken": sum(1 for v in visits if v["outcome"] == "gebrochen"),
            "pulled": sum(1 for v in visits if v.get("wall_pulled"))}


def track(state: Mapping[str, Any] | None, view: Mapping[str, Any], price: float, at: str) -> dict[str, Any]:
    """One step of the shadow log, pure.

    A visit opens when the price stands in a confirmed zone and the price of the step before lay outside it (so
    the side it came from is known). The zone is frozen at that moment. The visit closes when the price is more
    than the pad outside: on the side it came from = gehalten, on the other side = gebrochen. If the zone is no
    longer confirmed while the visit runs, ``wall_pulled`` is set; the visit still ends by price.
    """
    previous = state or {}
    out = {"schema": SCHEMA, "ruleset": RULESET, "started_at": previous.get("started_at") or at, "open": [],
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
                            "wall_pulled": False})
    out["visits"] = out["visits"][-MAX_VISITS:]
    return out


def update(path: Path, view: Mapping[str, Any] | None, price: float | None, now: datetime | None = None) -> dict[str, Any] | None:
    """Runtime hook: advance the shadow log with the current price and save it. Writes only its own file."""
    if not view or price is None:
        return None
    at = (now or datetime.now(timezone.utc)).isoformat()
    state = track(load(path), view, float(price), at)
    _save(state, Path(path))
    return state
