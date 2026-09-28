"""Verifiable single-case export.

Turns one research case into a self-contained JSON artifact and a standalone
HTML page that anyone can check: the ``output_hash`` is the SHA-256 of the
canonical JSON of the artifact without that field, the same contract used by
``src/research_ops/audit.py`` (OUTPUT_HASH_MISMATCH). Research evidence only,
no recommendation, no forecast, no signal.
"""

from __future__ import annotations

import base64
import html
import json
from datetime import datetime
from typing import Any

from src.research.case_engine import ResearchCase
from src.research_ops.audit import SHA256, canonical, digest


SCHEMA_VERSION = "1.0.0"
ARTIFACT = "tim_research_case"
DISCLAIMER = "Research-Beleg: keine Empfehlung, keine Prognose, kein Handelssignal."


def build_case_export(case: ResearchCase | dict[str, Any], *, exported_at: datetime) -> dict[str, Any]:
    if exported_at.tzinfo is None:
        raise ValueError("exported_at must be timezone-aware")
    payload = case.to_dict() if isinstance(case, ResearchCase) else dict(case)
    if not payload.get("case_id"):
        raise ValueError("case_id required")
    # Round-trip through canonical JSON so the stored artifact equals what was hashed.
    export = json.loads(canonical({
        "artifact": ARTIFACT,
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at.isoformat(),
        "disclaimer": DISCLAIMER,
        "case": payload,
    }))
    export["output_hash"] = digest(export)
    return export


def verify_case_export(export: dict[str, Any]) -> bool:
    body = dict(export)
    declared = str(body.pop("output_hash", ""))
    return bool(SHA256.fullmatch(declared)) and digest(body) == declared


