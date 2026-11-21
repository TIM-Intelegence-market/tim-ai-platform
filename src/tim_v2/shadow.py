"""V2.9 Schatten: the live 15m/1h plans of the plan journals, executed on paper by the V2.8 fake adapter.

Milestone V2.9 (docs/tim_v2/milestones.md): live-data observation with a disabled order path, latency and
decision-quality measurement, zero-order evidence. This module only reads the plan journals and the runtime's
closed candles and writes one JSON file. It never changes a journal and has no order path: execution goes through
``src.tim_v2.paper`` only, whose isolation proof is checked on every step and stored with the state.

Per plan (own adapter each, so plans never net against each other):

* order at the plan's ``created_at``: LIMIT at ``entry`` if the entry lies on the cheap side of the price at that
  moment, otherwise STOP at ``entry``; stop loss = plan stop; size = 0.25 % of 1,000 USD paper equity per R;
* the journal decides the end: a plan the journal closes is flattened on paper at the next bar after
  ``closed_at``; a plan that ends without fill (EXPIRED, INVALIDATED, REPLACED) is cancelled at ``closed_at``;
* partial targets of the journal are not copied; the paper stop loss stays as the safety net.

Measured: fill agreement with the journal, entry price difference in bp, paper net R against journal net R,
latency from plan creation to the shadow seeing it and to the paper fill, zero orders to any exchange.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.tim_v2.paper import AdapterConfig, Bar, FakeExecutionAdapter, KillSwitch, OrderRequest, OrderType, Side
from src.tim_v2.paper.isolation import scan

SCHEMA = "tim-v2-shadow/1"
DEFAULT_PATH = Path("data/journal/tim_v2_shadow.json")
SYMBOL = "BTCUSDT"
BAR_TIMEFRAMES = ("5m", "15m")  # finest closed bars the runtime offers; fixed at the first step
BAR_MINUTES = {"5m": 5, "15m": 15}
PAPER_EQUITY = Decimal("1000")
RISK_FRACTION = Decimal("0.0025")
MAX_BARS = 20000  # ~69 days of 5m bars; older bars are only dropped once no open plan needs them
NO_FILL_END = {"EXPIRED", "INVALIDATED", "REPLACED"}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dec(value: Any) -> Decimal | None:
    try:
        out = Decimal(str(value))
    except Exception:  # noqa: BLE001 - malformed journal values are skipped, not fatal
        return None
    return out if out.is_finite() and out > 0 else None


def load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(state: Mapping[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- bars


def _closed_bars(series: Mapping[str, Sequence[Mapping[str, Any]]], timeframe: str, now: datetime) -> list[dict[str, Any]]:
    out = []
    for c in series.get(timeframe) or []:
        try:
            close_time = _time(c["close_time"])
            if close_time > now:
                continue
            row = {"t": _iso(_time(c["open_time"])), "o": str(c["open"]), "h": str(c["high"]), "l": str(c["low"]),
                   "c": str(c["close"])}
            Bar(SYMBOL, _time(row["t"]), Decimal(row["o"]), Decimal(row["h"]), Decimal(row["l"]), Decimal(row["c"]))
        except (KeyError, ValueError, ArithmeticError):
            continue
        out.append(row)
    return out


def _merge_bars(stored: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append only bars newer than the last stored one; a stored bar is never rewritten."""
    last = _time(stored[-1]["t"]) if stored else None
    fresh = sorted((b for b in new if last is None or _time(b["t"]) > last), key=lambda b: b["t"])
    dedup: list[dict[str, Any]] = []
    for b in fresh:
        if not dedup or dedup[-1]["t"] != b["t"]:
            dedup.append(b)
    return stored + dedup


def _bar(row: Mapping[str, Any]) -> Bar:
    return Bar(SYMBOL, _time(row["t"]), Decimal(row["o"]), Decimal(row["h"]), Decimal(row["l"]), Decimal(row["c"]))


# --------------------------------------------------------------------------- one plan on paper


