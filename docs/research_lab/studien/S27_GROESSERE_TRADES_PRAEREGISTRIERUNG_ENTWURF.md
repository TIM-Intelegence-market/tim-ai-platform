# S27: Alle Indikatoren auf größeren Trades: Bleibt nach Bitunix-Kosten ein Edge? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S27 (11.11.2026; S24 = alle Indikatoren, S25 = GARCH-Größe, S26 = Aufwand gegen Ergebnis) |
| Version | **0.1, Entwurf.** Regeln als Code: `src/research_lab/studies/s27.py`, Tests `tests/test_research_lab_s27.py`. `evaluate` verweigert den Lauf, solange die Version mit 0 beginnt |
| Anlass | S24 1.0 ist am 11.11.2026 gescheitert: M2 sortierte echt (Abstand 0,135 R, p 0,004), aber auch die genommenen Trades verloren nach Kosten im Mittel 0,38 R. Uzi am selben Abend: „go“ für eine neue Studie mit weniger, größeren Trades |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Daten | wie S24: Binance Spot BTCUSDT 1h/30m, S8-Footprint, USD-M Funding-Archiv; 2019-10 bis 2024-12 |
| Holdout | ab 2025-01-01, wird nicht geladen. Training 2020–2022, Validierung 2023–2024 |

## 1. Fragestellung

In S24 waren Gebühren, Schlupf und Funding bei einem Stop von 1 ATR14 (1h) so groß gegenüber dem Risiko, dass jeder
Standard-Trade im Mittel verlor. Bei einem dreimal so weiten Stop kosten dieselben Gebühren ein Drittel so viel R.
Frage: Hat einer der beiden S24-Filter (M1 Stimmen, M2 Regression) auf diesen größeren Trades nach Kosten ein
positives Ergebnis, und zwar auch dann, wenn man immer nur einen Trade zur Zeit hält?

## 2. Was gleich bleibt, was sich ändert

Gleich wie S24 1.0, unverändert aus dem Code übernommen (`s24.build_rows`, `s24.evaluate`):
Momente (jede geschlossene 1h-Kerze, Long und Short), alle sechs Familien und 21 Merkmale, M1-Stimmen mit den
Schwellen ±4, M2 (logistische Regression, einmal auf dem Training gefittet, NEHMEN oberes Drittel, AUSLASSEN
unteres Drittel), die Bitunix-Kosten (Taker 0,06 % und Schlupf 0,03 % je Seite, 0,05 % mehr am Stop, Funding über
die ganze Haltedauer), Gate, Bootstrap, Holm über zwei Modelle, Verschiebungstest.

Neu und fest, ohne Suche, als eine einzige Wahl:

| | S24 | S27 |
|---|---|---|
| Stop | 1 ATR14 (1h) | **3 ATR14 (1h)** |
| Ziel | 2 ATR14 | **6 ATR14** |
| Höchstdauer | 48 h | **168 h (7 Tage)** |
| Zeitfenster | 48 h im eigenen Abschnitt | **168 h im eigenen Abschnitt** (kein Trainings-Trade läuft in die Validierung, keiner ins Holdout) |

Ehrlich vermerkt: Die Wahl ist nach dem S24-Ergebnis getroffen worden. Begründet ist sie nur mit dem Anteil der Kosten
am Risiko, nicht mit einem Blick auf Ergebnisse bei anderen Stops. Andere Weiten werden nicht geprüft.

## 3. Ablauf und Gate

1. `count` (ergebnisblind): Zeilen mit allen Familien je Abschnitt und Richtung. Gate wie S24: je Richtung und
   Abschnitt mindestens 300 vollständige Zeilen, Validierung mindestens 50 Wochen.
2. Einfrieren als 1.0 auf Uzis Wort.
3. `evaluate` auf der PS5.

## 4. Entscheidung (nur Validierung)

Ein Modell besteht nur, wenn alle sechs Bedingungen gelten:

1. Holm (über M1, M2) mit α = 0,05 auf „NEHMEN minus AUSLASSEN > 0“ (Wochen-Block-Bootstrap, 9.999 Ziehungen)
2. Abstand mindestens 0,05 R
3. gleiches Vorzeichen im Training
4. Verschiebungstest p < 0,05
5. NEHMEN im Mittel positiv nach Kosten
6. **neu:** Folge positiv nach Kosten. Gezählt werden die Trades, die das Modell nacheinander nimmt: immer nur
   einer offen, der nächste NEHMEN-Moment erst nach dem Ausstieg. Diese Folge muss mindestens 30 Trades haben und
   im Mittel positiv sein. Berichtet werden auch Trades je Woche und die Summe in R

Sonst „NO ROBUST EDGE PROVEN“.

## 5. Was folgt

Bestanden: Modell als Live-Schatten am Mac (kein Handel, mindestens 4 Wochen), danach Schlusstest 2025 nur mit Uzis
Wort. Nicht bestanden: offen berichten, keine weiteren Stop-Weiten auf denselben Daten.

## 6. Grenzen

- Die Trades überlappen in der Haupttest-Statistik stark (jede Stunde ein neuer Trade, 7 Tage Laufzeit). Der
  Wochen-Block-Bootstrap fängt das nur teilweise auf, deshalb gibt es Bedingung 6.
- Längere Haltedauer heißt mehr Funding; es ist eingerechnet, aber Bitunix-Raten können von Binance abweichen.
- Delta und Footprint aus Binance, nicht aus dem Bitunix-Buch.
