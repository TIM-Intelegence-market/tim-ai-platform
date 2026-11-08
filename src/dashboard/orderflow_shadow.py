"""Orderflow-Schatten: what the live orderflow said about every TIM plan, and when it would have left (paper only).

Paket 2 of "TIM soll die Welle reiten" (Uzi, 08.11.2026). The 15m and 1h plan journals keep trading as they do;
this shadow reads them and the Live-Orderflow-Lage (src/orderflow/live_state.py) and records, per plan:

- ``gate_at_plan`` / ``gate_at_fill``: the wave when the plan appeared and when it filled. BESTÄTIGT when the
  wave runs with the plan and is not exhausted, GEGEN when it runs against the plan, NEUTRAL otherwise.
  Later we can read off whether "only enter with confirmation" would have helped.
- ``of_exit``: once a plan is filled, the shadow leaves when the wave turns against the position (strength >= 2)
  or the own wave shows exhaustion. The shadow's R is compared with the journal's own exit (fixed targets).

Prospective: only plans created at or after ``started_at``. Resumable: every step reads the journals and the
current Lage and saves one JSON file. No look-ahead: a decision uses only the Lage of the moment it is taken.
Judgement after ``TARGET_TRADES`` closed plans, by Uzi. Nothing here trades or changes a journal.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "tim_orderflow_shadow/1"
DEFAULT_PATH = Path("data/journal/tim_orderflow_shadow.json")
TARGET_TRADES = 30
COST_R_PER_SIDE_BPS = 5  # Kraken taker, as measured 04.11.2026 (exit_variants.KRAKEN)
AGAINST_STRENGTH = 2
BESTAETIGT, GEGEN, NEUTRAL = "BESTÄTIGT", "GEGEN", "NEUTRAL"
WITH = {"LONG": "auf", "SHORT": "ab"}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _time(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def lage_view(lage: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The part of the Lage worth keeping on a plan (small, no thresholds, no level table)."""
    if not lage or lage.get("stale") or lage.get("price") is None:
        return None
    wave = dict(lage.get("wave") or {})
    near = [{"name": l["name"], "distance_pct": l["distance_pct"], "absorption": l.get("absorption"),
             "imbalance": l.get("imbalance")} for l in (lage.get("levels") or [])[:3]]
    perp = lage.get("perp") or {}
    return {"as_of": lage.get("as_of"), "price": lage.get("price"), "direction": wave.get("direction"),
            "strength": wave.get("strength"), "phase": wave.get("phase"), "exhaustion": bool(wave.get("exhaustion")),
            "tempo": lage.get("tempo"), "delta_5m": (lage.get("windows") or {}).get("5m", {}).get("delta"),
            "perp_delta_5m": perp.get("delta_5m"), "levels": near}


def gate(direction: str, view: Mapping[str, Any] | None) -> str:
    """BESTÄTIGT: wave with the plan and not exhausted. GEGEN: wave against the plan. NEUTRAL: no wave or no data."""
    if not view or view.get("direction") in (None, "keine"):
        return NEUTRAL
    if view["direction"] == WITH.get(direction):
        return NEUTRAL if view.get("exhaustion") else BESTAETIGT
    return GEGEN


def should_exit(direction: str, view: Mapping[str, Any] | None) -> str | None:
    """Reason to leave now, or None: wave against the position (strength >= AGAINST_STRENGTH) or own wave exhausted."""
    if not view or view.get("direction") in (None, "keine"):
        return None
    if view["direction"] != WITH.get(direction):
        return "Gegenwelle" if (view.get("strength") or 0) >= AGAINST_STRENGTH else None
    return "Exhaustion" if view.get("exhaustion") else None


