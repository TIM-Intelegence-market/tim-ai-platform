"""Idea check (F2): deterministic gate between an idea and a study draft.

For every open idea it asks, in this order:
1. Would it need archive days from the 2025 holdout?  -> ``holdout_locked``
2. Did TIM already test it (logbook) or close the same idea before?  -> ``already_tested``
3. Are the data it needs available?  -> ``waiting_data``
4. Is a study slot left this month?  -> ``waiting_budget``
Otherwise it is ``ready`` for a study draft (F3). Nothing is computed and no
data are loaded here; the check reads only the logbook, the queue and the
static data catalogue below. Expected case counts are measured later by the
count run of each study (F4), not guessed here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.research_lab.protocol import HOLDOUT_START_MS
from src.research_lab.workshop import charter
from src.research_lab.workshop.ideas import IdeaQueue

HOLDOUT_START = datetime.fromtimestamp(HOLDOUT_START_MS / 1000, tz=timezone.utc).date()
LOGBOOK_PATH = Path("docs/research_lab/LOGBUCH.json")
SIMILARITY_LIMIT = 0.4
OPEN = {"new", "ready", "waiting_data", "waiting_budget"}
CLOSED_AS_TESTED = {"already_tested", "rejected"}


@dataclass(frozen=True)
class DataSource:
    label: str
    archive: bool            # archive data end before the holdout; live data are prospective
    first_day: str | None
    ready: bool
    note: str = ""


# What TIM has. Archive sources stop at the holdout boundary on purpose.
DATA_CATALOGUE: dict[str, DataSource] = {
    "archive_spot_klines": DataSource("Binance Spot-Kerzen (Archiv)", True, "2017-08-17", True),
    "archive_usdm_klines": DataSource("Binance USD-M-Kerzen und Funding (Archiv)", True, "2020-01-01", True),
    "archive_aggtrades_btc": DataSource("BTC aggTrades / S8-Minutenbalken (Archiv)", True, "2020-01-01", True,
                                        "liegt auf dem Mac (S8-Archivlauf)"),
    "cpi_alfred": DataSource("US-CPI Point-in-Time (ALFRED)", True, "2017-01-01", True, "FRED-Schlüssel nur auf dem Mac"),
    "live_orderflow": DataSource("Live-Orderflow-Beobachtungen der Runtime", False, None, True, "nur lesend"),
    "plan_journal": DataSource("Papier-Plan-Journal", False, None, True),
    "perp_live": DataSource("Perp-Trades live (Futures)", False, None, False, "wartet auf F5, Perp-Sammler als Dienst"),
    "orderbook_depth": DataSource("Orderbuch-Tiefe", False, None, False, "S8-Depth-Datenvertrag ist nur Entwurf"),
}

STOPWORDS = {"der", "die", "das", "und", "oder", "mit", "ohne", "auf", "aus", "von", "vom", "zum", "zur", "für", "fur",
             "ein", "eine", "einer", "den", "dem", "des", "im", "in", "an", "am", "als", "bei", "nach", "vor", "ist",
             "wird", "werden", "nur", "nicht", "kein", "keine", "the", "and", "of", "to", "a"}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[0-9a-zäöüß]+", text.lower()) if len(t) >= 2 and t not in STOPWORDS}


def similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def load_logbook(path: Path | str = LOGBOOK_PATH) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("entries") or [])


@dataclass(frozen=True)
class Verdict:
    idea_id: str
    status: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"idea": self.idea_id, "status": self.status, "reasons": list(self.reasons)}


def _local_month(timestamp: str) -> str:
    moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return moment.astimezone(ZoneInfo(charter.LOCAL_TIMEZONE)).strftime("%Y-%m")


def _holdout(idea: Mapping[str, Any]) -> list[str]:
    period = idea.get("period")
    if not period or date.fromisoformat(period[1]) < HOLDOUT_START:
        return []
    archive = [d for d in idea.get("data") or [] if d in DATA_CATALOGUE and DATA_CATALOGUE[d].archive]
    if not archive:
        return []
    return [f"Zeitraum bis {period[1]} läge im Holdout ab {HOLDOUT_START.isoformat()} ({', '.join(archive)}); "
            "Archivdaten ab 2025 lädt TIM nie. Öffnen nur mit Uzis ausdrücklichem Wort."]


def _tested(idea: Mapping[str, Any], logbook: Sequence[Mapping[str, Any]], others: Sequence[Mapping[str, Any]]) -> list[str]:
    if idea.get("derived_from"):
        return []
    mine = tokens(f"{idea['title']} {' '.join(idea.get('tags') or [])}")
    reasons = []
    for entry in logbook:
        score = similarity(mine, tokens(f"{entry.get('id', '')} {entry.get('title', '')}"))
        if score >= SIMILARITY_LIMIT:
            reasons.append(f"ähnlich wie Studie {entry.get('id')} „{entry.get('title')}“ (Status {entry.get('status')}, "
                           f"Ähnlichkeit {score:.2f}); als Ableitung anmelden, wenn bewusst gewollt")
    for other in others:
        if other["id"] == idea["id"] or other["status"] not in CLOSED_AS_TESTED:
            continue
        score = similarity(mine, tokens(f"{other['title']} {' '.join(other.get('tags') or [])}"))
        if score >= SIMILARITY_LIMIT:
            reasons.append(f"ähnlich wie Idee {other['id']} „{other['title']}“ (Status {other['status']}, Ähnlichkeit {score:.2f})")
    return reasons


def _data(idea: Mapping[str, Any]) -> list[str]:
    needs = idea.get("data") or []
    if not needs:
        return ["Datenbedarf fehlt; mindestens eine Quelle aus dem Datenkatalog angeben"]
    reasons = []
    for need in needs:
        source = DATA_CATALOGUE.get(need)
        if source is None:
            reasons.append(f"unbekannte Datenquelle {need!r}; erlaubt: {', '.join(sorted(DATA_CATALOGUE))}")
        elif not source.ready:
            reasons.append(f"{source.label}: noch nicht vorhanden ({source.note})")
        elif source.first_day and idea.get("period") and idea["period"][0] < source.first_day:
            reasons.append(f"{source.label} beginnt erst am {source.first_day}")
    return reasons


def check_ideas(queue: IdeaQueue, logbook: Sequence[Mapping[str, Any]], *, now: str) -> list[Verdict]:
    ideas = queue.ideas()
    month = _local_month(now)
    used = sum(1 for idea in ideas.values() for status, at in idea["history"]
               if status == "study_draft" and _local_month(at) == month)
    free = max(charter.MONTHLY_STUDY_BUDGET - used, 0)
    verdicts = []
    for idea in sorted(ideas.values(), key=lambda i: i["id"]):
        if idea["status"] not in OPEN:
            continue
        for status, reasons in (("holdout_locked", _holdout(idea)),
                                ("already_tested", _tested(idea, logbook, list(ideas.values()))),
                                ("waiting_data", _data(idea))):
            if reasons:
                verdicts.append(Verdict(idea["id"], status, tuple(reasons)))
                break
        else:
            if free > 0:
                free -= 1
                note = [f"offen als Ableitung von {idea['derived_from']} deklariert; Vorbelastung im Entwurf nennen"] \
                    if idea.get("derived_from") else []
                verdicts.append(Verdict(idea["id"], "ready", tuple(note)))
            else:
                verdicts.append(Verdict(idea["id"], "waiting_budget",
                                        (f"Budget {charter.MONTHLY_STUDY_BUDGET} Studien im Monat {month} ist verbraucht",)))
    return verdicts


def record(queue: IdeaQueue, verdicts: Sequence[Verdict], *, now: str) -> int:
    """Writes only changed verdicts; returns how many lines were appended."""
    ideas = queue.ideas()
    written = 0
    for verdict in verdicts:
        idea = ideas[verdict.idea_id]
        if idea["status"] == verdict.status and list(idea["reasons"]) == list(verdict.reasons):
            continue
        queue.set_status(verdict.idea_id, verdict.status, verdict.reasons, at=now)
        written += 1
    return written
