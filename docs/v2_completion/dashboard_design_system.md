# TIM Dashboard V2: Design System

**PROGRAM 2 — Professional Dashboard V2 — Design Baseline**

Program: `TIM-V2-COMPLETION-PROGRAM-20260803`

## Scope

Design tokens, component inventory, layout, and responsiveness of the
"TIM OPERATIONS & RESEARCH CONTROL CENTER" (server-rendered, no build step,
dark-first). The source of truth is the `CSS`/`EXTRA_CSS` blocks in
`src/dashboard/app.py`.

## 1. Tokens (`:root`, dark scheme)

|Token|Value|Purpose|
|---|---|---|
|`--bg`|`#08111f`|page background|
|`--panel`|`#101c2e`|card/panel base|
|`--panel2`|`#132238`|hover/active|
|`--line`|`#263852`|borders, table rules|
|`--text`|`#e9f0f8`|primary text|
|`--muted`|`#91a2b8`|secondary text|
|`--green`|`#3ddc97`|pass/health|
|`--yellow`|`#f6c85f`|warn/degraded|
|`--red`|`#ff6b6b`|fail/error|
|`--blue`|`#66a6ff`|links, interactive|
|`--radius`|`14px`|panel radius|

Color scheme is declared via `color-scheme: dark` and the HTML
`<meta name='color-scheme' content='dark'>`.

## 2. Typography

- Body: `14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`.
- Code/hashes: `ui-monospace, SFMono-Regular, Menlo, monospace` (`.mono`).
- H1: `30px`, section h2: `19px`, table th: `11px` uppercase.
- `pre.code` renders JSON with `pre-wrap` + `word-break`, max height `420px`.

## 3. Component inventory

|Component|Class|Notes|
|---|---|---|
|App bar|`.topbar` + `.topbar__inner`|fixed→sticky; brand + primary nav + live status button|
|Primary nav|`.nav`|10 primary pages; `.active`/`aria-current='page'`|
|Legacy nav|`.legacy-nav details`|collapsible secondary research views|
|Live status|`#tim-status` button|`aria-live=polite`, yellow until first poll|
|Hero|`.hero`|page title + read-only note|
|Card|`.card`|`.card__label/.card__value/.card__note`|
|Operations card|`.operations-card`|status color rail via `:has(.badge--*)`|
|Panel|`.panel` + `.panel__head`|section container with heading/actions|
|Badge|`.badge--green/--yellow/--red/--snapshot`|status pill|
|Tag|`.tag`|inline chip (downloads, filters)|
|Table|`.table-wrap > table`|sticky header, horizontal scroll on narrow|
|Detail grid|`.detail-grid` / `.detail`|key-value pairs|
|Health card|`.health-card details`|expandable diagnostics|
|Filters|`.filters`|grid of labelled inputs|
|Safety callout|`.safety-callout` / `.operations-boundary`|green-bordered observe-only notice|

## 4. Layout & responsiveness

Primary shell max-width `1480px`, centered, `76px` top padding for the fixed bar.

Breakpoints (all `max-width`):

|Breakpoint|Behavior|
|---|---|
|`1180px`|operations grid 4→3 columns|
|`820px`|operations grid 3→2; topbar stacks (brand row, live, nav); hero stacks; safety stack wraps|
|`680px`|health meta + panel heads stack vertically|
|`520px`|operations grid → 1 column; nav becomes horizontally scrollable `nowrap`; legacy nav 2-column; brand/status shrink|

Honesty guard rails:
- Tables never set a body-level fixed width; wide tables scroll inside
  `.table-wrap` (`min-width:850px` on `table` only).
- `.shell`/`.topbar`/`.footer` use `max-width` + `padding-inline`, so no
  horizontal overflow at any breakpoint.

## 5. Accessibility contract

- Skip link (`Zum Hauptinhalt springen`) present and focusable.
- `:focus-visible` ring (`3px #9bc4ff`).
- One `h1` per page; `main#main-content` landmark; labelled `<nav>`.
- `aria-live="polite"` on the live status button; `aria-label`s on brand/status.
- No inline `on*` handlers anywhere.
- `prefers-reduced-motion: reduce` kills transitions/animations/scroll-behavior.
- `forced-colors: active` keeps visible borders for badges/cards/panels.

## 6. Content-Security-Policy

Strict by default (`default-src 'none'`); scripts and styles are inlined with
SHA-256 hashes; `unsafe-inline` is absent. HTTP headers set on every response:
CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `Permissions-Policy`, COOP, CORP.

## 7. Enforcement

CI (`tests/test_operations_dashboard_ui.py`) verifies: exact primary pages,
safety invariants, per-page real-or-unavailable state, secret redaction,
a11y/responsive contract (skip-link, focus ring, all breakpoints,
`prefers-reduced-motion`, `forced-colors`), and live HTTP header/CSP checks.