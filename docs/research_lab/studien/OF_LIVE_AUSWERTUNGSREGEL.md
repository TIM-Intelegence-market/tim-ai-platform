# Orderflow live (Stufe B, PS5): Auswertungsregel

Version 1.0, eingefroren am 17.11.2026 (nach Prüfung durch studien-pruefer nachgebessert) auf Uzis Wort "Einfrieren", vor dem ersten zählenden Tag (18.11.2026,
00:00 UTC). Gilt ab Merge. Bauplan of-live-ps5-2026-11-17, Paket P5. Nur Papier, kein Echtgeld, keine Orders.

Das Live-Journal (`src/research_lab/forward/of_live.py`, auf der PS5 im Ordner `~/tim-research/of-live/journal`,
am Mac gespiegelt nach `data/research/forward/OF_LIVE_PS5`) rechnet dieselbe Regel wie Stufe A
(`of_paper.py`, Ordner `data/research/forward/OF`), nur auf live mitgeschriebenen Binance-Spot-Trades. Diese
Regel legt vorab fest, wie seine Trades ausgewertet werden. Nichts davon wird nach Ansicht der Zahlen geändert.

## Ehrlichkeit vorab: was schon gesehen wurde

- P0-Diagnose (17.11.2026): Stufe A hatte vom 11.11. bis 16.11. **0 Trades**. Das OF-Tor und das Kostentor
  (`max_cost_r` 0,15) verwerfen alle Kandidaten. 100 Trades sind mit dieser Regel deshalb womöglich erst nach
  Monaten oder nie erreicht. Das ist bekannt und wird hier nicht durch Lockern behoben.
- Backtest OF2 1.0 (Training 2020–2022): 56 Trades, +0,27 R im Mittel, nicht belegt. Deflated Sharpe für OF2
  0,06. Das Kostentor 0,15 R wurde auf Trainingsdaten aus mehreren Werten gewählt (Mehrfachtest im Vorfeld).
- Vom Live-Journal selbst wurden vor dem Einfrieren keine zählenden Trades gesehen (Zählbeginn liegt in der Zukunft).

## Gegenstand

- Regel: OF2 1.0 mit OF-Tor (`PAPER_CONFIG`), Config-Digest
  `c9bb0c4af479812fe72359d8941f4408ccc13e80fe7491f7f9116cef085d5b17`, identisch zu Stufe A.
  Steht in `start.json` des Live-Journals ein anderer Digest oder ein `first_day` ungleich 2026-11-18, gibt es
  kein Urteil.
- Daten: Binance-Spot BTCUSDT aggTrades. Fertige Tage aus dem Archiv oder aus einem vollständigen
  Recorder-Tag (lückenlose id-Kette ab Mitternacht). Ein gesperrter oder fehlender Tag hält das Journal an.
- Kosten (Kostenmodell der Engine): Gebühr 0,06 % je Seite, Schlupf 0,03 % je Seite, 0,05 % Schlupf bei
  Stop-Ausführung, Risiko = |Einstieg − Stop|. Grenze: Gebühren von Bitunix-Perps, Preise von Binance Spot,
  Funding 0. Bei langen Haltezeiten fehlt Funding; das steht in jedem Bericht.

## Stichprobe

1. Zählbar ist ein Trade aus `journal.json` des Live-Journals mit `signal_ms` ≥ 2026-11-18 00:00 UTC
   (`first_day` in `start.json`) und `exit_ms` vor dem Ende von `status.last_day` (letzter **fertiger** Tag).
   Trades aus den laufenden Minuten des heutigen Tags zählen erst, wenn ihr Tag fertig ist.
2. Es gilt der Stand von `journal.json` am Auswertungstag. Ersetzt ein Archiv-Tag später einen Recorder-Tag und
   ändern sich dadurch Trades, gilt der Archiv-Stand; die Änderung steht im Bericht.
   Fehlt das Archiv eines Tags am Auswertungstag noch, gilt der Recorder-Stand, im Bericht markiert.
3. Sortiert nach `exit_ms`, bei Gleichstand nach `signal_ms`, `model`, `direction`.
4. Die Stufen unten werten genau die ersten 100 bzw. 318 zählbaren Trades aus, spätere nicht.
5. Stufe A ist die Kontrollspur. Ihre Trades werden nie dazugezählt. Zeigt der Abgleich mit Stufe A
   (`mirror.json`, `abgleich.ok` = false) eine Abweichung, ist das ein Datenfehler: Solange er nicht geklärt
   und im Bericht beschrieben ist, gibt es kein Urteil. Stufe-A-Trades werden nie ersatzweise gezählt.