def to_json(export: dict[str, Any]) -> str:
    return json.dumps(export, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _rows(items: list[tuple[str, Any]]) -> str:
    return "".join(f"<tr><th>{_e(key)}</th><td>{_e(value)}</td></tr>" for key, value in items)


def to_html(export: dict[str, Any]) -> str:
    case = export["case"]
    body = dict(export)
    body.pop("output_hash", None)
    # The exact hashed bytes are embedded (base64) so the browser check hashes the same bytes.
    embedded = base64.b64encode(canonical(body).encode()).decode()
    evidence = "".join(
        f"<tr><td>{_e(item.get('observed_at'))}</td><td>{_e(item.get('kind'))}</td>"
        f"<td class='mono'>{_e(item.get('observation_id'))}</td><td class='mono'>{_e(item.get('input_hash'))}</td></tr>"
        for item in case.get("evidence", [])
    ) or "<tr><td colspan='4'>keine</td></tr>"
    missing = "".join(f"<li>{_e(item)}</li>" for item in case.get("missing_evidence", [])) or "<li>keine</li>"
    rules = "".join(f"<li class='mono'>{_e(rule)} = {_e(version)}</li>" for rule, version in sorted(case.get("rule_versions", {}).items())) or "<li>keine</li>"
    facts = _rows([
        ("Case", case.get("case_id")), ("Symbol", case.get("symbol")), ("Timeframe", case.get("timeframe")),
        ("Eröffnet", case.get("opened_at")), ("Aktualisiert", case.get("updated_at")), ("Status", case.get("status")),
        ("Outcome", case.get("outcome") or "offen"), ("Exportiert", export.get("exported_at")),
    ])
    return f"""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{_e(case.get('case_id'))} · TIM Research-Beleg</title>
<style>
:root{{--bg:#0b0f14;--fg:#e6edf3;--muted:#8b98a5;--line:#243040;--ok:#3fb950;--bad:#f85149}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}}
.note{{border:1px solid var(--line);border-radius:8px;padding:10px 14px;color:var(--muted)}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:500;width:160px}} .mono{{font-family:ui-monospace,monospace;font-size:12px;word-break:break-all}}
.scroll{{overflow-x:auto}} .scroll table{{min-width:720px}} .ok{{color:var(--ok);border-color:var(--ok)}} .bad{{color:var(--bad);border-color:var(--bad)}}
</style></head><body><main>
<h1>TIM Research-Beleg</h1>
<p id='check' class='note'>Prüfung läuft … (ohne JavaScript bitte mit dem Skript prüfen)</p>
<div id='content'>
<p class='note'>{_e(export.get('disclaimer'))}</p>
<h2>Fall</h2><table>{facts}</table>
<h2>Belege</h2><div class='scroll'><table><tr><th>Zeit</th><th>Art</th><th>Observation</th><th>Input-Hash</th></tr>{evidence}</table></div>
<h2>Fehlende Belege</h2><ul>{missing}</ul>
<h2>Regelversionen</h2><ul>{rules}</ul>
</div>
<h2>Prüfung</h2>
<p>Output-Hash (SHA-256): <span id='hash' class='mono'>{_e(export.get('output_hash'))}</span></p>
<p class='note'>Die Seite zeigt nur Inhalte an, deren Hash stimmt. Als Zeitnachweis zählt, wo und wann dieser Hash
zuerst veröffentlicht wurde. Unabhängig prüfen: <span class='mono'>python3 scripts/verify_case.py {_e(case.get('case_id'))}.json</span></p>
<script type='text/plain' id='tim-case'>{embedded}</script>
<script>
(async()=>{{
const HASH={json.dumps(export.get('output_hash'))};
const el=document.getElementById('check'),box=document.getElementById('content');
const h=(tag,text,cls)=>{{const n=document.createElement(tag);if(text!==undefined)n.textContent=text==null?'':String(text);if(cls)n.className=cls;return n;}};
const table=(head,rows)=>{{const t=h('table');if(head){{const r=h('tr');head.forEach(x=>r.append(h('th',x)));t.append(r);}}
rows.forEach(row=>{{const r=h('tr');row.forEach(([v,c,th])=>r.append(h(th?'th':'td',v,c)));t.append(r);}});return t;}};
const list=(items,cls)=>{{const u=h('ul');(items.length?items:['keine']).forEach(x=>u.append(h('li',x,cls)));return u;}};
try{{
const bytes=Uint8Array.from(atob(document.getElementById('tim-case').textContent.trim()),c=>c.charCodeAt(0));
const hex=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
document.getElementById('hash').textContent=HASH;
box.replaceChildren();
if(hex!==HASH){{el.textContent='✗ Inhalt stimmt NICHT mit dem Hash überein. Inhalt wird nicht angezeigt.';el.className='note bad';return;}}
const d=JSON.parse(new TextDecoder().decode(bytes)),c=d.case;
const facts=[['Case',c.case_id],['Symbol',c.symbol],['Timeframe',c.timeframe],['Eröffnet',c.opened_at],['Aktualisiert',c.updated_at],['Status',c.status],['Outcome',c.outcome||'offen'],['Exportiert',d.exported_at]];
const ev=(c.evidence||[]).map(e=>[[e.observed_at],[e.kind],[e.observation_id,'mono'],[e.input_hash,'mono']]);
const sc=h('div',undefined,'scroll');sc.append(table(['Zeit','Art','Observation','Input-Hash'],ev.length?ev:[[['keine']]]));
box.append(h('p',d.disclaimer,'note'),h('h2','Fall'),table(null,facts.map(([k,v])=>[[k,'',true],[v]])),h('h2','Belege'),sc,
h('h2','Fehlende Belege'),list(c.missing_evidence||[]),h('h2','Regelversionen'),list(Object.keys(c.rule_versions||{{}}).sort().map(k=>k+' = '+c.rule_versions[k]),'mono'));
el.textContent='✓ Inhalt stimmt mit dem Hash überein.';el.className='note ok';
}}catch(e){{el.textContent='Browser-Prüfung hier nicht verfügbar – angezeigter Inhalt ist ungeprüft, bitte mit dem Skript prüfen.';el.className='note bad';}}
}})();
</script>
</main></body></html>
"""