def r_of(entry: Mapping[str, Any], exit_price: float) -> tuple[float, float] | None:
    """Gross and net R of leaving at ``exit_price`` (Kraken taker both sides)."""
    try:
        fill = float(entry.get("fill_price") or entry["entry"])
        stop = float(entry["stop"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(fill - stop)
    if risk <= 0:
        return None
    sign = 1 if entry.get("direction") == "LONG" else -1
    gross = sign * (exit_price - fill) / risk
    costs = (fill + exit_price) * COST_R_PER_SIDE_BPS / 10_000 / risk
    return round(gross, 4), round(gross - costs, 4)


def load(path: Path) -> dict[str, Any] | None:
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


def summary(state: Mapping[str, Any]) -> dict[str, Any]:
    plans = list((state.get("plans") or {}).values())
    closed = [p for p in plans if p.get("journal", {}).get("status") == "CLOSED" and p["journal"].get("net_r") is not None]
    by_gate: dict[str, dict[str, Any]] = {}
    for plan in closed:
        verdict = plan.get("gate_at_fill") or plan.get("gate_at_plan") or NEUTRAL
        row = by_gate.setdefault(verdict, {"n": 0, "sum_net_r": 0.0})
        row["n"] += 1
        row["sum_net_r"] = round(row["sum_net_r"] + float(plan["journal"]["net_r"]), 4)
    with_exit = [p for p in closed if p.get("of_exit")]
    return {"plans": len(plans), "closed": len(closed), "target": TARGET_TRADES, "judgeable": len(closed) >= TARGET_TRADES,
            "by_gate": by_gate,
            "of_exit": {"n": len(with_exit),
                        "sum_shadow_net_r": round(sum(float(p["of_exit"]["net_r"]) for p in with_exit), 4),
                        "sum_journal_net_r": round(sum(float(p["journal"]["net_r"]) for p in with_exit), 4)}}


def update(path: Path, journal_paths: Sequence[Path], lage: Mapping[str, Any] | None,
           now: datetime | None = None) -> dict[str, Any]:
    """One step: new plans get the gate, filled plans are watched for the orderflow exit, closed plans get the journal result."""
    from src.dashboard.plan_journal import load_view

    now = now or datetime.now(timezone.utc)
    state = load(Path(path)) or {"schema": SCHEMA, "started_at": _iso(now), "sources": [Path(p).name for p in journal_paths],
                                 "costs": f"{COST_R_PER_SIDE_BPS} bps je Seite", "plans": {}}
    started = _time(state["started_at"])
    view = lage_view(lage)
    plans = state["plans"]
    for journal_path in journal_paths:
        journal = load_view(Path(journal_path))
        if journal.get("blocked"):
            continue
        for entry in journal.get("entries") or []:
            if entry.get("excluded") or not entry.get("created_at") or _time(entry["created_at"]) < started:
                continue
            key = str(entry["id"])
            record = plans.get(key)
            if record is None:
                record = plans[key] = {"id": entry["id"], "journal_file": Path(journal_path).name, "timeframe": entry.get("timeframe"),
                                       "direction": entry.get("direction"), "created_at": entry["created_at"],
                                       "entry": entry.get("entry"), "stop": entry.get("stop"),
                                       "lage_at_plan": view, "gate_at_plan": gate(str(entry.get("direction")), view)}
            record["journal"] = {"status": entry.get("status"), "filled_at": entry.get("filled_at"), "closed_at": entry.get("closed_at"),
                                 "exit_reason": entry.get("exit_reason"), "exit_price": entry.get("exit_price"), "net_r": entry.get("net_r")}
            if entry.get("filled_at") and "gate_at_fill" not in record:
                record["fill_price"] = entry.get("fill_price") or entry.get("entry")
                record["lage_at_fill"] = view
                record["gate_at_fill"] = gate(str(entry.get("direction")), view)
            if entry.get("status") == "FILLED" and not record.get("of_exit") and view:
                reason = should_exit(str(entry.get("direction")), view)
                if reason:
                    r = r_of({**entry, "fill_price": record.get("fill_price")}, float(view["price"]))
                    if r:
                        record["of_exit"] = {"at": view["as_of"], "price": view["price"], "reason": reason,
                                             "gross_r": r[0], "net_r": r[1], "lage": view}
    state["checked_at"] = _iso(now)
    state["summary"] = summary(state)
    _save(state, Path(path))
    return state
