"""Paper journal of TIM's Setup-Pfad plans (long and short), with outcomes.

Each time a 30m candle closes, the plans shown on the Setup-Pfad page are
written down: entry, stop, invalidation and the three targets from TIM's
TradePlanBuilder. Afterwards every plan is followed on 1m candles:

- OPEN: waiting for the limit entry. A LONG limit above the close at recording
  (SHORT below) first waits for a 1m close beyond the entry (armed), then for the
  retest. Plans already beyond their stop or invalidation are not recorded. Ends as FILLED, INVALIDATED (30m close
  beyond the invalidation level first), REPLACED (TIM now proposes other
  levels in the same direction) or EXPIRED (24 h without fill). A plan that
  TIM stops showing stays OPEN like a resting limit order.
- FILLED: followed with TIM's management plan: one third out at each target,
  the last third at target 3 (the structural trailing stop is not modelled).
  Stop rule be_cost/1 (Uzi, 25.10.2026, every plan recorded from then on):
  the stop moves to break-even plus costs, the price at which the rest of
  the position closes at net 0 R (cost_stop_level), after target 1 and when
  TIM's own judgement of the running trade says so. At every 30m close TIM
  judges each filled plan from its chart model (judge_trades): SICHERN moves
  the stop, HALTEN leaves it; a safety net (FALLBACK_HOURS in the trade or
  FALLBACK_MFE_R reached) also says SICHERN. The verdict, its reasons and the
  close are written on the entry (tim_verdict, tim_verdict_reasons,
  tim_verdict_at), the move as cost_stop / cost_stop_at / cost_stop_kind, in
  force from the next 1m candle. Once protected, the stop trails behind the
  latest confirmed 30m swing in the trade's favour (swing low for a long,
  swing high for a short) like an orderflow trader locks in profit; it only
  ever moves further into profit. Entries without a stop_rule were recorded
  before and keep the old rule (stop to the entry after target 1). A 30m close beyond the
  invalidation level closes the rest at that close. Ends as CLOSED with a
  result in R.

Paper only. Nothing here places or suggests an order; it records what TIM's
rules would have done. When a 1m candle touches the stop and a target, the
stop counts first. No new entries inside the NY-open block.

Evidence gate (docs/ACCEPTANCE.md section 1): every entry carries, separately,
the heuristic setup grade of the scenario in its real state (never the forced
CONFIRMED state of the preview), the evidence status from the hypothesis
register (fail closed: INSUFFICIENT_EVIDENCE without a reviewed rule
equivalence), the execution status (RESEARCH_ONLY) and the journal decision
with its reasons (NO_TRADE unless evidence, execution and pipeline all allow a
paper trade). The pipeline's own decision is kept as pipeline_decision. These
fields are fixed when the plan is recorded; following the outcome never
changes them.

Storage (docs/ACCEPTANCE.md section 3): the only truth is the append-only,
hash-chained event log next to the document (`<name>.events.jsonl`, see
src.dashboard.journal_log). Every change that record_plans() or evaluate()
make to the in-memory journal is written as a PLAN_RECORDED or PLAN_UPDATED
event with the hash of the candles it was derived from; the JSON document is
a view folded from the log and can be rebuilt at any time. A restart with the
same candles produces no new events. A 30m close that arrives again with other
candle content is noted as CANDLE_REVISION_OBSERVED; the decisions taken on
the first content stay as they were.

Results: gross_r is the R multiple before costs; fee_r and slippage_r follow
research protocol 1.1 (docs/research_lab/PROTOKOLL.md section 4.3/4.4: taker
fee 0.05 % and slippage 0.03 % per side, 0.05 % on stop executions, costs in R
= cost in price / stop distance); net_r = gross_r - fee_r - slippage_r.
"""

from __future__ import annotations

import hashlib
import re
import json
import math
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dashboard import journal_log
from src.dashboard.chart_model import _time, build_chart_model, clean_candles, ny_open_windows
from src.research_lab.setup_evidence import DEFAULT_REGISTER_PATH, INSUFFICIENT_EVIDENCE, PASSED_HOLDOUT, RESEARCH_ONLY, evidence_fields

SCHEMA = "tim_plan_journal/2"
SOURCE = "Setup-Pfad 30m (80 Kerzen), TIM-Regeln, nur Papier"
PLAN_TIMEFRAME = "30m"
PLAN_VISIBLE = 80  # same window as the Setup-Pfad page (views.SETUP_CHART_CANDLES)
PENDING_HOURS = 24
MAX_HOLD_HOURS = 48
THIRD = 1.0 / 3.0
OPEN, FILLED = "OPEN", "FILLED"
DONE = {"CLOSED", "INVALIDATED", "REPLACED", "EXPIRED"}
RULE_TIM = "tim/1"  # TradePlanBuilder: flat stop, targets 1.5R / 2R / 3R
RULE_STRUCT = "struct/1"  # src/dashboard/structure_plan.py
RULE_LEVEL = "level/1"  # src/dashboard/level_plans.py
NO_TRADE, PAPER_TRADE = "NO_TRADE", "PAPER_TRADE"
PLAN_RECORDED, PLAN_UPDATED = "PLAN_RECORDED", "PLAN_UPDATED"
CANDLE_CLOSE_PROCESSED, CANDLE_REVISION_OBSERVED = "CANDLE_CLOSE_PROCESSED", "CANDLE_REVISION_OBSERVED"
# Research protocol 1.1, section 4.4, as fractions of the executed price per side.
COST_MODEL_VERSION = "protocol/1.1"
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0003
STOP_SLIPPAGE = 0.0005
# Stop rule of an entry, fixed when it is recorded. Entries without one keep the old rule.
STOP_RULE_COST = "be_cost/1"
COST_STOP_MIN_GAP_R = 0.1  # the 30m close must be at least this far beyond the new stop
VERDICT_RULESET = "verdict/1"
FALLBACK_HOURS = 4.0  # safety net: in the trade this long, the stop may move without a structure reason
FALLBACK_MFE_R = 0.75  # safety net: this much open profit seen, likewise
KIND_COSTS, KIND_SWING = "BREAK_EVEN_COSTS", "SWING"
HALTEN, SICHERN = "HALTEN", "SICHERN"
STRUCTURE_FOR = {"LONG": "UP", "SHORT": "DOWN"}
CONFIRMED_STATES = {"CONFIRMED", "PARTIALLY_CONFIRMED"}
STOP_EXITS = {"STOP", "BREAK_EVEN", "BREAK_EVEN_COSTS", "COST_STOP", "TRAIL_STOP"}  # executed as stop orders; everything else is a market exit
PAPER_APPROVED = "PAPER_APPROVED"  # no code path sets this yet; a human approval step would
# What the paper journal may assume about an instrument (docs/ACCEPTANCE.md section 2).
# A short on a spot market needs borrowed coins; the journal does not model margin, so it is not executable.
INSTRUMENT_SPEC_VERSION = "instrument/1"
INSTRUMENT_SPECS = {
    ("BINANCE", "SPOT", "BTCUSDT"): {"tick_size": 0.01, "lot_step": 0.00001, "short_executable": False},
}
STALE_AFTER = timedelta(minutes=60)  # two 30m intervals without a new close: no new plans
CANDLE_CLOSE_SKIPPED = "CANDLE_CLOSE_SKIPPED"
GRADE_NOTE = "Heuristischer Grade, kein empirischer Edge-Nachweis"
# Fields fixed at recording time. evaluate() must never touch them.
DECISION_FIELDS = (
    "setup_grade", "grade_reasons", "grade_ruleset_version", "graded_state",
    "evidence_status", "evidence_ref", "execution_status",
    "pipeline_decision", "pipeline_decision_reasons", "journal_decision", "journal_decision_reasons", "instrument",
)
# Fields that move with every candle. Changes to these alone are written at the
# next 30m close (checkpoint), not every minute; anything else is written at once.
CURSOR_FIELDS = {"evaluated_through", "max_favorable_r", "max_adverse_r", "last_seen_at"}
# Plans dropped at a close (counted in the view as structure_skips): by the struct/1 or
# level/1 rule, and for every rule plans that were already invalid on arrival.
STRUCTURE_PLANS_DROPPED = "STRUCTURE_PLANS_DROPPED"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_journal() -> dict[str, Any]:
    return {"schema": SCHEMA, "source": SOURCE, "last_plan_candle": None, "entries": []}


