# S23: Open Interest am Flip: Sagt Open Interest voraus, ob eine gebrochene Swing-Linie hält, besser als der Abstand zur Linie allein? (Präregistrierung, Entwurf 0.1)

| Feld | Wert |
|---|---|
| Studie | S23 (nächste freie Nummer nach S22, 11.11.2026) |
| Version | **0.1, Entwurf.** Regeln als Code: `src/research_lab/studies/s23.py`, Archiv-Leser `src/research_lab/data/metrics.py`, Tests `tests/test_research_lab_s23.py`. `evaluate` ist gesperrt, bis die Version 1.x ist |
| Anlass | Barti 10./11.11.2026: Open Interest als Flip-Signal nachholen (S21 hatte es ausgelassen). Entscheidungskarte „H5 in S20 nach PR #207“; weil S20 und S21 inzwischen als 1.0 eingefroren sind, wird daraus eine eigene Studie (Barti „S21?“, Antwort im Thread) |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Ereignisse | **unverändert aus S20** (`s20.find_events`, `s20.label`, S20 eingefroren als 1.0) |
| Daten | Binance Spot BTCUSDT 1h 2017-08 bis 2024-12 (wie S20, für Ereignisse und Abstand); Binance USD-M `metrics` BTCUSDT, Tagesdateien 2020-09-01 bis 2024-12-31 (5-Minuten-Schnappschüsse, Spalte `sum_open_interest` in BTC) |
| Holdout | ab 2025-01-01, wird nicht geladen (der Store sperrt auch Tagesdateien ab 2025). Training bis 2022-12-31, Validierung 2023–2024 |
| Einordnung | Beobachtungsstudie ohne Trades, ohne Registerplatz. Kein Filter für Engine, S7b oder Chart, auch bei Bestehen nicht (Abschnitt 8) |

## 1. Fragestellung

Eine Familie gegen das **Mechanik-Modell** (nur Abstand des Schlusses zur Linie in ATR, wie in S21):

| | Familie | Merkmale (fest) | Zeitraum |
|---|---|---|---|
| H1 | **O Open Interest** (Perpetual, in BTC) | `oi_fenster`: Log-Änderung über die 10 Stunden vor der Bruchkerze; `oi_bruch_z`: Log-Änderung in der Bruchstunde als z-Wert gegen die stündlichen Log-Änderungen der 14 Tage davor; `oi_niveau_z`: Log-Niveau bei Eröffnung der Bruchkerze als z-Wert gegen die 14 Tage davor | Ereignisse ab 2020-09-15 |

Gedanke dahinter (nicht Teil des Kriteriums): Ein Bruch, bei dem neue Positionen aufgebaut werden (OI steigt),
könnte eher halten als einer, der von Eindecken oder Liquidationen getragen wird (OI fällt). Die Merkmale
sind **nicht** nach Bruchrichtung gespiegelt, weil steigendes OI auf beiden Seiten „neue Positionen“ heißt.

Werte in BTC, nicht in USD, damit der Preis nicht ein zweites Mal hineinkommt. Ein Stundenwert ist der letzte
Schnappschuss bis zur vollen Stunde, höchstens 10 Minuten alt; sonst fehlt er. Es wird nichts aufgefüllt.

Nicht geprüft: Long/Short-Verhältnisse aus derselben Datei (Anfang 2022 teils leer), Liquidationen, OI
anderer Börsen, Coin-margined Kontrakte, Kombination mit den S21-Familien.

## 2. Vorbelastung

- **S20 und S21 sind gesehen** (beide nicht bestanden, Berichte `../reports/s20_ergebnis_2026-11-11.md`,
  `../reports/s21_ergebnis_2026-11-11.md`). Ereignisse, Label und Validierung sind dieselben, die Validierung
  2023–2024 ist damit zum dritten Mal benutzt und **nicht frisch**. Bekannt ist: Flip-Quote 37 % / 31 %, der
  Abstand sortiert (AUC 0,652 in der S21-Validierung), Kerzenform, CVD, Footprint und Funding bringen nichts.
- S23 übernimmt deshalb nur Ereignisse, Label, Abstand und N = 10 (S20-Wahl im Training) und testet allein,
  was OI zusätzlich bringt. Die OI-Daten selbst hat noch keine Studie angesehen.
- Die Merkmale wurden **nach** Kenntnis der S21-Ergebnisse entworfen, aber ohne einen Blick auf OI-Werte an
  den Ereignissen. Gesehen wurden nur 11 Stichproben-Tage zur Datenprüfung (Abschnitt 3).
- Folge: Ein Bestehen zählt nur als Kandidat für einen vorab festgelegten Vorwärtslauf (Abschnitt 8).

## 3. Daten und Ausschluss

Befund vom 11.11.2026 (vollständige Dateiliste des Archivs und 11 Stichproben-Tage):

- Tagesdateien lückenlos 2020-09-01 bis heute. Die Dateien 2020-09 bis 2021-11 hat Binance erst am
  18.03.2026 nachgeliefert; die Naht 2021-11-30 → 2021-12-01 ist stetig (59 210,65 → 59 230,06 BTC).
