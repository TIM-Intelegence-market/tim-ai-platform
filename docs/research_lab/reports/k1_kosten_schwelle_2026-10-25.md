# Studie K1: Ergebnis vom 25.10.2026

Festlegung: `docs/research_lab/studien/K1_KOSTEN_SCHWELLE.md`. Code-Stand 7f3a9b4, gerechnet auf dem Mac mit
Python 3.13 in einem eigenen Worktree. Daten: Kopien der Journal-Ansichten aus `~/TIM-live/data/journal/`, Stand
25.10.2026 01:46 Ortszeit, nur gelesen.

## Kurzurteil

- **Ergebnis: `INSUFFICIENT_CASES`.** Es gibt 2 geschlossene Fälle (tim/1: 1, struct/1: 1, level/1: 0). Nötig sind
  mindestens 30 Cluster. Die Daten belegen keine Grenze und widerlegen auch keine.
- **0,25 R bleibt eine Hypothese und reine Anzeige.** Aus der Kostenarithmetik ist sie eine vertretbare Mitte (siehe unten),
  aber nicht empirisch geprüft.
- **Stressfall ist der wichtigste Vorbehalt.** Mit doppelten Kosten braucht 0,25 R einen Stop ab etwa 1,43 % (LONG). Der feste
  1-%-Stop der TIM-Regel liegt dann bei 0,358 R, also über der Grenze. Die Anzeige rechnet nur mit Basiskosten.

## Validierung der Anzeige aus PR #408

`tests/test_plan_cost_check_rules.py` (93 Fälle) und `tests/test_plan_cost_check.py` sind grün. Kein Fehler gefunden.

- Ergebnis und Basispunkte stimmen mit einer unabhängig ausgeschriebenen Formel überein (Protokoll 1.1, aus
  `protocol.BASE_COSTS`). Geprüft für LONG und SHORT, drei Preisniveaus und sieben Stopabstände von 0,05 % bis 5 %.
  Abweichung höchstens 0,00015 R durch die Rundung auf 4 Stellen.
- Die Gebührenbasis ist je Seite der eigene Preis. Ein SHORT kostet deshalb bei gleichem Abstand etwas mehr als ein LONG.
  Der Mindestabstand für 0,25 R ist für LONG 0,72 % und für SHORT 0,73 %.
- Die Stop-Slippage (0,05 %) wird nur auf der Stop-Seite gerechnet, die normale Slippage (0,03 %) auf der Einstiegsseite.
- Ungültige Preise geben in beiden Richtungen `COST_UNKNOWN` und nie `COST_WITHIN_LIMIT`. Geprüft wurden None, 0,
  negative Werte, NaN, ±Inf, bool, Text, Liste und Dict. Fehlende Felder und eine unbekannte Richtung ebenso. Zahlen als
  Text (`"80000"`) werden als Zahl gelesen. Das Journal speichert immer Zahlen, das ist also unkritisch.
- Ein sehr enger Stop (0,01 USD) ergibt einen endlichen, sehr großen Wert und `NOT_TRADABLE_COST`.
- **Alle drei Regeln:** Einträge aus tim/1 (über `update`), struct/1 (über `structural_plan`) und level/1 (über `_level`)
  bekommen dieselbe Kostenprüfung. Bei gleichem Einstieg und Stop ist das Ergebnis regelunabhängig. Die
  Entscheidungsfelder (`DECISION_FIELDS`) bleiben unverändert. Ein Eintrag ohne Stop ist in jeder Regel `COST_UNKNOWN`.
- Die Schätzung nutzt den geplanten Einstieg, nicht einen späteren abweichenden Fill. Das ist gewollt, weil die Anzeige zur
  Planzeit gilt.

## Mindest-Stopabstand je Grenze

Diese Werte sind aus den Formeln berechnet und brauchen keine Marktdaten. Angaben in Prozent vom Einstieg.

| Grenze | Basis LONG | Basis SHORT | Stress LONG | Stress SHORT |
|---|---|---|---|---|
| 0.10 R | 1.78 | 1.82 | 3.53 | 3.67 |
| 0.15 R | 1.19 | 1.21 | 2.37 | 2.43 |
| 0.20 R | 0.90 | 0.90 | 1.78 | 1.82 |
| 0.25 R | 0.72 | 0.72 | 1.43 | 1.45 |
| 0.33 R | 0.54 | 0.55 | 1.08 | 1.10 |
| 0.50 R | 0.36 | 0.36 | 0.72 | 0.72 |

## Daten

| Datei | Einträge | Status |
|---|---|---|
| tim_plan_journal.json | 2 | CLOSED 1, FILLED 1 |
| tim_plan_journal_struct.json | 1 | CLOSED 1 |
| tim_plan_journal_level.json | 0 | – |

Geschlossene Fälle:

| Regel | Richtung | Ausstieg | Stopabstand | Kosten Basis | Kosten Stress | Brutto R | Netto Basis | Netto Stress |
|---|---|---|---|---|---|---|---|---|
| tim/1 | LONG | STOP | 1,00 % | 0,179 R | 0,358 R | −1,0 | −1,179 | −1,358 |
| struct/1 | LONG | STOP | 0,15 % | 1,200 R | 2,400 R | −1,0 | −2,200 | −3,400 |

Die volle Tabelle je Grenze steht in der JSON- und Markdown-Ausgabe des Laufs. Sie zeigt nur, welcher der zwei Fälle
eine Grenze passiert hätte. Bei 0,25 R mit Basiskosten wäre der struct-Fall gefiltert worden, der tim-Fall nicht. Bei 0,25 R
mit Stresskosten wären beide gefiltert worden. Daraus folgt nichts über die Güte einer Grenze.

## Einordnung von 0,25 R (Arithmetik, keine Messung)

- Kosten von c R erhöhen bei einem mittleren Gewinn von W R die nötige Trefferquote von 1/(1+W) auf etwa (1+c)/(1+W).
  Beispiel W = 2: 33,3 % ohne Kosten, 37,3 % bei 0,12 R, 41,7 % bei 0,25 R, 44,3 % bei 0,33 R, 50 % bei 0,50 R.
- Unter 0,15 R fielen schon die Pläne der TIM-Regel mit ihrem festen 1-%-Stop heraus (0,179 R), die Grenze würde also
  fast alles sperren. Über 0,33 R fressen die Kosten ein Drittel des Risikos oder mehr.
- 0,25 R liegt dazwischen und trennt die beiden echten Fälle so, wie es inhaltlich passt. Struktur-Pläne mit Stops um
  0,15 % liegen weit darüber. Das ist der Kernbefund vom 24.10.: Kosten fressen enge Stops.

## Unsicherheit und nächste Schritte

- Zwei Fälle reichen für keine Aussage über Netto-Ergebnisse. Der Status bleibt `INSUFFICIENT_CASES`, bis mindestens
  30 Cluster geschlossen sind. Seit dem Log-Neustart am 24.10. um 11:06 Ortszeit gab es etwa einen geschlossenen Fall pro Tag über alle Regeln. Bei dieser Rate dauert das Wochen bis Monate.
- Schneller ginge es mit einem historischen Nachlauf der drei Regeln über gespeicherte 1m-Kerzen (Backtest). Dafür wäre
  eine eigene Registrierung mit Training, Validierung und Holdout nötig, abgestimmt mit der Vorab-Registrierung der
  Strategie-Forschung.
- Die Schätzung deckt nur den Stop-Fall ab. Bei Ausstiegen an den Zielen sind die Kosten in R anders.
- Keine Produktivänderung: Die Anzeige bleibt Anzeige, kein Filter, keine Order- oder Risikoregel.
