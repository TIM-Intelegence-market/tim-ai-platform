"""Rules alone against rules plus AI, on the same plans, after costs (net R).

A judgement counts only if it was written before the plan was filled (or the plan never filled).
Plans that never filled are no trade in either arm. Open plans are pending.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.research_lab.ki_filter import AUSLASSEN, NEHMEN, PROMPT_VERSION
from src.research_lab.ki_filter.context import parse_time

MIN_TRADES = 60  # preregistration draft: no verdict before this many closed trades judged in time


def _drawdown(results: Sequence[float]) -> float:
    peak = total = worst = 0.0
    for r in results:
        total += r
        peak = max(peak, total)
        worst = min(worst, total - peak)
    return round(worst, 3)


def _arm(trades: Sequence[tuple[Any, float]]) -> dict[str, Any]:
    ordered = [r for _, r in sorted(trades, key=lambda pair: (pair[0] is None, pair[0] or 0))]
    return {"trades": len(ordered), "sum_net_r": round(sum(ordered), 3),
            "mean_net_r": round(sum(ordered) / len(ordered), 4) if ordered else None,
            "wins": sum(r > 0 for r in ordered), "max_drawdown_r": _drawdown(ordered)}


def evaluate(records: Sequence[Mapping[str, Any]], journals: Mapping[str, Mapping[str, Any]],
             model: str | None = None, prompt_version: str = PROMPT_VERSION) -> dict[str, Any]:
    """One count per (model, prompt version): a model or prompt change starts a new count.
    Without ``model`` the model of the latest record with this prompt version is used."""
    if model is None:
        model = next((r.get("model") for r in reversed(records) if r.get("prompt_version") == prompt_version), None)
    all_records, records, seen = list(records), [], set()
    other = duplicate = 0
    for record in all_records:
        if record.get("model") != model or record.get("prompt_version") != prompt_version:
            other += 1
            continue
        key = (record.get("timeframe"), record.get("plan_id"))
        if key in seen:
            duplicate += 1
            continue
        seen.add(key)
        records.append(record)
    entries = {}
    for timeframe, view in journals.items():
        for entry in view.get("entries") or []:
            if entry.get("id"):
                entries[(timeframe, entry["id"])] = entry
    counts = {"judged": len(records), "late": 0, "missing_plan": 0, "pending": 0, "no_fill": 0, "excluded": 0,
              "other_model_or_prompt": other, "duplicate": duplicate}
    rules, taken, skipped = [], [], []
    by_tf: dict[str, dict[str, list]] = {}
    for record in records:
        entry = entries.get((record.get("timeframe"), record.get("plan_id")))
        if entry is None:
            counts["missing_plan"] += 1
            continue
        if entry.get("excluded"):
            counts["excluded"] += 1
            continue
        # Late check on the moment the answer was written (decided_at is only the start of the run).
        decided = parse_time(record.get("written_at") or record.get("decided_at"))
        filled = parse_time(entry.get("filled_at"))
        if decided is None or (filled is not None and decided > filled):
            counts["late"] += 1
            continue
        status = entry.get("status")
        if status in ("OPEN", "FILLED"):
            counts["pending"] += 1
            continue
        if status != "CLOSED" or not isinstance(entry.get("net_r"), (int, float)):
            counts["no_fill"] += 1
            continue
        item = (parse_time(entry.get("closed_at")), float(entry["net_r"]))
        rules.append(item)
        arms = by_tf.setdefault(record["timeframe"], {"rules": [], "ki": []})
        arms["rules"].append(item)
        if record.get("decision") == NEHMEN:
            taken.append(item)
            arms["ki"].append(item)
        elif record.get("decision") == AUSLASSEN:
            skipped.append(item)
    ready = len(rules) >= MIN_TRADES
    return {
        "model": model, "prompt_version": prompt_version,
        "counts": counts, "min_trades": MIN_TRADES, "ready": ready,
        "status": "AUSWERTBAR" if ready else f"ZU_WENIG_DATEN ({len(rules)}/{MIN_TRADES})",
        "rules_alone": _arm(rules), "rules_plus_ki": _arm(taken), "ki_skipped": _arm(skipped),
        "by_timeframe": {tf: {"rules_alone": _arm(a["rules"]), "rules_plus_ki": _arm(a["ki"])} for tf, a in sorted(by_tf.items())},
        "note": "Papier. Kein Beleg vor MIN_TRADES; Entscheidung über Echtgeld nur durch Uzi.",
    }
