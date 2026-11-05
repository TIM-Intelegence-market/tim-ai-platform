# S16: Funding-Extreme als Kontraindikator: Verteilung der 24-h-Rendite nach extremem Funding (ohne Carry) (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S16 |
| Version | **Entwurf 0.1 – wartet auf Uzis Freigabe (Forschungsbereich Stufe 1); vorher werden keine Daten geladen** |
| Erzeugt | 2026-11-05 15:23 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0001 aus Quelle „Wöchentliche KI-Runde“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Ereignis-Studie (wie S1) |
| Spezifikation | SHA-256 `919e41a1c8ed25b8088e7b3205fcb224b9ce63c0c986f47b37b173e66070d338` |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |
| Register | Eigene Familie außerhalb des Holdout-Registers (wie S1/S8); belegt keine Registerplätze. |

## 1. Fragestellung

Nach Funding-Werten im obersten bzw. untersten Dezil (rollierend, nur Vergangenheit) unterscheidet sich die Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags von der Gesamtverteilung, weil überhitzte Positionierung Liquidationskaskaden begünstigt.

## 2. Hypothese und Herkunft

Nach Funding-Werten im obersten bzw. untersten Dezil (rollierend, nur Vergangenheit) unterscheidet sich die Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags von der Gesamtverteilung, weil überhitzte Positionierung Liquidationskaskaden begünstigt. Untersucht wird nur die Renditeverteilung als Ereignisstudie, nicht Carry und keine Trefferquote wie in S5.

Gegenargument: Extreme Funding-Werte clustern stark in wenigen Marktphasen. Die effektive Stichprobe ist daher viel kleiner als die Zahl der Funding-Termine, und überlappende 24-h-Fenster sind autokorreliert. S5 hat gezeigt, dass seltene Signale an der Stichprobe scheitern. Funding ist zudem breit bekannt, ein möglicher Effekt dürfte weitgehend wegarbitriert sein.

## 3. Vorbelastung

Keine bekannte Vorbelastung angegeben; Ideen-Prüfung fand keine ähnliche Studie.

## 4. Daten

- archive_spot_klines
- archive_usdm_klines

## 5. Ereignisse und Vergleich

- {'name': 'Rendite', 'type': 'continuous'}
- {'name': 'maximaler Rückschlag', 'type': 'continuous'}

Vergleich: {'group1': 'Funding-Werte im obersten Dezil', 'group2': 'Funding-Werte im untersten Dezil', 'group3': 'Gesamtverteilung'}

## 6. Messgröße und Entscheidung

- Messgröße: Verteilung der 24-h-Rendite und des maximalen Rückschlags
- Kleinster Effekt: 0.1
- Mindestzahl Fälle: 500 (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)
- Stoppregel: Stop bei Erreichen von min_cases oder bei p-Wert < 0.05

## 7. Bekannte Grenzen

- 0.05
- 0.2

## 8. Feste Grenzen

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Zustimmung von Uzi und Barti, Uzis ausdrückliches Wort bleibt Pflicht.
- Kein automatischer Merge; gemergt wird nur nach Uzis „merge“.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-05 | 0.1 | Entwurf vom Studien-Generator aus Idee I-0001 |
