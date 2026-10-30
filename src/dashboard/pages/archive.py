"""Archiv V2: the pages of the aborted V2 qualification campaign, out of the navigation."""
from __future__ import annotations

from src.dashboard.helpers import _safe
from src.dashboard.layout import _layout
from src.dashboard.navigation import ARCHIVE


def render_archive() -> str:
    items = "".join(
        f"<a href='{_safe(href)}'><b>{_safe(label)}</b><span>{_safe(text)}</span></a>" for label, href, text in ARCHIVE
    )
    body = (
        "<div class='hero'><div><h1>Archiv V2</h1>"
        "<p>Die V2-Qualifizierung wurde am 22.10.2026 abgebrochen. Ihre Seiten bleiben zum Nachlesen erreichbar, "
        "gehören aber nicht mehr zum Alltag und stehen deshalb nicht im Menü.</p></div></div>"
        f"<section class='panel'><div class='archive-list'>{items}</div></section>"
    )
    return _layout("Archiv V2", "Archiv", body)
