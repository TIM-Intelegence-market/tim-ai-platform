"""Options gamma for the Control Center: Deribit's public options book, read-only.

The runtime (main.py) calls ``refresh`` every few minutes. It reads two public
Deribit endpoints (no key, no account): the options book summary and the index
price, computes the snapshot with ``src.options_gamma.snapshot`` and stores it
in ``DashboardState.gamma``. Consumers:

- ``/api/gamma`` (full snapshot plus age and freshness),
- ``/api/prep`` (``gamma`` block: regime, levels, analysis input),
- the interactive chart (group "gamma": flip, gamma walls, open-interest walls, max pain, expected move;
  each line starts when the level reached its current price, never earlier),
- a level log (``append_level_log``, one JSON line per snapshot) so a later study can
  ask how price reacted at the walls (reel DfTgoOTx6Qs, Uzi 04.11.2026). Deribit keeps
  no history of these levels, so the log only grows from the day it was switched on.

Display and analysis context only: nothing here trades, writes a plan or
changes a score. A failed read keeps the last snapshot, which then turns stale.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.options_gamma.snapshot import build_gamma_snapshot

DERIBIT_PUBLIC = "https://www.deribit.com/api/v2/public"
CURRENCY_BY_SYMBOL = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
REFRESH_SECONDS = 300
STALE_AFTER = timedelta(minutes=20)  # four missed refreshes
SAME_LEVEL = 0.0025  # a level within 0.25 % of its anchor counts as unchanged (strikes lie further apart)
LOG_TAIL_BYTES = 200_000  # roughly the last day of the level log
TIMEOUT_SECONDS = 15
MAX_BYTES = 8_000_000

# Colour and line style per level key in the chart.
LEVEL_STYLE = {
    "flip": ("#ffb020", "solid"),
    "call_wall": ("#3ddc97", "solid"),
    "put_wall": ("#ff5c7a", "solid"),
    "max_pain": ("#c0c6d4", "dashed"),
    "em_high": ("#8a94a6", "dotted"),
    "em_low": ("#8a94a6", "dotted"),
    "oi_call": ("#3ddc97", "dashed"),
    "oi_put": ("#ff5c7a", "dashed"),
}

Fetch = Callable[[str, Mapping[str, str]], Any]


def _fetch_json(method: str, params: Mapping[str, str]) -> Any:
    url = f"{DERIBIT_PUBLIC}/{method}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "TIM-ControlCenter/1 (read-only)"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https host
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("deribit response too large")
    return json.loads(body)


def _result(payload: Any, label: str) -> Any:
    if not isinstance(payload, Mapping) or "result" not in payload:
        raise ValueError(f"deribit {label}: no result")
    return payload["result"]


def fetch_snapshot(currency: str = "BTC", fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Read the public book summary and index price, return the computed snapshot."""
    fetch = fetch or _fetch_json
    rows = _result(fetch("get_book_summary_by_currency", {"currency": currency, "kind": "option"}), "book summary")
    if not isinstance(rows, list):
        raise ValueError("deribit book summary: result is not a list")
    index = _result(fetch("get_index_price", {"index_name": f"{currency.lower()}_usd"}), "index price")
    spot = index.get("index_price") if isinstance(index, Mapping) else None
    if not isinstance(spot, (int, float)) or isinstance(spot, bool):
        raise ValueError("deribit index price missing")
    return build_gamma_snapshot(rows, float(spot), now or datetime.now(timezone.utc), currency=currency)


