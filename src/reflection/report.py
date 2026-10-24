"""Builds the weekly reflection report and at most one rule proposal.

The report is deterministic: the same cases give the same bytes and the same
hash. A proposal is text for a human; it is never applied by code.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Sequence

from .reader import ReflectionCase
from .scorecard import ALPHA, MIN_SAMPLE, READING_VERSION, RuleScore, score

LABEL = "TIM_REFLECTION"
STATUS = "VORSCHLAG, nicht aktiv"
NOTE = (
    "Rückblick auf nachgeprüfte Beobachtungen. Keine Prognose, kein Signal, keine Regeländerung. "
    "Basisrate = alle übrigen Regeln derselben Woche. Fälle eines Fensters überlappen sich, "
    "p-Werte sind deshalb eher zu günstig."
)


def iso_week_window(week: str) -> tuple[datetime, datetime]:
    """'2026-W48' -> Monday 00:00 UTC to the next Monday 00:00 UTC."""
    try:
        year_text, week_text = week.split("-W")
        monday = date.fromisocalendar(int(year_text), int(week_text), 1)
    except (ValueError, TypeError):
        raise ValueError(f"week must look like 2026-W48, got {week!r}") from None
    start = datetime.combine(monday, time(0), tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def previous_iso_week(now: datetime) -> str:
    """The last fully finished ISO week before ``now``."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    year, week, _ = (now.astimezone(timezone.utc).date() - timedelta(days=7)).isocalendar()
    return f"{year}-W{week:02d}"


def _percent(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f} %".replace(".", ",")


def _proposal(scores: Sequence[RuleScore]) -> dict[str, Any] | None:
    candidates = []
    for item in scores:
        if item.significant_above:
            candidates.append((item.p_above, item.kind, "above", item))
        if item.significant_below:
            candidates.append((item.p_below, item.kind, "below", item))
    if not candidates:
        return None
    p_value, kind, side, item = sorted(candidates, key=lambda entry: (entry[0], entry[1], entry[2]))[0]
    facts = (
        f"{kind} (Lesart {item.reading}) traf in {_percent(item.hit_rate)} der Fälle, "
        f"Basisrate {_percent(item.base_rate)}, n = {item.sample_size}, p nach Holm-Korrektur unter {str(ALPHA).replace('.', ',')}."
    )
    if side == "above":
        text = (
            f"{facts} Vorschlag: Die Regel als Hypothese im Research Lab auf der Binance-Historie prüfen "
            "(nur Training und Validierung). Hält der Vorteil dort, über eine neue Regelversion per PR entscheiden."
        )
        question = "Hält der Vorteil auf einer getrennten Historie, die diese Woche nicht enthält?"
    else:
        text = (
            f"{facts} Vorschlag: Prüfen, ob die Lesart {item.reading} falsch ist oder die Regel nichts aussagt. "
            "Erst im Research Lab (Training und Validierung) testen, dann über Umbau oder Rückbau per PR entscheiden."
        )
        question = "Liegt der Fehler in der Regel selbst oder in der festen Lesart der Reflexion?"
    return {
        "status": STATUS,
        "kind": kind,
        "direction": side,
        "p_value": round(p_value, 6),
        "text": text,
        "question": question,
        "automatic_rule_change": False,
    }


def build_report(
    week: str,
    cases: Sequence[ReflectionCase],
    previous_cases: Sequence[ReflectionCase] = (),
    *,
    source: str,
) -> dict[str, Any]:
    start, end = iso_week_window(week)
    outside = [case.observation_id for case in cases if not start <= case.observed_at < end or case.validated_through > end]
    if outside:
        raise ValueError(f"{len(outside)} cases lie outside the window or were not known by its end")
    scores = score(cases, previous_cases)
    proposal = _proposal(scores)
    report: dict[str, Any] = {
        "label": LABEL,
        "week": week,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "source": source,
        "reading_version": READING_VERSION,
        "rule_versions": sorted({case.rule_version for case in cases}),
        "min_sample": MIN_SAMPLE,
        "alpha": ALPHA,
        "case_count": len(cases),
        "previous_case_count": len(previous_cases),
        "symbols": sorted({case.symbol for case in cases}),
        "rules": [item.to_dict() for item in scores],
        "proposal": proposal,
        "no_proposal_reason": None if proposal else (
            "Keine Regel weicht nach Holm-Korrektur von der Basisrate ab."
            if any(item.sufficient for item in scores)
            else f"Keine Regel hat genug Fälle (mindestens {MIN_SAMPLE})."
        ),
        "automatic_rule_change": False,
        "note": NOTE,
    }
    report["report_hash"] = report_hash(report)
    return report


def report_hash(report: dict[str, Any]) -> str:
    body = {key: value for key, value in report.items() if key != "report_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# TIM-Reflexion {report['week']}",
        "",
        f"Fenster {report['window']['start']} bis {report['window']['end']} (UTC), Quelle: {report['source']}.",
        f"{report['case_count']} nachgeprüfte Fälle, Vorwoche {report['previous_case_count']}. "
        f"Lesart {report['reading_version']}, Regelversionen {', '.join(report['rule_versions']) or '–'}.",
        "",
        "## Vorschlag",
        "",
    ]
    proposal = report["proposal"]
    if proposal:
        lines += [f"**{proposal['status']}.** {proposal['text']}", "", f"Offene Frage: {proposal['question']}"]
    else:
        lines += [f"Kein Vorschlag. {report['no_proposal_reason']}"]
    lines += [
        "",
        "## Regeln gegen Basisrate",
        "",
        "| Regel | Lesart | n | Treffer | Basisrate | 95 %-Band | 5 / 15 / 30 min | Vorwoche | Fehler: Gegenrichtung / seitwärts | Befund |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rule in report["rules"]:
        band = "–" if rule["interval_95"] is None else f"{_percent(rule['interval_95'][0])} bis {_percent(rule['interval_95'][1])}"
        horizons = " / ".join(_percent(rule["horizon_hit_rates"][key]) for key in ("5", "15", "30"))
        if not rule["sufficient"]:
            verdict = f"zu wenig Daten (unter {report['min_sample']})"
        elif rule["significant_above"]:
            verdict = "über Basisrate"
        elif rule["significant_below"]:
            verdict = "unter Basisrate"
        else:
            verdict = "kein Unterschied"
        previous = rule["previous_week"]
        lines.append(
            f"| {rule['kind']} | {rule['reading']} | {rule['sample_size']} | {_percent(rule['hit_rate'])} | "
            f"{_percent(rule['base_rate'])} | {band} | {horizons} | {_percent(previous['hit_rate'])} (n={previous['sample_size']}) | "
            f"{rule['misses']['opposite']} / {rule['misses']['sideways']} | {verdict} |"
        )
    lines += ["", report["note"], "", f"Bericht-Hash: `{report['report_hash']}`", ""]
    return "\n".join(lines)
