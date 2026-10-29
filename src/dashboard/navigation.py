"""The one navigation of the Control Center.

Five areas, ordered by what the user does in a day: today, chart, journal,
research, system. Every page belongs to exactly one area and shows up as a
sub-link there. Pages of the aborted V2 campaign live only on /archiv.

New pages are added here as a sub-link of an existing area, never as a sixth
area. ``tests/test_navigation.py`` fails if the top level grows past five
entries or a label slips back into English.
"""
from __future__ import annotations

from typing import TypedDict


class Area(TypedDict):
    key: str
    label: str
    href: str
    pages: list[tuple[str, str]]


AREAS: list[Area] = [
    {"key": "heute", "label": "Heute", "href": "/", "pages": [
        ("Lage", "/"),
        ("Markt & Pläne", "/neu/markt"),
        ("Vorbereitung", "/prep"),
        ("Mein Tag", "/my-day"),
        ("Setup-Pfad", "/setup-path"),
    ]},
    {"key": "chart", "label": "Chart", "href": "/chart", "pages": [
        ("TIM-Chart", "/chart"),
    ]},
    {"key": "journal", "label": "Journal", "href": "/journal", "pages": [
        ("Plan-Journal", "/journal"),
        ("Trader-Journal", "/trader-journal"),
    ]},
    {"key": "forschung", "label": "Forschung", "href": "/neu/forschung", "pages": [
        ("Überblick", "/neu/forschung"),
        ("Research-Fälle", "/cases"),
        ("Beobachtungen", "/observations"),
        ("Orderflow", "/orderflow"),
        ("Signal-Research", "/signals"),
        ("Analysen", "/analytics"),
        ("Erkenntnisse", "/insights"),
        ("Recherche-Werkzeug", "/research"),
    ]},
    {"key": "system", "label": "System", "href": "/neu/betrieb", "pages": [
        ("Betrieb", "/neu/betrieb"),
        ("Mac jetzt", "/neu/mac"),
        ("Freigabe & Sicherheit", "/neu/system"),
        ("Laufzeit", "/runtime"),
        ("Datenqualität", "/data-quality"),
        ("Vorfälle & Lücken", "/gaps"),
        ("Systemzustand", "/health"),
        ("Ausnahmen", "/exceptions"),
        ("Zeitleiste", "/timeline"),
        ("Sicherheit", "/security"),
        ("Audit & Evidenz", "/audit-evidence"),
        ("Graphify & MCP", "/mcp"),
        ("Graphify-Graph", "/graphify"),
        ("Archiv V2", "/archiv"),
    ]},
]
AREA_BY_KEY = {area["key"]: area for area in AREAS}

# Pages of the V2 qualification campaign (aborted 22.10.2026). Still reachable,
# listed only on /archiv, never in the navigation.
ARCHIVE: list[tuple[str, str, str]] = [
    ("Qualifikation", "/qualification", "Stand der abgebrochenen Qualifizierungskampagne"),
    ("V2-Bereitschaft", "/v2-readiness", "Gates, Blocker und Verantwortliche der Kampagne"),
    ("Unabhängige Fälle", "/independent-cases", "Fälle, die für die Qualifizierung gesammelt wurden"),
    ("Pilotansicht", "/pilot", "Pilot-Fälle der Kampagne"),
    ("Alte Übersicht", "/uebersicht-alt", "Die frühere Startseite mit Gates und Horizonten"),
]

# Sub-paths that belong to a page listed above (path prefix -> page path).
_ALIASES = {"/neu": "/", "/neu/": "/", "/journal/struct": "/journal", "/journal/level": "/journal",
            "/graphify/": "/graphify"}

# Page keys used by the classic page shell (``layout._layout``) -> their path.
PAGE_PATHS = {
    "Overview": "/uebersicht-alt", "Runtime": "/runtime", "Data Quality": "/data-quality",
    "Incidents & Gaps": "/gaps", "Health Center": "/health", "Data Quality Exceptions": "/exceptions",
    "Timeline": "/timeline", "Observations": "/observations", "Research Cases": "/cases",
    "Orderflow": "/orderflow", "Signal Research": "/signals", "Analytics": "/analytics",
    "Insights": "/insights", "Independent Cases": "/independent-cases", "Qualification": "/qualification",
    "Prep": "/prep", "My Day": "/my-day", "Trader Journal": "/trader-journal", "Setup Path": "/setup-path",
    "Plan Journal": "/journal", "Plan Journal Struct": "/journal", "Plan Journal Level": "/journal",
    "Chart": "/chart", "V2 Readiness": "/v2-readiness", "Security": "/security",
    "Audit & Evidence": "/audit-evidence", "Graphify & MCP": "/mcp", "Graphify-Graph": "/graphify",
    "Research": "/research", "Pilotansicht": "/pilot", "Archiv": "/archiv",
}

_ARCHIVE_PATHS = {href for _, href, _ in ARCHIVE}


def locate(path: str) -> tuple[str, str]:
    """Return (area key, page path) for a request path; archive pages sit under System."""
    path = _ALIASES.get(path, path)
    if path in _ARCHIVE_PATHS:
        return "system", "/archiv"
    for area in AREAS:
        for _, href in area["pages"]:
            if href == path:
                return area["key"], href
    return "", path


def links(path: str) -> list[dict[str, object]]:
    """The navigation for one page: five areas, the active one with its sub-links."""
    active, page = locate(path)
    out: list[dict[str, object]] = []
    for area in AREAS:
        current = area["key"] == active
        subs = [{"label": label, "href": href, "current": href == page} for label, href in area["pages"]] if current and len(area["pages"]) > 1 else []
        out.append({"label": area["label"], "href": area["href"], "current": current, "pages": subs})
    return out
