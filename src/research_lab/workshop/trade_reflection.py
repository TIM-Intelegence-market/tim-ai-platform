"""Trade reflection: TIM looks back at every closed paper trade (Uzi, 31.10.2026).

For each CLOSED, non-excluded entry of a plan journal the reflection writes one
record with the facts of the trade and the lessons that the facts show, from a
fixed rule set (READING). It states only what was observed; it makes no
counterfactual claim ("with a wider stop it would have won") and changes no
rule, stop, target or cost. Records are append-only with a hash chain, one per
trade; a trade is never reflected twice.

When a lesson repeats often enough over enough trades, it becomes an idea in
the research workshop's idea queue. That is the only way a reflection can lead
to a change: idea -> check -> pre-registered study -> prospective test.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.research_lab.workshop.ideas import IdeaQueue

RULES_VERSION = "trade-reflection/1.0"
DEFAULT_PATH = Path("data/research/trade_reflections.jsonl")
GENESIS = "0" * 64

# Thresholds are fixed here, not tuned on the journal.
GAVE_BACK_MFE_R = 1.0         # was at least 1 R in profit ...
INSTANT_MAE_R = -0.8          # ... or ran almost straight to the stop
INSTANT_MFE_R = 0.3
FLAT_NET_R = 0.05             # |net| below this counts as "about zero"
IDEA_MIN_TRADES = 20          # a pattern needs at least this many reflected trades ...
IDEA_MIN_SHARE = 0.30         # ... and must appear in at least this share of them

LESSONS = {
    "COSTS_ATE_PROFIT": "Brutto im Plus, netto nicht: Kosten haben den Gewinn aufgefressen.",
    "GAVE_BACK": "War mindestens 1 R im Plus und endete ohne Gewinn.",
    "WRONG_AT_ONCE": "Lief fast sofort gegen den Plan (kaum Plus, fast voller Stop).",
    "STOP_BY_WICK": "Stop nur per Docht: der Kurs schloss danach wieder auf der Seite des Trades.",
    "AGAINST_TREND": "Trade gegen TIMs Marktzustand.",
    "TIMEOUT": "Nach der Höchstdauer ohne Entscheidung beendet.",
    "INVALIDATED": "Plan durch Schluss jenseits der Ungültigkeitsmarke beendet.",
    "FULL_TARGET": "Alle drei Ziele erreicht.",
    "DATA_GAP": "Während des Trades fehlten Kerzen; das Ergebnis ist unsicher.",
}


class ReflectionError(ValueError):
    pass


def _digest(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def _f(entry: Mapping[str, Any], key: str) -> float:
    value = entry.get(key)
    return float(value) if value is not None else 0.0


def reflect(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Facts and lessons of one closed trade. Pure: the entry is not changed."""
    from src.dashboard.plan_journal import counter_trend  # read-only helper, imported lazily

    net, gross = _f(entry, "net_r"), _f(entry, "gross_r")
    cost = _f(entry, "fee_r") + _f(entry, "slippage_r")
    mfe, mae = _f(entry, "max_favorable_r"), _f(entry, "max_adverse_r")
    exit_reason = str(entry.get("exit_reason") or "")
    lessons = []
    if gross > 0 and net <= 0:
        lessons.append("COSTS_ATE_PROFIT")
    if mfe >= GAVE_BACK_MFE_R and net <= 0:
        lessons.append("GAVE_BACK")
    if mae <= INSTANT_MAE_R and mfe < INSTANT_MFE_R:
        lessons.append("WRONG_AT_ONCE")
    if (entry.get("stop_review") or {}).get("wick"):
        lessons.append("STOP_BY_WICK")
    if counter_trend(entry.get("direction"), entry.get("market_state")):
        lessons.append("AGAINST_TREND")
    if exit_reason == "TIMEOUT":
        lessons.append("TIMEOUT")
    if exit_reason == "INVALIDATION":
        lessons.append("INVALIDATED")
    if exit_reason == "TP3":
        lessons.append("FULL_TARGET")
    if entry.get("data_gap"):
        lessons.append("DATA_GAP")
    outcome = "win" if net >= FLAT_NET_R else "loss" if net <= -FLAT_NET_R else "flat"
    word = {"win": "Gewinn", "loss": "Verlust", "flat": "etwa null"}[outcome]
    summary = (f"{entry.get('direction')} {entry.get('timeframe', '30m')}: {word} {net:+.2f} R netto "
               f"(brutto {gross:+.2f} R, Kosten {cost:.2f} R), bestes Plus {mfe:+.2f} R, tiefstes Minus {mae:+.2f} R, "
               f"Ausstieg {exit_reason or '—'}, {len(entry.get('tp_hits') or [])} von 3 Zielen.")
    return {
        "trade_id": entry["id"], "timeframe": entry.get("timeframe", "30m"), "direction": entry.get("direction"),
        "scenario_type": entry.get("scenario_type"), "setup_grade": entry.get("setup_grade"),
        "created_at": entry.get("created_at"), "closed_at": entry.get("closed_at"),
        "facts": {"net_r": net, "gross_r": gross, "cost_r": round(cost, 4), "mfe_r": mfe, "mae_r": mae,
                  "exit_reason": exit_reason, "targets_hit": len(entry.get("tp_hits") or []),
                  "tim_verdict": entry.get("tim_verdict"), "market_state": entry.get("market_state")},
        "outcome": outcome, "lessons": lessons, "summary": summary,
        "lesson_text": [LESSONS[k] for k in lessons], "rules": RULES_VERSION, "automatic_rule_change": False,
    }