def refresh(state: Any, symbol: str, fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Store a new snapshot for ``symbol`` in ``state.gamma``; None for symbols without options data."""
    currency = CURRENCY_BY_SYMBOL.get(symbol)
    if currency is None:
        return None
    snapshot = fetch_snapshot(currency, fetch=fetch, now=now)
    log_path = getattr(state, "gamma_log_path", None)
    with state.lock:
        previous = state.gamma.get(symbol)
    if previous is None and log_path is not None:
        previous = {"level_since": since_from_log(snapshot, symbol, Path(log_path))}
    snapshot["level_since"] = level_since(snapshot, previous)
    with state.lock:
        state.gamma = {**state.gamma, symbol: snapshot}
    if log_path is not None:
        append_level_log(snapshot, symbol, Path(log_path))
    return snapshot


def _same_level(a: Any, b: Any) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > 0 and abs(a / b - 1) <= SAME_LEVEL


def level_since(snapshot: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Since when each level stands where it is now: ``{key: {"since": iso, "price": anchor}}``.

    A level keeps its start while it stays within ``SAME_LEVEL`` of the price it had at that start (the anchor,
    so slow drift cannot stretch a line for ever); otherwise it starts anew with this snapshot. The chart draws
    a level only from its start. A line reaching further back would lie over candles that traded while the
    level was somewhere else, and look like a reaction that never happened.
    """
    known = (previous or {}).get("level_since") or {}
    out = {}
    for item in snapshot["levels"]:
        old = known.get(item["key"])
        keep = isinstance(old, Mapping) and _same_level(item["price"], old.get("price"))
        out[item["key"]] = dict(old) if keep else {"since": snapshot["as_of"], "price": item["price"]}
    return out


def _logged_levels(record: Mapping[str, Any]) -> dict[str, Any]:
    walls = record.get("oi_walls") or {}
    return {"flip": record.get("gamma_flip"), "call_wall": record.get("call_wall"), "put_wall": record.get("put_wall"),
            "max_pain": record.get("max_pain"),
            "oi_call": (walls.get("calls") or [[None]])[0][0], "oi_put": (walls.get("puts") or [[None]])[0][0]}


def since_from_log(snapshot: Mapping[str, Any], symbol: str, path: Path) -> dict[str, dict[str, Any]]:
    """After a restart: read the starts back from the tail of the level log (about the last day)."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            offset = max(0, handle.tell() - LOG_TAIL_BYTES)
            handle.seek(offset)
            lines = handle.read().decode("utf-8", "replace").splitlines()[1 if offset else 0:]  # a cut first line is dropped
    except OSError:
        return {}
    records = []
    for line in lines:
        try:
            record = json.loads(line)
            if record.get("symbol") == symbol and datetime.fromisoformat(str(record["as_of"])) < datetime.fromisoformat(str(snapshot["as_of"])):
                records.append(record)
        except (ValueError, KeyError, TypeError):
            continue
    out = {}
    for item in snapshot["levels"]:
        since = None
        for newer, record in zip([snapshot] + records[::-1], records[::-1]):
            gap = datetime.fromisoformat(str(newer["as_of"])) - datetime.fromisoformat(str(record["as_of"]))
            if gap > STALE_AFTER or not _same_level(_logged_levels(record).get(item["key"]), item["price"]):
                break
            since = record["as_of"]
        if since is not None:
            out[item["key"]] = {"since": since, "price": item["price"]}
    return out


def level_record(snapshot: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    """The compact line of the level log: walls, flip, max pain and regime of one snapshot."""
    overall, main = snapshot["all_expiries"], snapshot["main_expiry"]
    return {
        "symbol": symbol, "as_of": snapshot["as_of"], "spot": snapshot["spot"],
        "call_wall": overall["call_wall"], "put_wall": overall["put_wall"], "gamma_flip": overall["gamma_flip"],
        "regime": overall["regime"], "price_vs_flip": overall["price_vs_flip"],
        "net_gex_usd_per_1pct": overall["net_gex_usd_per_1pct"],
        "main_expiry": main.get("expiry"), "main_call_wall": main["call_wall"], "main_put_wall": main["put_wall"],
        "max_pain": main["max_pain"], "oi_walls": overall["oi_walls"],
    }


def append_level_log(snapshot: Mapping[str, Any], symbol: str, path: Path) -> bool:
    """Append one line per new snapshot; the same ``as_of`` twice is written once. Returns whether it wrote."""
    record = level_record(snapshot, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 4096))
            tail = handle.read().decode("utf-8", "replace").strip().splitlines()
        if tail and json.loads(tail[-1]).get("as_of") == record["as_of"] and json.loads(tail[-1]).get("symbol") == symbol:
            return False
    except (OSError, ValueError):
        pass
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return True


def with_age(snapshot: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any] | None:
    """Snapshot plus ``age_seconds``, ``future`` and ``stale``; None when there is none.

    A snapshot from after ``now`` is not yet available (point in time): ``future`` and ``stale`` are both True."""
    if not snapshot:
        return None
    now = now or datetime.now(timezone.utc)
    age = now - datetime.fromisoformat(str(snapshot["as_of"]))
    future = age < timedelta(0)
    return {**snapshot, "age_seconds": int(age.total_seconds()), "future": future, "stale": future or age > STALE_AFTER}


def prep_block(snapshot: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """Compact gamma block for /api/prep and the analyses."""
    current = with_age(snapshot, now)
    if current is None:
        return {"status": "MISSING", "note": "noch kein Deribit-Schnappschuss"}
    overall = current["all_expiries"]
    return {
        "status": "STALE" if current["stale"] else "OK",
        "as_of": current["as_of"],
        "age_seconds": current["age_seconds"],
        "source": current["source"],
        "convention": current["convention"],
        "spot": current["spot"],
        "regime": overall["regime"],
        "price_vs_flip": overall["price_vs_flip"],
        "net_gex_usd_per_1pct": overall["net_gex_usd_per_1pct"],
        "main_expiry": current["main_expiry"]["expiry"],
        "main_expiry_share": current["main_expiry"]["share_of_open_interest"],
        "main_expiry_regime": current["main_expiry"]["regime"],
        "expected_move": current["expected_move"],
        "oi_walls": overall["oi_walls"],
        "levels": [dict(item) for item in current["levels"]],
        "analysis_input": dict(current["analysis_input"]),
    }


STATE_TEXT = {
    "BELOW_FLIP": "NEGATIV (Preis unter dem Flip: Händler verstärken Bewegungen eher)",
    "ABOVE_FLIP": "POSITIV (Preis über dem Flip: Händler dämpfen Bewegungen eher)",
    "AT_FLIP": "NEUTRAL (Preis am Flip)",
}


def state_note(snapshot: Mapping[str, Any]) -> str | None:
    """One line for the chart: gamma state by price against the flip. An estimate, never a signal."""
    overall = snapshot["all_expiries"]
    text = STATE_TEXT.get(overall.get("price_vs_flip"))
    if text is None:
        return None
    flip = overall.get("gamma_flip")
    return f"Gamma-Zustand: {text}, Flip {flip:,.0f}. Schätzung aus Deribit-Open-Interest, nur Beobachtung."


def chart_drawings(snapshot: Mapping[str, Any] | None, now: datetime | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Chart drawings (group "gamma") and notes. Stale snapshots draw nothing."""
    current = with_age(snapshot, now)
    if current is None:
        return [], []
    if current["stale"]:
        return [], [f"Gamma: Deribit-Stand ist {current['age_seconds'] // 60} min alt, Level ausgeblendet."]
    since = current.get("level_since") or {}
    drawings = []
    notes = [note for note in (state_note(current),) if note]
    for item in current["levels"]:
        color, style = LEVEL_STYLE.get(item["key"], ("#ffb020", "dashed"))
        drawings.append({"group": "gamma", "tf": "Opt", "name": item["name"], "label": f"Opt {item['name']}",
                         "price": float(item["price"]), "start": (since.get(item["key"]) or {}).get("since", current["as_of"]), "note": item["note"],
                         "color": color, "style": style})
    return drawings, notes
