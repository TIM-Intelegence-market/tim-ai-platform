# S21: Trade-Reflexion tim_plan_journal: AGAINST_TREND (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S21 |
| Version | **Entwurf 0.1 – wartet auf Uzis Freigabe (Forschungsbereich Stufe 1); vorher werden keine Daten geladen** |
| Erzeugt | 2026-11-11 01:06 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0003 aus Quelle „Reflexion jedes Papier-Trades“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Regel-Backtest auf dem Archiv (wie S4–S7, S9, S10) |
| Spezifikation | SHA-256 `7bf6c79e589158fa36e09e3bdaf9ddfab5de0ee518ba11368fde34f322102332` |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |
| Register | 2 Varianten im Holdout-Register: m = 58 → 60 von 60. |

## 1. Fragestellung

Zeigt sich in der TIM-Planung ein Muster, bei dem Trades gegen den Marktzustand erfolgen, und kann eine Regeländerung das Netto-Ergebnis auf neuen Daten verbessern?

## 2. Hypothese und Herkunft

In tim_plan_journal zeigt sich bei 8 von 20 Trades: Trade gegen TIMs Marktzustand. Eine Regeländerung dagegen verbessert das Netto-Ergebnis auf neuen Daten.

Gegenargument: Muster aus wenigen, überlappenden Papier-Trades; die Abhilfe muss auf Archiv und frischen Daten bestehen.

## 3. Vorbelastung

Keine bekannte Vorbelastung angegeben; Ideen-Prüfung fand keine ähnliche Studie.

## 4. Daten

- archive_spot_klines (Binance Spot-Kerzen (Archiv))
- plan_journal (Papier-Plan-Journal)

## 5. Varianten und Regeln

| Variante | Regel | Parameter (fest) |
|---|---|---|
| V1 | Trade-Reflexion tim_plan_journal: AGAINST_TREND | `{"threshold": 0.8, "window": 20}` |
| V2 | Trade-Reflexion tim_plan_journal: AGAINST_TREND | `{"threshold": 0.9, "window": 20}` |

Kosten: Keine Kosten für die Durchführung der Studie, da es sich um Papierhandel handelt.

Zufallsvergleich: Die Zufallsbaseline basiert auf zufälligen Trades gemäß den historischen Marktdaten aus dem Archiv.

## 6. Messgröße und Entscheidung

- Messgröße: Netto-Rendite
- Kleinster Effekt: 0,1 Prozentpunkte Median-Rendite
- Mindestzahl Fälle: 20 (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)
- Stoppregel: Feste Fallzahl von 20 Trades erreicht

## 7. Bekannte Grenzen

- Die Studie betrachtet nur Papierhandel ohne Echtgeld.
- Der Zeitraum muss vor dem 1. Januar 2025 enden.
- Es wird keine Holdout-Periode verwendet.
- Die Daten stammen ausschließlich aus dem Archiv und der Planung.

## 8. Feste Grenzen

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Zustimmung von Uzi und Barti, Uzis ausdrückliches Wort bleibt Pflicht.
- Kein automatischer Merge; gemergt wird nur nach Uzis „merge“.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-11 | 0.1 | Entwurf vom Studien-Generator aus Idee I-0003 |
