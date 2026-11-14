"""Muster-Schatten: QM, OB and SFP tracked as a paper shadow (Uzi 14.11.2026, "TIM sollte die Pattern auch tracken").

Detectors and frozen rules: ``src/analysis/patterns.py`` (``muster-schatten/1.0``). This module only keeps the
journal and the display:

- ``setups``: every pattern found on the HTF (also INVALID order blocks), with what the HTF did afterwards
  (``Ziel``, ``gebrochen``, ``offen``). Pure pattern tracking, independent of any entry.
- ``plans``: a setup with a clean exec order block near its zone becomes an ARMED plan. Entry only at the close of
  the retest candle, with at least one orderflow confluence (otherwise SKIPPED), stop beyond the exec zone,
  R:R >= 1.5 and costs <= 0.25 R. Result in R after costs, weighted with the model's risk (0.7 / 1 / x2 from 4h).
- Day rules from the model: at most 2 shots per UTC day, at most 2.0 weighted R lost per day (assumes 1R = 1 %),
  after a loss or a missed plan only setups formed afterwards.

Prospective: only setups formed at or after ``started_at``. Reads only, writes only its own file. No order path,
no real money. Judgement after ``TARGET_PLANS`` closed plans and ``MIN_DAYS`` days, by Uzi.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.analysis import patterns as P
from src.dashboard.chart_model import TIMEFRAME_SECONDS

SCHEMA = "tim_pattern_shadow/1"
DEFAULT_PATH = Path("data/journal/tim_pattern_shadow.json")
TARGET_PLANS = 30
MIN_DAYS = 28
MAX_SHOTS_PER_DAY = 2
MAX_DAY_LOSS_R = 2.0
KEEP_SETUPS, KEEP_PLANS = 400, 400
MISSING = ("TPO poor high/low", "Single Prints", "Orderbook-Spot-Skew ±10 %", "5m-Ausführung (15m statt 5m)")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


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


def _setup_record(setup: Mapping[str, Any], profile: str) -> dict[str, Any]:
    keep = ("id", "kind", "direction", "tf", "zone_low", "zone_high", "invalid_beyond", "target", "valid", "reason", "fate", "rvol_origin")
    return {**{k: setup.get(k) for k in keep}, "profile": profile, "created": _iso(setup["created"])}


def _plan_from(setup: Mapping[str, Any], block: Mapping[str, Any], profile: str, exec_tf: str, now: datetime) -> dict[str, Any]:
    return {"id": f"{setup['id']}>{block['id']}", "profile": profile, "htf": setup["tf"], "exec": exec_tf, "kind": setup["kind"],
            "direction": setup["direction"], "setup_id": setup["id"], "setup_created": _iso(setup["created"]),
            "htf_invalid_beyond": setup["invalid_beyond"], "target": setup["target"],
            "zone_low": block["zone_low"], "zone_high": block["zone_high"], "exec_created": _iso(block["created"]),
            "rvol_origin": block.get("rvol_origin"), "armed_at": _iso(now), "status": "ARMED"}


def _ctx_for(plans: Mapping[str, Mapping[str, Any]], me: str, at: datetime) -> dict[str, Any]:
    """Day counters and the last loss/miss before ``at``, from the other plans."""
    day = at.astimezone(timezone.utc).date()
    shots, lost, last_event = 0, 0.0, None
    for pid, plan in plans.items():
        if pid == me:
            continue
        entered = datetime.fromisoformat(plan["entry_time"]) if plan.get("entry_time") else None
        if entered and entered <= at and entered.astimezone(timezone.utc).date() == day:
            shots += 1
            closed = datetime.fromisoformat(plan["closed_at"]) if plan.get("closed_at") else None
            if closed and closed <= at and (plan.get("weighted_r") or 0) < 0:
                lost += -plan["weighted_r"]
        ended = plan.get("closed_at") if (plan.get("weighted_r") or 0) < 0 or plan.get("reason") == "abgelaufen" else None
        if ended and datetime.fromisoformat(ended) <= at and (last_event is None or datetime.fromisoformat(ended) > last_event):
            last_event = datetime.fromisoformat(ended)
    return {"shots": shots, "lost": lost, "last_event": last_event}


def _skip(plan: dict[str, Any], reason: str, at: datetime) -> None:
    plan.update(status="SKIPPED", reason=reason, closed_at=_iso(at))


def advance(plan: dict[str, Any], ex: Sequence[Mapping[str, Any]], plans: Mapping[str, Mapping[str, Any]],
            trades: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One step of a plan over the closed exec candles, pure apart from the plan dict. Causal: candle j decides at its close."""
    long = plan["direction"] == P.LONG
    seconds = TIMEFRAME_SECONDS[plan["exec"]]
    for j, c in enumerate(ex):
        end = c["close_time"]
        if plan["status"] == "ARMED":
            armed = datetime.fromisoformat(plan["armed_at"])
            if end <= armed:
                continue
            invalid = plan["htf_invalid_beyond"]
            if (c["close"] < max(plan["zone_low"], invalid)) if long else (c["close"] > min(plan["zone_high"], invalid)):
                _skip(plan, "gebrochen", end)
                continue
            if (end - armed).total_seconds() / seconds > P.WAIT_BARS:
                _skip(plan, "abgelaufen", end)
                continue
            touch = (c["low"] <= plan["zone_high"] and c["close"] >= plan["zone_low"]) if long else (c["high"] >= plan["zone_low"] and c["close"] <= plan["zone_high"])
            atr = P.atr_at(ex, j)
            if not touch or atr is None:
                continue
            conf = P.confluences(plan["direction"], ex, plan.get("rvol_origin"), j, trades)
            entry = c["close"]
            stop = plan["zone_low"] - P.ZONE_PAD_ATR * atr if long else plan["zone_high"] + P.ZONE_PAD_ATR * atr
            risk = abs(entry - stop)
            reward = (plan["target"] - entry) if long else (entry - plan["target"])
            ctx = _ctx_for(plans, plan["id"], end)
            plan["confluence"] = conf
            if conf["count"] < 1:
                _skip(plan, "keine Konfluenz", end)
            elif risk <= 0 or reward / risk < P.MIN_RR:
                _skip(plan, "R:R unter 1,5", end)
            elif P.COST_PCT * entry / risk > P.MAX_COST_R:
                _skip(plan, "Kosten über 0,25 R", end)
            elif ctx["shots"] >= MAX_SHOTS_PER_DAY or ctx["lost"] >= MAX_DAY_LOSS_R:
                _skip(plan, "Tageslimit", end)
            elif ctx["last_event"] and datetime.fromisoformat(plan["setup_created"]) <= ctx["last_event"]:
                _skip(plan, "Sperre nach Verlust/verpasst", end)
            else:
                plan.update(status="OPEN", entry=entry, stop=stop, risk=risk, entry_time=_iso(end), cost_r=P.COST_PCT * entry / risk,
                            risk_mult=P.risk_multiplier(conf["count"], plan["htf"]))
            continue
        if plan["status"] == "OPEN":
            if end <= datetime.fromisoformat(plan["entry_time"]):
                continue
            exit_price, how = None, None
            if (c["low"] <= plan["stop"]) if long else (c["high"] >= plan["stop"]):
                exit_price, how = plan["stop"], "STOP"  # stop first when both are in one candle
            elif (c["high"] >= plan["target"]) if long else (c["low"] <= plan["target"]):
                exit_price, how = plan["target"], "ZIEL"
            elif (end - datetime.fromisoformat(plan["entry_time"])).total_seconds() / seconds >= P.HOLD_BARS:
                exit_price, how = c["close"], "ZEIT"
            if exit_price is not None:
                gross = ((exit_price - plan["entry"]) if long else (plan["entry"] - exit_price)) / plan["risk"]
                net = gross - plan["cost_r"]
                plan.update(status="CLOSED", exit=exit_price, how=how, gross_r=round(gross, 3), net_r=round(net, 3),
                            weighted_r=round(net * plan["risk_mult"], 3), closed_at=_iso(end))
    return plan


