"""German UI labels for the dashboard.

The page builders keep their English source labels; ``translate_html`` replaces
exact text nodes of the final HTML with the German label from ``DE``. Only whole
text nodes are touched, never attributes, JSON APIs or data values that merely
contain a word. Text inside <script>/<style> and inside data containers
(<td>, <dd>, <pre>, <code>, <option> and elements with class ``mono``) is never
translated, so stored values that happen to equal a label stay as they are.
"""

from __future__ import annotations

import html
import re

DE: dict[str, str] = {
    # Navigation & page titles
    "Overview": "Überblick",
    "Observations": "Beobachtungen",
    "Research Cases": "Research-Fälle",
    "Signal Research": "Signal-Research",
    "Analytics": "Analysen",
    "Insights": "Erkenntnisse",
    "Health Center": "Systemzustand",
    "Data Quality Exceptions": "Datenqualitäts-Ausnahmen",
    "Timeline": "Zeitleiste",
    "Research": "Forschung",
    "TIM Research Dashboard": "TIM Research-Dashboard",
    "Research Overview": "Research-Überblick",
    "Research Overview · deterministischer Systemzustand und aktuelle Research-Aktivität.": "Deterministischer Systemzustand und aktuelle Research-Aktivität.",
    "Observation Explorer": "Beobachtungen",
    "Research Case Explorer": "Research-Fälle",
    "Orderflow Research": "Orderflow-Research",
    "Research Analytics": "Research-Analysen",
    "Research Insights": "Research-Erkenntnisse",
    "System Timeline": "Systemzeitleiste",
    "Research Workspace": "Recherche-Werkzeug",
    "Research Workspace öffnen →": "Recherche-Werkzeug öffnen →",
    # Overview
    "Scientific Data Progress & V2 Readiness": "Wissenschaftlicher Datenfortschritt und V2-Bereitschaft",
    "Market Status": "Marktstatus",
    "Active Observations": "Aktive Beobachtungen",
    "Research Cases & Missing Evidence": "Research-Fälle und fehlende Belege",
    "News": "Nachrichten",
    "Research Module": "Research-Modul",
    "Acceptance Countdown": "Acceptance-Countdown",
    "Data Quality": "Datenqualität",
    "Stream Status": "Stream-Status",
    "Validator Status": "Validator-Status",
    "Runtime": "Laufzeit",
    "Active Research Cases": "Aktive Research-Fälle",
    "Closed Research Cases": "Abgeschlossene Research-Fälle",
    "Completed Research Cases": "Abgeschlossene Research-Fälle",
    "Abgeschlossene Research Cases": "Abgeschlossene Research-Fälle",
    "Abgeschlossene Research Cases:": "Abgeschlossene Research-Fälle:",
    "Candles (sichtbar)": "Kerzen (sichtbar)",
    "Dashboard Version": "Dashboard-Version",
    "Read-only Research UI": "Nur-Lese-Oberfläche",
    "Sichtbare Observations": "Sichtbare Beobachtungen",
    "· Sichtbare Observations:": "· Sichtbare Beobachtungen:",
    "· Sichtbare Cases:": "· Sichtbare Fälle:",
    "sichtbarer letzter Ausschnitt, keine Gesamtzahlen. Sichtbare Candles:": "sichtbarer letzter Ausschnitt, keine Gesamtzahlen. Sichtbare Kerzen:",
    "Offene Cases": "Offene Fälle",
    "Validierte Cases": "Validierte Fälle",
    "Neue Continuous Coverage": "Neue durchgehende Abdeckung",
    "Cases pro Stunde": "Fälle pro Stunde",
    "Cases pro Tag": "Fälle pro Tag",
    "persistierte Research Cases": "gespeicherte Research-Fälle",
    "Persistierter Case-Status": "Gespeicherter Fallstatus",
    "Alle öffnen →": "Alle anzeigen →",
    # Table headers & fields
    "Timestamp": "Zeitpunkt",
    "Timestamp UTC": "Zeitpunkt (UTC)",
    "Observation": "Beobachtung",
    "Observation ID": "Beobachtungs-ID",
    "Observation Type": "Beobachtungsart",
    "Type": "Art",
    "Types": "Arten",
    "Rule": "Regel",
    "Rule Version": "Regelversion",
    "Rule Versions": "Regelversionen",
    "Evidence": "Belege",
    "Evidence Score": "Beleg-Score",
    "Evidence Count": "Anzahl Belege",
    "Evidence Card": "Belegkarte",
    "Gespeicherter Evidence Score": "Gespeicherter Beleg-Score",
    "Missing Evidence": "Fehlende Belege",
    "Missing Evidence Count": "Anzahl fehlender Belege",
    "Häufigste Missing Evidence": "Häufigste fehlende Belege",
    "Provenance": "Herkunft",
    "Status": "Status",
    "Case": "Fall",
    "Case ID": "Fall-ID",
    "Case Detail": "Falldetails",
    "Case Hash": "Fall-Hash",
    "Case Cluster": "Fallgruppe",
    "Total Cases": "Fälle gesamt",
    "Outcome": "Ergebnis",
    "Outcome ausstehend": "Ergebnis ausstehend",
    "Retrospective Outcome": "Rückblickendes Ergebnis",
    "Retrospective Outcomes": "Rückblickende Ergebnisse",
    "Review History": "Prüfverlauf",
    "Time Window": "Zeitfenster",
    "Timeframe": "Zeitrahmen",
    "Version": "Version",
    "Component": "Komponente",
    "Detail": "Details",
    "Horizon": "Horizont",
    "Sample": "Stichprobe",
    "Session": "Sitzung",
    "Label": "Bezeichnung",
    "Mode": "Modus",
    "Reason Code": "Grund-Code",
    "Reason Text": "Begründung",
    "Linked Blocker": "Verknüpfter Blocker",
    "Linked Report": "Verknüpfter Bericht",
    "Gap Count": "Anzahl Lücken",
    "Missing AggTrades": "Fehlende AggTrades",
    "Missing Minutes": "Fehlende Minuten",
    "Missing Validation": "Fehlende Validierung",
    "Trade Frequency": "Handelsfrequenz",
    "Buy/Sell Ratio": "Kauf-/Verkaufsverhältnis",
    "Median Delta": "Median-Delta",
    "Price Increased": "Preis gestiegen",
    "Price Decreased": "Preis gefallen",
    "Price Sideways": "Preis seitwärts",
    "Collecting Evidence": "Sammelt Belege",
    "Confirmed": "Bestätigt",
    "Closed": "Abgeschlossen",
    "Fully Validated": "Vollständig validiert",
    "Alle aktiven / alle Status": "Alle aktiven / alle Status",
    "Review Ready": "Review bereit",
    "Rejected": "Verworfen",
    "Quarantined": "In Quarantäne",
    # Orderflow / signals
    "Persistierte Orderflow-Observations": "Gespeicherte Orderflow-Beobachtungen",
    "Neue oder unvollständige Observations": "Neue oder unvollständige Beobachtungen",
    "Validation Queue": "Validierungswarteschlange",
    "Validation Stage": "Validierungsstufe",
    "Live Research Queue": "Aktuelle Research-Warteschlange",
    "Market Sessions (UTC)": "Marktsitzungen (UTC)",
    "Rule Analytics": "Regelanalysen",
    "Data Quality Analytics": "Datenqualitätsanalysen",
    "Data Quality Gating": "Datenqualitäts-Gate",
    "Data Quality Summary": "Datenqualität – Zusammenfassung",
    "Data Quality Evidence Register": "Register der Datenqualitätsbelege",
    "Exceptions Register": "Ausnahmeregister",
    "Exceptions": "Ausnahmen",
    "Kein Trading-Signal:": "Kein Handelssignal:",
    # Health center
    "Operational Health": "Betriebszustand",
    "1 · Live Operational Health": "1 · Aktueller Betriebszustand",
    "2 · Historical Scientific Baseline": "2 · Historische wissenschaftliche Basis",
    "3 · V2 Governance & Readiness": "3 · V2-Governance und Bereitschaft",
    "Governance Health": "Governance-Zustand",
    "Scientific Health": "Wissenschaftlicher Zustand",
    "Health Timeline": "Zustandsverlauf",
    "Database": "Datenbank",
    "Stream": "Stream",
    "Dashboard": "Dashboard",
    "Capture Process": "Erfassungsprozess",
    "WebSocket Connectivity": "WebSocket-Verbindung",
    "Persistency": "Persistenz",
    "Queue": "Warteschlange",
    "Storage": "Speicher",
    "Ollama Availability": "Ollama-Verfügbarkeit",
    "Data Freshness": "Datenfrische",
    "Continuous Coverage": "Durchgehende Abdeckung",
    "Current Coverage": "Aktuelle Abdeckung",
    "Research Integrity": "Research-Integrität",
    "Research Status": "Research-Status",
    "Readiness Status": "Bereitschaftsstatus",
    "Hash Contract Status": "Hash-Vertragsstatus",
    "Integrity Status": "Integritätsstatus",
    "Core Freeze Status": "Core-Freeze-Status",
    "OBSERVE-only Status": "Nur-Beobachtungs-Status",
    "Scientific Review Status": "Wissenschaftlicher Prüfstatus",
    "Data Gap Governance": "Umgang mit Datenlücken",
    "Letzter Research Audit": "Letzter Research-Audit",
    "Replay": "Replay",
    "Validator": "Validator",
    "Acceptance": "Abnahme",
    "No auto-close": "Kein automatisches Schließen",
    "No automatic approval": "Keine automatische Freigabe",
    "No automatic release": "Keine automatische Veröffentlichung",
    "No core edits": "Keine Änderungen am Core",
    "No execution controls": "Keine Ausführungsfunktionen",
    "No reconstruction": "Keine Rekonstruktion",
    "No retroactive rewrite": "Kein nachträgliches Umschreiben",
    "No trading / no signals": "Kein Handel, keine Signale",
    "Open blocker register": "Register offener Blocker",
    "Evidence traceability": "Nachvollziehbarkeit der Belege",
    "Research integrity": "Research-Integrität",
    "Research pipeline integrity": "Integrität der Research-Pipeline",
    "Data quality report": "Datenqualitätsbericht",
    "Quality validation report.": "Qualitätsvalidierungsbericht.",
    "Coverage historical and continuous window differ": "Historisches und durchgehendes Abdeckungsfenster weichen ab",
    # Research workspace
    "Deep Research (lokal)": "Tiefenrecherche (lokal)",
    "Standard Report": "Standardbericht",
    "Report-Typ": "Berichtstyp",
    # Dashboard 4.1: Control-Center pages and status matrix
    "Incidents & Gaps": "Vorfälle & Lücken",
    "Independent Cases": "Unabhängige Fälle",
    "Qualification": "Qualifikation",
    "Setup Path": "Setup-Pfad",
    "V2 Readiness": "V2-Bereitschaft",
    "Security": "Sicherheit",
    "Audit & Evidence": "Audit & Evidenz",
    "Incidents & Gaps →": "Vorfälle & Lücken →",
    "V2 Readiness →": "V2-Bereitschaft →",
    "Data Quality →": "Datenqualität →",
    "Audit & Evidence →": "Audit & Evidenz →",
    "LIVE DATA": "LIVE-DATEN",
    "QUEUE": "WARTESCHLANGE",
    "DATA QUALITY": "DATENQUALITÄT",
    "RESEARCH": "FORSCHUNG",
    "Operations Overview": "Betriebsüberblick",
    "Runtime process": "Runtime-Prozess",
    "Live data": "Live-Daten",
    "Last event": "Letztes Ereignis",
    "Readiness": "Bereitschaft",
    "Research readiness": "Research-Bereitschaft",
    "Horizons and gates": "Horizonte und Gates",
    "Tests, incidents and datasets": "Tests, Vorfälle und Datensätze",
    "Last full test": "Letzter vollständiger Test",
    "Last incident": "Letzter Vorfall",
    "Data spaces": "Datenräume",
    "Live input": "Live-Eingang",
    "Queue & throughput": "Warteschlange & Durchsatz",
    "Live event flow": "Live-Ereignisfluss",
    "Disk and logs": "Speicher und Logs",
    "Security gate": "Sicherheits-Gate",
    "Data age": "Datenalter",
    "Gap inventory": "Lücken-Inventar",
    "Dataset coverage": "Datensatz-Abdeckung",
    "Live freshness": "Live-Aktualität",
    "Gap register": "Lückenregister",
    "Open data gaps": "Offene Datenlücken",
    "Open P0 gaps": "Offene P0-Lücken",
    "Open P1 gaps": "Offene P1-Lücken",
    "Open P1 data gaps": "Offene P1-Datenlücken",
    "Gap evidence scope": "Umfang der Lückenevidenz",
    "Incident timeline": "Vorfall-Zeitleiste",
    "Case counts": "Fallzahlen",
    "Gate evidence": "Gate-Evidenz",
    "Gate status": "Gate-Status",
    "Qualification campaign": "Qualifikationskampagne",
    "Qualification cases": "Qualifikationsfälle",
    "Last test run": "Letzter Testlauf",
    "Last finished test:": "Letzter abgeschlossener Test:",
    "Live start": "Live-Start",
    "Live Queue": "Live-Warteschlange",
    "Research Evidence": "Research-Evidenz",
    "Observation & Outcome Detail": "Beobachtung & Ergebnis im Detail",
    "Live Cutover & Offline Backfill": "Live-Umschaltung & Offline-Nachholung",
    # Headings and notes of the detail pages (one German control center, 29.10.2026)
    "Baseline cursor": "Ausgangs-Cursor",
    "Active and historical incidents plus the persisted data-gap register; diagnosis without reconstruction.": "Aktive und frühere Vorfälle sowie das gespeicherte Lückenregister; Diagnose ohne Rekonstruktion.",
    "Boundary status": "Zustand der Schutzgrenze",
    "Can the persisted data be trusted? Coverage, gaps and live freshness from separate evidence rooms.": "Kann man den gespeicherten Daten trauen? Abdeckung, Lücken und Live-Frische aus getrennten Belegräumen.",
    "Collector freshness": "Frische des Sammlers",
    "Credential rotation": "Wechsel der Zugangsdaten",
    "Current pipeline state": "Aktueller Zustand der Pipeline",
    "Deferred offline events": "Zurückgestellte Offline-Ereignisse",
    "Delivery quality": "Zustellqualität",
    "Developer mode": "Entwicklermodus",
    "Durable cursor": "Gespeicherter Cursor",
    "Event": "Ereignis",
    "Every UI state traces to a source path listed below.": "Jeder angezeigte Zustand führt auf eine der unten genannten Quellen zurück.",
    "Fail-closed state of the local operating boundary. Secrets are never rendered.": "Zustand der lokalen Schutzgrenze; im Zweifel geschlossen. Geheimnisse werden nie angezeigt.",
    "First live trade": "Erster Live-Trade",
    "Gap rows list cause, repairability and backfill status per window.": "Je Lücke: Ursache, Reparierbarkeit und Stand der Nachholung.",
    "Incidents": "Vorfälle",
    "LAN exposure": "Erreichbarkeit im LAN",
    "Latency": "Latenz",
    "Latest incident": "Letzter Vorfall",
    "Listener after hardening": "Listener nach der Härtung",
    "Listener before hardening": "Listener vor der Härtung",
    "Loaded gap records": "Geladene Lücken",
    "MCP status": "MCP-Status",
    "Missing or stale evidence stays UNAVAILABLE and is never interpreted as PASS.": "Fehlende oder veraltete Belege bleiben UNAVAILABLE und gelten nie als bestanden.",
    "Most recent recorded incident": "Zuletzt erfasster Vorfall",
    "OBSERVE mode": "Beobachtungsmodus",
    "Process": "Prozess",
    "Quality": "Qualität",
    "Read-only Research Index": "Research-Index (nur lesen)",
    "Read-only Sicht auf alle dokumentierten Data-Quality-Abweichungen.": "Alle dokumentierten Abweichungen der Datenqualität, nur lesend.",
    "Real, source-bound measurements. Missing instrumentation stays visible as UNAVAILABLE.": "Echte Messwerte mit Quelle. Was nicht gemessen wird, steht sichtbar als UNAVAILABLE da.",
    "Recorded incidents": "Erfasste Vorfälle",
    "Safe stop": "Sicherer Stopp",
    "Secret provider": "Geheimnis-Quelle",
    "Separate external support path; never part of the V2 core release gate.": "Getrennter externer Weg; gehört nie zur V2-Kernfreigabe.",
    "Source": "Quelle",
    "Sourced from the bounded runtime timeline. Historical findings stay frozen and are not counted as current failures.": "Aus der begrenzten Zeitleiste der Runtime. Alte Befunde bleiben eingefroren und zählen nicht als aktuelle Fehler.",
    "Support case": "Support-Fall",
    "Test evidence": "Testbelege",
    "Tests, protected state, incidents and source-bound evidence for traceability.": "Tests, geschützter Zustand, Vorfälle und Belege mit Quelle, damit alles nachvollziehbar bleibt.",
    "UNAVAILABLE means no documented case": "UNAVAILABLE heißt: kein dokumentierter Fall",
    "Window UTC": "Zeitfenster (UTC)",
    "controlled shutdown test": "Test des kontrollierten Herunterfahrens",
    "current binding evidence": "aktueller Beleg der Bindung",
    "cursor age": "Cursor-Alter",
    "drop count": "verworfen",
    "duplicate count": "doppelt",
    "event loop lag": "Event-Loop-Verzug",
    "external reachability test": "Test der Erreichbarkeit von außen",
    "external support path": "externer Support-Weg",
    "fail-closed migration evidence": "Beleg der geschlossenen Umstellung",
    "late count": "verspätet",
    "live measurement": "Live-Messung",
    "live pipeline measurement": "Live-Messung der Pipeline",
    "mode of the running runtime": "Modus der laufenden Runtime",
    "no secrets in UI or repo": "keine Geheimnisse in Oberfläche oder Repo",
    "persist rate": "gespeichert je Sekunde",
    "persisted cursor record": "gespeicherter Cursor-Eintrag",
    "queue age": "Alter der Warteschlange",
    "queue depth": "Länge der Warteschlange",
    "receive rate": "empfangen je Sekunde",
    "recorded listener state": "erfasster Listener-Zustand",
    "source to store latency": "Latenz Quelle bis Speicher",
    "No incident recorded in the bounded timeline window.": "Kein Vorfall im betrachteten Zeitfenster.",
    "gap events": "Lücken-Ereignisse",
    "validator events": "Validator-Ereignisse",
    "Protected state": "Geschützter Zustand",
    "Bounded incident timeline": "Zeitleiste der Vorfälle",
    "Loaded read-only evidence sources": "Geladene Belegquellen (nur lesen)",
    "Open": "Offen",
    "Full register with evidence:": "Ganzes Register mit Belegen:",
    "Incidents from the persisted runtime timeline": "Vorfälle aus der gespeicherten Zeitleiste der Runtime",
    "Persisted data gaps with cause and repair status": "Gespeicherte Datenlücken mit Ursache und Reparaturstand",
    "external state": "externer Zustand",
    "the MCP status cannot override TIM security, data or science gates.": "der MCP-Status kann TIMs Sicherheits-, Daten- und Wissenschafts-Gates nicht übersteuern.",
    "processes": "Prozesse",
    "uptime": "Laufzeit",
    "restarts": "Neustarts",
    "Read-only Gate": "Gate (nur lesen)",
    "CVD State": "CVD-Zustand",
    "Continuous coverage": "Lückenlose Abdeckung",
    "From exception register": "Aus dem Ausnahmeregister",
    "Persisted events": "Gespeicherte Ereignisse",
}

