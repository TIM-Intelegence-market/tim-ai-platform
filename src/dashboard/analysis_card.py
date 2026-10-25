"""Analysis card ("Steckbrief") for one chart timeframe (read-only, no orders).

Collects in one place what a full analysis needs, from the chart model only:

- symbol, timeframe, data age and data quality,
- market structure (last BOS/MSS on this timeframe, pipeline market/auction state),
- trend (1D/4h bias of the preparation map, structure of this timeframe, location),
- liquidity (nearest reference levels above and below price),
- order-flow observations; TIM has no delta or footprint data, so these are
  candle approximations (value area, POC, poor highs/lows, relative volume),
- each plan (level/1 and the pipeline's previews) with entry, stop,
  invalidation, targets, gross and net R after the journal's cost model,
  research evidence and the journal gate's decision with its reasons in words.

Costs follow the plan journal (research protocol 1.1): fee and slippage per side
on the executed price, stop slippage on stop exits. The decision uses the same
gate as the journal (``plan_journal.journal_gate``), so the card says NO_TRADE
exactly when the journal would. ``journal_check`` compares the card's level/1
plans with the level journal. Paper only: nothing here is a trade signal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "analysis_card/1"
LIQUIDITY_PER_SIDE = 3
PRICE_TOLERANCE = 0.01  # chart and journal prices are rounded to cents
REQUIRED = ("symbol", "timeframe", "structure", "trend", "liquidity", "orderflow", "plans", "data", "decision")
REASON_TEXT = {
    "evidence_not_evaluated": "Forschung: Evidenz nicht geprüft",
    "evidence_insufficient_evidence": "Forschung: kein belastbarer Nachweis im Hypothesen-Register (INSUFFICIENT_EVIDENCE)",
    "evidence_negative_evidence": "Forschung: das Register zeigt einen negativen Befund (NEGATIVE_EVIDENCE)",
    "evidence_candidate_frozen": "Forschung: Kandidat eingefroren, Holdout steht aus (CANDIDATE_FROZEN)",
    "execution_research_only": "Ausführung: nur Forschung, keine Papier-Freigabe (PAPER_APPROVED setzt bisher kein Codepfad)",
    "scenario_not_confirmed": "Szenario nicht bestätigt",
    "instrument_unknown": "Instrument im Journal unbekannt",
    "short_not_executable_on_spot": "Short auf Binance Spot nicht ausführbar (kein Margin-Modell)",
}
JOURNAL_STATES = {
    "MATCH": "Chart und Journal stimmen überein",
    "JOURNAL_BEHIND": "Journal noch nicht beim letzten 30m-Schluss",
    "RESTING": "Journal hält einen älteren Plan dieser Richtung (ein Plan je Richtung)",
    "MISMATCH": "Chart und Journal weichen ab",
    "MISSING": "Plan nicht im Journal",
    "NO_JOURNAL": "Level-Journal nicht lesbar",
}


def _de(value: float, digits: int = 2) -> str:
    """German number format: 80.302,90."""
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def reason_text(code: str) -> str:
    """A gate reason code in words."""
    if code in REASON_TEXT:
        return REASON_TEXT[code]
    if code.startswith("pipeline_"):
        return f"Pipeline-Entscheidung {code.removeprefix('pipeline_').upper()} (kein TRADE_PLAN)"
    if code.startswith("data_quality_"):
        return f"Datenqualität {code.removeprefix('data_quality_').upper()}, nicht PASS"
    if code.startswith("evidence_"):
        return f"Forschung: {code.removeprefix('evidence_').upper()}"
    if code.startswith("execution_"):
        return f"Ausführung: {code.removeprefix('execution_').upper()}"
    return code


def economics(direction: str, entry: float, stop: float, targets: Sequence[float]) -> dict[str, Any] | None:
    """Gross and net R of a plan after the journal's cost model.

    tp1: whole size out at target 1. plan: thirds at targets 1-3 (the journal's
    exit model). stop: whole size out at the stop. Costs are in R; round_trip_pct
    is the cost of entry and exit at target 1 as a share of the entry price."""
    from src.dashboard.plan_journal import COST_MODEL_VERSION, THIRD, costs_r

    risk = abs(entry - stop)
    targets = [float(t) for t in targets if t is not None][:3]
    if risk <= 0 or not targets:
        return None
    sign = 1.0 if direction == "LONG" else -1.0
    plan = {"entry": entry, "stop": stop, "targets": targets, "direction": direction}

    def r(price: float) -> float:
        return sign * (price - entry) / risk

    fee1, slip1 = costs_r({**plan, "tp_hits": []}, targets[0], "TARGET")
    gross_tp1 = r(targets[0])
    full = (targets + [targets[-1]] * 3)[:3]
    fee3, slip3 = costs_r({**plan, "targets": full, "tp_hits": [1, 2, 3]}, full[2], "TARGET")
    gross_plan = sum(THIRD * r(t) for t in full)
    fee_stop, slip_stop = costs_r({**plan, "tp_hits": []}, stop, "STOP")
    net_tp1 = gross_tp1 - fee1 - slip1
    net_stop = -1.0 - fee_stop - slip_stop
    breakeven = -net_stop / (net_tp1 - net_stop) if net_tp1 > 0 else None
    return {
        "risk_pct": round(risk / entry * 100, 3),
        "gross_r_tp1": round(gross_tp1, 2), "costs_r_tp1": round(fee1 + slip1, 3), "net_r_tp1": round(net_tp1, 2),
        "gross_r_plan": round(gross_plan, 2), "costs_r_plan": round(fee3 + slip3, 3), "net_r_plan": round(gross_plan - fee3 - slip3, 2),
        "net_r_stop": round(net_stop, 2),
        "round_trip_pct": round((fee1 + slip1) * risk / entry * 100, 3),
        "breakeven_hit_rate": round(breakeven, 3) if breakeven is not None else None,
        "cost_model": COST_MODEL_VERSION,
    }


def _structure(model: Mapping[str, Any]) -> dict[str, Any]:
    analysis = model.get("analysis") or {}
    events = model.get("bos") or []
    last = events[-1] if events else None
    tf_trend = {"UP": "aufwärts", "DOWN": "abwärts"}.get((last or {}).get("direction"), "unklar")
    text = (f"Letzter Strukturbruch {last['kind']} {'↑' if last['direction'] == 'UP' else '↓'} bei {_de(last['level'])} ({last['break_time'][:16].replace('T', ' ')})"
            if last else "Kein Strukturbruch im Chartfenster")
    return {"last_event": dict(last) if last else None, "events": len(events), "tf_trend": tf_trend,
            "market_state": analysis.get("market_state"), "auction_state": analysis.get("auction_state"), "text": text}


def _trend(model: Mapping[str, Any], structure: Mapping[str, Any]) -> dict[str, Any]:
    bias = model.get("bias") or {}
    location = model.get("location") or {}
    return {"htf_bias": bias.get("bias"), "htf_text": bias.get("text"), "tf_trend": structure["tf_trend"],
            "location": location.get("label"), "location_hint": location.get("hint")}


def _liquidity(model: Mapping[str, Any], last: float) -> dict[str, Any]:
    levels = [r for r in model.get("reference_levels") or [] if r.get("price")]
    profile = model.get("profile") or {}
    known = {round(float(l["price"]), 2) for l in levels}
    for key, label in (("vah", "VAH Chart"), ("poc", "POC Chart"), ("val", "VAL Chart")):
        if profile.get(key) is not None and round(float(profile[key]), 2) not in known:
            levels.append({"label": label, "price": profile[key], "source": "Profil Chartfenster"})

    def item(level: Mapping[str, Any]) -> dict[str, Any]:
        price = float(level["price"])
        return {"label": level["label"], "price": round(price, 2), "source": level.get("source"),
                "distance_pct": round((price - last) / last * 100, 2), "poor": "Poor" in str(level["label"])}

    above = sorted((item(l) for l in levels if float(l["price"]) > last), key=lambda x: x["price"])[:LIQUIDITY_PER_SIDE]
    below = sorted((item(l) for l in levels if float(l["price"]) < last), key=lambda x: -x["price"])[:LIQUIDITY_PER_SIDE]
    return {"above": above, "below": below}


def _orderflow(model: Mapping[str, Any], last: float) -> dict[str, Any]:
    observations: list[str] = []
    profile = model.get("profile") or {}
    vah, val, poc = profile.get("vah"), profile.get("val"), profile.get("poc")
    if vah is not None and val is not None:
        where = "über der Value Area" if last > vah else "unter der Value Area" if last < val else "in der Value Area"
        observations.append(f"Kurs {where} des Chartfensters (VAL {_de(val)} – VAH {_de(vah)})")
    if poc is not None:
        observations.append(f"POC {_de(poc)}, {_de(abs(last - poc) / last * 100)} % {'über' if poc > last else 'unter'} dem Kurs")
    poor = [r["label"] for r in model.get("reference_levels") or [] if "Poor" in str(r.get("label"))]
    if poor:
        observations.append("Unfertige Auktion: " + ", ".join(poor))
    candles = model.get("candles") or []
    if len(candles) >= 21:
        volumes = [float(c.get("volume") or 0) for c in candles[-21:-1]]
        average = sum(volumes) / len(volumes)
        if average > 0:
            ratio = float(candles[-1].get("volume") or 0) / average
            observations.append(f"Volumen der letzten Kerze {_de(ratio, 1)}x des Schnitts der 20 davor")
    analysis = model.get("analysis") or {}
    if analysis.get("auction_state"):
        observations.append(f"Auktion laut Pipeline: {analysis['auction_state']}")
    return {"observations": observations,
            "limits": "Keine Delta-, Footprint- oder Orderbuchdaten: alle Beobachtungen sind Näherungen aus Kerzen und Volumen."}


def _evidence(plan: Mapping[str, Any], timeframe: str, register_path: Path | str) -> dict[str, Any]:
    from src.research_lab.setup_evidence import evidence_fields

    return evidence_fields(str(plan.get("scenario_type")), timeframe, register_path)


def _card_plan(source: str, plan: Mapping[str, Any], evidence_tf: str, register_path: Path | str) -> dict[str, Any]:
    from src.dashboard.plan_journal import journal_gate

    judged = {**dict(plan), **_evidence(plan, evidence_tf, register_path)}
    decision, reasons = journal_gate(judged)
    ref = judged.get("evidence_ref") or {}
    return {
        "source": source, "id": plan.get("scenario_id"), "direction": plan["direction"], "scenario_type": plan.get("scenario_type"),
        "plan_text": plan.get("plan_text"), "trend": plan.get("trend"), "anchor": plan.get("anchor"),
        "entry_low": plan.get("entry_low"), "entry_high": plan.get("entry_high"),
        "entry": plan["entry"], "stop": plan["stop"], "targets": list(plan["targets"]), "target_labels": list(plan.get("target_labels") or []),
        "invalidation": {"level": plan.get("invalidation_level"), "side": plan.get("invalidation_side")},
        "missing_confirmations": list(plan.get("missing_confirmations") or []),
        "economics": economics(plan["direction"], float(plan["entry"]), float(plan["stop"]), plan["targets"]),
        "evidence": {"status": judged.get("evidence_status"), "timeframe": evidence_tf, "reason": ref.get("reason"),
                     "variant_ids": list(ref.get("variant_ids") or []), "execution_status": judged.get("execution_status")},
        "decision": decision, "reasons": reasons, "reasons_text": [reason_text(code) for code in reasons],
    }


def _primary(plans: Sequence[Mapping[str, Any]], last: float) -> Mapping[str, Any] | None:
    """The plan to read first: level plans with the trend, then the nearest entry."""
    if not plans:
        return None
    return min(plans, key=lambda p: (p.get("trend") != "mit Trend", p["source"] != "level/1", abs(float(p["entry"]) - last)))


def build_analysis_card(model: Mapping[str, Any], register_path: Path | str | None = None) -> dict[str, Any]:
    """The card for the chart model's timeframe (pure; reads only the evidence register)."""
    from src.dashboard.plan_journal import level_entry, plans_from_model
    from src.research_lab.setup_evidence import DEFAULT_REGISTER_PATH

    register_path = register_path or DEFAULT_REGISTER_PATH
    timeframe = model.get("timeframe")
    levels = model.get("levels") or {}
    analysis = model.get("analysis") or {}
    market = analysis.get("market") or {}
    card: dict[str, Any] = {"schema": SCHEMA, "symbol": market.get("symbol") or "BTCUSDT", "timeframe": timeframe,
                            "generated_at": model.get("generated_at"), "read_only": True, "paper_only": True}
    if not model.get("candles"):
        card.update(decision={"status": "NO_TRADE", "summary": "Keine Kerzen für diesen Zeitrahmen: keine Analyse.", "reasons_text": ["keine Daten"]},
                    missing=list(REQUIRED[2:]), complete=False)
        return card
    last = float(levels["last"])
    quality = analysis.get("data_quality") or {}
    age = int(levels.get("age_seconds") or 0)
    from src.dashboard.chart_model import TIMEFRAME_SECONDS

    stale = age > TIMEFRAME_SECONDS.get(str(timeframe), 1800) + 300
    card["data"] = {"last": last, "last_close_time": levels.get("last_time"), "age_seconds": age, "stale": stale,
                    "quality": quality.get("status"), "confidence": quality.get("confidence"),
                    "missing": list(quality.get("missing") or []), "problems": list(quality.get("problems") or []),
                    "provenance": model.get("provenance")}
    structure = _structure(model)
    card["structure"] = structure
    card["trend"] = _trend(model, structure)
    card["liquidity"] = _liquidity(model, last)
    card["orderflow"] = _orderflow(model, last)

    plans = [_card_plan("level/1", level_entry(item, analysis), "30m", register_path)
             for item in (model.get("level_plans") or {}).get("plans") or []]
    plans += [_card_plan("pipeline", plan, str(timeframe), register_path) for plan in plans_from_model(model)]
    card["plans"] = plans
    primary = _primary(plans, last)
    card["primary"] = primary["id"] if primary else None
    card["dropped"] = list((model.get("level_plans") or {}).get("dropped") or [])

    if stale:
        summary = "NO_TRADE: die Daten sind veraltet, die Pläne gelten nicht."
        reasons = ["Daten veraltet"]
    elif not plans:
        summary = "NO_TRADE: kein Plan erfüllt TIMs Regeln."
        reasons = [*card["dropped"], *[f"Pipeline: {r}" for r in (analysis.get("decision") or {}).get("reasons") or []]] or ["kein Plan"]
    elif all(p["decision"] == "NO_TRADE" for p in plans):
        summary = "NO_TRADE: es gibt Pläne, aber das Gate des Plan-Journals ist geschlossen."
        reasons = list(dict.fromkeys(text for p in plans for text in p["reasons_text"]))
    else:
        summary = "PAPER_TRADE möglich: alle Gates offen (nur Papier)."
        reasons = []
    card["decision"] = {"status": "NO_TRADE" if reasons else "PAPER_TRADE", "summary": summary, "reasons_text": reasons}
    card["missing"] = [key for key in REQUIRED if card.get(key) in (None, {}, [])
                       and not (key == "plans" and card["decision"]["status"] == "NO_TRADE")]
    card["complete"] = not card["missing"]
    return card


