# TIM Dashboard 4.1

Version 4.1.0 (2026-09-28) merges the live Control Center (4.0.0, branch `opencode/rolling-liveness-ops-fix`,
PR #87 plus the live snapshot) with Dashboard 3.0 from `platform-main`. See the addenda in
`docs/TIM_CORE_1_0_FREEZE.md`. Layout and operations pages are the Control Center; German labels,
lifecycle badges, case proofs, retrospective and the pilot view come from 3.0.
The dashboard stays OBSERVE-only and read-only on `127.0.0.1:8765`. The research core
(rules, thresholds, metrics, validation, outcomes, data) is unchanged.

## Code structure

| Module | Content |
|---|---|
| `src/dashboard/app.py` | Compatibility layer, re-exports every previous name (`DashboardServer`, `DashboardState`, `render`, …) |
| `constants.py` | `DASHBOARD_VERSION`, visible limits, `MAX_RESPONSE_BYTES`, allowed timeline events |
| `security.py` | Loopback-only bind and Host-header check (DNS rebinding) |
| `helpers.py` | Formatting and status helpers, `_case_status` (case lifecycle badges) |
| `state.py` | `DashboardState` (snapshot incl. operations, gate model, live cutover) |
| `api.py` | `_research_cases_collection` (filters, pagination, stats) |
| `components.py` | Table rows, health cards, timeline rows, `_case_proof_panel` |
| `layout.py` | Control Center frame, status matrix, `NAV_GROUPS`, CSP (`_content_security_policy_for`) |
| `design_system.py`, `operations.py` | Control Center components and the ten operations pages |
| `i18n.py` | German label catalog applied to whole text nodes of the final HTML |
| `views.py` | `render()` for all operator pages |
| `pages/signals.py`, `pages/operations.py`, `pages/setup_path.py`, `pages/pilot.py` | Signal research; health center, data quality, timeline; setup path; pilot view |
| `server.py` | HTTP routing and security headers |
| `assets/style.css`, `assets/extra.css`, `assets/auto_refresh.html` | Control Center styles, polling script |

## Navigation

Betrieb (Überblick, Laufzeit, Datenqualität, Vorfälle & Lücken, Systemzustand,
Datenqualitäts-Ausnahmen, Zeitleiste) · Forschung (Beobachtungen, Research-Fälle, Orderflow,
Signal-Research, Analysen, Erkenntnisse, Unabhängige Fälle, Qualifikation, Setup-Pfad) ·
Freigabe (V2-Bereitschaft) · System (Sicherheit, Audit & Evidenz, Graphify & MCP) ·
Werkzeuge (Recherche-Werkzeug, Pilotansicht). Below 820 px the sidebar becomes a horizontally
scrollable bar above the status matrix.

## Design and security rules

- Dark Control Center theme. Status is never colour alone: badges carry ✓ / ! / ✕ / ◷ plus text.
- Case lifecycle colours: in progress yellow, confirmed green, closed/rejected neutral, quarantined red.
- No horizontal page scroll at 390 px; wide tables scroll inside their container.
- Safety markers stay visible: `OBSERVE-ONLY`, `TRADING LOCKED`, `EXECUTION DISABLED`.
- Labels are translated via `i18n.py`; data containers (`td`, `dd`, `pre`, `code`, `option`,
  `.mono`, `.tag`, `.badge`) are never translated. Long evidence texts of the operations pages
  stay in their original (English) wording.
- The server binds to loopback only and answers 421 to non-loopback `Host` headers.
- Every HTML response gets a Content-Security-Policy that allows exactly the inline `<style>` and
  executable `<script>` blocks of that page (SHA-256), never `unsafe-inline`. JSON responses keep
  the global policy.

## Routes

Unchanged against the live Control Center (byte-identical in the golden comparison apart from
version strings): all pages (`/`, `/runtime`, `/data-quality`, `/gaps`, `/qualification`,
`/independent-cases`, `/v2-readiness`, `/mcp`, `/security`, `/audit-evidence`, `/setup-path`,
`/observations`, `/cases`, `/orderflow`, `/signals`, `/analytics`, `/insights`, `/health`,
`/exceptions`, `/timeline`, `/research`), `/api/state`, `/api/operations`, `/api/health`,
`/api/analytics`, `/api/insights`, `/api/readiness`, `/api/cases/<id>`, `/api/observations/<id>`,
`/api/rag`, `/api/llm/explain`, `/exports/analytics.*`, `/exports/insights.*`, `/reports/<name>`,
`POST /api/research/{quick,deep}`.

Added from `platform-main`:

| Route | Purpose |
|---|---|
| `/api/research-cases[/stats|/<id>]` | Research Case Explorer API |
| `/exports/case/<id>.json`, `.html` | Verifiable research-case proof (`src/research/case_export.py`); orderflow cases include the `RETROSPECTIVE` block |
| `/api/orderflow/history` | `{"observations": [...], "validations": [...]}` for exports |
| `/pilot` | Pilot view for coaches and pilot customers |

## Pilot view

Shows only `case_id`, `symbol`, `timeframe`, `opened_at`, `status`, `outcome`, the evidence
count, the retrospective summary and links to the proof. It contains no navigation, no
scripts and no health, runtime, validator, path or event data (enforced by
`tests/test_dashboard_v3.py`). The allowlist limits what the page shows; it is not an access
boundary: the linked proof export contains the full case record (documentation, review
history, evidence hashes) and the same local server also serves the operator pages. It is
served on `127.0.0.1` like the rest of the dashboard; share it by screen sharing or publish
exported proof pages instead.

## Retrospective basis

The retrospective counts outcomes from the orderflow history held in memory (the runtime
keeps the most recent observations). Every block therefore carries a `basis` line such as
"Grundlage: 500 Orderflow-Beobachtungen im geladenen Verlauf, nicht die vollständige
Historie." Two exports of the same case at different times can differ in `n`.

## Proof export from the command line

```bash
python3 scripts/export_case.py <case_id>            # fetches case + orderflow history from the dashboard
python3 scripts/export_case.py <case_id> --no-history
python3 scripts/verify_case.py exports/<case_id>.json
```