_TAG_OR_TEXT = re.compile(r"(<[^>]*>)")
_RAW_START = re.compile(r"<(script|style)\b", re.I)
_TITLE_SUFFIX = " · TIM"


def _translate_text(segment: str) -> str:
    stripped = segment.strip()
    if not stripped:
        return segment
    plain = html.unescape(stripped)
    suffix = ""
    if plain not in DE and plain.endswith(_TITLE_SUFFIX):
        plain, suffix = plain[: -len(_TITLE_SUFFIX)], _TITLE_SUFFIX
    target = DE.get(plain)
    if target is None:
        return segment
    lead = segment[: len(segment) - len(segment.lstrip())]
    tail = segment[len(segment.rstrip()):]
    return lead + html.escape(target + suffix, quote=False) + tail


_DATA_TAGS = {"td", "dd", "pre", "code", "option", "strong"}
_START_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)([^>]*)>")
_END_TAG = re.compile(r"</([a-zA-Z][a-zA-Z0-9]*)\s*>")
_VOID = {"br", "hr", "img", "input", "meta", "link", "source", "wbr"}
_MONO = re.compile(r"""class\s*=\s*['"][^'"]*\b(?:mono|tag|badge|card__value)\b""")


def translate_html(page: str) -> str:
    out: list[str] = []
    raw_until: str | None = None
    data_stack: list[str] = []  # open tags that make their content data (never translated)
    for part in _TAG_OR_TEXT.split(page):
        if not part:
            continue
        if part.startswith("<"):
            if raw_until is None:
                match = _RAW_START.match(part)
                if match:
                    raw_until = f"</{match.group(1).lower()}"
                else:
                    start = _START_TAG.match(part)
                    end = _END_TAG.match(part)
                    if start and not part.endswith("/>"):
                        name = start.group(1).lower()
                        if data_stack or name in _DATA_TAGS or _MONO.search(start.group(2)):
                            if name not in _VOID:
                                data_stack.append(name)
                    elif end and data_stack and end.group(1).lower() == data_stack[-1]:
                        data_stack.pop()
            elif part.lower().startswith(raw_until):
                raw_until = None
            out.append(part)
        elif raw_until is not None or data_stack:
            out.append(part)
        else:
            out.append(_translate_text(part))
    return "".join(out)
