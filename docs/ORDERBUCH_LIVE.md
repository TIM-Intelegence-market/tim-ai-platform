# Orderbuch live (`/orderbuch`)

Read-only Seite im Bereich Cockpit: Live-Orderbuch, Tiefendiagramm und Liquiditäts-Heatmap für BTC, ETH, SOL.

**Quellen (öffentlich, ohne Key):** Binance `wss://stream.binance.com:9443/ws/<symbol>@depth@100ms` plus REST-Snapshot
`api.binance.com/api/v3/depth` (offizielles Sync-Verfahren: puffern, Snapshot, `U <= lastUpdateId+1 <= u`, Lücke = neu laden).
Fallback Coinbase Exchange `level2_batch`. Auto-Modus wechselt nach zwei Fehlversuchen zu Coinbase.

**Architektur:** Der Browser verbindet sich direkt mit der Börse; der TIM-Server liefert nur Seite und Skripte
(`src/dashboard/pages/orderbook.py`, `assets/orderbook_core.js` = reine Logik, `assets/orderbook.js` = Anzeige).
Die Seite hat eine eigene CSP: `connect-src` nur `'self'` und die drei Börsen-Endpunkte, keine Inline-Styles/-Skripte
über die gemeinsame Basis hinaus. Keine Orders, keine Keys, nichts wird gespeichert (TRADING bleibt LOCKED).

**Mikrostruktur-Kennzahlen:** bestes Gebot/Angebot, Spread (bp), Mikropreis, Ungleichgewicht der Top 10 Stufen, Updates/s.
Heatmap: eine Spalte pro Sekunde, ±1 % um die Mitte, ca. 8 Minuten. Sie zeigt sichtbare Liquidität, keine Ausführung (Spoofing möglich).

**Tests:** `node --test tests/js/orderbook_core.test.js` (Book, Sync, Tiefe, Heatmap), `pytest tests/test_orderbook_page.py`.
**Nicht geprüft:** echte Börsenverbindung (Cloud erreicht Binance nicht); Test mit simuliertem WebSocket. Coinbase-`level2_batch` ohne Key ist nicht belegt.
Binance ist aus manchen Ländern (z. B. USA) gesperrt, dann greift der Coinbase-Fallback.
