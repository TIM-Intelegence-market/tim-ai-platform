"""Fixed rules of the research workshop (docs/research_lab/FORSCHUNGSBEREICH.md).

Changing a value here is a charter change: it needs Uzi's word and a line in the
change log of the charter document. Code never raises these limits by itself.
"""
from __future__ import annotations

CHARTER_VERSION = "forschungsbereich/1.0"

# Autonomy: 0 = tool only, 1 = propose and compute after approval per study,
# 2 = register studies from approved templates within the budget.
STAGE = 1
MAX_STAGE_WITHOUT_UZI = 1

MONTHLY_STUDY_BUDGET = 4          # new study drafts per calendar month (local time)
KI_IDEAS_PER_WEEK = 3             # ideas from the weekly AI round per ISO week
SNOOPING_TEST_FROM_VARIANTS = 5   # SPA/StepM is mandatory from this many variants
SHADOW_WINDOW_DAYS = 30           # prospective shadow window for an update
LOCAL_TIMEZONE = "Europe/Berlin"

SOURCES = {
    "uzi": "Uzi",
    "journal_review": "Plan-Journal (Lernvorschlag)",
    "reflection": "Wöchentliche Reflexion",
    "logbook_lesson": "Lehre aus dem Logbuch",
    "community": "GoatHub/Broncx (nur Frage, kein Beleg)",
    "ki_runde": "Wöchentliche KI-Runde",
}

TEMPLATES = {
    "regel_backtest": "Regel-Backtest auf dem Archiv (wie S4–S7, S9, S10)",
    "ereignis_studie": "Ereignis-Studie (wie S1)",
    "modellvergleich": "Modellvergleich mit prospektivem Test (wie S8)",
}

FIXED_LIMITS = (
    "Nur Papier, kein Echtgeld, keine echten Orders.",
    "Risikogrenzen und Kostenmodell ändern sich nie automatisch.",
    "Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Uzis ausdrücklichem Wort.",
    "Kein automatischer Merge; gemergt wird nur nach Uzis „merge“.",
    "Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.",
)
