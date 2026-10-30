# Herkunft: TradingView Lightweight Charts 4.2.3

- Datei: `lightweight-charts-4.2.3.standalone.production.js` (unverändert aus dem npm-Paket
  `lightweight-charts@4.2.3`, `dist/lightweight-charts.standalone.production.js`).
- Quelle: https://registry.npmjs.org/lightweight-charts/-/lightweight-charts-4.2.3.tgz
- npm-Integrität des Pakets (geprüft): `sha512-5kS/2hY3wNYNzhnS8Gb+GAS07DX8GPF2YVDnd2NMC85gJVQ6RLU6YrXNgNJ6eg0AnWPwCnvaGtYmGky3HiLQEw==`
- SHA-256 der Datei: `c7dda807d662a95b3d257119ed315cec669e3bdf5aaece75c480a39307f23540`
  (Test `tests/test_chart_live.py::test_vendored_library_is_the_checked_release`).
- Lizenz: Apache 2.0, Copyright TradingView, Inc. (`LICENSE-lightweight-charts`). Die Seite `/chart`
  nennt TradingView mit Link, wie die Lizenzhinweise von Lightweight Charts es verlangen; das
  eingebaute Logo ist aus (`attributionLogo: false`), weil es ein Inline-Style bräuchte, das die CSP sperrt.
- Geprüft am 26.10.2026: keine Netzaufrufe (kein fetch, XMLHttpRequest, WebSocket, eval), einzige
  externe URL ist der Logo-Link auf tradingview.com. Abhängigkeit `fancy-canvas` ist im Standalone-Build enthalten.
- Ausgeliefert vom Control Center unter `/assets/chart/lightweight-charts-4.2.3.js` (nur lokal, kein CDN).
