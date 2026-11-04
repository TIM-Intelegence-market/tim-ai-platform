# S7b mit Makro-Filtern: Erkundung, Ergebnisse und Entscheidung

| Feld | Wert |
|---|---|
| Studie | Erkundung zu S7b-D20-T3 mit Signal-Filtern aus externen Daten, **kein Registereintrag** |
| Version | 1.0 vom 04.11.2026 (Entwurf 0.2 vom 02.11. im privaten PR #460, dort entschieden) |
| Status | **Entschieden (Uzi, 04.11.2026): A und C freigegeben, B nicht.** Der Holdout ab 2025-01-01 wurde nicht geladen und bleibt zu |
| Anlass | Umbau der BTC Research Engine nach dem Beirat-Urteil „UMBAUEN“ vom 01.11.2026. Statt alle Datenfamilien zu bauen, werden wenige, vorab festgelegte Fragen an die einzige Kandidatin S7b-D20-T3 gestellt. Bis zum 02.11. lief die Arbeit vertraulich, seitdem über den normalen Weg |
| Protokoll | `../PROTOKOLL.md` Version 1.3, Satzung `../FORSCHUNGSBEREICH.md` 1.0 |
| Kandidatin | S7b-D20-T3, unverändert (`S7B_EINE_POSITION_PRAEREGISTRIERUNG.md`) |
| Ergebnisse | Vollständig in Abschnitt 3, auch die nicht bestandenen Filter |

## 1. Fragestellung

Wird S7b-D20-T3 nach allen Kosten besser, wenn neue Einstiege in bestimmten Makro- oder Marktlagen unterbleiben, zum Beispiel rund um CPI- und FOMC-Termine, bei extremem Funding, bei sinkender Fed-Liquidität, bei steigendem Dollar oder bei steigendem Realzins?

## 2. Vorgehen

- **Rechner und Abgrenzung:** Mac, Benutzer chris, Prüfskripte außerhalb des Repos. Gerechnet wurde nur auf Training (bis 2022) und Validierung (2023–2024), nach `section_trades`. Der Holdout wurde nie geladen.
- **Rechenweg:** S7b-D20-T3 über `engine.run_portfolio` (höchstens eine Position, BTC > ETH > SOL), `BASE_COSTS` und `STRESS_COSTS`. Gefiltert wird auf Signal-Ebene, bevor die Positionsgrenze greift.
- **Selbstprobe vor jeder Frage:** Der ungefilterte Lauf muss den veröffentlichten S7b-Bericht genau treffen, auch beim Datensatz-Hash. Erst dann wird die Frage gerechnet.
- **Point in time:** Externe Werte zählen erst ab ihrer Veröffentlichung. Bei ALFRED-Vintages gilt ein Wert ab dem Tag nach der Veröffentlichung. CPI- und FOMC-Termine kommen aus V1.1 und V1.2.
- **Bestehensregel, vorab festgelegt:** In Training **und** Validierung liegt E[R] mit Filter mindestens 0,05 R über dem Wert ohne Filter, der Drawdown ist nicht größer, und es bleiben mindestens 150 bzw. 80 Trades. Jede Frage wurde vor dem Rechnen schriftlich eingefroren und genau einmal gerechnet.
- **Beschreibend, ohne Test:** Ein Einfluss-Barometer je Halbjahr zeigt, wie stark BTC auf CPI- und FOMC-Termine und auf laufende Treiber reagiert hat (Dollar, Zinsen, Realzins, Öl, VIX, Liquidität). Dazu gibt es eine kurze Literaturrecherche zu BTC-Treibern.

## 3. Ergebnisse (Training bis 2022, Validierung 2023–2024)

Selbstprobe vor jeder Frage: 292 Trades / E[R] 0,227 (Training) und 207 / 0,272 (Validierung), Datensatz-Hash `9ac4d1357e57…415ecc`, jedes Mal getroffen.

| Frage | Filter (kein neuer Einstieg, wenn …) | Training ΔE[R] | Validierung ΔE[R] | Urteil |
|---|---|---:|---:|---|
| F1 | 24 h vor bis 4 h nach CPI/FOMC | −0,022 | +0,010 | nicht bestanden |
| F2 | Funding über 95. bzw. unter 5. Perzentil (365 Tage) | +0,005 | +0,008 | nicht bestanden |
| F3 | kein Long, wenn Netto-Liquidität (WALCL − WTREGEN − RRPONTSYD) über 13 Wochen gefallen | +0,014 | +0,047 | knapp nicht bestanden |
| F4 | kein Long, wenn Dollar-Index (DTWEXBGS) über 13 Wochen gestiegen | −0,038 | +0,058 | nicht bestanden |
| F5 | kein Long, wenn 10-jähriger Realzins (DFII10) über 13 Wochen gestiegen | +0,167 | +0,061 | **bestanden** |

F5 im Detail: Training 224 Trades, E[R] 0,394, Drawdown 12,3 R (ohne Filter 20,8 R). Validierung 143 Trades, E[R] 0,333, Drawdown 10,95 R (ohne Filter gleich). Mit Stresskosten dasselbe Bild.

**Beschreibend, ohne Test (Einfluss-Barometer):**

- CPI/FOMC je Halbjahr: bis 2019 kaum Einfluss. FOMC wirkt seit 2020 stark (BTC-Spanne in der ersten Stunde 2- bis 5-mal so groß wie sonst), CPI seit Ende 2021.
- Laufende Treiber (wöchentlich, 2017–2024): Der Realzins hat den deutlichsten Vorlauf. Nach 13 Wochen Anstieg kam BTC danach im Mittel auf −0,19 % pro Woche, nach 13 Wochen Fall auf +1,49 % pro Woche. Dollar und 10-jährige Zinsen (DGS10) wirken schwächer, Öl kaum. Der VIX läuft nur in derselben Woche mit, ohne Vorlauf. Dieses zweite Barometer rechnet mit heutigen Datenständen, nicht zeitpunktgenau wie F3 bis F5.

## 4. Offenlegung und Vorbehalte nach der Satzung

- Insgesamt wurden **fünf Filter** auf derselben Kandidatin und denselben Daten geprüft. F5 war der fünfte. Der Abstand in der Validierung liegt nur knapp über der Schwelle, und ein großer Teil des Effekts stammt aus 2022.
- **Glückstest über die fünf Filter (02.11.2026, nach Pflicht aus `FORSCHUNGSBEREICH.md`):** vorab eingefroren, ein Lauf, nur 2017–2024. Je Filter s = min(ΔE[R] Training, ΔE[R] Validierung). In 1000 Durchläufen wurden die Sperrzeiten jedes Filters zirkulär verschoben. Beobachtet F5 +0,061 R, 95-%-Quantil des zufällig Besten +0,066. **p über alle fünf = 0,066, damit nicht bestanden** (Schwelle 0,05). Für F5 allein p = 0,017. F5 bleibt Kandidat, und der Vorwärtstest ist die eigentliche Prüfung.
- Die Fragen liefen außerhalb des Registers und ohne Studienfreigabe. Nach der Satzung sind es deshalb Erkundungen. Eine offizielle Studie muss diese Vorbelastung nennen.
- **Holdout teilweise schon gesehen:** Laut `S7B_EINE_POSITION_PRAEREGISTRIERUNG.md` Abschnitt 14 zeigte ein Probelauf am 01.11.2026 S7b-Ergebnisse für 2026-07-04 bis 2026-11-01 (D20-T3: 35 Trades, −0,17 R je Trade). Ein Holdout-Lauf nach B wäre für diesen Teil nicht ergebnisblind. S7b ohne Filter lief dort im Minus.

## 5. Antrag

**A. Schattenbetrieb (vorwärts, ohne Holdout).** Der Realzins-Filter F5 und der Liquiditäts-Filter F3 laufen neben dem bestehenden Papier-Vorwärtstest von S7b (seit 01.11.) im Schattenbetrieb mit. Die Regeln werden vor Beginn eingefroren, und es wird genau einmal bewertet. Die Satzung nennt 30 Tage. Bei etwa 8 bis 9 S7b-Trades im Monat wären das nur rund 8 Trades. Vorschlag deshalb: Bewertung nach mindestens 60 Trades (etwa 7 Monate). Bestanden, wenn der Filter mindestens 0,05 R je Trade über S7b ohne Filter liegt und der Drawdown nicht größer ist. Diese Abweichung von der Satzung braucht Uzis Freigabe.

**B. Holdout-Lauf (einmal).** S7b-D20-T3 mit dem Realzins-Filter F5 als Hauptfrage, der Liquiditäts-Filter F3 wird nur berichtet. Zeitraum 2025-01-01 bis zum Ende des Holdout-Fensters nach Abschnitt 8 der S7b-Studie (2026-10-01). Die Bestehensregel wird vorab festgelegt:

1. E[R] mit Filter ist nach Basis- und nach Stresskosten größer als 0.
2. E[R] liegt mindestens 0,05 R über S7b ohne Filter.
3. Der Drawdown ist nicht größer als ohne Filter.
4. Es bleiben mindestens 60 Trades.

Es gibt genau einen Lauf, und alle Zahlen werden ausgegeben. **Folge:** Laut `PROTOKOLL.md` (Eintrag 26.10.) verbraucht ein Holdout-Lauf von S7b den Holdout für den ganzen Registerzeitraum. Die Satzung verlangt dafür Uzis ausdrückliches Wort.

**C. Satzung.** Vorschlag: „Holdout öffnen nur mit Zustimmung von Uzi und Barti.“

## 6. Entscheidung (Uzi, 04.11.2026)

- **A, Schattenbetrieb: freigegeben.** Gezählt werden 60 Trades von S7b ohne Filter. Das Ergebnis wird als Beobachtung berichtet, nicht als Bestätigung. Die eingefrorenen Regeln stehen in `S7B_EINE_POSITION_PRAEREGISTRIERUNG.md`, Abschnitt 15. Auf Bartis Wunsch kamen hinzu (04.11.): mindestens 30 Trades je gefilterter Reihe, getrennte Aussagen „besser als ungefiltert“ und „profitabel“ sowie ein zweites Urteil bei 150 Trades.
- **B, Holdout-Lauf: jetzt nicht.** Gründe: Der Lauf würde den Holdout für alle 58 Registereinträge verbrauchen, Juli bis Oktober 2026 sind schon gesehen, und der Glückstest ist nicht bestanden.
- **C, Satzung: freigegeben.** Der Holdout wird nur mit Zustimmung von Uzi und Barti geöffnet, Uzis ausdrückliches Wort bleibt Pflicht (`../FORSCHUNGSBEREICH.md`).
- **D, Termin-Marker:** Die Termindatei für den Chart liegt seit 04.11. in `~/TIM-live/data/macro/calendar.json` (239 Termine).

## 7. Code

- `src/research_lab/forward/macro_filters.py`: tägliches Log der Filterzustände F3/F5 (`log`) und wöchentliches Barometer (`barometer`), nur Beobachtung, mit Tests in `tests/test_research_forward_macro_filters.py`.
- Die Erkundungsskripte von F1 bis F5 und der Glückstest liefen außerhalb des Repos auf dem Mac (`~/pruefung`). Die Vorregistrierungen und Ergebnisse sind oben zusammengefasst. Rohdaten werden nicht versioniert.
