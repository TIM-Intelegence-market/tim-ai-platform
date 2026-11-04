"""Wochenbericht der Lernschleife: Sonntags ein kurzer Bericht an Uzi, höchstens eine Ja/Nein-Frage.

Uzi, 04.11.2026 ("go" zu Vorschlag 2): TIM wertet jede Woche selbst alle Papier-Journale aus, schlägt
höchstens einen Filter vor, rechnet ihn nach, und Uzi sagt nur ja oder nein.

Die Rechenarbeit macht F11 (``self_improve``): vier feste Filter aus den Trade-Lehren, Rückblick, 30 Tage
Vorwärtsfenster, ein Urteil mit Bonferroni-Bootstrap. Dieses Modul fasst das Ergebnis der Wochenrunde
zusammen und legt Uzi **höchstens einen** Filter zur Entscheidung vor: einen, der sein Vorwärtsfenster
bestanden hat und noch nicht entschieden ist. Alles andere steht nur zur Information im Bericht.

Uzis Antwort wird mit ``record_decision`` im Lern-Log festgehalten (Hash-Kette). Ein Ja ändert TIM nicht
von selbst: Es ist der Auftrag, den Filter per Pull Request ins Papier-Journal einzubauen. Ein Nein beendet
den Filter für diese Fassung. Keine Daten ab 2025 als Holdout, kein Echtgeld.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from src.research_lab.workshop import self_improve as si

VERSION = "wochenbericht/1.0"
ANSWERS = ("ja", "nein")
JOURNAL_LABELS = {
    "tim_plan_journal": "TIM 30m", "tim_plan_journal_struct": "Struktur 30m", "tim_plan_journal_short": "15m",
    "tim_plan_journal_mid": "1h", "tim_plan_journal_long": "1d", "tim_plan_journal_vp": "VP 30m",
}
STATUS_WORDS = {
    "beobachtung": "wird beobachtet",
    "bestanden": "bestanden",
    "nicht_bestanden": "nicht bestanden",
    "zu_wenig": "zu wenige neue Trades, neues Fenster",
    "rueckblick_dagegen": "Rückblick spricht dagegen (gestrichene Trades lagen im Plus)",
    "trifft_fast_alle": "würde fast alle Trades streichen, kein sinnvoller Filter",
    "beobachtet nicht": "noch kein Anlass",
    "uebernommen": "von Uzi angenommen, Einbau per PR",
    "abgelehnt": "von Uzi abgelehnt",
}


def _r(value: float) -> str:
    return f"{value:+.2f}".replace(".", ",") + " R"


def _date(value: str) -> str:
    moment = si._time(value).astimezone(_local())
    return moment.strftime("%d.%m.")


def _local():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Europe/Berlin")


def decisions(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Uzi's answer per filter (the filter's current hash only; a changed filter is a new question)."""
    out: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event") == "decision" and event.get("filter") in si.FILTERS \
                and event.get("filter_hash") == si.filter_hash(event["filter"]):
            out[event["filter"]] = dict(event)
    return out