def simulate_plan(plan: Mapping[str, Any], bars: Sequence[Mapping[str, Any]], kill_file: Path | None = None) -> dict[str, Any]:
    """Replay one plan from its creation through the stored bars. Deterministic; nothing outside is touched."""
    created = _time(plan["created_at"])
    entry, stop = _dec(plan.get("entry")), _dec(plan.get("stop"))
    direction = plan.get("direction")
    if entry is None or stop is None or direction not in {"LONG", "SHORT"} or entry == stop:
        return {"state": "SKIPPED", "reason": "plan without valid entry/stop/direction"}
    if (direction == "LONG") != (stop < entry):
        return {"state": "SKIPPED", "reason": "stop on the wrong side"}
    before = [b for b in bars if _time(b["t"]) < created]
    after = [b for b in bars if _time(b["t"]) >= created]
    if not before:
        return {"state": "WAITING", "reason": "no bar before plan creation"}
    adapter = FakeExecutionAdapter(AdapterConfig(initial_equity=PAPER_EQUITY, symbols=(SYMBOL,)),
                                   KillSwitch(kill_file=kill_file))
    seed = _bar(before[-1])
    adapter.marks[SYMBOL] = seed.close
    adapter.last_bar_at[SYMBOL] = seed.opened_at
    risk = PAPER_EQUITY * RISK_FRACTION
    qty = (risk / abs(entry - stop)).quantize(Decimal("0.000001"))
    long = direction == "LONG"
    cheap_side = entry < seed.close if long else entry > seed.close
    request = OrderRequest(f"plan_{plan.get('id')}", SYMBOL, Side.BUY if long else Side.SELL, qty,
                           OrderType.LIMIT if cheap_side else OrderType.STOP, entry, stop_loss=stop)
    order = adapter.submit(request, created)
    journal_end = _time(plan["journal"]["closed_at"]) if (plan.get("journal") or {}).get("closed_at") else None
    journal_status = (plan.get("journal") or {}).get("status")
    end_handled = False
    for row in after:
        bar = _bar(row)
        if journal_end is not None and not end_handled and bar.opened_at > journal_end:
            if journal_status in NO_FILL_END and order.status.value == "NEW":
                adapter.cancel(request.client_id, journal_end, f"journal {journal_status}")
            elif journal_status == "CLOSED":
                adapter.cancel(request.client_id, journal_end, "journal closed")
                adapter.flatten(SYMBOL, journal_end)
            end_handled = True
        adapter.on_bar(bar)
        pos = adapter.positions[SYMBOL]
        if end_handled and not pos.quantity and not adapter.open_orders():
            break
    entry_fill = next((f for f in adapter.fills if f.client_id == request.client_id), None)
    pos = adapter.positions[SYMBOL]
    if order.status.value == "REJECTED":
        state = "REJECTED"
    elif entry_fill is None:
        state = "CANCELLED" if order.status.value == "CANCELLED" else "PENDING"
    else:
        state = "OPEN" if pos.quantity else "CLOSED"
    mark = adapter.marks.get(SYMBOL)
    paper_r = ((adapter.equity() - PAPER_EQUITY) / risk) if entry_fill is not None else None
    return {
        "state": state,
        "order_type": request.order_type.value,
        "order_status": order.status.value,
        "order_reason": order.reason,
        "quantity": str(qty),
        "entry_fill_at": _iso(entry_fill.filled_at) if entry_fill else None,
        "entry_fill_price": str(entry_fill.price) if entry_fill else None,
        "entry_diff_bp": float((entry_fill.price - entry) / entry * 10000 * (1 if long else -1)) if entry_fill else None,
        "fill_latency_s": (entry_fill.filled_at - created).total_seconds() if entry_fill else None,
        "exit_kinds": [f.kind for f in adapter.fills if f.client_id != request.client_id],
        "paper_net_r": round(float(paper_r), 4) if paper_r is not None else None,
        "mark": str(mark) if mark is not None else None,
        "kill": [e.to_dict() for e in adapter.kill.events],
        "orders_sent_to_exchange": 0,
    }


# --------------------------------------------------------------------------- runtime step