def events_path_for(path: Path) -> Path:
    return path.with_name(path.stem + ".events.jsonl")


def load(path: Path) -> dict[str, Any]:
    """The journal view, checked against its event log. If the document is
    missing or unreadable but the log exists, the view is folded from the log
    (read only, nothing written). A broken, shortened or replaced log raises
    journal_log.LogError: never a silently empty or stale journal."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    events = events_path_for(path)
    if isinstance(data, dict) and data.get("schema") == SCHEMA and isinstance(data.get("entries"), list):
        if events.exists():
            _check_anchor(path, journal_log.read(events))
        return data
    if events.exists():
        journal = fold(journal_log.read(events).events)
        journal["integrity"] = "VIEW_FOLDED_FROM_LOG"
        return journal
    return empty_journal()


def load_view(path: Path) -> dict[str, Any]:
    """load() for pages and the API: a broken log is shown as a locked journal
    (integrity LOG_BROKEN, no entries), never as an empty healthy one."""
    try:
        return load(path)
    except journal_log.LogError as error:
        return {**empty_journal(), "integrity": f"LOG_BROKEN: {error}", "blocked": True}


def save(journal: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(journal, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _same_levels(entry: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    def level(item: Mapping[str, Any], key: str) -> float | None:
        return None if item.get(key) is None else round(float(item[key]), 2)

    return all(level(entry, key) == level(plan, key) for key in ("entry", "stop", "entry_low", "entry_high"))


def plans_from_model(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Plans with entry, stop and targets from a chart model (Setup-Pfad)."""
    analysis = model.get("analysis") or {}
    result = []
    for scenario in analysis.get("scenarios") or []:
        preview = scenario.get("preview") or {}
        direction = scenario.get("direction")
        targets = [t for t in preview.get("targets") or [] if t is not None]
        if direction not in {"LONG", "SHORT"} or not scenario.get("plan_text") or preview.get("entry") is None or preview.get("stop") is None or len(targets) < 3:
            continue
        entry, stop = float(preview["entry"]), float(preview["stop"])
        if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
            continue
        invalid = scenario.get("invalidation_level") or {}
        result.append({
            "scenario_id": scenario.get("id"),
            "scenario_type": scenario.get("type"),
            "direction": direction,
            "entry_model": scenario.get("entry_model"),
            "plan_text": scenario.get("plan_text"),
            "entry_low": scenario.get("entry_low"),
            "entry_high": scenario.get("entry_high"),
            "entry": entry,
            "stop": stop,
            "targets": [float(t) for t in targets[:3]],
            "invalidation_level": invalid.get("level"),
            "invalidation_side": invalid.get("side"),
            "scenario_state": scenario.get("state"),
            "score": scenario.get("score"),
            "missing_confirmations": list(scenario.get("missing_confirmations") or []),
            "pipeline_decision": (analysis.get("decision") or {}).get("status"),
            "pipeline_decision_reasons": list((analysis.get("decision") or {}).get("reasons") or []),
            "market_state": analysis.get("market_state"),
            "grade": dict(scenario.get("grade") or {}) or None,
            **{k: (analysis.get("market") or {}).get(k) for k in ("symbol", "venue", "market_type")},
            "data_quality": (analysis.get("data_quality") or {}).get("status"),
        })
    return result


def instrument_for(plan: Mapping[str, Any]) -> dict[str, Any] | None:
    """The instrument spec of a plan, or None when the journal knows nothing about it."""
    spec = INSTRUMENT_SPECS.get((str(plan.get("venue")), str(plan.get("market_type")), str(plan.get("symbol"))))
    if spec is None:
        return None
    return {"symbol": plan.get("symbol"), "venue": plan.get("venue"), "market_type": plan.get("market_type"), "spec_version": INSTRUMENT_SPEC_VERSION, **spec}


def executability(plan: Mapping[str, Any]) -> list[str]:
    """Reasons why a plan could not be executed even on paper: unknown instrument,
    short on spot, data quality below PASS."""
    reasons: list[str] = []
    spec = instrument_for(plan)
    if spec is None:
        reasons.append("instrument_unknown")
    elif plan.get("direction") == "SHORT" and not spec["short_executable"]:
        reasons.append("short_not_executable_on_spot")
    quality = plan.get("data_quality")
    if quality != "PASS":
        reasons.append(f"data_quality_{str(quality or 'unknown').lower()}")
    return reasons


