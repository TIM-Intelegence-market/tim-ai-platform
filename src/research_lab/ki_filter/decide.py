"""Ask the local AI about every new plan and write the answer before the outcome is known.

A plan is judged only while it is OPEN (not filled, not closed) and was created at most
DECIDE_WINDOW ago. A failed AI call writes nothing; the next run tries again while the window lasts.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.research_lab.ki_filter import DECISIONS, PROMPT_VERSION, SCHEMA
from src.research_lab.ki_filter.context import (history_context, market_context, parse_time,
                                                peers_context, plan_context)

UTC = timezone.utc
DECIDE_WINDOW = timedelta(minutes=20)
REASON_MAX = 500
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"entscheidung": {"type": "string", "enum": list(DECISIONS)},
                   "vertrauen": {"type": "number", "minimum": 0, "maximum": 1},
                   "grund": {"type": "string", "maxLength": REASON_MAX}},
    "required": ["entscheidung", "vertrauen", "grund"],
}
INSTRUCTIONS = """Du bist ein erfahrener BTC-Orderflow-Trader und prüfst einen Plan von TIM, bevor er gehandelt wird.
Antworte NEHMEN, wenn der Plan nach Marktlage, Orderflow (Delta, Volumen), Lage der anderen TIM-Strategien und
bisherigen Ergebnissen gute Chancen nach Kosten hat. Sonst AUSLASSEN. Kosten pro Trade liegen bei etwa 0,1 bis 0,2 R.
Du siehst nur Daten bis zum Zeitpunkt des Plans. Erfinde nichts. Gib Vertrauen 0 bis 1 und einen kurzen Grund auf Deutsch.
Antworte nur mit JSON."""


class LogError(Exception):
    pass


def _canonical(record: Mapping[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def read_log(path: Path) -> list[dict[str, Any]]:
    """All records, with the hash chain checked. A broken chain raises: never a silently shorter log."""
    if not path.exists():
        return []
    records, previous = [], None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise LogError(f"ki filter log unreadable at line {number}") from None
        if not isinstance(record, dict):
            raise LogError(f"ki filter log unreadable at line {number}")
        claimed = record.pop("hash", None)
        if record.get("prev_hash") != previous or hashlib.sha256(_canonical(record).encode()).hexdigest() != claimed:
            raise LogError(f"ki filter log broken at line {number}")
        record["hash"] = claimed
        previous = claimed
        records.append(record)
    _check_head(path, records)
    return records


def head_path(path: Path) -> Path:
    return path.with_name(path.name + ".head")


def _check_head(path: Path, records: list[dict[str, Any]]) -> None:
    """The head file names the last written record (count and hash). A shortened or replaced log no longer
    contains it. It does not stop someone who rewrites log and head together; the run summary prints the
    head so it can be kept elsewhere (evidence file)."""
    head = head_path(path)
    if not head.exists():
        if records:
            raise LogError("ki filter log without head file")
        return
    try:
        data = json.loads(head.read_text(encoding="utf-8"))
        count, digest = int(data["count"]), str(data["hash"])
    except (ValueError, KeyError, TypeError):
        raise LogError("ki filter head file unreadable") from None
    if count > len(records) or (count and records[count - 1]["hash"] != digest) or (count == 0 and records):
        raise LogError("ki filter log does not contain its recorded head (shortened or replaced)")


def _write_head(path: Path, records: list[dict[str, Any]]) -> None:
    head = head_path(path)
    temporary = head.with_name(head.name + ".tmp")
    temporary.write_text(json.dumps({"count": len(records), "hash": records[-1]["hash"]}) + "\n", encoding="utf-8")
    os.replace(temporary, head)


def append_log(path: Path, record: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    body = dict(record)
    body["prev_hash"] = records[-1]["hash"] if records else None
    body["hash"] = hashlib.sha256(_canonical(body).encode()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical(body) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    records.append(body)
    _write_head(path, records)
    return body


def build_context(entry: Mapping[str, Any], entries: Sequence[Mapping[str, Any]],
                  peers: Mapping[str, Sequence[Mapping[str, Any]]], candles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cutoff = parse_time(entry.get("created_at"))
    if cutoff is None:
        raise ValueError("plan without created_at")
    timeframe = str(entry.get("timeframe") or "15m")
    return {"plan": plan_context(entry), "history": history_context(entries, cutoff),
            "other_strategies": peers_context(peers, cutoff), "market": market_context(candles, cutoff, timeframe)}


def build_prompt(context: Mapping[str, Any]) -> str:
    return INSTRUCTIONS + "\n\nDATEN:\n" + json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)


def check_answer(answer: Any) -> tuple[str, float, str]:
    if not isinstance(answer, dict) or answer.get("entscheidung") not in DECISIONS:
        raise ValueError("answer without a valid entscheidung")
    confidence = answer.get("vertrauen")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("answer without a valid vertrauen")
    return answer["entscheidung"], float(confidence), str(answer.get("grund") or "")[:REASON_MAX]


def candidates(entries: Sequence[Mapping[str, Any]], decided: set[str], now: datetime) -> list[Mapping[str, Any]]:
    out = []
    for entry in entries:
        created = parse_time(entry.get("created_at"))
        if (entry.get("status") != "OPEN" or entry.get("filled_at") or entry.get("excluded") or created is None
                or not entry.get("id") or entry["id"] in decided or not timedelta(0) <= now - created <= DECIDE_WINDOW):
            continue
        out.append(entry)
    return out


def run(journals: Mapping[str, Mapping[str, Any]], peers: Mapping[str, Mapping[str, Any]], log_path: Path,
        ask: Callable[[str], Any], model: str, market: Callable[[str, str, datetime], Sequence[Mapping[str, Any]]],
        now: datetime | None = None, clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """One pass. ``journals``: timeframe -> journal view to judge; ``peers``: name -> other journal views."""
    now = now or datetime.now(UTC)
    records = read_log(log_path)
    decided = {r["plan_id"] for r in records}
    peer_entries = {name: list(view.get("entries") or []) for name, view in peers.items()}
    summary = {"decided": 0, "failed": 0, "skipped_blocked": 0}
    for timeframe, view in journals.items():
        if view.get("blocked"):
            summary["skipped_blocked"] += 1
            continue
        entries = list(view.get("entries") or [])
        for entry in candidates(entries, decided, now):
            cutoff = parse_time(entry["created_at"])
            try:
                candles = market(str(entry.get("symbol") or "BTCUSDT"), timeframe, cutoff)
                context = build_context(entry, entries, {k: v for k, v in peer_entries.items() if k != timeframe}, candles)
                prompt = build_prompt(context)
                decision, confidence, reason = check_answer(ask(prompt))
            except Exception as error:  # the AI or the database failed: nothing is written, retry next run
                summary["failed"] += 1
                summary.setdefault("errors", []).append(f"{entry['id']}: {type(error).__name__}")
                continue
            append_log(log_path, {
                "schema": SCHEMA, "prompt_version": PROMPT_VERSION, "model": model, "plan_id": entry["id"],
                "timeframe": timeframe, "direction": entry.get("direction"), "plan_created_at": entry["created_at"],
                "decided_at": now.isoformat().replace("+00:00", "Z"), "plan_status_at_decision": entry.get("status"),
                "context_hash": hashlib.sha256(prompt.encode()).hexdigest(), "market_candles": context["market"].get("candles", 0),
                "decision": decision, "confidence": round(confidence, 3), "reason": reason, "context": context,
                "written_at": (clock() if clock else datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
            }, records)
            decided.add(entry["id"])
            summary["decided"] += 1
    if records:
        summary["head"] = {"count": len(records), "hash": records[-1]["hash"]}
    return summary
