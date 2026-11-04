"""Options gamma for the Control Center: Deribit's public options book, read-only.

The runtime (main.py) calls ``refresh`` every few minutes. It reads two public
Deribit endpoints (no key, no account): the options book summary and the index
price, computes the snapshot with ``src.options_gamma.snapshot`` and stores it
in ``DashboardState.gamma``. Consumers:

- ``/api/gamma`` (full snapshot plus age and freshness),
- ``/api/prep`` (``gamma`` block: regime, levels, analysis input),
- the interactive chart (group "gamma": flip, walls, max pain, expected move),
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
    with state.lock:
        state.gamma = {**state.gamma, symbol: snapshot}
    log_path = getattr(state, "gamma_log_path", None)
    if log_path is not None:
        append_level_log(snapshot, symbol, Path(log_path))
    return snapshot


def level_record(snapshot: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    """The compact line of the level log: walls, flip, max pain and regime of one snapshot."""
    overall, main = snapshot["all_expiries"], snapshot["main_expiry"]
    return {
        "symbol": symbol, "as_of": snapshot["as_of"], "spot": snapshot["spot"],
        "call_wall": overall["call_wall"], "put_wall": overall["put_wall"], "gamma_flip": overall["gamma_flip"],
        "regime": overall["regime"], "net_gex_usd_per_1pct": overall["net_gex_usd_per_1pct"],
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
    """Snapshot plus ``age_seconds`` and ``stale``; None when there is none."""
    if not snapshot:
        return None
    now = now or datetime.now(timezone.utc)
    age = now - datetime.fromisoformat(str(snapshot["as_of"]))
    return {**snapshot, "age_seconds": int(age.total_seconds()), "stale": age > STALE_AFTER}


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


def chart_drawings(snapshot: Mapping[str, Any] | None, now: datetime | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Chart drawings (group "gamma") and notes. Stale snapshots draw nothing."""
    current = with_age(snapshot, now)
    if current is None:
        return [], []
    if current["stale"]:
        return [], [f"Gamma: Deribit-Stand ist {current['age_seconds'] // 60} min alt, Level ausgeblendet."]
    as_of = datetime.fromisoformat(str(current["as_of"]))
    start = (as_of - timedelta(days=1)).isoformat()  # visible as a level, not a one-candle stub
    drawings = []
    for item in current["levels"]:
        color, style = LEVEL_STYLE.get(item["key"], ("#ffb020", "dashed"))
        drawings.append({"group": "gamma", "tf": "Opt", "name": item["name"], "label": f"Opt {item['name']}",
                         "price": float(item["price"]), "start": start, "note": item["note"],
                         "color": color, "style": style})
    return drawings, []