## Kennzahlen

- Netto-R je Trade (`net_r`), Summe, Mittelwert, Trefferquote (Anteil `net_r` > 0).
- Größter Rückgang der kumulierten Netto-R in Stichproben-Reihenfolge.
- Band: 95-%-Bootstrap des Mittelwerts (Quantile 2,5 % und 97,5 %), 10 000 Ziehungen, Seed 20261118. Gezogen
  werden ganze Cluster: Trades, deren Haltezeiten (`fill_ms` bis `exit_ms`) sich überlappen, bilden einen
  Cluster. Die Zahl der Cluster steht im Bericht.
- Zufallsvergleich: Für jeden Trade 200 Zufallseinstiege am UTC-Tag seines `signal_ms`. Einstieg zum
  Eröffnungskurs einer gleichverteilt gezogenen Minute dieses Tages mit mindestens einem Trade (Seed 20261118,
  Ziehung in Stichproben-Reihenfolge), gleiche Richtung, Stop im gleichen prozentualen Abstand, Ziel im gleichen
  R-Vielfachen wie der echte Trade. Ausstieg mit derselben Ausstiegslogik wie die Engine (`Tracker` in
  `src/research_lab/of2/backtest.py`: Stop, Ziel, Zeitstopp mit dem `tf` des echten Trades, höchstens 1440
  Minuten), gleiche Kosten. Minutenbalken aus derselben Quelle wie das Journal (Archiv vor Recorder). Der
  Vergleich wird erst gerechnet, wenn auch der Folgetag des letzten Trades fertig ist. Zufallslauf k (k = 1..200) nimmt je Trade den k-ten Zufallseinstieg. p = Anteil der 200
  Zufallsläufe, deren Mittel-R ≥ dem echten Mittel-R ist.
- Stresstest: jeder Trade mit doppelten Kosten (`gross_r` − 2 × (`fee_r` + `slippage_r`)).

## Urteilsstufen (genau ein Urteil je Stufe)

| Stufe | Bedingung | Urteil |
|---|---|---|
| Abbruch (jederzeit) | kumulierte Netto-R ≤ −15 R | NICHT BESTANDEN, Zählung endet |
| Erste Stufe, 100 Trades | Mittel-R > 0, p < 0,10, größter Rückgang < 15 R, Mittel-R bei doppelten Kosten > 0 | VIELVERSPRECHEND: im Papier weiter beobachten |
| Erste Stufe, 100 Trades | sonst | NICHT BELEGT: Zwischenstand, die Zählung läuft weiter |
| Nachweis, 318 Trades | Mittel-R > 0, p < 0,05, untere Bandgrenze > 0, gleiches Vorzeichen des Mittel-R in beiden Hälften (Trades 1–159 und 160–318), Mittel-R bei doppelten Kosten > 0 | BELEGT IM PAPIER: Vorschlag an Uzi, mehr nicht |
| Nachweis, 318 Trades | Mittel-R < 0 und obere Bandgrenze < 0 | NICHT BESTANDEN |
| Nachweis, 318 Trades | sonst | NICHT BELEGT |

Die Zählung läuft immer bis 318 Trades oder bis zum Abbruch, unabhängig vom Zwischenstand bei 100. Die erste
Stufe ist nur ein Zwischenblick und kein Beleg. Für den Nachweis zählt allein die Stufe 318
(Stichprobengröße aus der Konsolidierung vom 16.11.2026). Kein Urteil führt zu Echtgeld; Echtgeld bleibt gesperrt.

## Ausdrücklich verboten

- Keine Änderung an Parametern, Kosten oder Daten während der Zählung. Neuer Digest = neue Hypothese mit
  eigenem Journal-Ordner und eigenem Einfrieren.
- Kein Holdout 2025.
- Keine Mischung mit Stufe-A-Trades oder Backtest-Trades.
- Keine Unterteilung (Session, Modell, Richtung) als Beleg; solche Zahlen sind nur beschreibend.
- Ein gelockertes OF-Tor oder Kostentor ist eine eigene, neue Hypothese und braucht Uzis Wort.

## Bericht

Jeder Bericht nennt: Zahl der zählbaren Trades, Zeitraum, herausgefallene Tage mit Grund, Digest aus
`start.json`, Ergebnis des Abgleichs mit Stufe A, alle Kennzahlen oben und das eine Urteil der Stufe.
