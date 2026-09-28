from __future__ import annotations

from pathlib import Path

from src.dashboard.helpers import _safe
from src.dashboard.i18n import translate_html


_ASSETS = Path(__file__).resolve().parent / "assets"

CSS = (_ASSETS / "style.css").read_text(encoding="utf-8")




AUTO_REFRESH_SCRIPT = (_ASSETS / "auto_refresh.html").read_text(encoding="utf-8")


NAV_SCRIPT = (_ASSETS / "nav.html").read_text(encoding="utf-8")


NAV_GROUPS = (
    ("Overview", (("Overview", "/"),)),
    ("Forschung", (("Observations", "/observations"), ("Research Cases", "/cases"), ("Orderflow", "/orderflow"), ("Signal Research", "/signals"), ("Analytics", "/analytics"), ("Insights", "/insights"))),
    ("Betrieb", (("Health Center", "/health"), ("Data Quality Exceptions", "/exceptions"), ("Timeline", "/timeline"))),
    ("Werkzeuge", (("Research", "/research"), ("Pilotansicht", "/pilot"))),
)


CURRENT = " aria-current='page'"


def _nav(page: str) -> str:
    parts = []
    for group, links in NAV_GROUPS:
        if len(links) == 1 and links[0][0] == group:
            key, href = links[0]
            parts.append(f"<a href='{href}' class='{'active' if page == key else ''}'{CURRENT if page == key else ''}>{key}</a>")
            continue
        active = any(page == key for key, _ in links)
        items = "".join(f"<a href='{href}' class='{'active' if page == key else ''}'{CURRENT if page == key else ''}>{key}</a>" for key, href in links)
        parts.append(f"<details class='navgroup{' active' if active else ''}'><summary>{group}</summary><div class='navgroup__menu'>{items}</div></details>")
    return "".join(parts)


def _layout(title: str, page: str, body: str) -> str:
    return translate_html(f"""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_safe(title)} · TIM</title><style>{CSS}</style></head><body><header class='topbar'><div class='topbar__inner'><a class='brand' href='/'>TIM<small>TRANSPARENT INTELLIGENCE FOR MARKETS</small></a><details class='menu-toggle'><summary>Menü</summary></details><nav class='nav' aria-label='Hauptnavigation'>{_nav(page)}</nav><div id='tim-status' class='live badge--yellow' role='status' aria-live='polite'>● Startet…</div></div></header><main class='shell'>{body}</main>{AUTO_REFRESH_SCRIPT}{NAV_SCRIPT}</body></html>""")


def _hero(title: str, text: str) -> str:
    return f"<div class='hero'><div><h1>{_safe(title)}</h1><p>{_safe(text)}</p></div><div class='observe'>OBSERVE • READ-ONLY</div></div>"