def summary(state: Mapping[str, Any]) -> dict[str, Any]:
    plans = list((state.get("plans") or {}).values())
    sim = [p for p in plans if (p.get("paper") or {}).get("state") not in (None, "SKIPPED", "WAITING")]
    journal_filled = [p for p in sim if (p.get("journal") or {}).get("filled_at")]
    both = [p for p in journal_filled if p["paper"].get("entry_fill_at")]
    paper_only = [p for p in sim if p["paper"].get("entry_fill_at") and not (p.get("journal") or {}).get("filled_at")
                  and (p.get("journal") or {}).get("status") in NO_FILL_END | {"CLOSED"}]
    closed = [p for p in sim if p["paper"].get("state") == "CLOSED" and (p.get("journal") or {}).get("net_r") is not None]
    latencies = sorted(p["seen_latency_s"] for p in plans if p.get("seen_latency_s") is not None)
    diffs = sorted(p["paper"]["entry_diff_bp"] for p in both if p["paper"].get("entry_diff_bp") is not None)

    def median(xs: list[float]) -> float | None:
        return round(xs[len(xs) // 2], 3) if xs else None

    return {
        "plans_seen": len(plans),
        "plans_simulated": len(sim),
        "journal_filled": len(journal_filled),
        "fill_agreement": round(len(both) / len(journal_filled), 4) if journal_filled else None,
        "paper_filled_journal_not": len(paper_only),
        "entry_diff_bp_median": median(diffs),
        "seen_latency_s_median": median(latencies),
        "closed_compared": len(closed),
        "sum_paper_net_r": round(sum(p["paper"]["paper_net_r"] for p in closed), 4) if closed else None,
        "sum_journal_net_r": round(sum(float(p["journal"]["net_r"]) for p in closed), 4) if closed else None,
        "orders_sent_to_exchange": 0,
    }


def update(path: Path, journal_paths: Sequence[Path], series: Mapping[str, Sequence[Mapping[str, Any]]],
           now: datetime | None = None, kill_file: Path | None = None) -> dict[str, Any]:
    """One step: store new closed bars, pick up new plans, replay every unfinished plan on paper, save."""
    from src.dashboard.plan_journal import load_view

    now = now or datetime.now(timezone.utc)
    isolation = scan()
    if kill_file is None and os.environ.get("TIM_PAPER_KILL_FILE"):
        kill_file = Path(os.environ["TIM_PAPER_KILL_FILE"])
    state = load(Path(path)) or {"schema": SCHEMA, "started_at": _iso(now), "bar_timeframe": None, "bars": [],
                                 "plans": {}, "sources": [Path(p).name for p in journal_paths]}
    if state.get("bar_timeframe") is None:
        state["bar_timeframe"] = next((tf for tf in BAR_TIMEFRAMES if series.get(tf)), None)
    timeframe = state["bar_timeframe"]
    if timeframe is not None:
        state["bars"] = _merge_bars(state.get("bars") or [], _closed_bars(series, timeframe, now))
    started = _time(state["started_at"])
    plans = state["plans"]
    if not isolation.ok:
        state.update(checked_at=_iso(now), isolation=isolation.to_dict(), halted="paper isolation failed")
        _save(state, Path(path))
        return state
    for journal_path in journal_paths:
        journal = load_view(Path(journal_path))
        if journal.get("blocked"):
            continue
        for entry in journal.get("entries") or []:
            if entry.get("excluded") or not entry.get("created_at") or _time(entry["created_at"]) < started:
                continue
            key = f"{Path(journal_path).name}:{entry['id']}"
            record = plans.get(key)
            if record is None:
                created = _time(entry["created_at"])
                record = plans[key] = {"id": entry["id"], "journal_file": Path(journal_path).name,
                                       "timeframe": entry.get("timeframe"), "direction": entry.get("direction"),
                                       "created_at": entry["created_at"], "entry": entry.get("entry"),
                                       "stop": entry.get("stop"), "seen_at": _iso(now),
                                       "seen_latency_s": max(0.0, (now - created).total_seconds())}
            record["journal"] = {"status": entry.get("status"), "filled_at": entry.get("filled_at"),
                                 "closed_at": entry.get("closed_at"), "exit_reason": entry.get("exit_reason"),
                                 "net_r": entry.get("net_r")}
    bars = state["bars"]
    for record in plans.values():
        paper = record.get("paper") or {}
        if paper.get("state") in {"CLOSED", "CANCELLED", "REJECTED", "SKIPPED"}:
            continue
        record["paper"] = simulate_plan(record, bars, kill_file)
    _trim_bars(state)
    state.update(checked_at=_iso(now), isolation=isolation.to_dict(), live_execution=False, summary=summary(state))
    state.pop("halted", None)
    _save(state, Path(path))
    return state


def _trim_bars(state: dict[str, Any]) -> None:
    bars = state["bars"]
    if len(bars) <= MAX_BARS:
        return
    unfinished = [_time(p["created_at"]) for p in state["plans"].values()
                  if (p.get("paper") or {}).get("state") not in {"CLOSED", "CANCELLED", "REJECTED", "SKIPPED"}]
    keep_from = min(unfinished) - timedelta(minutes=BAR_MINUTES.get(state.get("bar_timeframe") or "15m", 15)) if unfinished else None
    cut = len(bars) - MAX_BARS
    if keep_from is not None:
        cut = min(cut, next((i for i, b in enumerate(bars) if _time(b["t"]) >= keep_from), len(bars)))
    state["bars"] = bars[max(0, cut):]


def render_de(state: Mapping[str, Any] | None) -> str:
    """Short German status line for the Control Center."""
    if not state:
        return "V2.9 Schatten: noch kein Lauf."
    s = state.get("summary") or {}
    if state.get("halted"):
        return f"V2.9 Schatten angehalten: {state['halted']}."
    agree = s.get("fill_agreement")
    return (f"V2.9 Schatten seit {str(state.get('started_at', ''))[:10]}: {s.get('plans_simulated', 0)} Pläne auf Papier, "
            f"Einstieg wie im Journal {('%.0f %%' % (agree * 100)) if agree is not None else '–'}, "
            f"{s.get('closed_compared', 0)} abgeschlossen verglichen, 0 Orders an eine Börse.")
