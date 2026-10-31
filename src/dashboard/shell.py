"""The one frame of the Control Center (new Control Center, 31.10.2026).

Every page gets the same frame: a slim bar on the left with the four screens
(Cockpit, Journal, Forschung, System), a header with BTC price, system light,
"Papier" and the next blocked window, and on the phone the four screens as a
bar at the bottom. One dark look for every page.

Display only. The header facts are read from the running dashboard state and
kept for a few seconds, so many page loads do not repeat the work.
"""

from __future__ import annotations

import html
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard.navigation import links as nav_links

LOCAL = ZoneInfo("Europe/Berlin")
FACTS_SECONDS = 15
PRICE_MAX_AGE = 15 * 60  # older than this the price is shown as stale

# Plain symbols: no icon font, no external file.
ICONS = {"cockpit": "◉", "journal": "▤", "forschung": "⚗", "system": "⚙"}

SHELL_CSS = """
body.ncc{--n-bg:#0b0f14;--n-side:#080b10;--n-top:#0d1218;--n-panel:#121820;--n-panel2:#18202a;--n-line:#232d3a;--n-text:#e6edf3;--n-muted:#8b98a8;--n-ok:#2ecc8f;--n-warn:#f5b942;--n-fail:#ff5c6c;--n-unknown:#6b7685;--n-accent:#7c8cff;
margin:0;padding-left:84px;background:var(--n-bg);color:var(--n-text);color-scheme:dark}
.ncc-skip{position:absolute;left:-999px;top:0}.ncc-skip:focus{left:96px;top:8px;z-index:50;background:var(--n-panel2);color:var(--n-text);padding:6px 10px;border-radius:8px}
.ncc-side{position:fixed;left:0;top:0;bottom:0;width:84px;z-index:40;background:var(--n-side);border-right:1px solid var(--n-line);display:flex;flex-direction:column;align-items:center;padding:14px 0;gap:6px}
.ncc-logo{font:800 17px/1 Inter,-apple-system,"Segoe UI",sans-serif;letter-spacing:.06em;color:var(--n-accent);margin:4px 0 16px;text-decoration:none}
.ncc-nav{display:flex;flex-direction:column;gap:6px;width:100%;align-items:center}
.ncc-nav a{width:68px;padding:10px 0 8px;border-radius:12px;text-align:center;color:var(--n-muted);font:600 11.5px/1.2 Inter,-apple-system,"Segoe UI",sans-serif;text-decoration:none}
.ncc-nav a:hover{color:var(--n-text);background:var(--n-panel);text-decoration:none}
.ncc-nav a[aria-current=page],.ncc-nav a.area{background:var(--n-panel2);color:var(--n-text)}
.ncc-ico{display:block;font-size:20px;line-height:1;margin-bottom:5px}
.ncc-top{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:10px 14px;flex-wrap:wrap;padding:10px 24px;background:var(--n-top);border-bottom:1px solid var(--n-line);font:14px/1.4 Inter,-apple-system,"Segoe UI",sans-serif}
.ncc-brand{display:none;font-weight:800;color:var(--n-accent);text-decoration:none}
.ncc-price{font-weight:700;font-size:16px;color:var(--n-text);font-variant-numeric:tabular-nums;white-space:nowrap}
.ncc-price small{font-size:12px;font-weight:600;color:var(--n-muted);margin-left:6px}
.ncc-pill{display:inline-flex;align-items:center;gap:7px;padding:4px 11px;border-radius:99px;background:var(--n-panel2);color:var(--n-muted);font-size:12.5px;white-space:nowrap;text-decoration:none}
a.ncc-pill:hover{color:var(--n-text);text-decoration:none}
.ncc-dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:var(--n-unknown);flex:none}
.ncc-dot[data-s=ok]{background:var(--n-ok)}.ncc-dot[data-s=warn]{background:var(--n-warn)}.ncc-dot[data-s=fail]{background:var(--n-fail)}
.ncc-live{margin-left:auto;font-size:12.5px;color:var(--n-muted);white-space:nowrap}
.ncc-live .live{all:unset;cursor:pointer;font-size:12.5px;color:var(--n-muted)}
.ncc-live [data-state=fail]{color:var(--n-fail)}
.ncc-sub{display:flex;flex-wrap:wrap;gap:4px 18px;padding:8px 24px;border-bottom:1px solid var(--n-line);background:var(--n-bg);font:600 13px/1.4 Inter,-apple-system,"Segoe UI",sans-serif}
.ncc-sub a{color:var(--n-muted);text-decoration:none;padding:3px 0}.ncc-sub a:hover{color:var(--n-text)}
.ncc-sub a[aria-current=page]{color:var(--n-text);text-decoration:underline;text-underline-offset:5px}
.ncc-sub .ncc-back{color:var(--n-accent)}
.ncc-foot{padding:18px 24px 26px;color:var(--n-muted);font:12.5px/1.5 Inter,-apple-system,"Segoe UI",sans-serif}
@media (max-width:700px){
body.ncc{padding-left:0;padding-bottom:calc(66px + env(safe-area-inset-bottom))}
.ncc-side{top:auto;right:0;width:auto;height:auto;flex-direction:row;padding:4px 0 calc(4px + env(safe-area-inset-bottom));border-right:0;border-top:1px solid var(--n-line)}
.ncc-logo{display:none}.ncc-nav{flex-direction:row;justify-content:space-around}.ncc-nav a{width:auto;flex:1;margin:0 3px}
.ncc-top{padding:9px 14px;gap:8px 10px}.ncc-brand{display:inline}.ncc-hide{display:none}
.ncc-sub{padding:8px 14px;flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch}.ncc-sub a{white-space:nowrap}
.ncc-live{margin-left:0;flex-basis:100%}
}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


# --- header facts ---------------------------------------------------------------

_LOCK = threading.Lock()
_SOURCE: dict[str, Any] = {"state": None}
_CACHE: dict[str, Any] = {"at": 0.0, "facts": None}


def use_state(state: Any) -> None:
    """The running dashboard registers its state; without it the header shows "keine Daten"."""
    with _LOCK:
        _SOURCE["state"] = state
        _CACHE.update(at=0.0, facts=None)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _price_text(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours >= 24:
        return f"{hours // 24} T {hours % 24} h"
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def _last_price(state: Any) -> tuple[float | None, datetime | None]:
    best: tuple[datetime, float] | None = None
    # A short wait only: the header must never block a page behind the runtime's lock.
    if not state.lock.acquire(timeout=0.5):
        return None, None
    try:
        rows = [dict(items[-1]) for items in (getattr(state, "chart_candles", {}) or {}).values() if items]
        if not rows:
            rows = [dict(item) for item in list(getattr(state, "recent_candles", []) or [])[-1:]]
    finally:
        state.lock.release()
    for row in rows:
        close, moment = _number(row.get("close")), _time(row.get("close_time") or row.get("open_time"))
        if close is not None and moment is not None and (best is None or moment > best[0]):
            best = (moment, close)
    return (best[1], best[0]) if best else (None, None)


def _block(now: datetime) -> dict[str, str]:
    from src.dashboard.chart_model import ny_open_windows

    for window in ny_open_windows(now - timedelta(hours=2), now + timedelta(days=4)):
        start, end = _time(window.get("start")), _time(window.get("end"))
        if start is None or end is None or end < now:
            continue
        if start <= now:
            return {"state": "warn", "text": f"Sperrzeit jetzt bis {end.astimezone(LOCAL):%H:%M}"}
        return {"state": "unknown", "text": f"Sperrzeit NY-Open in {_duration((start - now).total_seconds())}"}
    return {"state": "unknown", "text": "keine Sperrzeit in Sicht"}


SYSTEM_WORDS = {"ok": "System OK", "warn": "System prüfen", "fail": "System Fehler", "unknown": "System: keine Daten"}


def compute_facts(state: Any, now: datetime | None = None) -> dict[str, Any]:
    """Price, system light and next blocked window for the header. Never raises."""
    now = now or datetime.now(timezone.utc)
    facts: dict[str, Any] = {"price": None, "price_state": "unknown", "price_note": "kein Kurs",
                             "system": "unknown", "block": {"state": "unknown", "text": "Sperrzeit unbekannt"}}
    try:
        price, at = _last_price(state)
        if price is not None and at is not None:
            age = (now - at).total_seconds()
            facts.update(price=price, price_state="ok" if age <= PRICE_MAX_AGE else "warn",
                         price_note=f"{at.astimezone(LOCAL):%H:%M}" if age <= PRICE_MAX_AGE else f"Stand {at.astimezone(LOCAL):%d.%m. %H:%M}")
    except Exception:  # noqa: BLE001 - the header must never break a page
        pass
    try:
        status = str(((state.snapshot() or {}).get("operational_health") or {}).get("status") or "").upper()
        facts["system"] = {"GREEN": "ok", "YELLOW": "warn", "RED": "fail"}.get(status, "unknown")
    except Exception:  # noqa: BLE001
        pass
    try:
        facts["block"] = _block(now)
    except Exception:  # noqa: BLE001
        pass
    return facts


def facts() -> dict[str, Any] | None:
    with _LOCK:
        state = _SOURCE["state"]
        if state is None:
            return None
        if _CACHE["facts"] is not None and time.monotonic() - _CACHE["at"] < FACTS_SECONDS:
            return _CACHE["facts"]
    value = compute_facts(state)
    with _LOCK:
        _CACHE.update(at=time.monotonic(), facts=value)
    return value


def header_pills(value: dict[str, Any] | None) -> str:
    if value is None:
        return ("<span class='ncc-price'>BTC —</span>"
                "<a class='ncc-pill' href='/system'><span class='ncc-dot' data-s='unknown'></span>System: keine Daten</a>"
                "<span class='ncc-pill'><span class='ncc-dot' data-s='warn'></span>Papier · kein Echtgeld</span>")
    price = value.get("price")
    price_html = (f"<a class='ncc-price' href='/chart'>BTC {_e(_price_text(price))}<small>{_e(value.get('price_note'))}</small></a>"
                  if price is not None else "<a class='ncc-price' href='/chart'>BTC —<small>kein Kurs</small></a>")
    system = str(value.get("system") or "unknown")
    block = value.get("block") or {}
    return (
        price_html
        + f"<a class='ncc-pill' href='/system'><span class='ncc-dot' data-s='{_e(system)}'></span>{_e(SYSTEM_WORDS.get(system, SYSTEM_WORDS['unknown']))}</a>"
        + "<span class='ncc-pill'><span class='ncc-dot' data-s='warn'></span>Papier · kein Echtgeld</span>"
        + f"<span class='ncc-pill ncc-hide'><span class='ncc-dot' data-s='{_e(block.get('state') or 'unknown')}'></span>{_e(block.get('text') or '')}</span>"
    )


# --- frame ----------------------------------------------------------------------

def nav_html(path: str, subnav: bool = True) -> tuple[str, str]:
    """The four screens; and, on a detail page, its siblings with a way back to the screen."""
    side, subs = [], []
    for area in nav_links(path):
        current = bool(area["current"])
        pages = list(area["pages"])  # type: ignore[arg-type]
        on_screen = current and (not pages or bool(pages[0]["current"]))
        mark = " aria-current='page'" if on_screen else (" class='area'" if current else "")
        side.append(f"<a href='{_e(area['href'])}'{mark}><span class='ncc-ico' aria-hidden='true'>{ICONS.get(str(area['key']), '•')}</span>{_e(area['label'])}</a>")
        if current and subnav and not on_screen:
            for index, sub in enumerate(pages):
                css = " class='ncc-back'" if index == 0 else ""
                label = f"← {sub['label']}" if index == 0 else sub["label"]
                cur = " aria-current='page'" if sub["current"] else ""
                subs.append(f"<a href='{_e(sub['href'])}'{css}{cur}>{_e(label)}</a>")
    return "".join(side), "".join(subs)


def frame(path: str, body: str, *, live: str = "", main_attrs: str = "", footer: str = "", main_class: str = "") -> str:
    """Side bar, header and (on detail pages) the sibling row around ``body``. Returns the <body> inner HTML."""
    side, subs = nav_html(path)
    sub_html = f"<nav class='ncc-sub' aria-label='Seiten in diesem Bereich'>{subs}</nav>" if subs else ""
    cls = f" class='{_e(main_class)}'" if main_class else ""
    foot = footer or "TIM beobachtet nur und handelt auf Papier: keine Orders, keine Trading-, Shell- oder Git-Aktionen. Alle Zeiten in deutscher Ortszeit."
    return (
        "<a class='ncc-skip' href='#main-content'>Zum Hauptinhalt springen</a>"
        "<aside class='ncc-side'><a class='ncc-logo' href='/' aria-label='TIM Cockpit'>TIM</a>"
        f"<nav class='ncc-nav' aria-label='Hauptnavigation'>{side}</nav></aside>"
        f"<header class='ncc-top'><a class='ncc-brand' href='/'>TIM</a>{header_pills(facts())}<span class='ncc-live'>{live}</span></header>"
        f"{sub_html}<main id='main-content' tabindex='-1'{cls}{main_attrs}>{body}</main>"
        f"<footer class='ncc-foot'>{_e(foot)}</footer>"
    )
