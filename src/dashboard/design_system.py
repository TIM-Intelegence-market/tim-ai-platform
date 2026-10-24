"""Control Center design system: semantic severity tokens and UI primitives.

Every operational status rendered by the TIM dashboard flows through this
module so that identical states look identical on every page. The system is
presentation-only: it never invents values, upgrades failures, or converts a
missing measurement into a number. An absent value stays UNAVAILABLE.

Severity vocabulary (CSS class prefix ``sev``):

- ok        validated healthy / pass (green is reserved for evidence)
- info      neutral state, waiting on a scheduled or human gate (blue)
- warn      warning that needs attention (amber)
- degraded  partially impaired operation (orange)
- fail      failure / red
- blocked   hard blocker, requires external or admin action (magenta)
- unknown   no evidence available — never rendered as a number (gray)
- disabled  intentionally off by policy (muted gray)
"""

from __future__ import annotations

import html
from typing import Any, Iterable

UNAVAILABLE = "UNAVAILABLE"


def _esc(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def severity(status: Any) -> str:
    """Map a raw or normalized status string to a severity key.

    The mapping is deliberately conservative: only validated healthy states
    may appear green, and missing evidence is always ``unknown``.
    """
    text = str(status if status not in (None, "", {}) else UNAVAILABLE).strip().upper()
    if text in {"UNAVAILABLE", "UNKNOWN", "MISSING", "STALE", "ARCHIVED", "N/A", "NONE", "—"} or text.startswith("MISSING:"):
        return "unknown"
    if text in {"DISABLED", "DISABLED BY POLICY", "PAUSED", "OBSERVE", "OBSERVE-ONLY", "AWAITING INTELLIGENCE", "PREPARED · INACTIVE"} or text.startswith("DISABLED") or text.startswith("HISTORICAL"):
        return "disabled"
    if text.startswith("STALE"):
        return "warn"
    if "FAIL" in text or text in {"ERROR", "RED", "CRITICAL", "EXPOSED", "LOCKED"} or "ERROR" in text:
        return "fail"
    if "BLOCKED" in text or "ADMIN ACTION REQUIRED" in text or "EXTERNAL ACTION REQUIRED" in text:
        return "blocked"
    if text in {"DEGRADED", "ORANGE"} or text.startswith("DEGRADED"):
        return "degraded"
    if text in {"PASS", "ACTIVE", "RUNNING", "GREEN", "HEALTHY", "OK", "COMPLETED", "COMPLETE", "FROZEN", "CONNECTED", "MEASURED"} or text.startswith("PASS"):
        return "ok"
    if "TIME GATE" in text or "PENDING HUMAN APPROVAL" in text or "HUMAN ACTION REQUIRED" in text or "HUMAN_ACTION_REQUIRED" in text or text in {"SCHEDULED", "WAITING"}:
        return "info"
    if "NOT APPROVED" in text or "INSUFFICIENT" in text or "NOT READY" in text or "NOT_READY" in text:
        return "warn"
    if "WARN" in text or text in {"YELLOW", "AMBER", "PENDING", "CANDIDATE"} or text.startswith("CANDIDATE"):
        return "warn"
    return "warn"


def short_state(status: Any) -> str:
    """Compact operator-facing state word for a raw status value."""
    key = severity(status)
    return {
        "ok": "PASS",
        "info": "GATE",
        "warn": "WARNING",
        "degraded": "DEGRADED",
        "fail": "FAIL",
        "blocked": "BLOCKED",
        "unknown": "UNKNOWN",
        "disabled": "OFF",
    }[key]


# ---------------------------------------------------------------------------
# CSS layer (appended to the dashboard stylesheet by app.py; the CSP hash is
# recomputed automatically from the final string).
# ---------------------------------------------------------------------------

COMPONENT_CSS = r"""
:root{--ok:#35d39a;--ok-soft:#0d2d25;--ok-line:#1e5947;--info:#70a7ff;--info-soft:#12233c;--info-line:#2c4a75;--warn:#f2bd55;--warn-soft:#332710;--warn-line:#664b19;--degraded:#f29055;--degraded-soft:#332012;--degraded-line:#6b421f;--fail:#ff6577;--fail-soft:#341720;--fail-line:#6b2937;--blocked:#e57ae0;--blocked-soft:#2f1730;--blocked-line:#5f2d63;--unknown:#8491a3;--unknown-soft:#161c26;--unknown-line:#2c3644;--disabled:#5c6875;--disabled-soft:#12161d;--disabled-line:#242c37;--space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:22px;--radius-s:6px;--radius-m:10px;--font-mono:ui-monospace,SFMono-Regular,Menlo,monospace}
.sev{display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border:1px solid var(--unknown-line);border-radius:5px;font:800 10px/1.4 inherit;letter-spacing:.055em;text-transform:uppercase;white-space:nowrap;max-width:100%}
.metricstrip__item .sev,.gate .sev,.coverage__row .sev,.attention__row>.sev,.cellstate{display:inline-block;font-family:var(--font-mono);font-size:10.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;overflow-wrap:break-word;min-width:0}
.cellstate:before{content:"";display:inline-block;width:7px;height:7px;margin-right:6px;border-radius:50%;background:currentColor;vertical-align:middle}
.cellstate--ok{color:var(--ok)}.cellstate--info{color:var(--info)}.cellstate--warn{color:var(--warn)}.cellstate--degraded{color:var(--degraded)}.cellstate--fail{color:var(--fail)}.cellstate--blocked{color:var(--blocked)}.cellstate--unknown{color:var(--unknown)}.cellstate--disabled{color:var(--disabled)}
td .sev{display:inline-block;white-space:normal;overflow-wrap:break-word;line-height:1.5}
td .sev:before{display:inline-block;vertical-align:middle}
.sev:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
.sev--ok{background:var(--ok-soft);border-color:var(--ok-line);color:var(--ok)}
.sev--info{background:var(--info-soft);border-color:var(--info-line);color:var(--info)}
.sev--warn{background:var(--warn-soft);border-color:var(--warn-line);color:var(--warn)}
.sev--degraded{background:var(--degraded-soft);border-color:var(--degraded-line);color:var(--degraded)}
.sev--fail{background:var(--fail-soft);border-color:var(--fail-line);color:var(--fail)}
.sev--blocked{background:var(--blocked-soft);border-color:var(--blocked-line);color:var(--blocked)}
.sev--unknown{background:var(--unknown-soft);border-color:var(--unknown-line);color:var(--unknown)}
.sev--disabled{background:var(--disabled-soft);border-color:var(--disabled-line);color:var(--disabled)}
.cc-page-head{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin:4px 0 18px}
.cc-page-head__right{display:flex;flex-direction:column;align-items:flex-end;gap:10px}
.cc-page-head h1{margin:0 0 6px;font-size:clamp(22px,2.2vw,30px);line-height:1.12;letter-spacing:-.03em}
.cc-page-head p{margin:0;max-width:820px;color:var(--muted);font-size:14px}
.cc-meta{font:11px var(--font-mono);color:var(--muted);text-align:right;line-height:1.7;white-space:nowrap}
.cc-safety{display:flex;align-items:center;gap:0;margin:0 0 18px;border:1px solid var(--line);border-radius:8px;background:#0b1118;overflow:hidden;flex-wrap:wrap}
.cc-safety span,.cc-safety strong{padding:8px 13px;border-right:1px solid var(--line);font:10px var(--font-mono);letter-spacing:.05em;color:var(--muted)}
.cc-safety strong{margin-left:auto;border-right:0;border-left:1px solid var(--fail-line);color:var(--fail);background:var(--fail-soft)}
.cc-section{margin-top:26px}
.cc-section__head{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:12px}
.cc-section__head h2{margin:0;font-size:17px;letter-spacing:-.01em}
.cc-section__eyebrow{margin:0 0 5px;color:var(--info);font-size:10px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}
.cc-section__note{margin:4px 0 0;color:var(--muted);font-size:12px}
.cc-section__meta{color:var(--muted);font-size:11px;text-align:right;white-space:nowrap}
.cc-surface{background:linear-gradient(150deg,rgba(19,26,36,.96),rgba(12,17,24,.98));border:1px solid var(--line);border-radius:var(--radius-m);box-shadow:var(--shadow)}
.state-banner{display:grid;grid-template-columns:minmax(220px,340px) 1fr;border:1px solid var(--unknown-line);border-radius:var(--radius-m);background:linear-gradient(140deg,rgba(19,26,36,.97),rgba(12,17,24,.99));box-shadow:var(--shadow);overflow:hidden}
.state-banner--ok{border-color:var(--ok-line)}
.state-banner--warn,.state-banner--degraded{border-color:var(--warn-line)}
.state-banner--fail,.state-banner--blocked{border-color:var(--fail-line)}
.state-banner__primary{padding:20px 22px;border-right:1px solid var(--line);background:rgba(10,15,22,.55)}
.state-banner__primary .sev{margin-bottom:10px}
.state-banner__state{margin:0;font-size:30px;line-height:1.05;font-weight:800;letter-spacing:-.03em}
.state-banner__sub{margin:7px 0 0;color:var(--muted);font-size:12px}
.state-banner__metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:1px;background:var(--line)}
.state-banner__metric{padding:14px 16px;background:#0d131c}
.state-banner__metric dt{margin:0;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase}
.state-banner__metric dd{margin:6px 0 0;font-size:19px;font-weight:750;letter-spacing:-.02em;font-family:var(--font-mono);overflow-wrap:break-word}
.state-banner__metric dd small{display:block;margin-top:4px;color:var(--muted);font-family:inherit;font-size:11px;font-weight:500;line-height:1.45;letter-spacing:0}
.attention{border:1px solid var(--line);border-radius:var(--radius-m);overflow:hidden}
.attention__row{display:flex;gap:14px;align-items:flex-start;padding:13px 16px;border-bottom:1px solid var(--line);background:#0d131c}
.attention__row:last-child{border-bottom:0}
.attention__row>.sev{margin-top:2px;flex:none;min-width:86px;justify-content:center}
.attention__body{flex:1;min-width:0}
.attention__title{margin:0;font-weight:750;font-size:13.5px}
.attention__detail{margin:3px 0 0;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.attention__source{margin:3px 0 0;color:var(--muted);font:10.5px var(--font-mono);overflow-wrap:anywhere}
.attention--empty{padding:26px;text-align:center;color:var(--muted)}
.pipeline{display:flex;align-items:stretch;gap:0;border:1px solid var(--line);border-radius:var(--radius-m);background:#0b1017;overflow-x:auto}
.pipeline__stage{flex:1 1 0;min-width:118px;padding:14px 13px;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:7px}
.pipeline__stage:last-child{border-right:0}
.pipeline__stage b{font-size:10px;font-weight:800;letter-spacing:.1em;color:var(--muted);text-transform:uppercase}
.pipeline__stage .sev{align-self:flex-start}
.pipeline__value{font:12.5px var(--font-mono);color:var(--text-soft);overflow-wrap:break-word}
.pipeline__value small{display:block;color:var(--muted);font-size:10.5px;margin-top:2px}
.statusrows{border:1px solid var(--line);border-radius:var(--radius-m);overflow:hidden}
.statusrow{display:grid;grid-template-columns:minmax(150px,230px) minmax(0,1fr) auto;gap:14px;align-items:center;padding:11px 15px;border-bottom:1px solid var(--line);background:#0d131c}
.statusrow:last-child{border-bottom:0}
.statusrow dt{margin:0;color:var(--text-soft);font-size:13px;font-weight:650}
.statusrow dt small{display:block;color:var(--muted);font-weight:500;font-size:11px;margin-top:2px}
.statusrow dd{margin:0;color:var(--text);font:12.5px var(--font-mono);overflow-wrap:anywhere;min-width:0}
.statusrow dd small{display:block;margin-top:3px;color:var(--muted);font-family:var(--text);font-size:11px}
.metricstrip{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px}
.metricstrip__item{padding:12px 14px;border:1px solid var(--line);border-radius:8px;background:#0d131c;display:flex;flex-direction:column;align-items:flex-start;min-width:0;overflow:hidden}
.metricstrip__item dt{margin:0;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;overflow-wrap:anywhere}
.metricstrip__item dd{margin:7px 0 0;font:14px var(--font-mono);font-weight:700;letter-spacing:-.01em;overflow-wrap:anywhere;max-width:100%}
.metricstrip__item dd small{display:block;color:var(--muted);font-weight:500;font-size:11px}
.metricstrip__item .sev{margin-top:9px}
.hgroup{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.horizon{padding:16px 17px;background:#0d131c;border:1px solid var(--line);border-radius:var(--radius-m);position:relative;overflow:hidden}
.horizon:after{content:"";position:absolute;inset:auto -15% -55% 30%;height:120px;background:radial-gradient(circle,rgba(81,199,217,.08),transparent 65%)}
.horizon__head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}
.horizon__key{font:800 12px var(--font-mono);letter-spacing:.12em;color:var(--cyan)}
.horizon h3{margin:0 0 2px;font-size:16px;letter-spacing:-.01em}
.horizon__tf{color:var(--muted);font:11px var(--font-mono)}
.horizon table{min-width:0;margin-top:10px}
.horizon td{padding:6px 8px;font-size:12px}
.horizon td:first-child{color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;width:118px}
.coverage{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:var(--radius-m);overflow:hidden}
.coverage__row{display:grid;grid-template-columns:minmax(170px,240px) minmax(0,1fr) auto;gap:16px;align-items:center;padding:13px 16px;border-bottom:1px solid var(--line);background:#0d131c}
.coverage__row:last-child{border-bottom:0}
.coverage__name{font-weight:700;font-size:13px}
.coverage__name small{display:block;color:var(--muted);font-weight:500;font-size:11px;margin-top:2px;font-family:var(--font-mono);overflow-wrap:anywhere}
.coverage__bar{height:6px;border-radius:3px;background:var(--surface-soft);overflow:hidden;margin-top:7px}
.cov-fill{display:block;width:0;height:100%;border-radius:3px;background:var(--unknown);transition:width .3s ease}
.coverage__bar--ok .cov-fill{background:var(--ok)}
.coverage__bar--warn .cov-fill{background:var(--warn)}
.coverage__bar--fail .cov-fill{background:var(--fail)}
.coverage__bar--blocked .cov-fill{background:var(--blocked)}
.coverage__bar--degraded .cov-fill{background:var(--degraded)}
.coverage__nums{font:12px var(--font-mono);color:var(--text-soft);text-align:right;white-space:nowrap}
.coverage__nums small{display:block;color:var(--muted);font-size:10.5px}
.incident{border:1px solid var(--fail-line);border-radius:var(--radius-m);background:linear-gradient(150deg,rgba(52,23,32,.35),rgba(12,17,24,.98));padding:16px 18px}
.incident dl{margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px 18px}
.incident dt{color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase}
.incident dd{margin:4px 0 0;font:12.5px var(--font-mono);overflow-wrap:anywhere}
.gates{border:1px solid var(--line);border-radius:var(--radius-m);overflow:hidden}
.gate{display:grid;grid-template-columns:minmax(120px,180px) auto minmax(0,1fr) auto;gap:14px;align-items:center;padding:11px 15px;border-bottom:1px solid var(--line);background:#0d131c}
.gate:last-child{border-bottom:0}
.gate>*{min-width:0}
.gate b{font:12.5px var(--font-mono);overflow-wrap:anywhere}
.gate span{color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.gate .gate__owner{color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;align-items:start}
.split>*{min-width:0}
.cc-note{margin:10px 0 0;color:var(--muted);font-size:11.5px;line-height:1.55}
.cc-note b{color:var(--text-soft)}
@media(max-width:1180px){.state-banner{grid-template-columns:1fr}.state-banner__primary{border-right:0;border-bottom:1px solid var(--line)}.hgroup{grid-template-columns:1fr}.split{grid-template-columns:1fr}}
@media(max-width:820px){.cc-page-head{flex-direction:column;align-items:flex-start}.cc-meta{text-align:left}.pipeline{flex-direction:column}.pipeline__stage{border-right:0;border-bottom:1px solid var(--line);min-width:0}.pipeline__stage:last-child{border-bottom:0}}
@media(max-width:520px){.statusrow{grid-template-columns:1fr;gap:6px}.coverage__row{grid-template-columns:1fr;gap:8px}.coverage__nums{text-align:left}.gate{grid-template-columns:1fr;gap:6px}.state-banner__state{font-size:24px}}
td{overflow-wrap:break-word}
.legacy-nav{position:static;width:auto;margin:14px 0 0}
.nav__group{display:flex;flex-direction:column;gap:3px;padding-top:14px}
.nav__group:first-child{padding-top:0}
.nav__label{margin:0 0 2px;padding:0 12px;color:#5f6d80;font-size:9px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}
.status-matrix{margin:14px 0 12px;padding:12px 10px;border:1px solid var(--line);border-radius:8px;background:#0b1017;display:grid;gap:7px}
.status-matrix__row{display:flex;justify-content:space-between;gap:10px;align-items:center}
.status-matrix__row span{color:var(--muted);font-size:9.5px;font-weight:800;letter-spacing:.11em;text-transform:uppercase}
.status-matrix__row b{font:700 10.5px var(--font-mono);letter-spacing:.06em;color:var(--text-soft)}
.status-matrix__row b[data-sev="ok"]{color:var(--ok)}
.status-matrix__row b[data-sev="info"]{color:var(--info)}
.status-matrix__row b[data-sev="warn"]{color:var(--warn)}
.status-matrix__row b[data-sev="degraded"]{color:var(--degraded)}
.status-matrix__row b[data-sev="fail"]{color:var(--fail)}
.status-matrix__row b[data-sev="blocked"]{color:var(--blocked)}
.status-matrix__row b[data-sev="unknown"]{color:var(--unknown)}
.status-matrix__row b[data-sev="disabled"]{color:var(--disabled)}
.status-matrix__row--locked b{color:var(--fail)!important}
@media(max-width:820px){.nav__group{display:contents}.nav__label{display:none}}
.statusrow__state{text-align:right}
.cc-note--flush{margin-top:0}
.block-gap{margin-top:14px}
.block-gap-sm{margin-top:12px}
.table--gaps{min-width:1080px;table-layout:fixed}
.u-col-185{width:185px}.u-col-165{width:165px}.u-col-195{width:195px}.u-col-150{width:150px}.u-col-124{width:124px}.u-col-84{width:84px}
.safety-callout--info{border-left-color:var(--info);background:var(--info-soft);color:#bfdaff}
.setup-chart{padding:14px;overflow:hidden}.setup-chart svg{display:block;width:100%;height:auto;min-height:250px}.setup-chart text{fill:var(--muted);font:11px var(--font-mono)}.setup-chart__frame{fill:#0b1017;stroke:var(--line);stroke-width:1}.setup-chart__line{fill:none;stroke:var(--cyan);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

""" + "".join(f".cov-fill--{percent}{{width:{percent}%}}" for percent in range(101))


# ---------------------------------------------------------------------------
# Python primitives
# ---------------------------------------------------------------------------

def chip(status: Any, label: str | None = None) -> str:
    """Semantic status chip. The text label is always rendered (a11y)."""
    key = severity(status)
    text = label or short_state(status)
    return f"<span class='sev sev--{key}'>{_esc(text)}</span>"


def evidence_chip(status: Any, raw: Any = None) -> str:
    """Chip that preserves the original evidence wording next to the severity."""
    key = severity(status)
    text = str(raw if raw not in (None, "") else status if status not in (None, "") else UNAVAILABLE)
    return f"<span class='sev sev--{key}'>{_esc(text)}</span>"


def section(eyebrow: str, title: str, body: str, *, note: str = "", meta: str = "", badge: str = "") -> str:
    meta_parts = [part for part in (meta, badge) if part]
    head_meta = f"<div class='cc-section__meta'>{'<br>'.join(meta_parts)}</div>" if meta_parts else ""
    note_html = f"<p class='cc-section__note'>{_esc(note)}</p>" if note else ""
    return (
        "<section class='cc-section'>"
        f"<div class='cc-section__head'><div><p class='cc-section__eyebrow'>{_esc(eyebrow)}</p>"
        f"<h2>{_esc(title)}</h2>{note_html}</div>{head_meta}</div>"
        f"{body}</section>"
    )


def page_head(title: str, lead: str, *, generated_at: Any = None, safety_stack: bool = True) -> str:
    meta_lines = []
    if generated_at:
        meta_lines.append(f"generated {_esc(generated_at)} UTC")
    meta_html = f"<div class='cc-meta'>{'<br>'.join(meta_lines)}</div>" if meta_lines else ""
    safety = (
        "<div class='safety-stack' aria-label='Sicherheitsmodus'>"
        "<span class='badge badge--green'>OBSERVE-ONLY</span>"
        "<span class='badge badge--green'>TRADING LOCKED</span>"
        "<span class='badge badge--green'>EXECUTION DISABLED</span></div>"
    ) if safety_stack else ""
    right = f"<div class='cc-page-head__right'>{meta_html}{safety}</div>" if (meta_lines or safety) else ""
    return (
        "<div class='cc-page-head'><div>"
        f"<h1>{_esc(title)}</h1><p>{_esc(lead)}</p></div>{right}</div>"
        + ("<div class='cc-safety' role='list' aria-label='Systemgrenzen'>"
           "<span role='listitem'>READ-ONLY</span><span role='listitem'>NO ORDERS</span>"
           "<span role='listitem'>NO SHELL</span><span role='listitem'>NO GIT</span>"
           "<span role='listitem'>NO SECRETS</span><strong role='listitem'>EXECUTION DISABLED</strong></div>"
           if safety_stack else "")
    )


def state_banner(state_status: Any, state_label: str, sub: str, metrics: Iterable[tuple[str, Any, str]]) -> str:
    """Level 1 primitive: primary system state with a bounded metric strip.

    ``metrics`` yields (label, value, note) tuples; a value of ``None`` renders
    as UNAVAILABLE, never as 0.
    """
    items = []
    for label, value, note in metrics:
        shown = _esc(value) if value not in (None, "") else UNAVAILABLE
        note_html = f"<small>{_esc(note)}</small>" if note else ""
        items.append(f"<div class='state-banner__metric'><dt>{_esc(label)}</dt><dd>{shown}{note_html}</dd></div>")
    return (
        f"<div class='state-banner state-banner--{severity(state_status)}' role='status'>"
        "<div class='state-banner__primary'>"
        f"{chip(state_status, state_label)}"
        f"<p class='state-banner__state'>{_esc(state_label)}</p>"
        f"<p class='state-banner__sub'>{_esc(sub)}</p></div>"
        f"<dl class='state-banner__metrics'>{''.join(items)}</dl></div>"
    )


def attention_row(kind: str, title: str, detail: str, source: str = "") -> str:
    source_html = f"<p class='attention__source'>{_esc(source)}</p>" if source else ""
    return (
        "<div class='attention__row'>"
        f"{chip(kind)}"
        f"<div class='attention__body'><p class='attention__title'>{_esc(title)}</p>"
        f"<p class='attention__detail'>{_esc(detail)}</p>{source_html}</div></div>"
    )


def attention_list(rows: Iterable[str], empty_message: str) -> str:
    body = "".join(rows)
    if not body:
        return f"<div class='attention attention--empty'>{_esc(empty_message)}</div>"
    return f"<div class='attention'>{body}</div>"


def pipeline(stages: Iterable[tuple[str, Any, str, str]]) -> str:
    """Pipeline visualization. Yields (name, status, value, note) per stage."""
    cells = []
    for name, status, value, note in stages:
        note_html = f"<small>{_esc(note)}</small>" if note else ""
        cells.append(
            f"<div class='pipeline__stage'><b>{_esc(name)}</b>"
            f"{chip(status)}"
            f"<div class='pipeline__value'>{_esc(value)}{note_html}</div></div>"
        )
    return f"<div class='pipeline' role='list' aria-label='Datenpipeline'>{''.join(cells)}</div>"


def status_rows(rows: Iterable[tuple[str, str, Any, str, str]]) -> str:
    """Status rows: (label, label_note, status, value, value_note)."""
    out = []
    for label, label_note, status, value, value_note in rows:
        note_html = f"<small>{_esc(value_note)}</small>" if value_note else ""
        label_note_html = f"<small>{_esc(label_note)}</small>" if label_note else ""
        out.append(
            "<div class='statusrow'>"
            f"<dt>{_esc(label)}{label_note_html}</dt>"
            f"<dd>{_esc(value) if value not in (None, '') else UNAVAILABLE}{note_html}</dd>"
            f"<dd class='statusrow__state'>{evidence_chip(status)}</dd></div>"
        )
    return f"<dl class='statusrows'>{''.join(out)}</dl>"


def metric_strip(items: Iterable[tuple[str, Any, str, Any]]) -> str:
    """Compact metric strip: (label, value, unit, status)."""
    out = []
    for label, value, unit, status in items:
        present = value not in (None, "")
        has_status = status not in (None, "") and severity(status) != "unknown"
        value_html = ""
        if present:
            shown = _esc(value)
            if unit:
                shown = f"{shown} <small>{_esc(unit)}</small>"
            value_html = f"<dd>{shown}</dd>"
        elif not has_status:
            value_html = f"<dd>{UNAVAILABLE}</dd>"
        out.append(
            f"<div class='metricstrip__item'><dt>{_esc(label)}</dt>{value_html}"
            f"{evidence_chip(status) if status not in (None, '') else ''}</div>"
        )
    return f"<dl class='metricstrip'>{''.join(out)}</dl>"


def coverage_rows(datasets: Iterable[dict[str, Any]]) -> str:
    out = []
    for item in datasets:
        key = severity(item.get("status"))
        percent_text = str(item.get("coverage", UNAVAILABLE))
        fill_class = ""
        try:
            number = float(str(percent_text).rstrip("%"))
            fill_class = f" cov-fill--{int(round(min(max(number, 0), 100)))}"
        except ValueError:
            pass
        out.append(
            "<div class='coverage__row'>"
            f"<div class='coverage__name'>{_esc(item.get('label'))}"
            f"<small>{_esc(item.get('source'))}</small>"
            + (f"<small class='disposition'>{_esc(item.get('disposition'))}</small>" if item.get("disposition") else "")
            + "</div>"
            f"<div><div class='coverage__nums'>{_esc(percent_text)} · {_esc(item.get('observed'))} / {_esc(item.get('expected'))}</div>"
            f"<div class='coverage__bar coverage__bar--{key}'><span class='cov-fill{fill_class}'></span></div></div>"
            f"<div>{evidence_chip(item.get('status'))}</div></div>"
        )
    return f"<div class='coverage'>{''.join(out)}</div>"


def gate_rows(gates: Iterable[dict[str, Any]]) -> str:
    out = []
    for gate in gates:
        evidence = gate.get("evidence", [])
        evidence = evidence if isinstance(evidence, str) else ", ".join(str(value) for value in evidence)
        evidence_html = f"<span class='gate__owner' title=''>{_esc(evidence)}</span>" if evidence else ""
        out.append(
            "<div class='gate'>"
            f"<b>{_esc(gate.get('id'))}</b>{evidence_chip(gate.get('status'))}"
            f"<span>{_esc(gate.get('limitation'))}"
            + (f"<br><span class='gate__now'>Heute: {evidence_chip(gate.get('current_status'))} {_esc(gate.get('current_note'))}</span>" if gate.get("current_status") else "")
            + "</span>"
            f"<span class='gate__owner'>{_esc(gate.get('owner'))}</span></div>"
        )
    return f"<div class='gates'>{''.join(out)}</div>"


def incident_card(incident: Any, fallback: str = "No incident recorded in the bounded timeline window.") -> str:
    if not incident or incident == UNAVAILABLE:
        return f"<div class='attention attention--empty'>{_esc(fallback)}</div>"
    if isinstance(incident, str):
        return f"<div class='incident'><dl><div><dt>Event</dt><dd>{_esc(incident)}</dd></div></dl></div>"
    rows = "".join(f"<div><dt>{_esc(key)}</dt><dd>{_esc(value)}</dd></div>" for key, value in sorted(incident.items()) if value not in (None, ""))
    return f"<div class='incident'><dl>{rows}</dl></div>"


def cell_state(status: Any) -> str:
    """Dense-table status text: colored dot + raw value, wraps within its column."""
    key = severity(status)
    text = str(status if status not in (None, "") else UNAVAILABLE)
    return f"<span class='cellstate cellstate--{key}'>{_esc(text)}</span>"


def horizon_panel(horizons: Iterable[tuple[str, str, str, str, list[tuple[str, Any]]]]) -> str:
    """Horizon readiness cards. Tuples: (key, name, timeframes, description, dimensions).

    ``dimensions`` are (label, status) pairs rendered as evidence chips; missing
    per-horizon evidence renders as UNKNOWN, never as a direction or signal.
    """
    cards = []
    for key, name, timeframes, description, dimensions in horizons:
        dim_rows = "".join(
            f"<tr><td>{_esc(label)}</td><td>{evidence_chip(status, raw=status)}</td></tr>"
            for label, status in dimensions
        )
        cards.append(
            "<article class='horizon'>"
            f"<div class='horizon__head'><div><h3>{_esc(name)}</h3>"
            f"<span class='horizon__tf'>{_esc(timeframes)}</span></div>"
            f"<span class='horizon__key'>{_esc(key)}</span></div>"
            f"<p class='cc-note cc-note--flush'>{_esc(description)}</p>"
            f"<table><tbody>{dim_rows}</tbody></table></article>"
        )
    return f"<div class='hgroup'>{''.join(cards)}</div>"