def journal_gate(plan: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Journal decision for a plan: NO_TRADE with reasons unless every gate is open.

    The gates are evidence (PASSED_HOLDOUT), execution (PAPER_APPROVED), the
    pipeline (TRADE_PLAN) and the scenario state (CONFIRMED). Nothing in the
    product sets PAPER_APPROVED today, so the result is NO_TRADE for every plan.
    """
    reasons: list[str] = []
    evidence = plan.get("evidence_status")
    if evidence is None:
        reasons.append("evidence_not_evaluated")
    elif evidence != PASSED_HOLDOUT:
        reasons.append(f"evidence_{str(evidence).lower()}")
    execution = plan.get("execution_status") or RESEARCH_ONLY
    if execution != PAPER_APPROVED:
        reasons.append(f"execution_{str(execution).lower()}")
    pipeline = plan.get("pipeline_decision")
    if pipeline != "TRADE_PLAN":
        reasons.append(f"pipeline_{str(pipeline or 'unknown').lower()}")
    graded_state = (plan.get("grade") or {}).get("graded_state")
    if graded_state != "CONFIRMED":
        reasons.append("scenario_not_confirmed")
    reasons.extend(executability(plan))
    return (NO_TRADE if reasons else PAPER_TRADE), reasons


def decision_fields(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The fields of DECISION_FIELDS for a new entry, fail closed when something is missing."""
    grade = plan.get("grade") or {}
    evidence_status = plan.get("evidence_status")
    evidence_ref = plan.get("evidence_ref")
    if evidence_status is None:
        evidence_status, evidence_ref = INSUFFICIENT_EVIDENCE, {"reason": "EVIDENCE_NOT_EVALUATED", "variant_ids": []}
    decision, reasons = journal_gate(plan)
    return {
        "setup_grade": grade.get("setup_grade"),
        "grade_reasons": list(grade.get("grade_reasons") or ["grade_not_computed"]),
        "grade_ruleset_version": grade.get("grade_ruleset_version"),
        "graded_state": grade.get("graded_state"),
        "evidence_status": evidence_status,
        "evidence_ref": dict(evidence_ref or {}),
        "execution_status": plan.get("execution_status") or RESEARCH_ONLY,
        "pipeline_decision": plan.get("pipeline_decision"),
        "pipeline_decision_reasons": list(plan.get("pipeline_decision_reasons") or []),
        "journal_decision": decision,
        "journal_decision_reasons": reasons,
        "instrument": instrument_for(plan),
    }


def record_plans(journal: dict[str, Any], plans: Sequence[Mapping[str, Any]], at: datetime, timeframe: str = PLAN_TIMEFRAME) -> list[dict[str, Any]]:
    """Add new plans; close OPEN ones whose levels TIM changed. Returns the new entries."""
    entries = journal.setdefault("entries", [])
    added = []
    by_direction = {plan["direction"]: plan for plan in plans}
    for entry in entries:
        if entry.get("status") != OPEN or entry.get("timeframe") != timeframe:
            continue
        plan = by_direction.get(entry["direction"])
        if plan is None:
            continue  # a resting limit stays until invalidation, replacement or expiry
        if not _same_levels(entry, plan):
            entry.update(status="REPLACED", closed_at=_iso(at), note="TIM hat neue Marken für diese Richtung.")
        else:
            entry["last_seen_at"] = _iso(at)
    # One plan per direction: no second entry while one waits or is in the trade.
    open_directions = {e["direction"] for e in entries if e.get("status") in {OPEN, FILLED} and e.get("timeframe") == timeframe}
    for plan in plans:
        if plan["direction"] in open_directions:
            continue
        start = _start_after_previous(entries, plan["direction"], timeframe, at)
        key = "|".join(str(x) for x in (timeframe, plan["direction"], plan.get("scenario_type"), plan.get("scenario_id"), _iso(at),
                                        f"{float(plan['entry']):.2f}", f"{float(plan['stop']):.2f}"))
        payload = {k: v for k, v in plan.items() if k not in {"grade", "evidence_status", "evidence_ref", "execution_status", "pipeline_decision", "pipeline_decision_reasons"}}
        entry = {
            "id": hashlib.sha256(key.encode()).hexdigest()[:12],
            "timeframe": timeframe,
            "created_at": _iso(at),
            "last_seen_at": _iso(at),
            **payload,
            **decision_fields(plan),
            "status": OPEN,
            **_arming(plan),
            "stop_rule": STOP_RULE_COST,
            "evaluated_through": _iso(start),
            "tp_hits": [],
            "gross_r": None,
            "fee_r": None,
            "slippage_r": None,
            "net_r": None,
        }
        entries.append(entry)
        added.append(entry)
    return added


def _start_after_previous(entries: Sequence[Mapping[str, Any]], direction: str, timeframe: str, at: datetime) -> datetime:
    """The first minute a new plan may trade: its close, or later if the previous trade in this direction ended later.

    A 30m close can be processed minutes late (busy Mac). The previous trade may then have
    been stopped after that close, and a new plan evaluated from the close would trade the
    same minutes again and book the same stop twice (26.10.2026, level/1: plan of 13:00
    written at 13:04, "filled" 13:01 and stopped 13:03 like the trade before it)."""
    start = at
    for entry in entries:
        if entry.get("direction") != direction or entry.get("timeframe") != timeframe or not entry.get("filled_at"):
            continue
        closed = entry.get("closed_at")
        if closed and _time(closed) > start:
            start = _time(closed)
    return start


def invalid_on_arrival(plan: Mapping[str, Any], close: float) -> str | None:
    """Why a plan is already dead at the 30m close it would be recorded on, or None.

    A plan whose stop or invalidation level the closing price has already
    passed cannot be traded: a resting limit on the wrong side of the market
    would fill at once and be stopped in the same minute. Such plans are not
    written down (25.10.2026: one LONG retest plan 1.5 % above the market was
    recorded ten times in a row and booked as ten -1.36 R losses)."""
    long = plan.get("direction") == "LONG"
    stop = plan.get("stop")
    if stop is not None and ((long and close <= float(stop)) or (not long and close >= float(stop))):
        return f"{plan.get('direction')}: Plan {plan.get('scenario_id')}: Schlusskurs {close:.2f} schon jenseits des Stops {float(stop):.2f}"
    level, side = plan.get("invalidation_level"), plan.get("invalidation_side")
    if level is not None and ((side == "<" and close < float(level)) or (side == ">" and close > float(level))):
        return f"{plan.get('direction')}: Plan {plan.get('scenario_id')}: Schlusskurs {close:.2f} schon jenseits der Ungültigkeitsmarke {float(level):.2f}"
    return None


def drop_invalid_on_arrival(plans: Sequence[Mapping[str, Any]], close: float | None) -> tuple[list[dict[str, Any]], list[str]]:
    """The plans still valid at ``close`` (with ``close_at_record``) and the reasons for the dropped ones."""
    if close is None:
        return [dict(plan) for plan in plans], []
    kept, dropped = [], []
    for plan in plans:
        reason = invalid_on_arrival(plan, float(close))
        if reason:
            dropped.append(reason)
        else:
            kept.append({**dict(plan), "close_at_record": float(close)})
    return kept, dropped


def _arming(plan: Mapping[str, Any]) -> dict[str, Any]:
    """A LONG limit above the close (SHORT below) is no resting order: it waits for the breakout.

    Such a plan (retest of a breakout edge, reclaim of a lost level) starts unarmed and its
    limit only counts after a 1m close beyond the entry. Without it the limit "filled" in the
    first minute at a price the market never traded. Plans recorded without a close stay armed."""
    close = plan.get("close_at_record")
    if close is None:
        return {}
    entry = float(plan["entry"])
    waits = (plan["direction"] == "LONG" and entry > float(close)) or (plan["direction"] == "SHORT" and entry < float(close))
    return {"armed": not waits}


def tick_fill(entry: Mapping[str, Any]) -> float:
    """The limit entry rounded to the instrument's tick, against the plan (buy up, sell down)."""
    tick = ((entry.get("instrument") or {}).get("tick_size")) or 0.0
    price = float(entry["entry"])
    if tick <= 0:
        return price
    steps = price / tick
    rounded = (math.ceil(steps - 1e-9) if entry["direction"] == "LONG" else math.floor(steps + 1e-9)) * tick
    return round(rounded, 8)


def _blocked(moment: datetime, windows: Sequence[Mapping[str, Any]]) -> bool:
    return any(_time(w["start"]) <= moment < _time(w["end"]) for w in windows)


def _r(entry: Mapping[str, Any], price: float) -> float:
    risk = abs(entry["entry"] - entry["stop"])
    move = price - entry["entry"] if entry["direction"] == "LONG" else entry["entry"] - price
    return move / risk if risk else 0.0


def costs_r(entry: Mapping[str, Any], exit_price: float, reason: str) -> tuple[float, float]:
    """(fee_r, slippage_r) of a filled plan closed at exit_price after its booked thirds.

    Protocol 1.1: fee and slippage on the whole size at entry, on each third at
    its target, and on the rest at the final exit; stop slippage only when the
    final exit was a stop execution. Costs in R = cost in price / stop distance."""
    risk = abs(float(entry["entry"]) - float(entry["stop"]))
    if risk <= 0:
        return 0.0, 0.0
    fill = float(entry.get("fill_price") or entry["entry"])
    hits = len(entry.get("tp_hits") or [])
    rest = 1.0 - THIRD * hits
    fee = FEE_PER_SIDE * fill
    slippage = SLIPPAGE_PER_SIDE * fill
    for index in range(hits):
        target = float(entry["targets"][index])
        fee += THIRD * FEE_PER_SIDE * target
        slippage += THIRD * SLIPPAGE_PER_SIDE * target
    fee += rest * FEE_PER_SIDE * exit_price
    slippage += rest * (STOP_SLIPPAGE if reason in STOP_EXITS else SLIPPAGE_PER_SIDE) * exit_price
    return round(fee / risk, 4), round(slippage / risk, 4)


def cost_stop_level(entry: Mapping[str, Any]) -> float:
    """Break-even plus costs: the stop price at which the rest of a filled plan closes at net 0 R.

    Protocol 1.1 on the rest: fee and slippage at the fill, fee and stop
    slippage at the stop. LONG: fill * (1 + fee + slippage) / (1 - fee - stop
    slippage); SHORT mirrored. Rounded to the tick away from the entry, so the
    level never covers less than the costs."""
    fill = float(entry.get("fill_price") or entry["entry"])
    if entry["direction"] == "LONG":
        level = fill * (1 + FEE_PER_SIDE + SLIPPAGE_PER_SIDE) / (1 - FEE_PER_SIDE - STOP_SLIPPAGE)
    else:
        level = fill * (1 - FEE_PER_SIDE - SLIPPAGE_PER_SIDE) / (1 + FEE_PER_SIDE + STOP_SLIPPAGE)
    tick = ((entry.get("instrument") or {}).get("tick_size")) or 0.0
    if tick > 0:
        steps = level / tick
        level = (math.ceil(steps - 1e-9) if entry["direction"] == "LONG" else math.floor(steps + 1e-9)) * tick
    return round(level, 8)


def _active_stop(entry: Mapping[str, Any], candle: Mapping[str, Any] | None = None) -> tuple[float, str]:
    """The stop in force for a FILLED entry on this candle and the exit reason it books."""
    if entry.get("stop_rule") != STOP_RULE_COST:
        return (entry["entry"], "BREAK_EVEN") if entry["tp_hits"] else (entry["stop"], "STOP")
    stop, reason = entry["stop"], "STOP"
    if entry["tp_hits"]:
        level = cost_stop_level(entry)
        # A stop so tight that the costs reach target 1 cannot sit behind it: fall back to the entry.
        stop, reason = (level, "BREAK_EVEN_COSTS") if _r(entry, level) < _r(entry, entry["targets"][0]) else (entry["entry"], "BREAK_EVEN")
    if entry.get("cost_stop") is not None and (candle is None or candle["open_time"] >= _time(entry["cost_stop_at"])):
        protected = float(entry["cost_stop"])
        if _r(entry, protected) > _r(entry, stop):
            stop, reason = protected, ("TRAIL_STOP" if entry.get("cost_stop_kind") == KIND_SWING else "COST_STOP")
    return stop, reason


def judge_trade(entry: Mapping[str, Any], model: Mapping[str, Any], close: float, at: datetime | None = None) -> tuple[str, list[str]]:
    """TIM's verdict on a filled plan at a 30m close: SICHERN (stop to break-even plus
    costs) or HALTEN (original stop stays), with reason codes.

    Price only decides whether a move is possible: the close must be at least
    COST_STOP_MIN_GAP_R beyond the cost level, so the stop never sits on the
    market. Then TIM's chart model at that close decides. SICHERN when the
    market structure confirmed the trade direction since the fill (BOS/MSS in
    its direction: the move is earned), or when the thesis weakens: a
    structure break against it, the market state against it, or a scenario in
    the opposite direction that is confirmed. The safety net Uzi chose
    (FALLBACK_HOURS in the trade, or FALLBACK_MFE_R of open profit seen) says
    SICHERN as well. HALTEN otherwise: the plan runs as intended and keeps its
    room."""
    direction = entry["direction"]
    level = cost_stop_level(entry)
    if _r(entry, close) - _r(entry, level) < COST_STOP_MIN_GAP_R:
        return HALTEN, ["price_not_beyond_cost_level"]
    filled_at = str(entry.get("filled_at") or "")
    reasons: list[str] = []
    if at is not None and filled_at and at - _time(filled_at) >= timedelta(hours=FALLBACK_HOURS):
        reasons.append(f"fallback_{FALLBACK_HOURS:g}h_in_trade")
    if float(entry.get("max_favorable_r") or 0.0) >= FALLBACK_MFE_R:
        reasons.append(f"fallback_mfe_{FALLBACK_MFE_R:g}r")
    with_us, against = STRUCTURE_FOR[direction], STRUCTURE_FOR["SHORT" if direction == "LONG" else "LONG"]
    for event in model.get("bos") or []:
        if str(event.get("break_time") or "") < filled_at:
            continue
        if event.get("direction") == with_us:
            reasons.append(f"structure_confirms_{str(event.get('kind', 'BOS')).lower()}")
        elif event.get("direction") == against:
            reasons.append(f"structure_against_{str(event.get('kind', 'BOS')).lower()}")
    if counter_trend(direction, model.get("market_state")):
        reasons.append("market_state_against")
    for scenario in model.get("scenarios") or []:
        if scenario.get("direction") not in {"LONG", "SHORT"} or scenario.get("direction") == direction:
            continue
        if scenario.get("state") in CONFIRMED_STATES:
            reasons.append(f"opposite_scenario_{str(scenario.get('state')).lower()}")
    reasons = sorted(set(reasons))
    return (SICHERN, reasons) if reasons else (HALTEN, ["thesis_intact"])


def swing_stop(entry: Mapping[str, Any], candles: Sequence[Mapping[str, Any]], close: float) -> float | None:
    """The latest confirmed 30m swing behind the trade since its fill (swing low for
    a long, swing high for a short), when it lies beyond the current protected stop
    and the close is at least COST_STOP_MIN_GAP_R beyond it. Else None."""
    from src.dashboard.chart_model import PIVOT_WINDOW, swing_points

    long = entry["direction"] == "LONG"
    filled = _time(entry["filled_at"])
    current = entry.get("cost_stop")
    floor = float(current) if current is not None else (cost_stop_level(entry) if entry["tp_hits"] else None)
    if floor is None:
        return None
    best = None
    for swing in swing_points(candles, PIVOT_WINDOW):
        if swing["kind"] != ("LOW" if long else "HIGH") or candles[swing["index"]]["open_time"] < filled:
            continue
        price = float(swing["price"])
        if (price > floor if long else price < floor) and _r(entry, close) - _r(entry, price) >= COST_STOP_MIN_GAP_R:
            best = price  # swings come in time order: the latest wins
    return best


def judge_trades(journal: dict[str, Any], model: Mapping[str, Any], candles: Sequence[Mapping[str, Any]]) -> None:
    """TIM judges every filled be_cost/1 plan at the 30m close ``candles[-1]``:
    SICHERN moves the stop to break-even plus costs, a protected stop trails
    behind the latest confirmed swing; both in force from the next 1m candle."""
    if not candles:
        return
    close_candle = candles[-1]
    at = _iso(close_candle["close_time"])
    close = float(close_candle["close"])
    for entry in journal.get("entries", []):
        if entry.get("status") != FILLED or entry.get("stop_rule") != STOP_RULE_COST:
            continue
        if not entry.get("filled_at") or _time(entry["filled_at"]) > close_candle["close_time"]:
            continue
        if not entry["tp_hits"] and entry.get("cost_stop") is None:
            verdict, reasons = judge_trade(entry, model, close, close_candle["close_time"])
            entry.update(tim_verdict=verdict, tim_verdict_reasons=reasons, tim_verdict_at=at, tim_verdict_ruleset=VERDICT_RULESET)
            if verdict == SICHERN:
                entry.update(cost_stop=cost_stop_level(entry), cost_stop_at=at, cost_stop_kind=KIND_COSTS)
            continue
        trailed = swing_stop(entry, candles, close)
        if trailed is not None:
            entry.update(cost_stop=trailed, cost_stop_at=at, cost_stop_kind=KIND_SWING)


def _close(entry: dict[str, Any], at: datetime, price: float, reason: str) -> None:
    """Close the rest of the position; earlier thirds stay booked. Books gross, costs and net."""
    realised = sum(THIRD * _r(entry, entry["targets"][i]) for i in range(len(entry["tp_hits"])))
    rest = 1.0 - THIRD * len(entry["tp_hits"])
    gross = round(realised + rest * _r(entry, price), 3)
    fee_r, slippage_r = costs_r(entry, price, reason)
    entry.update(status="CLOSED", closed_at=_iso(at), exit_reason=reason, exit_price=price,
                 gross_r=gross, fee_r=fee_r, slippage_r=slippage_r, net_r=round(gross - fee_r - slippage_r, 4),
                 cost_model_version=COST_MODEL_VERSION)


def _follow(entry: dict[str, Any], candle: Mapping[str, Any]) -> None:
    """One 1m candle for a FILLED position (stop first, then targets in order)."""
    long = entry["direction"] == "LONG"
    stop, reason = _active_stop(entry, candle)
    entry["max_favorable_r"] = round(max(entry.get("max_favorable_r", 0.0), _r(entry, candle["high"] if long else candle["low"])), 3)
    entry["max_adverse_r"] = round(min(entry.get("max_adverse_r", 0.0), _r(entry, candle["low"] if long else candle["high"])), 3)
    if (long and candle["low"] <= stop) or (not long and candle["high"] >= stop):
        _close(entry, candle["close_time"], stop, reason)
        return
    for index in range(len(entry["tp_hits"]), 3):
        target = entry["targets"][index]
        if (long and candle["high"] >= target) or (not long and candle["low"] <= target):
            entry["tp_hits"].append(_iso(candle["close_time"]))
        else:
            break
    if len(entry["tp_hits"]) == 3:
        _close(entry, candle["close_time"], entry["targets"][2], "TP3")


def evaluate(journal: dict[str, Any], minute_candles: Sequence[Mapping[str, Any]], plan_candles: Sequence[Mapping[str, Any]], now: datetime) -> None:
    """Follow OPEN and FILLED entries on candles after their last evaluation."""
    minutes = clean_candles(minute_candles, "1m")
    for entry in journal.get("entries", []):
        if entry.get("status") not in {OPEN, FILLED}:
            continue
        closes = clean_candles(plan_candles, entry.get("timeframe", PLAN_TIMEFRAME))
        through = _time(entry["evaluated_through"])
        fresh = [c for c in minutes if c["open_time"] >= through]
        if fresh and fresh[0]["open_time"] > through + timedelta(minutes=1) and not entry.get("data_gap"):
            entry["data_gap"] = f"1m-Kerzen fehlen zwischen {_iso(through)} und {_iso(fresh[0]['open_time'])}"
        windows = ny_open_windows(through - timedelta(days=1), now + timedelta(days=1)) if fresh else []
        long = entry["direction"] == "LONG"
        level, side = entry.get("invalidation_level"), entry.get("invalidation_side")
        seen = through
        for candle in fresh:
            # 30m closes that completed since the previous 1m candle.
            broken = [c for c in closes if c["timeframe"] == entry.get("timeframe", PLAN_TIMEFRAME) and seen < c["close_time"] <= candle["open_time"] and level is not None
                      and ((side == "<" and c["close"] < level) or (side == ">" and c["close"] > level))]
            seen = candle["open_time"]
            if broken and entry["status"] == OPEN:
                entry.update(status="INVALIDATED", closed_at=_iso(broken[0]["close_time"]), note=f"{entry.get('timeframe', PLAN_TIMEFRAME)}-Schluss jenseits der Ungültigkeitsmarke vor dem Einstieg.")
                break
            if broken:
                _close(entry, broken[0]["close_time"], broken[0]["close"], "INVALIDATION")
                break
            if entry["status"] == OPEN:
                if candle["open_time"] >= _time(entry["created_at"]) + timedelta(hours=PENDING_HOURS):
                    entry.update(status="EXPIRED", closed_at=_iso(candle["open_time"]), note=f"{PENDING_HOURS} h ohne Einstieg.")
                    break
                if not entry.get("armed", True):
                    # Breakout first: a 1m close beyond the entry arms the limit for the retest.
                    if (long and candle["close"] > entry["entry"]) or (not long and candle["close"] < entry["entry"]):
                        entry.update(armed=True, armed_at=_iso(candle["close_time"]))
                    continue
                touched = candle["low"] <= entry["entry"] if long else candle["high"] >= entry["entry"]
                if touched and not _blocked(candle["open_time"], windows):
                    entry.update(status=FILLED, filled_at=_iso(candle["open_time"]), fill_price=tick_fill(entry))
                    # Fill candle: only the stop can trigger (order inside the candle is unknown).
                    stop_hit = candle["low"] <= entry["stop"] if long else candle["high"] >= entry["stop"]
                    if stop_hit:
                        _close(entry, candle["close_time"], entry["stop"], "STOP")
                        break
                continue
            if candle["open_time"] >= _time(entry["filled_at"]) + timedelta(hours=MAX_HOLD_HOURS):
                _close(entry, candle["open_time"], candle["open"], "TIMEOUT")
                break
            _follow(entry, candle)
            if entry["status"] != FILLED:
                break
        if fresh and entry["status"] in {OPEN, FILLED}:
            entry["evaluated_through"] = _iso(fresh[-1]["close_time"])
        elif fresh:
            entry["evaluated_through"] = entry.get("closed_at", entry["evaluated_through"])


def _minute_ceil(value: datetime) -> datetime:
    """30m close times may end in :59.999; journal times start at the full minute."""
    floor = value.replace(second=0, microsecond=0)
    return floor if floor == value else floor + timedelta(minutes=1)


AGAINST_TREND = {"LONG": "TREND_DOWN", "SHORT": "TREND_UP"}


def counter_trend(direction: Any, market_state: Any) -> bool:
    """True when a plan trades against TIM's market state (LONG in TREND_DOWN, SHORT in TREND_UP)."""
    return AGAINST_TREND.get(str(direction)) == str(market_state)


def summary(journal: Mapping[str, Any]) -> dict[str, Any]:
    entries = list(journal.get("entries") or [])
    closed = [e for e in entries if e.get("status") == "CLOSED" and e.get("gross_r") is not None]
    wins = [e for e in closed if e["gross_r"] > 0]
    net_wins = [e for e in closed if (e.get("net_r") or 0.0) > 0]
    by_direction = {}
    for direction in ("LONG", "SHORT"):
        mine = [e for e in closed if e["direction"] == direction]
        by_direction[direction] = {"closed": len(mine), "sum_r": round(sum(e["gross_r"] for e in mine), 3),
                                   "sum_net_r": round(sum(e.get("net_r") or 0.0 for e in mine), 3)}
    against = [e for e in closed if counter_trend(e.get("direction"), e.get("market_state"))]
    return {
        "plans": len(entries),
        "open": sum(e.get("status") == OPEN for e in entries),
        "filled": sum(e.get("status") == FILLED for e in entries),
        "closed": len(closed),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "net_wins": len(net_wins),
        "sum_r": round(sum(e["gross_r"] for e in closed), 3),
        "sum_net_r": round(sum(e.get("net_r") or 0.0 for e in closed), 3),
        "result_basis": "GROSS_R_AND_NET_R",
        "cost_model_version": COST_MODEL_VERSION,
        "paper_trades": sum(e.get("journal_decision") == PAPER_TRADE for e in entries),
        "no_trade": sum(e.get("journal_decision") == NO_TRADE for e in entries),
        "by_direction": by_direction,
        "counter_trend": {
            "plans": sum(counter_trend(e.get("direction"), e.get("market_state")) for e in entries),
            "closed": len(against),
            "sum_r": round(sum(e["gross_r"] for e in against), 3),
        },
    }


def _structural(plans: list[dict[str, Any]], series: Mapping[str, Sequence[Mapping[str, Any]]], at: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    """Rule version struct/1: same plans, stop behind the swing, targets at liquidity.

    Returns the kept plans and the reasons for the dropped ones."""
    from src.dashboard.session_map import build_session_map
    from src.dashboard.structure_plan import candles_until, structural_plans

    closed = candles_until(series, at)
    try:
        prep = build_session_map(closed, at)
    except Exception:  # noqa: BLE001 - without the map the 30m swings remain as targets
        prep = None
    kept, dropped = structural_plans(plans, closed["30m"], prep)
    return kept, list(dropped)


def level_entry(item: Mapping[str, Any], analysis: Mapping[str, Any]) -> dict[str, Any]:
    """A level/1 plan (src/dashboard/level_plans.py) in the journal's plan shape.

    The chart's analysis card uses the same mapping, so chart and journal judge a plan alike."""
    preview = item["preview"]
    invalid = item["invalidation_level"]
    return {
        "rule": RULE_LEVEL,
        "scenario_id": item["id"],
        "scenario_type": item["type"],
        "direction": item["direction"],
        "entry_model": item["entry_model"],
        "plan_text": item["plan_text"],
        "anchor": item["anchor"],
        "trend": item["trend"],
        "location": item["location"],
        "entry_low": item["entry_low"],
        "entry_high": item["entry_high"],
        "entry": float(preview["entry"]),
        "stop": float(preview["stop"]),
        "targets": [float(t) for t in preview["targets"][:3]],
        "target_labels": list(preview["target_labels"][:3]),
        "invalidation_level": invalid["level"],
        "invalidation_side": invalid["side"],
        "scenario_state": item["state"],
        "score": None,
        "missing_confirmations": list(item["missing_confirmations"]),
        "pipeline_decision": (analysis.get("decision") or {}).get("status"),
        "pipeline_decision_reasons": list((analysis.get("decision") or {}).get("reasons") or []),
        "market_state": analysis.get("market_state"),
        "grade": None,
        **{k: (analysis.get("market") or {}).get(k) for k in ("symbol", "venue", "market_type")},
        "data_quality": (analysis.get("data_quality") or {}).get("status"),
    }


def _level(series: Mapping[str, Sequence[Mapping[str, Any]]], at: datetime, model: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Rule version level/1: plans at the nearest main levels (src/dashboard/level_plans.py).

    Uses only candles closed at ``at``, like struct/1. Returns the plans in the
    journal's plan shape and the reasons for dropped candidates."""
    from src.dashboard.level_plans import build_level_plans
    from src.dashboard.session_map import build_session_map
    from src.dashboard.structure_plan import candles_until

    closed = candles_until(series, at)
    try:
        prep = build_session_map(closed, at)
    except Exception:  # noqa: BLE001 - without the map there are no main levels
        return [], ["keine Vorbereitungs-Karte"]
    result = build_level_plans(prep, closed["30m"], at)
    plans = [level_entry(item, model.get("analysis") or {}) for item in result["plans"]]
    return plans, list(result["dropped"])


def _skip_key(reason: str) -> str:
    # "LONG: <Level>: nächstes Ziel nur 1.05 R entfernt" -> "nächstes Ziel"; numbers never split a key.
    return re.sub(r"\d+[.,]\d+|\b\d+(?= ?%)", "x", reason.rsplit(": ", 1)[-1].split(" nur ")[0])


def with_evidence(plans: Sequence[Mapping[str, Any]], timeframe: str = PLAN_TIMEFRAME, register_path: Path | str = DEFAULT_REGISTER_PATH) -> list[dict[str, Any]]:
    """Plans with their evidence fields from the hypothesis register (fail closed)."""
    return [{**dict(plan), **evidence_fields(str(plan.get("scenario_type")), timeframe, register_path)} for plan in plans]


def fold(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The journal view from its events. Rejects events that would change a
    decision field or touch an entry after its terminal state."""
    journal = empty_journal()
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        kind, payload = event.get("kind"), event.get("payload") or {}
        if kind == PLAN_RECORDED:
            entry = deepcopy(payload["entry"])
            if entry["id"] in by_id:
                raise journal_log.LogError(f"plan {entry['id']} recorded twice")
            journal["entries"].append(entry)
            by_id[entry["id"]] = entry
        elif kind == PLAN_UPDATED:
            entry = by_id.get(payload.get("id"))
            if entry is None:
                raise journal_log.LogError(f"update for unknown plan {payload.get('id')}")
            changes = payload.get("changes") or {}
            if set(changes) & set(DECISION_FIELDS):
                raise journal_log.LogError(f"plan {entry['id']}: decision fields are immutable")
            if entry.get("status") in DONE:
                raise journal_log.LogError(f"plan {entry['id']}: event after terminal state {entry.get('status')}")
            entry.update(deepcopy(changes))
        elif kind == CANDLE_CLOSE_PROCESSED:
            journal["last_plan_candle"] = payload["close_time"]
            journal["last_plan_candle_source_hash"] = payload["source_hash"]
            if payload.get("rule") in (RULE_STRUCT, RULE_LEVEL):  # TIM-rule events carry no rule field
                journal["rule"] = payload["rule"]
                journal.setdefault("structure_skips", {})
                journal["last_skips"] = []  # a STRUCTURE_PLANS_DROPPED event for this close follows it
            elif "last_skips" in journal:
                journal["last_skips"] = []  # tim/1: only plans dropped as invalid on arrival
        elif kind == CANDLE_REVISION_OBSERVED:
            journal.setdefault("revisions", []).append(deepcopy(payload))
        elif kind == CANDLE_CLOSE_SKIPPED:
            journal.setdefault("skipped", []).append(deepcopy(payload))
        elif kind == STRUCTURE_PLANS_DROPPED:
            counts = journal.setdefault("structure_skips", {})
            for reason in payload.get("reasons") or []:
                counts[_skip_key(reason)] = counts.get(_skip_key(reason), 0) + 1
            journal["last_skips"] = list(payload.get("reasons") or [])
        else:
            raise journal_log.LogError(f"unknown event kind {kind}")
        journal["updated_at"] = event.get("recorded_at")
    return journal


def diff_events(before: Mapping[str, Any], after: Mapping[str, Any], *, recorded_at: datetime, source_hash: str, source_range: Mapping[str, Any],
                close_source_hash: str | None = None, checkpoint: bool = True) -> list[dict[str, Any]]:
    """Events that turn `before` into `after` (entries and last_plan_candle).

    `source_hash` names the candles the plan events were derived from;
    `close_source_hash` the 30m candles behind a processed close. Without
    `checkpoint`, updates that only move CURSOR_FIELDS are left out: the next
    update() re-derives them from the same candles."""
    events: list[dict[str, Any]] = []
    old = {e["id"]: e for e in before.get("entries") or []}
    common = {"recorded_at": _iso(recorded_at), "source_hash": source_hash, "source_range": dict(source_range)}
    for entry in after.get("entries") or []:
        previous = old.get(entry["id"])
        if previous is None:
            events.append({"event_id": journal_log.event_id(PLAN_RECORDED, entry["id"], entry.get("grade_ruleset_version"), entry.get("evidence_ref", {}).get("register_head_hash")),
                           "kind": PLAN_RECORDED, "aggregate_id": entry["id"], **common, "payload": {"entry": deepcopy(entry)}})
            continue
        changes = {k: v for k, v in entry.items() if previous.get(k) != v}
        removed = [k for k in previous if k not in entry]
        if removed:
            raise journal_log.LogError(f"plan {entry['id']}: fields disappeared: {removed}")
        if changes and (checkpoint or not set(changes) <= CURSOR_FIELDS):
            events.append({"event_id": journal_log.event_id(PLAN_UPDATED, entry["id"], changes, source_hash),
                           "kind": PLAN_UPDATED, "aggregate_id": entry["id"], **common, "payload": {"id": entry["id"], "changes": deepcopy(changes)}})
    if after.get("last_plan_candle") != before.get("last_plan_candle"):
        close_hash = close_source_hash or source_hash
        events.append({"event_id": journal_log.event_id(CANDLE_CLOSE_PROCESSED, after["last_plan_candle"], close_hash), "kind": CANDLE_CLOSE_PROCESSED,
                       "aggregate_id": "journal", **common, "source_hash": close_hash, "payload": {"close_time": after["last_plan_candle"], "source_hash": close_hash}})
    return events


def rebuild(path: Path) -> dict[str, Any]:
    """Fold the log and write the view atomically. Raises LogError on a broken log."""
    journal = fold(journal_log.read(events_path_for(path)).events)
    save(journal, path)
    return journal


def _source(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    minutes = clean_candles(series.get("1m") or [], "1m")
    plan_candles = clean_candles(series.get(PLAN_TIMEFRAME) or [], PLAN_TIMEFRAME)
    legacy = clean_candles(series.get("15m") or [], "15m")
    digest = journal_log.content_hash({"1m": minutes, PLAN_TIMEFRAME: plan_candles, "legacy_15m": legacy})
    span = {"1m_first": _iso(minutes[0]["open_time"]) if minutes else None, "1m_last": _iso(minutes[-1]["close_time"]) if minutes else None,
            f"{PLAN_TIMEFRAME}_count": len(plan_candles), "now": _iso(now)}
    return digest, span, minutes, plan_candles


def update(path: Path, series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime | None = None, register_path: Path | str = DEFAULT_REGISTER_PATH,
           rule: str = RULE_TIM) -> dict[str, Any]:
    """One journal step: fold the log, follow outcomes, record plans at a new
    30m close, append the resulting events, then write the view.

    ``rule`` picks the rule version: TIM's flat stop and R targets, or
    struct/1 (stop behind the swing, targets at liquidity) in its own file.

    A broken event log raises journal_log.LogError and nothing is written."""
    now = now or datetime.now(timezone.utc)
    from src.dashboard.chart_model import analytical_series
    series = analytical_series(series, now)
    events_path = events_path_for(path)
    state = journal_log.read(events_path)
    _check_anchor(path, state)
    journal = fold(state.events)
    before = deepcopy(journal)
    source_hash, source_range, minutes, plan_candles = _source(series, now)
    evaluate(journal, minutes, [*plan_candles, *series.get("15m", [])], now)
    new_events: list[dict[str, Any]] = []
    closed_30m = [c for c in plan_candles if c["close_time"] <= now]
    checkpoint, close_hash = False, None
    if closed_30m:
        latest = _minute_ceil(closed_30m[-1]["close_time"])
        close_hash = journal_log.content_hash(plan_candles[-PLAN_VISIBLE:])
        age = now - latest
        if journal.get("last_plan_candle") != _iso(latest) and age > STALE_AFTER:
            # Stale market data: no new plans (section 2). Noted once per close; the next close records again.
            new_events.append({"event_id": journal_log.event_id(CANDLE_CLOSE_SKIPPED, _iso(latest), "stale"), "kind": CANDLE_CLOSE_SKIPPED,
                               "aggregate_id": "journal", "recorded_at": _iso(now), "source_hash": close_hash, "source_range": source_range,
                               "payload": {"close_time": _iso(latest), "reason": "stale_data", "age_seconds": int(age.total_seconds())}})
        elif journal.get("last_plan_candle") != _iso(latest):
            model = build_chart_model(series, PLAN_TIMEFRAME, now=latest, visible=PLAN_VISIBLE)
            plans = plans_from_model(model)
            dropped: list[str] = []
            if rule == RULE_STRUCT:
                plans, dropped = _structural(plans, series, latest)
            elif rule == RULE_LEVEL:
                plans, dropped = _level(series, latest, model)
            plans, dead = drop_invalid_on_arrival(plans, closed_30m[-1].get("close"))
            dropped += dead
            if dropped:
                new_events.append({"event_id": journal_log.event_id(STRUCTURE_PLANS_DROPPED, _iso(latest), close_hash), "kind": STRUCTURE_PLANS_DROPPED,
                                   "aggregate_id": "journal", "recorded_at": _iso(now), "source_hash": close_hash, "source_range": source_range,
                                   "payload": {"close_time": _iso(latest), "rule": rule, "reasons": dropped}})
            record_plans(journal, with_evidence(plans, PLAN_TIMEFRAME, register_path), latest)
            judge_trades(journal, model, closed_30m)
            journal["last_plan_candle"] = _iso(latest)
            checkpoint = True
        elif journal.get("last_plan_candle_source_hash") not in {None, close_hash}:
            # Same 30m close, other candle content: noted, decisions untouched.
            new_events.append({"event_id": journal_log.event_id(CANDLE_REVISION_OBSERVED, _iso(latest), close_hash), "kind": CANDLE_REVISION_OBSERVED,
                               "aggregate_id": "journal", "recorded_at": _iso(now), "source_hash": close_hash, "source_range": source_range,
                               "payload": {"close_time": _iso(latest), "supersedes_source_hash": journal["last_plan_candle_source_hash"], "source_hash": close_hash}})
    new_events = diff_events(before, journal, recorded_at=now, source_hash=source_hash, source_range=source_range,
                             close_source_hash=close_hash, checkpoint=checkpoint) + new_events
    if rule != RULE_TIM:
        for event in new_events:
            if event["kind"] == CANDLE_CLOSE_PROCESSED:
                event["payload"]["rule"] = rule
    written = journal_log.append(events_path, new_events, state)
    events = state.events + written
    # The view is always the fold: cursor-only progress that was not written is re-derived next time.
    journal = fold(events)
    journal["checked_at"] = _iso(now)
    journal["log_seq"] = len(events)
    journal["log_head"] = events[-1]["hash"] if events else journal_log.GENESIS
    save(journal, path)
    return journal


def _check_anchor(path: Path, state: journal_log.LogState) -> None:
    """The view remembers how long the log was when it was written. A log that
    is shorter now, or whose event at that point has another hash, lost events
    (truncation, replaced file) and must not be continued. A dropped tail is
    only accepted when it lies beyond the anchored length."""
    try:
        view = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(view, dict) or view.get("schema") != SCHEMA or not isinstance(view.get("log_seq"), int):
        return
    seq, head = view["log_seq"], view.get("log_head")
    if len(state.events) < seq:
        raise journal_log.LogError(f"the log has {len(state.events)} events but the view was written at {seq}; events were lost")
    if seq and state.events[seq - 1]["hash"] != head:
        raise journal_log.LogError(f"the log diverges from the view at seq {seq - 1}; the log was replaced")