class ReflectionLog:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        previous = GENESIS
        for number, record in enumerate(records, 1):
            body = {k: v for k, v in record.items() if k != "hash"}
            if body.get("previous") != previous or record.get("hash") != _digest(previous, body):
                raise ReflectionError(f"Hash-Kette in {self.path} bricht in Zeile {number}")
            previous = record["hash"]
        return records

    def append(self, reflections: Iterable[Mapping[str, Any]], *, journal: str, at: str) -> list[str]:
        records = self.records()
        seen = {(r["journal"], r["trade_id"]) for r in records}
        previous = records[-1]["hash"] if records else GENESIS
        written, lines = [], []
        for reflection in reflections:
            if (journal, reflection["trade_id"]) in seen:
                continue
            body = {**reflection, "journal": journal, "reflected_at": at, "previous": previous}
            record = {**body, "hash": _digest(previous, body)}
            lines.append(json.dumps(record, sort_keys=True, ensure_ascii=False))
            previous = record["hash"]
            seen.add((journal, reflection["trade_id"]))
            written.append(reflection["trade_id"])
        if lines:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        return written


def closed_trades(journal: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [e for e in journal.get("entries") or []
            if e.get("status") == "CLOSED" and not e.get("excluded") and e.get("net_r") is not None]


def reflect_journal(journal: Mapping[str, Any], log: ReflectionLog, *, name: str, at: str | None = None,
                    write: bool = True) -> list[dict[str, Any]]:
    """Reflects every closed trade not reflected yet. The journal is only read."""
    at = at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    done = {r["trade_id"] for r in log.records() if r["journal"] == name}
    fresh = [reflect(e) for e in closed_trades(journal) if e["id"] not in done]
    if write and fresh:
        log.append(fresh, journal=name, at=at)
    return fresh


def patterns(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(records)
    counts = Counter(lesson for r in records for lesson in r["lessons"])
    n = len(records)
    return {"trades": n, "lessons": {k: {"count": c, "share": round(c / n, 3)} for k, c in sorted(counts.items())},
            "net_r_sum": round(sum(r["facts"]["net_r"] for r in records), 4)}


def propose_ideas(records: Iterable[Mapping[str, Any]], queue: IdeaQueue, *, at: str | None = None) -> list[str]:
    """A loss-side lesson that repeats in >= 30 % of >= 20 trades becomes one idea per journal and lesson."""
    by_journal: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        by_journal.setdefault(record["journal"], []).append(record)
    added = []
    for journal, mine in sorted(by_journal.items()):
        stats = patterns(mine)
        if stats["trades"] < IDEA_MIN_TRADES:
            continue
        for lesson, value in stats["lessons"].items():
            if lesson == "FULL_TARGET" or value["share"] < IDEA_MIN_SHARE:
                continue
            idea_id = queue.add(
                source="trade_reflexion",
                title=f"Trade-Reflexion {journal}: {lesson}",
                hypothesis=(f"In {journal} zeigt sich bei {value['count']} von {stats['trades']} Trades: {LESSONS[lesson]} "
                            "Eine Regeländerung dagegen verbessert das Netto-Ergebnis auf neuen Daten."),
                data=["plan_journal", "archive_spot_klines"], tags=[lesson.lower(), "trade-reflexion"],
                template="regel_backtest",
                counterargument="Muster aus wenigen, überlappenden Papier-Trades; die Abhilfe muss auf Archiv und frischen Daten bestehen.",
                source_ref=f"trade_reflexion:{journal}:{lesson}", at=at,
            )
            if idea_id:
                added.append(idea_id)
    return added
