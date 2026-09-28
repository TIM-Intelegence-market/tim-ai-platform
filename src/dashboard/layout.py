from __future__ import annotations

from pathlib import Path

from src.dashboard.helpers import _safe


_ASSETS = Path(__file__).resolve().parent / "assets"

CSS = (_ASSETS / "style.css").read_text(encoding="utf-8")


EXTRA_CSS = (_ASSETS / "extra.css").read_text(encoding="utf-8")


AUTO_REFRESH_SCRIPT = (_ASSETS / "auto_refresh.html").read_text(encoding="utf-8")


def _layout(title: str, page: str, body: str) -> str:
    links = [("Overview", "/"), ("Observations", "/observations"), ("Research Cases", "/cases"), ("Orderflow", "/orderflow"), ("Signal Research", "/signals"), ("Analytics", "/analytics"), ("Insights", "/insights"), ("Health Center", "/health"), ("Data Quality Exceptions", "/exceptions"), ("Timeline", "/timeline"), ("Research", "/research")]
    nav = "".join(f"<a href='{href}' class='{'active' if page == key else ''}'>{key}</a>" for key, href in links)
    return f"""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_safe(title)} · TIM</title><style>{CSS}{EXTRA_CSS}</style></head><body><header class='topbar'><div class='topbar__inner'><a class='brand' href='/'>TIM<small>TRANSPARENT INTELLIGENCE FOR MARKETS</small></a><nav class='nav'>{nav}</nav><div id='tim-status' class='live badge--yellow'>● Startet…</div></div></header><main class='shell'>{body}</main>{AUTO_REFRESH_SCRIPT}</body></html>"""


def _hero(title: str, text: str) -> str:
    return f"<div class='hero'><div><h1>{_safe(title)}</h1><p>{_safe(text)}</p></div><div class='observe'>OBSERVE • READ-ONLY</div></div>"
