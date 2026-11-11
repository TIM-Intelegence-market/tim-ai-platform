# S24: Trade-Reflexion tim_plan_journal: INVALIDATED (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S24 |
| Version | **Entwurf 0.1 – wartet auf Uzis Freigabe (Forschungsbereich Stufe 2); vorher werden keine Daten geladen** |
| Erzeugt | 2026-11-11 20:52 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0004 aus Quelle „Reflexion jedes Papier-Trades“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Regel-Backtest auf dem Archiv (wie S4–S7, S9, S10) |
| Spezifikation | SHA-256 `a56866bee3fcc08a7efa8a11e9393aff68c589ab49fd5944e7dac95becb66f2c` |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |
| Register | Außerhalb des Registers (prospektive Papier-Journal-Daten, Uzis Entscheidung 11.11.2026, PR #214); belegt keine Registerplätze. |

## 1. Fragestellung

Zeigt sich in den Papier-Trades des TIM-Plan-Journals ein Muster, bei dem Trades durch Schlusskurse jenseits der Ungültigkeitsmarke beendet werden, und kann eine Regeländerung das Netto-Ergebnis auf neuen Daten verbessern?

## 2. Hypothese und Herkunft

In tim_plan_journal zeigt sich bei 6 von 20 Trades: Plan durch Schluss jenseits der Ungültigkeitsmarke beendet. Eine Regeländerung dagegen verbessert das Netto-Ergebnis auf neuen Daten.

Gegenargument: Muster aus wenigen, überlappenden Papier-Trades; die Abhilfe muss auf Archiv und frischen Daten bestehen.

## 3. Vorbelastung

Keine bekannte Vorbelastung angegeben; Ideen-Prüfung fand keine ähnliche Studie.

## 4. Daten

- archive_spot_klines (Binance Spot-Kerzen (Archiv))
- plan_journal (Papier-Plan-Journal)

## 5. Varianten und Regeln

| Variante | Regel | Parameter (fest) |
|---|---|---|
| V1 | Abgeleitet: Basis: Ausstieg wie bisher beim Schlusskurs jenseits der Ungültigkeitsmarke. | `{"bestaetigung_kerzen": 1, "puffer_prozent": 0.0}` |
| V2 | Abgeleitet: Ausstieg erst, wenn zwei aufeinanderfolgende Schlusskurse jenseits der Ungültigkeitsmarke liegen. | `{"bestaetigung_kerzen": 2, "puffer_prozent": 0.0}` |

Kosten: Die Studie verwendet keine zusätzlichen Kosten, da sie auf bestehenden Papierdaten basiert.

Zufallsvergleich: Die Zufallsbaseline ist die durchschnittliche Rendite bei zufälliger Ausstiegszeitpunktwahl innerhalb der Handelsperiode.

## 6. Messgröße und Entscheidung

- Messgröße: Netto-Rendite
- Kleinster Effekt: 0,1 Prozentpunkte Median-Rendite
- Mindestzahl Fälle: 20 (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)
- Stoppregel: Festgelegte Fallzahl von 20 Trades erreicht

## 7. Bekannte Grenzen

- Die Studie berücksichtigt nur Trades aus dem TIM-Plan-Journal mit mindestens einer Kursbewegung jenseits der Ungültigkeitsmarke.
- Es wird nur ein Vergleich zwischen zwei Varianten durchgeführt, da die Fallzahl begrenzt ist.
- Die Regeländerung basiert auf einer plausiblen Erweiterung der Ausstiegsbedingung, um Überlappungen in den Daten zu reduzieren.

## 8. Feste Grenzen

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Zustimmung von Uzi und Barti, Uzis ausdrückliches Wort bleibt Pflicht.
- Kein automatischer Merge; gemergt wird nur nach Uzis „merge“. Ausnahme ab Stufe 2: ein Studien-Entwurf (eine Datei unter docs/research_lab/studien/) nach Codex-„OK“ und grünen Pflicht-Checks.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-11 | 0.1 | Entwurf vom Studien-Generator aus Idee I-0004 |
