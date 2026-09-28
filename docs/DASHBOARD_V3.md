# TIM Dashboard 3.0

Released 2026-09-28 by owner decision (see addendum in `docs/TIM_CORE_1_0_FREEZE.md`).
The dashboard stays OBSERVE-only and read-only on `127.0.0.1:8765`. The research core
(rules, thresholds, metrics, validation, outcomes, data) is unchanged.

## Code structure

| Module | Content |
|---|---|
| `src/dashboard/app.py` | Compatibility layer, re-exports every previous name (`DashboardServer`, `DashboardState`, `render`, …) |
| `constants.py` | `DASHBOARD_VERSION`, visible limits, allowed timeline events |
| `helpers.py` | Formatting and status helpers, `_case_status` (case lifecycle badges) |
| `state.py` | `DashboardState` (snapshot, readiness, analytics, insights) |
| `api.py` | `_research_cases_collection` (filters, pagination, stats) |
| `components.py` | Table rows, health cards, timeline rows, `_case_proof_panel` |
| `layout.py` | Page frame, grouped navigation (`NAV_GROUPS`), assets |
| `i18n.py` | German label catalog applied to whole text nodes of the final HTML |
| `views.py` | `render()` for the operator pages |
| `pages/signals.py`, `pages/operations.py` | Signal research; health center, data quality, timeline |
| `pages/pilot.py` | Pilot view |
| `server.py` | HTTP routing |
| `assets/style.css`, `assets/auto_refresh.html`, `assets/nav.html` | Design system, polling script, menu script |

## Navigation

Überblick · Forschung (Beobachtungen, Research-Fälle, Orderflow, Signal-Research, Analysen,
Erkenntnisse) · Betrieb (Systemzustand, Datenqualität, Zeitleiste) · Werkzeuge
(Recherche-Werkzeug, Pilotansicht). On screens below 761 px the navigation collapses into a
"Menü" button.

## Design rules

- Dark theme by default, light theme via the operating system setting.
- Status is never colour alone: badges carry ✓ / ! / ✕ / ◷ plus text.
- Case lifecycle colours: in progress yellow, confirmed green, closed/rejected neutral,
  quarantined red.
- No horizontal page scroll at 390 px; wide tables scroll inside their container.
- Safety markers stay visible: `OBSERVE • READ-ONLY`, `NO ORDERS OR EXECUTION`.

## Routes

Unchanged (byte-identical responses): `/api/state`, `/api/health`, `/api/analytics`,
`/api/insights`, `/api/readiness`, `/api/cases/<id>`, `/api/research-cases[/stats|/<id>]`,
`/api/observations/<id>`, `/exports/analytics.*`, `/exports/insights.*`, all HTML pages'
URLs.

New:

| Route | Purpose |
|---|---|
| `/exports/case/<id>.json`, `.html` | Verifiable research-case proof (`src/research/case_export.py`); orderflow cases include the `RETROSPECTIVE` block |
| `/api/orderflow/history` | `{"observations": [...], "validations": [...]}` for exports |
| `/pilot` | Pilot view for coaches and pilot customers |

## Pilot view

Shows only `case_id`, `symbol`, `timeframe`, `opened_at`, `status`, `outcome`, the evidence
count, the retrospective summary and links to the proof. It contains no navigation, no
scripts and no health, runtime, validator, path or event data (enforced by
`tests/test_dashboard_v3.py`). It is served on `127.0.0.1` like the rest of the dashboard;
share it by screen sharing or publish exported proof pages instead.

## Proof export from the command line

```bash
python3 scripts/export_case.py <case_id>            # fetches case + orderflow history from the dashboard
python3 scripts/export_case.py <case_id> --no-history
python3 scripts/verify_case.py exports/<case_id>.json
```