def _same(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= PRICE_TOLERANCE


def journal_check(card: Mapping[str, Any], journal: Mapping[str, Any] | None, last_30m_close: str | None) -> dict[str, Any]:
    """Compare the card's level/1 plans with the level journal (read-only).

    ``last_30m_close`` is the close time of the newest closed 30m candle the chart saw (ISO, Z)."""
    if journal is None:
        return {"state": "NO_JOURNAL", "text": JOURNAL_STATES["NO_JOURNAL"], "plans": []}
    behind = journal.get("last_plan_candle") != last_30m_close
    live = {e["direction"]: e for e in journal.get("entries") or []
            if e.get("status") in {"OPEN", "FILLED"} and e.get("timeframe") == "30m"}
    rows = []
    for plan in (p for p in card.get("plans") or [] if p["source"] == "level/1"):
        entry = live.get(plan["direction"])
        if entry is None:
            state = "JOURNAL_BEHIND" if behind else "MISSING"
        elif _same(entry["entry"], plan["entry"]) and _same(entry["stop"], plan["stop"]) and all(
                _same(a, b) for a, b in zip(entry.get("targets") or [], plan["targets"])):
            state = "MATCH"
        elif behind:
            state = "JOURNAL_BEHIND"
        elif entry.get("created_at", "") < (last_30m_close or "") or entry.get("status") == "FILLED":
            state = "RESTING"
        else:
            state = "MISMATCH"
        rows.append({"id": plan["id"], "direction": plan["direction"], "state": state, "text": JOURNAL_STATES[state],
                     "journal_id": (entry or {}).get("id"), "journal_status": (entry or {}).get("status"),
                     "journal_decision": (entry or {}).get("journal_decision"),
                     "decision_equal": entry is None or entry.get("journal_decision") == plan["decision"],
                     "journal": {k: (entry or {}).get(k) for k in ("entry", "stop", "targets", "created_at")} if entry else None})
    states = {row["state"] for row in rows}
    overall = "MISMATCH" if "MISMATCH" in states else "JOURNAL_BEHIND" if "JOURNAL_BEHIND" in states else (
        "MISSING" if "MISSING" in states else "RESTING" if "RESTING" in states else "MATCH")
    if not rows:
        overall = "JOURNAL_BEHIND" if behind else "MATCH"
    return {"state": overall, "text": JOURNAL_STATES[overall] if rows else ("Kein Level-Plan, nichts abzugleichen" if not behind else JOURNAL_STATES[overall]),
            "journal_last_close": journal.get("last_plan_candle"), "chart_last_close": last_30m_close, "plans": rows}


def last_30m_close(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime) -> str | None:
    """Close time of the newest closed 30m candle in ``series`` (ISO with Z), as the journal writes it."""
    from src.dashboard.chart_model import analytical_series, clean_candles

    closed = [c for c in clean_candles(analytical_series(series, now).get("30m") or [], "30m") if c["close_time"] <= now]
    if not closed:
        return None
    from src.dashboard.plan_journal import _iso, _minute_ceil

    return _iso(_minute_ceil(closed[-1]["close_time"]))


def with_journal_check(model: dict[str, Any], series: Mapping[str, Sequence[Mapping[str, Any]]], journal_path: Path | None,
                       now: datetime) -> dict[str, Any]:
    """Add ``journal_check`` to the model's analysis card from the level journal at ``journal_path`` (read-only)."""
    card = model.get("analysis_card")
    if not card:
        return model
    journal = None
    if journal_path is not None and (Path(journal_path).exists() or Path(journal_path).with_name(Path(journal_path).stem + ".events.jsonl").exists()):
        from src.dashboard.plan_journal import load

        try:
            journal = load(Path(journal_path))
        except Exception:  # noqa: BLE001 - a broken log shows as unreadable, never as a match
            journal = None
    card["journal_check"] = journal_check(card, journal, last_30m_close(series, now))
    return model