def passed(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Filters with a passed forward verdict, with that verdict."""
    out = {}
    for key, history in si.windows(events).items():
        for window in history:
            if window["verdict"] and window["verdict"].get("verdict") == "bestanden":
                out[key] = window["verdict"]
    return out


def record_decision(log: si.LearningLog, key: str, answer: str, *, by: str, reference: str,
                    at: datetime) -> dict[str, Any]:
    """Write Uzi's yes or no. Only a passed, undecided filter can be decided; nothing in TIM changes here."""
    answer = answer.strip().lower()
    if key not in si.FILTERS:
        raise ValueError(f"unbekannter Filter {key!r}")
    if answer not in ANSWERS:
        raise ValueError("Antwort muss ja oder nein sein")
    if not reference.strip():
        raise ValueError("Beleg fehlt (wo und wann Uzi geantwortet hat)")
    events = log.events()
    if key not in passed(events):
        raise ValueError(f"{key} hat kein bestandenes Vorwärtsfenster, es gibt nichts zu entscheiden")
    if key in decisions(events):
        raise ValueError(f"{key} ist schon entschieden ({decisions(events)[key]['answer']})")
    return log.append({"event": "decision", "filter": key, "filter_hash": si.filter_hash(key), "answer": answer,
                       "by": by, "reference": reference.strip(), "at": si._iso(at), "changes_tim": False,
                       "next": "Pull Request: Filter ins Papier-Journal einbauen" if answer == "ja" else "keiner"})


def proposal(events: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """At most one filter for Uzi: passed and undecided; the one whose dropped trades lost most per trade."""
    open_ = {k: v for k, v in passed(events).items() if k not in decisions(events)}
    if not open_:
        return None
    key = min(sorted(open_), key=lambda k: open_[k]["figures"]["dropped_mean_r"])
    figures = open_[key]["figures"]
    return {"filter": key, "text": si.FILTERS[key].text, "figures": figures, "waiting": sorted(set(open_) - {key})}


def build(journals: Mapping[str, Mapping[str, Any]], learning: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
          now: datetime) -> dict[str, Any]:
    """The week in numbers. ``learning`` is the report of ``self_improve.step`` from the same round."""
    since = now - timedelta(days=7)
    trades = si.closed(journals)
    rows = []
    for name in journals:
        mine = [t for t in trades if t["_journal"] == name]
        week = [t for t in mine if t.get("closed_at") and since <= si._time(t["closed_at"]) < now]
        rows.append({"journal": name, "label": JOURNAL_LABELS.get(name, name), "closed": len(mine),
                     "net_r": round(sum(float(t["net_r"]) for t in mine), 3), "week_closed": len(week),
                     "week_net_r": round(sum(float(t["net_r"]) for t in week), 3)})
    decided = decisions(events)
    open_windows = si.windows(events)
    filters = []
    for key, item in (learning.get("filters") or {}).items():
        state = item.get("status", "beobachtet nicht")
        if key in decided:
            state = "uebernommen" if decided[key]["answer"] == "ja" else "abgelehnt"
        line = {"filter": key, "text": item.get("text", ""), "status": state,
                "lookback": item.get("lookback") or {}}
        history = open_windows.get(key) or []
        if state == "beobachtung" and history and history[-1]["verdict"] is None:
            start, end = si._time(history[-1]["start"]), si._time(history[-1]["end"])
            line["window_end"] = history[-1]["end"]
            line["fresh"] = sum(1 for t in trades if t.get("created_at") and start <= si._time(t["created_at"]) < end)
        filters.append(line)
    year, week, _ = now.astimezone(_local()).isocalendar()
    return {"version": VERSION, "week": f"{year}-W{week:02d}", "at": si._iso(now), "journals": rows,
            "trades": len(trades), "week_trades": sum(r["week_closed"] for r in rows),
            "week_net_r": round(sum(r["week_net_r"] for r in rows), 3), "filters": filters,
            "proposal": proposal(events), "changes_tim": False}


def render(report: Mapping[str, Any]) -> str:
    """Short German text for Uzi (fits a phone screen)."""
    lines = [f"# TIM lernt: Woche {report['week']}", ""]
    lines.append(f"Diese Woche {report['week_trades']} Papier-Trades geschlossen, zusammen {_r(report['week_net_r'])} "
                 f"nach Kosten. Insgesamt {report['trades']} Trades ausgewertet.")
    lines.append("")
    for row in report["journals"]:
        if row["closed"]:
            lines.append(f"- {row['label']}: Woche {row['week_closed']} Trades {_r(row['week_net_r'])}, "
                         f"gesamt {row['closed']} Trades {_r(row['net_r'])}")
    lines.append("")
    pick = report.get("proposal")
    if pick:
        f = pick["figures"]
        lines.append(f"**Deine Entscheidung (ja/nein):** Filter „{pick['text']}“ ins Papier-Journal übernehmen?")
        lines.append(f"Nachgerechnet auf {f['trades']} neuen Trades nach dem Start: die {f['dropped']} gestrichenen "
                     f"Trades brachten {_r(f['dropped_net_r'])} ({_r(f['dropped_mean_r'])} je Trade, Band "
                     f"{_r(f['interval'][0])} bis {_r(f['interval'][1])}, Glückstest mit Bonferroni bestanden).")
        lines.append("Ja = TIM baut den Filter per PR ins Papier-Journal ein (kein Echtgeld). Nein = Filter ist erledigt.")
        if pick["waiting"]:
            lines.append(f"Danach warten noch: {', '.join(pick['waiting'])}.")
    else:
        lines.append("**Keine Entscheidung nötig.** Kein Filter hat diese Woche seinen Test bestanden.")
    lines.append("")
    lines.append("Filter im Test:")
    for line in report["filters"]:
        detail = STATUS_WORDS.get(line["status"], line["status"])
        if line.get("window_end"):
            detail += f" bis {_date(line['window_end'])}, {line.get('fresh', 0)} neue Trades bisher"
        look = line["lookback"]
        if look.get("dropped"):
            detail += f" (Rückblick: {look['dropped']} gestrichen, {_r(look['dropped_net_r'])})"
        lines.append(f"- {line['text']}: {detail}")
    lines.append("")
    lines.append("Nur Papier. TIM ändert nichts ohne dein Ja; Holdout 2025 bleibt gesperrt.")
    return "\n".join(lines) + "\n"