- Dateien bis 2021-11 enthalten jede Zeile doppelt; der Leser fasst gleiche Zeilen zusammen und bricht ab, wenn
  eine Zeit zwei verschiedene Werte hat.
- Einzelne Tage haben weniger als 288 Schnappschüsse (z. B. 284 am 2021-11-30).
- Binance hat viele Tage später neu hochgeladen (2026-07 bis 2026-10). Der Store hält die Prüfsumme des ersten
  geprüften Downloads fest; der Datensatz-Hash geht in jedes Ergebnis.

Ausschluss: Ereignisse vor 2020-09-15 (14 Tage Vorlauf), und Ereignisse, bei denen einer der Stundenwerte am
Fensteranfang, bei Eröffnung oder Schluss der Bruchkerze fehlt oder weniger als 300 der 336 Vorlaufstunden
vorliegen. Sie verlassen die Studie, ohne dass etwas aufgefüllt wird.

## 4. Modell

Zwei logistische Regressionen mit festem L2-Strafterm 1,0 auf standardisierten Merkmalen (`s20.fit`):
A = nur Abstand, B = Abstand plus die drei OI-Merkmale. Beide nur auf dem Training angepasst, ein Blick auf
2023–2024. Kein Tuning, keine Merkmalsauswahl.

## 5. Erfolgskriterien

In der Validierung, alle müssen erfüllt sein:

| # | Kriterium |
|---|---|
| 1 | Machbarkeits-Gate: ≥ 200 Ereignisse Training und ≥ 150 Validierung mit vollständigen Merkmalen |
| 2 | Log-Verlust von B mindestens 1 % unter A |
| 3 | Block-Bootstrap über Ereignis-Wochen (Blocklänge 4, 9 999 Ziehungen): p < 0,05. Eine Familie, kein Holm (m = 1) |
| 4 | Glückstest: Labels je Abschnitt im Kreis verschoben (mindestens 50 Ereignisse), A und B neu angepasst, 199 Verschiebungen: p < 0,05 |
| 5 | Naht-Prüfung: A und B nur auf Trainingsereignissen ab 2021-12-01 angepasst (der damals veröffentlichte Teil des Archivs), B ist in der Validierung besser als A (Gewinn > 0). Weniger als 80 solche Ereignisse: Kriterium nicht erfüllt |

Urteil: „BESTANDEN (Kandidat)“, „NICHT BESTANDEN“ oder „nicht testbar (Gate)“. Gegenprobe am synthetischen
Datensatz ohne OI-Signal, nur der Abstand wirkt (fünf Seeds 10–14, keine echten Daten): jedes Mal nicht
bestanden (Gewinn −0,4 % bis +0,4 %, Bootstrap-p 0,36 bis 0,85). Ein gepflanztes Signal nur in den
nachgelieferten Jahren fällt an Kriterium 5 durch (Test).

### 5.1 Machbarkeits-Gate (ergebnisblind)

`count` zählt Ereignisse ab 2020-09-15 je Abschnitt, davon mit vollständigen Merkmalen, und die Trainings-
ereignisse ab 2021-12, ohne Label. Aus dem S21-Zähllauf bekannt: 318/216 Ereignisse ab 2020-01; ab 2020-09-15
sind im Training grob 240 zu erwarten. Deshalb liegt das Gate bei 200 statt 250. Es wird nach dem Zähllauf
nicht gelockert.

## 6. Was nicht geändert wird

S20-Ereignisregeln, die drei Merkmale, 10 Stunden, 14 Tage, 10 Minuten Höchstalter, Kriterien. Kein zweites
Modell, keine weiteren Merkmale, kein Lauf auf ETH/SOL als „zweiter Versuch“, keine Kombination mit S21.

## 7. Ablauf bis 1.0

1. Code und Tests (0.1, dieser Stand): Leser für Tagesdateien mit Prüfsumme und Holdout-Sperre, Merkmale ohne
   Vorausschau (Test: Schnappschüsse nach dem Bruchschluss ändern nichts), Höchstalter, Naht-Prüfung, Sperre
   von `evaluate`. Gepflanztes OI-Signal besteht; reiner Abstand besteht nicht.
2. Zähllauf auf PS5 oder Mac (lädt rund 1 580 Tagesdateien, je etwa 12 KB):
   `python -m src.research_lab.studies.s23 count --root data/research_lab --out ~/tim-research/results/s23 --fetch`
3. Einfrieren als 1.0 auf Uzis Wort **und** Bartis schriftliches Go im Thread.
4. Ergebnislauf: derselbe Befehl mit `evaluate`. Bericht nach Abschnitt 5.

## 8. Einordnung ins Gesamtsystem

Auch bei Bestehen geht nichts direkt in Engine, S7b, Chart oder Setup-Pfad. Die Validierung ist durch S20 und
S21 vorbelastet. Nächster Schritt wäre ein vorab festgelegter Vorwärtslauf (wie das F3/F5-Log, OI live über
die Binance-API) oder der Holdout nach Freigabe von Uzi und Barti.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-11 | 0.1 | Entwurf mit Code und Tests. Keine OI-Werte an Ereignissen angesehen, kein Zähllauf. |
