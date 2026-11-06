# S17: Kosten in R nach Tageszeit: In welchen Stunden fressen feste Gebühren den Vorteil am wenigsten? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S17 |
| Version | **Entwurf 0.1 – wartet auf Uzis Freigabe (Forschungsbereich Stufe 1); vorher werden keine Daten geladen** |
| Erzeugt | 2026-11-07 00:16 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0002 aus Quelle „Wöchentliche KI-Runde“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Ereignis-Studie (wie S1) |
| Spezifikation | SHA-256 `2bc948fc2c70189c4c62b227f08542aac588d7af49fdfb05fe26b100fd1152ac` |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |
| Register | Eigene Familie außerhalb des Holdout-Registers (wie S1/S8); belegt keine Registerplätze. |

## 1. Fragestellung

In welchen Stunden fressen feste Gebühren den Vorteil am wenigsten?

## 2. Hypothese und Herkunft

Die realisierte Minutenvolatilität (aus S8-Minutenbalken) und die aggressive Handelsaktivität unterscheiden sich systematisch nach UTC-Stunde und Wochentag. Bei festen Gebühren plus Slippage-Annahme liegen die Kosten in Einheiten eines typischen Stop-Abstands (R) in den volatilsten Stunden (etwa Überlappung Europa/New York) deutlich unter 0,25 R, in ruhigen Stunden darüber. Die Studie schätzt die Kosten-in-R-Verteilung je Stunde und prüft, ob der Unterschied zwischen den besten und schlechtesten Stunden über mehrere Jahre stabil ist (Jahr-für-Jahr-Rangkorrelation). Sie liefert einen Zeitfilter für spätere Regeln, aber selbst keine Richtung.

Gegenargument: Das Ergebnis ist weitgehend bekannt (Volatilität und Volumen haben eine Tagesstruktur), der Informationsgewinn kann gering sein. Höhere Volatilität senkt zwar die Kosten in R, erhöht aber auch die Wahrscheinlichkeit, per Wick ausgestoppt zu werden (STOP_BY_WICK) und die Ereignisnähe zu CPI-Terminen. Die Stundenstruktur kann sich zudem zwischen Jahren verschieben. Ohne Richtungsvorteil im Einstieg bleibt ein Zeitfilter nur eine Kostenverbesserung und macht keine negative Erwartung positiv (Lehre aus S4 und S6).

## 3. Vorbelastung

S4, S6, S8

## 4. Daten

- archive_aggtrades_btc (BTC aggTrades / S8-Minutenbalken (Archiv))
- archive_spot_klines (Binance Spot-Kerzen (Archiv))

## 5. Ereignisse und Vergleich

- Minutenvolatilität aus S8-Minutenbalken
- Aggressive Handelsaktivität

Vergleich: Vergleich der Kosten-in-R-Verteilung je Stunde und Wochentag

## 6. Messgröße und Entscheidung

- Messgröße: Kosten in R
- Kleinster Effekt: 0,1 Prozentpunkte Median-Rendite
- Mindestzahl Fälle: 5000 (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)
- Stoppregel: Feste Fallzahl von 5000 Ereignissen erreicht

## 7. Bekannte Grenzen

- Die Studie betrachtet nur Daten bis 2024-12-31, da der Holdout-Zeitraum gesperrt ist.
- Es wird nur eine feste Gebührenstruktur mit Slippage-Annahme verwendet, keine dynamischen Kostenmodelle.
- Die Ergebnisse gelten nur für den Papierhandel unter festen Gebühren und nicht für Echtgeld-Handel.

## 8. Feste Grenzen

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Zustimmung von Uzi und Barti, Uzis ausdrückliches Wort bleibt Pflicht.
- Kein automatischer Merge; gemergt wird nur nach Uzis „merge“.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-07 | 0.1 | Entwurf vom Studien-Generator aus Idee I-0002 |
