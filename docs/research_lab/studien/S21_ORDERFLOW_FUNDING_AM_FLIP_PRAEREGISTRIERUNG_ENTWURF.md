# S21: Orderflow und Funding am Flip: Sagen CVD, Footprint oder Funding voraus, ob eine gebrochene Swing-Linie hält, besser als der Abstand zur Linie allein? (Präregistrierung 1.0)

| Feld | Wert |
|---|---|
| Studie | S21 (nächste freie Nummer nach S20, 11.11.2026) |
| Version | **1.0, eingefroren am 11.11.2026** auf Bartis schriftliches Go (11.11.2026 15:19) und Uzis Wort (11.11.2026 15:37). Regeln, Konstanten und Kriterien unverändert gegenüber 0.1 (mit Funding-Fix aus PR #215); geändert wurde nur `VERSION`. Regeln als Code: `src/research_lab/studies/s21.py`, Tests `tests/test_research_lab_s21.py`. Zähllauf bestanden (Abschnitt 5.1). Der Dateiname behält „ENTWURF“, damit Verweise nicht brechen |
| Anlass | Barti 11.11.2026, nach dem S20-Ergebnis: Die Flip-Signale sollen auch Volumen und Orderflow umfassen (CVD und Divergenz, Volumentrend, Footprint an der Linie, Funding). Entscheidungskarte „Neue Studie S21“ |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Ereignisse | **unverändert aus S20** (`s20.find_events`, `s20.label`, S20 eingefroren als 1.0): erster Stundenschluss mindestens 0,25 ATR14 jenseits eines bestätigten Swing-Hochs/-Tiefs (24 Kerzen je Seite), Flip = 24 Stunden kein Schluss zurück |
| Daten | Binance Spot BTCUSDT 1h 2017-08 bis 2024-12 (wie S20, Datensatz-Hash `a9f525df…6fa9`); S8-Minutenbalken 2020–2024 (Footprint, wie S19); Binance USD-M Funding BTCUSDT 2020-01 bis 2024-12 (das Archiv beginnt 2020-01; Ereignisse im ersten Monat 2020 haben noch keine 90 Raten und verlassen nur G, Abschnitt 3) |
| Holdout | ab 2025-01-01, wird nicht geladen. Training bis 2022-12-31, Validierung 2023–2024 |
| Einordnung | Beobachtungsstudie ohne Trades, ohne Registerplatz. Kein Filter für Engine, S7b oder Chart, auch bei Bestehen nicht (Abschnitt 8) |

## 1. Fragestellung

Je Familie eine Frage, jede gegen das **Mechanik-Modell** (nur Abstand des Schlusses zur Linie in ATR, das
Einzige, was in S20 sortiert hat):

| | Familie | Merkmale (fest) | Zeitraum |
|---|---|---|---|
| H1 | **K Kerzen-Orderflow** | CVD-Anteil in Bruchrichtung über die 10 Kerzen davor und die Bruchkerze; CVD-Gleichlauf (Korrelation kumuliertes Delta mit Schlusskurs, negativ = Divergenz); Volumentrend (Log-Volumen zweite minus erste Fensterhälfte) | 2017–2024 |
| H2 | **F Footprint an der Linie** | je Engine-Familie (Imbalance-Stapel, Auktionsrand, Absorptions-Cluster, dünnes Extrem, Absorption mit Anstrengung, Erschöpfung) mit dem heutigen Schwellwert: Signale in Bruchrichtung minus dagegen, geteilt durch 8, über die acht 15m-Kerzen von einer Stunde vor dem Bruch bis zum Bruchschluss | 2020–2024 |
| H3 | **G Funding** | letzte bis zum Bruchschluss veröffentlichte Rate (Basispunkte) und ihr z-Wert gegen die 90 Raten davor, beide in Bruchrichtung gespiegelt (positiv = die Seite des Ausbruchs zahlt schon) | 2020–2024 |

Nicht geprüft: Open Interest (eigener Thread; Archiv nach heutigem Stand erst ab 12/2021), Liquidationen,
Makro, Tageszeit, Einstieg/Stop/Ziel/Kosten. Keine Kombination aller Familien im Urteil.

## 2. Vorbelastung

- **S20 ist gesehen** (nicht bestanden, Bericht `../reports/s20_ergebnis_2026-11-11.md`): Flip-Quote 37 %
  (Training) bzw. 31 % (Validierung); Kerzenmerkmale (Körper, Dochte, Spanne, Volumen, Taker-Saldo der
  Bruchkerze, Fenstermerkmale) bringen nichts über den Abstand hinaus; der Abstand sortiert. Folgen für S21:
  - Ereignisse, Label und Daten sind dieselben. Die Validierung 2023–2024 ist damit **nicht frisch**: Wer S20
    kennt, kennt dort die Flip-Quote und dass der Abstand trägt. S21 testet deshalb nur, was **zusätzlich**
    zum Abstand trägt, und übernimmt kein S20-Merkmal außer dem Abstand.
  - Das Fenster N = 10 stammt aus der S20-Wahl **im Training** (Kreuzvalidierung 2019–2022). Es wird hier
    nicht neu gewählt. Dass 10 in der S20-Validierung nichts brachte, ist bekannt; N bleibt trotzdem 10, um
    keine zweite Wahl auf gesehenen Daten zu treffen.
  - Volumentrend und CVD sind neu, aber verwandt mit S20s Volumenverhältnis und Taker-Saldo (beide ohne
    Wirkung). Ein Erfolg von K muss deshalb deutlich sein (Kriterien in 5).
- **S19** (Orderflow-Schwellen, Entwurf, kein Ergebnis): S21 nutzt S19s Leser nur mit den heutigen
  Schwellen, nie das Raster. Ändert S19 später eine Schwelle, bleibt S21 beim Stand des Einfrierens.
- **S8** (lokale Orderflow-Prognose, kein Zusatznutzen): Dieselben Minutenbalken 2020–2024 sind für S8
  ausgewertet worden, mit anderen Merkmalen und anderer Frage.
- **S16** (Funding-Extreme, Entwurf) und **F2** (Funding-Filter auf S7b, nicht bestanden): Funding auf
  BTC 2020–2024 ist als Renditefilter angesehen, nicht als Merkmal für das Halten von Linien.
- Der Code war zuerst als S20 0.3 gedacht (PR #207) und wurde fertig, eine Minute nachdem Uzi S20
  eingefroren und gerechnet hatte. Die Merkmale wurden **vor** Kenntnis des S20-Ergebnisses entworfen und
  danach nicht verändert; nur Abschnitt 1 (gegen Mechanik statt gegen das S20-Modell) ist neu.

## 3. Ereignisse und Ausschluss

Wie S20 (Abschnitt 3 dort). Zusätzlich je Familie: Ein Ereignis ohne vollständige Merkmale (fehlende oder
handelslose 15m-Kerze, weniger als 90 frühere Funding-Raten, Ereignis vor 2020 für F und G) verlässt nur
diese Familie. Es wird nichts aufgefüllt.

## 4. Modell

Je Familie zwei logistische Regressionen mit festem L2-Strafterm 1,0 auf standardisierten Merkmalen (der
S20-Code `s20.fit`): A = nur Abstand, B = Abstand plus die Familie. Beide nur auf dem Training der Familie
angepasst, ein Blick auf 2023–2024. Kein Tuning, keine Fensterwahl, keine Merkmalsauswahl.

## 5. Erfolgskriterien

Je Familie, in der Validierung:

| # | Kriterium |
|---|---|
| 1 | Machbarkeits-Gate: K ≥ 400 Ereignisse Training und 150 Validierung; F und G ≥ 250 und 150 mit vollständigen Merkmalen |
| 2 | Log-Verlust von B mindestens 1 % unter A |
| 3 | Block-Bootstrap über Ereignis-Wochen (Blocklänge 4, 9 999 Ziehungen, Seed 21), Holm über H1–H3 (m = 3, nicht testbar zählt als p = 1): p < 0,05 |
| 4 | Glückstest: Labels je Abschnitt im Kreis verschoben (mindestens 100 bzw. 50 Ereignisse), A und B neu angepasst, 199 Verschiebungen: p < 0,05 |

Urteil je Familie: „BESTANDEN (Kandidat)“, „NICHT BESTANDEN“ oder „nicht testbar (Gate)“. Gegenprobe am
synthetischen Zufallspfad (fünf Seeds, nur K, keine echten Daten): K jedes Mal nicht bestanden (Gewinn −0,8 %
bis +0,3 %, Bootstrap-p 0,07 bis 0,95).

### 5.1 Machbarkeits-Gate (ergebnisblind)

`count` zählt je Familie die Ereignisse mit vollständigen Merkmalen in Training und Validierung, ohne Label.
Das Gate wird nicht gelockert. Aus S20 ist schon bekannt: 561/216 Ereignisse insgesamt, davon etwa 318/216
ab 2020. Ob F und G ihr Gate schaffen, hängt von der Footprint- und Funding-Abdeckung ab.

## 6. Was nicht geändert wird

S20-Ereignisregeln, Merkmale in Abschnitt 1, N = 10, Kriterien. Kein zweites Modell, keine weiteren
Merkmale, kein Lauf auf ETH/SOL als „zweiter Versuch“.

## 7. Ablauf bis 1.0

1. Code und Tests (0.1, erledigt): Merkmale ohne Vorausschau (Tests: nur Kerzen bis zum Bruchschluss, nur
   bis dahin veröffentlichte Funding-Raten, fehlende 15m-Kerze), Familienprüfung, Holm, Glückstest,
   Sperre von `evaluate`. Gepflanztes Footprint-Signal besteht nur in F; reiner Abstand besteht nirgends.
2. Zähllauf auf PS5 oder Mac:
   `python -m src.research_lab.studies.s21 count --root data/research_lab --out ~/tim-research/results/s21 --fetch --footprint ~/tim-research/data/orderflow_ml_120 --fp-cache ~/tim-research/results/s19/cache --workers 16`
3. Einfrieren als 1.0 auf Uzis Wort **und** Bartis schriftliches Go im Thread (bei S20 fehlte das).
4. Ergebnislauf: derselbe Befehl mit `evaluate`. Bericht nach Abschnitt 5.

## 8. Einordnung ins Gesamtsystem

Auch eine bestandene Familie geht nicht direkt in Engine, S7b, Chart oder Setup-Pfad. Die S7b-Filterfragen
auf 2017–2024 sind verbraucht, und die Validierung ist durch S20 vorbelastet. Nächster Schritt wäre dann ein
vorab festgelegter Vorwärtslauf (wie das F3/F5-Log) oder der Holdout nach Freigabe von Uzi und Barti.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-11 | 0.1 | Entwurf mit Code und Tests aus dem zurückgezogenen S20-0.3-Vorschlag (PR #207), umgestellt auf drei Familien gegen das Mechanik-Modell. Keine Daten geladen. |
| 2026-11-11 | 0.1 | Funding-Daten ab 2020-01 statt 2019-10: Das Binance-Archiv hat vorher keine Monatsdateien (404), der Zähllauf brach ab. Merkmale, Lookback und Kriterien unverändert; vor jedem Zähl- oder Ergebnislauf. |
| 2026-11-11 | 0.1 | Zähllauf (ergebnisblind, ohne Label) auf der PS5, Code cb12cef: Binance Spot BTCUSDT 1h 2017-08 bis 2024-12, 64 525 Kerzen, Datensatz-Hash a9f525df…4826fa9 (wie S20). Verworfen: 313 entprellt, 21 Lücke oder Rand, 325 mitgenommen. K 561/216, F 318/216, G 308/216 (Training/Validierung). Alle drei Gates bestanden. |
| 2026-11-11 | 1.0 | Eingefroren auf Bartis schriftliches Go und Uzis Wort. Keine Regel, keine Konstante, kein Kriterium geändert. |
