"""F9: read-only overview of the research workshop for the Forschung screen of the Control Center.

Reads what the workshop writes under ``data/research/`` (idea queue, trade reflections, timetable status,
shadow register, monthly reports). Writes nothing. A broken or missing file shows up as a note, never as
an empty healthy state.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.research_lab.workshop import charter
from src.research_lab.workshop.ideas import STATUSES, IdeaQueue

RESEARCH_DIR = Path("data/research")
OPEN_STATUSES = ("ready", "new", "waiting_data", "waiting_budget")


def _local_month(timestamp: str) -> str:
    moment = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    return moment.astimezone(ZoneInfo(charter.LOCAL_TIMEZONE)).strftime("%Y-%m")


def overview(root: Path | str = ".", now: datetime | None = None) -> dict[str, Any]:
    research = Path(root) / RESEARCH_DIR
    now = now or datetime.now(timezone.utc)
    month = now.astimezone(ZoneInfo(charter.LOCAL_TIMEZONE)).strftime("%Y-%m")
    notes: list[str] = []
    result: dict[str, Any] = {"stage": charter.STAGE, "budget": charter.MONTHLY_STUDY_BUDGET, "month": month,
                              "notes": notes, "ideas": [], "idea_counts": {}, "drafts_this_month": 0,
                              "trades": None, "schedule": {}, "shadows": [], "last_reflection": None}
    try:
        ideas = list(IdeaQueue(research / "IDEEN.jsonl").ideas().values())
        result["idea_counts"] = dict(Counter(i["status"] for i in ideas))
        result["drafts_this_month"] = sum(1 for i in ideas for status, at in i.get("history") or []
                                          if status == "study_draft" and _local_month(at) == month)
        order = {s: n for n, s in enumerate(OPEN_STATUSES)}
        open_ideas = sorted((i for i in ideas if i["status"] in order),
                            key=lambda i: (order[i["status"]], i["created_at"]), reverse=False)
        result["ideas"] = [{"id": i["id"], "title": i["title"], "status": i["status"],
                            "status_text": STATUSES[i["status"]], "source": charter.SOURCES.get(i["source"], i["source"]),
                            "reason": (i.get("reasons") or [""])[0]} for i in open_ideas[:6]]
    except Exception as error:  # noqa: BLE001 - the screen shows it instead of failing
        notes.append(f"Ideen-Liste nicht lesbar: {type(error).__name__}")
    try:
        from src.research_lab.workshop.trade_reflection import LESSONS, ReflectionLog, patterns
        records = ReflectionLog(research / "trade_reflections.jsonl").records()
        found = patterns(records) if records else {"trades": 0, "lessons": {}, "net_r_sum": 0.0}
        top = sorted(((k, v) for k, v in found["lessons"].items() if k != "FULL_TARGET"),
                     key=lambda kv: kv[1]["count"], reverse=True)[:3]
        result["trades"] = {"count": found["trades"], "net_r_sum": found["net_r_sum"],
                            "top": [{"lesson": k, "text": LESSONS.get(k, k), "count": v["count"], "share": v["share"]}
                                    for k, v in top]}
    except Exception as error:  # noqa: BLE001
        notes.append(f"Trade-Reflexionen nicht lesbar: {type(error).__name__}")
    try:
        state_file = research / "schedule/state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
            result["schedule"] = {task: {"last_run": (state.get(task) or {}).get("last_run"),
                                         "ok": ((state.get(task) or {}).get("last_result") or {}).get("ok"),
                                         "held": bool((state.get(task) or {}).get("deferred_since"))}
                                  for task in ("trades", "weekly", "monthly")}
            result["schedule_paused"] = (research / "schedule/PAUSE").exists()
        else:
            notes.append("Zeitplan hat noch keinen Lauf gemeldet")
    except Exception as error:  # noqa: BLE001
        notes.append(f"Zeitplan-Status nicht lesbar: {type(error).__name__}")
    try:
        from src.research_lab.learning.registry import ModelRegister
        from src.research_lab.workshop import shadow
        register_file = Path(root) / shadow.REGISTER_PATH
        if register_file.exists():
            result["shadows"] = shadow.status(ModelRegister(register_file), Path(root) / shadow.SHADOW_DIR)
    except Exception as error:  # noqa: BLE001
        notes.append(f"Schattenbetrieb nicht lesbar: {type(error).__name__}")
    reports = sorted((research / "reports").glob("forschung_*.md")) if (research / "reports").is_dir() else []
    if reports:
        result["last_reflection"] = reports[-1].stem.removeprefix("forschung_")
    return result
