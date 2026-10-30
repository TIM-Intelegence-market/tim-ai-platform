"""Options gamma for the Control Center: Deribit's public options book, read-only.

The runtime (main.py) calls ``refresh`` every few minutes. It reads two public
Deribit endpoints (no key, no account): the options book summary and the index
price, computes the snapshot with ``src.options_gamma.snapshot`` and stores it
in ``DashboardState.gamma``. Consumers:

- ``/api/gamma`` (full snapshot plus age and freshness),
- ``/api/prep`` (``gamma`` block: regime, levels, analysis input),
- the interactive chart (group "gamma": flip, walls, max pain, expected move).

Display and analysis context only: nothing here trades, writes a plan or
changes a score. A failed read keeps the last snapshot, which then turns stale.
"""

from __future__ import annotations

import json
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
    return snapshot


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