def update(path: Path, series: Mapping[str, Sequence[Mapping[str, Any]]], lage: Mapping[str, Any] | None = None,
           now: datetime | None = None, trades: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Runtime hook: find setups, arm plans, advance them and save. ``lage`` is unused (kept for the hook signature)."""
    now = now or datetime.now(timezone.utc)
    state = load(path) or {}
    state = {"schema": SCHEMA, "ruleset": P.RULESET, "started_at": state.get("started_at") or _iso(now), "setups": dict(state.get("setups") or {}),
             "plans": dict(state.get("plans") or {}), "updated_at": _iso(now)}
    started = datetime.fromisoformat(state["started_at"])
    prepped: dict[str, list[dict[str, Any]]] = {}
    for name, htf_tf, exec_tf in P.PROFILES:
        htf, ex = prepped.setdefault(htf_tf, P.prep(series.get(htf_tf) or [])), prepped.setdefault(exec_tf, P.prep(series.get(exec_tf) or []))
        if len(htf) < 40 or len(ex) < 60:
            continue
        htf_atr = P.atr_at(htf, len(htf) - 1)
        for setup in P.htf_setups(htf, htf_tf):
            if setup["created"] < started:
                continue
            sid = f"{name}:{setup['id']}"
            state["setups"][sid] = _setup_record({**setup, "id": sid}, name)
            if not (setup["alive"] and setup["valid"] and htf_atr):
                continue
            for block in P.exec_blocks(setup, ex, exec_tf, htf_atr):
                if block["created"] < started or block["fate"] != "offen":
                    continue
                plan = _plan_from({**setup, "id": sid}, {**block, "id": block["created"].isoformat()}, name, exec_tf, now)
                state["plans"].setdefault(plan["id"], plan)
    for plan in sorted(state["plans"].values(), key=lambda p: p["armed_at"]):
        if plan["status"] in ("ARMED", "OPEN"):
            advance(plan, prepped.setdefault(plan["exec"], P.prep(series.get(plan["exec"]) or [])), state["plans"], trades)
    state["setups"] = dict(sorted(state["setups"].items(), key=lambda kv: kv[1]["created"])[-KEEP_SETUPS:])
    state["plans"] = dict(sorted(state["plans"].items(), key=lambda kv: kv[1]["armed_at"])[-KEEP_PLANS:])
    _save(state, Path(path))
    return state


def summary(state: Mapping[str, Any]) -> dict[str, Any]:
    setups, plans = list((state.get("setups") or {}).values()), list((state.get("plans") or {}).values())
    by_kind: dict[str, dict[str, int]] = {}
    for s in setups:
        row = by_kind.setdefault(s["kind"], {"n": 0, "valid": 0, "Ziel": 0, "gebrochen": 0, "offen": 0})
        row["n"] += 1
        row["valid"] += 1 if s["valid"] else 0
        row[s["fate"]] += 1
    closed = [p for p in plans if p["status"] == "CLOSED"]
    skipped: dict[str, int] = {}
    for p in plans:
        if p["status"] == "SKIPPED":
            skipped[p["reason"]] = skipped.get(p["reason"], 0) + 1
    wins = sum(1 for p in closed if p["net_r"] > 0)
    return {"setups": by_kind, "armed": sum(1 for p in plans if p["status"] == "ARMED"), "open": sum(1 for p in plans if p["status"] == "OPEN"),
            "closed": len(closed), "wins": wins, "net_r": round(sum(p["net_r"] for p in closed), 2),
            "weighted_r": round(sum(p["weighted_r"] for p in closed), 2), "skipped": skipped}


def current(series: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Setups alive right now per profile (display only, no state)."""
    out = []
    for name, htf_tf, _exec_tf in P.PROFILES:
        htf = P.prep(series.get(htf_tf) or [])
        if len(htf) < 40:
            continue
        for setup in P.htf_setups(htf, htf_tf):
            if setup["alive"]:
                out.append({**setup, "profile": name})
    return sorted(out, key=lambda s: s["created"], reverse=True)


def _p(value: float | None) -> str:
    return "–" if value is None else f"{value:,.0f}".replace(",", ".")


def render_de(live: Sequence[Mapping[str, Any]] | None, state: Mapping[str, Any] | None = None) -> str:
    """Section "Muster (QM, OB, SFP)" for the chart page."""
    from src.dashboard.helpers import _safe

    out = [f"<section class='cc-section tc-patterns' data-patterns='{P.RULESET}'><p class='cc-section__eyebrow'>Muster: QM, OB, SFP</p>"]
    if live:
        out.append("<p><b>Gerade lebendig:</b></p><ul>")
        for s in list(live)[:8]:
            side = "Long" if s["direction"] == P.LONG else "Short"
            note = "" if s["valid"] else f" (ungültig: {s['reason']})"
            out.append(f"<li>{_safe(s['tf'])} {_safe(s['kind'])} {side} {_safe(_p(s['zone_low']))}–{_safe(_p(s['zone_high']))}, "
                       f"Ziel {_safe(_p(s['target']))}, ungültig jenseits {_safe(_p(s['invalid_beyond']))}{_safe(note)}</li>")
        out.append("</ul>")
    else:
        out.append("<p class='empty'>Gerade kein lebendiges Muster.</p>")
    if state:
        s = summary(state)
        kinds = ", ".join(f"{k}: {v['n']} gefunden ({v['valid']} gültig, {v['Ziel']} Ziel, {v['gebrochen']} gebrochen)" for k, v in sorted(s["setups"].items())) or "noch nichts"
        skipped = ", ".join(f"{n}× {_safe(r)}" for r, n in sorted(s["skipped"].items())) or "–"
        out.append(f"<p class='cc-note'>Beobachtet seit {_safe(str(state.get('started_at', ''))[:10])}: {_safe(kinds)}. Pläne: {s['armed']} wartend, "
                   f"{s['open']} offen, {s['closed']} geschlossen ({s['wins']} im Plus, {s['net_r']:+.2f} R netto, {s['weighted_r']:+.2f} R gewichtet). "
                   f"Verworfen: {skipped}.</p>")
    out.append(f"<p class='cc-note'>Nur Papier und Anzeige ({P.RULESET}): keine Order. Einstieg nur mit mindestens einer Orderflow-Konfluenz "
               f"(RVOL am Ursprung/Retest, gefangene Trader per Delta), Risiko 0,7R / 1R, ab 4h doppelt, höchstens {MAX_SHOTS_PER_DAY} Schüsse "
               f"und {MAX_DAY_LOSS_R:.0f} R Verlust am Tag. Vergleich frühestens nach {TARGET_PLANS} geschlossenen Plänen und {MIN_DAYS} Tagen, "
               f"Übernahme nur auf Uzis Wort. Level-Reaktionen waren in S22 bis S30 nach Kosten ohne belegten Vorteil. "
               f"Nicht enthalten: {_safe(', '.join(MISSING))}.</p></section>")
    return "".join(out)
