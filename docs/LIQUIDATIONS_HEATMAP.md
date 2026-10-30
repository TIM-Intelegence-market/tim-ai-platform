# Liquidations-Heatmap (Schätzung)

Seit 27.10.2026 im Control Center und im öffentlichen Chart (Ebene „Liquidations-Heatmap (Schätzung)“,
englisch „Liquidation heatmap (estimate)“). Vorbild: die Heatmap von Trading Different, die Uzi am
27.10. als Screenshot schickte. Deren Daten sind nicht frei, TIM rechnet deshalb selbst.

## Was die Ebene zeigt

- **Bänder:** geschätzte Liquidationspreise offener Positionen. Teal = wenig, gelb = mittel, rot = viel
  (im Vergleich zum stärksten Band). Ein Band beginnt dort, wo die Positionen eröffnet wurden.
- **Kräftig = noch offen.** Läuft eine Kerze durch ein Band, gilt es als abgeräumt. Es bleibt dann blass
  bis zu dieser Kerze stehen.
- **Zwei Linien:** „Liq-Cluster oben“ (stärkste geschätzte Short-Liquidationen über dem Preis) und
  „Liq-Cluster unten“ (stärkste geschätzte Long-Liquidationen darunter).

## Wie gerechnet wird (`src/liquidation_map/heatmap.py`)

Daten: Binance Futures, öffentlich, ohne Schlüssel. Die Runtime liest alle 5 Minuten für BTC, ETH und
SOL die Open-Interest-Historie (`/futures/data/openInterestHist`, 30m, 500 Werte ≈ 10 Tage) und die
30m-Kerzen (`/fapi/v1/klines`). Die Rechnung läuft in `src/dashboard/liquidation_data.py`.

1. Steigt das Open Interest in einer 30m-Periode, wurden neue Positionen eröffnet, und zwar zum
   typischen Preis der Kerze, also (Hoch + Tief + Schluss) / 3.
2. **Annahmen:** Die Hälfte der neuen Positionen ist long, die andere Hälfte short. Für die Hebel
   gilt ein fester Mix: 10x 30 %, 25x 30 %, 50x 25 %, 100x 15 %.
3. Die Liquidation liegt bei Einstieg × (1 − 1/Hebel) für Longs und bei Einstieg × (1 + 1/Hebel) für
   Shorts. Die Erhaltungsmarge ist dabei weggelassen. Echte Liquidationen liegen deshalb etwas näher
   am Einstieg.
4. Fällt das Open Interest, schrumpfen alle offenen Schätzungen im gleichen Verhältnis.
5. Handelt eine spätere Kerze durch ein Band, ist es abgeräumt.

Die Preisstufe liegt bei etwa 0,12 % des Preises, bei BTC also 100 $. Bänder unter 2 % des stärksten
Bands fallen weg, höchstens 400 Bänder werden gezeigt.

## Grenzen

- Die Ebene ist eine **Schätzung** aus einer einzigen Börse (Binance) und keine echten Orders.
- Seite und Hebel der Positionen sind unbekannt. Andere Annahmen ergeben andere Bänder.
- Die Ebene dient nur der Anzeige und als Analyse-Kontext. Sie erzeugt kein Signal, keinen Score und
  keinen Plan, und es wird nichts gehandelt.
- Ist der letzte Binance-Stand älter als 20 Minuten, blendet der Chart die Ebene aus und zeigt einen
  Hinweis.

## Abruf

- `GET /api/liquidation?symbol=BTCUSDT` (Control Center): ganze Schätzung mit Alter.
- `/api/chart/live`: Schlüssel `liquidation` (Bänder) und Gruppe `liq` (Cluster-Linien), öffentlich auf
  Englisch.

Nächster sinnvoller Schritt: echte Liquidationen von Binance (`forceOrder`-Stream) mitschreiben. Damit
lässt sich prüfen, ob die geschätzten Bänder getroffen werden.
