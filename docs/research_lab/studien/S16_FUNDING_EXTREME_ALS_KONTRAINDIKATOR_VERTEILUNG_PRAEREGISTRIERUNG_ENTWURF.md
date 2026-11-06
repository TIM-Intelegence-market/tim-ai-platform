# S16: Funding-Extreme als Kontraindikator: Verteilung der 24-h-Rendite nach extremem Funding (ohne Carry) (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S16 |
| Version | **Entwurf 0.1 – wartet auf Uzis Freigabe (Forschungsbereich Stufe 1); vorher werden keine Daten geladen** |
| Erzeugt | 2026-11-06 09:18 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0001 aus Quelle „Wöchentliche KI-Runde“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Ereignis-Studie (wie S1) |
| Spezifikation | SHA-256 `25621adf840d848bc556da909d55b657f995c860fb7e08e6692e2d3b978e55a1` |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |
| Register | Eigene Familie außerhalb des Holdout-Registers (wie S1/S8); belegt keine Registerplätze. |

## 1. Fragestellung

Nach Funding-Werten im obersten bzw. untersten Dezil (rollierend, nur Vergangenheit) unterscheidet sich die Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags von der Gesamtverteilung, weil überhitzte Positionierung Liquidationskaskaden begünstigt.

## 2. Hypothese und Herkunft

Nach Funding-Werten im obersten bzw. untersten Dezil (rollierend, nur Vergangenheit) unterscheidet sich die Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags von der Gesamtverteilung, weil überhitzte Positionierung Liquidationskaskaden begünstigt. Untersucht wird nur die Renditeverteilung als Ereignisstudie, nicht Carry und keine Trefferquote wie in S5.

Gegenargument: Extreme Funding-Werte clustern stark in wenigen Marktphasen. Die effektive Stichprobe ist daher viel kleiner als die Zahl der Funding-Termine, und überlappende 24-h-Fenster sind autokorreliert. S5 hat gezeigt, dass seltene Signale an der Stichprobe scheitern. Funding ist zudem breit bekannt, ein möglicher Effekt dürfte weitgehend wegarbitriert sein.

## 3. Vorbelastung

S5 hat gezeigt, dass seltene Signale an der Stichprobe scheitern. Daher wird eine robuste Analyse gewährleistet.

## 4. Daten

- archive_spot_klines (Binance Spot-Kerzen (Archiv))
- archive_usdm_klines (Binance USD-M-Kerzen und Funding (Archiv))

## 5. Ereignisse und Vergleich

- Funding-Werte im obersten Dezil
- Funding-Werte im untersten Dezil

Vergleich: Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags im Vergleich zur Gesamtverteilung

## 6. Messgröße und Entscheidung

- Messgröße: Verteilung der 24-h-Rendite und des maximalen Rückschlags
- Kleinster Effekt: 0,1 Prozentpunkte Median-Rendite
- Mindestzahl Fälle: 500 (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)
- Stoppregel: Feste Fallzahl von 500 Ereignissen erreicht

## 7. Bekannte Grenzen

- Die Studie betrachtet nur Daten bis 2024-12-31, Holdout-Zeitraum ist gesperrt.
- Es wird nur die Renditeverteilung als Ereignisstudie untersucht, nicht Carry und keine Trefferquote wie in S5.
- Die effektive Stichprobe ist aufgrund von Clustering und Autokorrelation kleiner als die Anzahl der Funding-Termine.
- Überlappende 24-h-Fenster sind autokorreliert, daher wird eine robuste Analyse gewährleistet.

## 8. Feste Grenzen

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Zustimmung von Uzi und Barti, Uzis ausdrückliches Wort bleibt Pflicht.
- Kein automatischer Merge; gemergt wird nur nach Uzis „merge“.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-06 | 0.1 | Entwurf vom Studien-Generator aus Idee I-0001 |
