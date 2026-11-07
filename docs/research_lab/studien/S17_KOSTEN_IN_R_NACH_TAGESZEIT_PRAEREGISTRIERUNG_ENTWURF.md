# S17: Kosten in R nach Tageszeit: In welchen Stunden fressen feste Gebühren den Vorteil am wenigsten? (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S17 |
| Version | **Entwurf 0.2 – wartet auf Uzis Freigabe (Forschungsbereich Stufe 1); vorher werden keine Daten geladen** |
| Erzeugt | 2026-11-07 00:16 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0002 aus Quelle „Wöchentliche KI-Runde“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Ereignis-Studie (wie S1) |
| Spezifikation | SHA-256 `2bc948fc2c70189c4c62b227f08542aac588d7af49fdfb05fe26b100fd1152ac` (gilt für Entwurf 0.1 vom Generator; die Ergänzungen in 0.2 sind von Hand und vom Hash **nicht** gedeckt) |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |
| Register | Eigene Familie außerhalb des Holdout-Registers (wie S1/S8); belegt keine Registerplätze. |

## 1. Fragestellung

In welchen Stunden fressen feste Gebühren den Vorteil am wenigsten?

## 2. Hypothese und Herkunft

Die realisierte Minutenvolatilität (aus S8-Minutenbalken) und die aggressive Handelsaktivität unterscheiden sich systematisch nach UTC-Stunde und Wochentag. Bei festen Gebühren plus Slippage-Annahme liegen die Kosten in Einheiten eines typischen Stop-Abstands (R) in den volatilsten Stunden (etwa Überlappung Europa/New York) deutlich unter 0,25 R, in ruhigen Stunden darüber. Die Studie schätzt die Kosten-in-R-Verteilung je Stunde und prüft, ob der Unterschied zwischen den besten und schlechtesten Stunden über mehrere Jahre stabil ist (Jahr-für-Jahr-Rangkorrelation). Sie liefert einen Zeitfilter für spätere Regeln, aber selbst keine Richtung.

Gegenargument: Das Ergebnis ist weitgehend bekannt (Volatilität und Volumen haben eine Tagesstruktur), der Informationsgewinn kann gering sein. Höhere Volatilität senkt zwar die Kosten in R, erhöht aber auch die Wahrscheinlichkeit, per Wick ausgestoppt zu werden (STOP_BY_WICK) und die Ereignisnähe zu CPI-Terminen. Die Stundenstruktur kann sich zudem zwischen Jahren verschieben. Ohne Richtungsvorteil im Einstieg bleibt ein Zeitfilter nur eine Kostenverbesserung und macht keine negative Erwartung positiv (Lehre aus S4 und S6).

## 3. Vorbelastung

- **S4** (Trefferquote 75 %, beendet NICHT TESTBAR am Machbarkeits-Gate): Ihre Ausgangslage hält fest, dass alle Short-Varianten aus R4 netto negativ waren, weil die Kosten enge Stops auffressen, und dass die Struktur-Regel im Plan-Journal mit 0,15 % Stop 1,2 R Kosten je Trade hatte. S4 hat deshalb ein Kostentor „Stop ≥ 1,0 %“ gesetzt (höchstens 0,18 R Stopfall-Kosten mit `BASE_COSTS`). Belastend für S17: Der Kostenblock in R ist bekannt und mit dem 1-%-Tor schon gedeckelt; S17 kann nur zeigen, in welchen Stunden ATR-Stops die Kosten senken, nicht, dass dort ein Vorteil entsteht.
- **S6** (Maker-Mean-Reversion, NICHT BESTANDEN im Training): Trotz Maker-Gebühr 0,02 % lag E[R] bei −0,07 bis −0,11 R. Belastend für S17: Niedrigere Kosten allein haben eine negative Erwartung nicht positiv gemacht. S17 übernimmt aus S6 nur die n_eff-Regel (PROTOKOLL.md 1.3, A3).
- **S8** (lokale BTC-Orderflow-Prognose, Sequenzvergleich 28.10.: kein praktischer Zusatznutzen): S8 nutzt dieselben BTCUSDT-Spot-aggTrades und Minutenbalken 2020–2024 und führt `hour_utc` als Merkmal. Belastend für S17: Training und Validierung dieses Datensatzes sind schon für S8 ausgewertet worden; die Daten sind für S17 nicht frisch. Den frischen Test liefert erst der gesperrte Holdout ab 2025.

## 4. Daten

- archive_aggtrades_btc (BTC aggTrades / S8-Minutenbalken (Archiv))
- archive_spot_klines (Binance Spot-Kerzen (Archiv))

### 4.1 Instrumente und Zeitraum

- Instrument: nur BTCUSDT Spot.
- Hauptreihe: S8-Minutenbalken (`src/research_lab/orderflow_ml/bars.py`, `MinuteBar`), reduziert aus den täglichen Binance-aggTrades-Archiven mit Prüfsumme (wie S8). Daraus werden 1h-Kerzen je UTC-Stunde gebildet: Eröffnung = erster Preis der ersten Minute mit Handel, Hoch/Tief = Extrem über die Minuten, Schluss = letzter Preis der letzten Minute mit Handel.
- Binance Spot-Kerzen (1h, `archive_spot_klines`) dienen nur zur Gegenprobe der aggregierten Kerzen (Abweichung von Eröffnung, Hoch, Tief, Schluss je Stunde wird berichtet); sie gehen nicht in die Messgröße ein.
- Zeitraum: 2020-01-01 bis 2024-12-31 (UTC), plus 14 Stunden Vorlauf für die ATR.
- Datensplit nach PROTOKOLL.md 3.2: Training 2020-01-01 bis einschließlich 2022-12-31, Validierung 2023-01-01 bis 2024-12-31. Ein Fall gehört zu dem Abschnitt, in dem seine Stunde beginnt. Die ATR-Vorlaufstunden dürfen aus dem vorigen Abschnitt stammen (nur Vergangenheit, keine Ergebnisse); kein Abschnitt liest Daten des nächsten.
- Der Holdout ab 2025-01-01 ist gesperrt und wird nicht geladen.

## 5. Ereignisse und Vergleich

- Minutenvolatilität aus S8-Minutenbalken
- Aggressive Handelsaktivität

Vergleich: Vergleich der Kosten-in-R-Verteilung je Stunde und Wochentag

### 5.1 Ereignisdefinition

- **Fall:** jede UTC-Stunde jedes Tages im Zeitraum. Zelle = UTC-Stunde (0–23) × Wochentag (Mo–So, UTC). Etwa 26 300 Fälle im Training und 17 500 in der Validierung, je Zelle in der Validierung etwa 104.
- **Kostensatz** aus dem Protokoll-Kostenmodell (`src/research_lab/protocol.py`, `BASE_COSTS`, PROTOKOLL.md 4.4): Gebühr `fee` = 0,05 % je Seite (Taker), Slippage `slippage` = 0,03 % je Seite. Hin und zurück c = 2 × (0,05 % + 0,03 %) = **0,16 %** (wie der Kostenboden in S8 und der Gewinnfall in S4). Beschreibend zusätzlich: Stopfall mit `stop_slippage` 0,05 % beim Ausstieg (0,18 %) und `STRESS_COSTS` (0,32 %).
- **Stop-Abstand** nach der Stop-Definition des Papier-Journals S7b (`src/research_lab/hypotheses/s7.py`, auch in `forward/s7b.py`): `ATR_FACTOR` 1,5 × ATR(14), ATR nach `src/research_lab/backtest/indicators.py` `atr()` = einfacher Mittelwert der True Range der letzten 14 **geschlossenen** Kerzen (kein Wilder-Glätten). In S17 wird die ATR zu Stundenbeginn aus den 14 vorher geschlossenen 1h-Kerzen berechnet (nur Vergangenheit).
- **Kosten in R je Fall** (PROTOKOLL.md 4.3) = c × Eröffnungskurs der Stunde / Stop-Abstand.
- **Abweichungen vom Papier, Vorschlag in 0.2, Entscheid bei Uzis Freigabe:**
  1. Intervall: S7b rechnet die ATR auf 4h-Kerzen USD-M. Eine 4h-ATR ist innerhalb eines 4h-Blocks für alle Stunden gleich und glättet die Tagesstruktur weg, deshalb verwendet die Hauptmessung 1h-Kerzen. Die 4h-Variante (aus denselben Minutenbalken, 14 geschlossene 4h-Blöcke ab 00:00 UTC) wird beschreibend berichtet.
  2. Mindestabstand: S7b setzt den Stop auf mindestens `MIN_STOP_DISTANCE` = 1 % des Kurses. Damit sind die Kosten auf höchstens 0,16 R gedeckelt; greift der Mindestabstand in vielen Stunden, verschwindet jeder Stundenunterschied. Die Hauptmessung rechnet deshalb **ohne** Mindestabstand. Beschreibend berichtet werden: Kosten in R mit Mindestabstand und der Anteil der Fälle je Stunde, in denen der Mindestabstand greift.
- **Ausschluss:** Ein Fall zählt nicht, wenn die Stunde selbst oder eine der 14 Vorlaufstunden keine Minute mit Handel hat oder wenn eine Minute laut Reduktionsbericht fehlerhaft ist. Ausschlüsse werden je Abschnitt und Grund gezählt.
- **Aggressive Handelsaktivität** (Kaufanteil `buy_quote_e8 / (buy_quote_e8 + sell_quote_e8)` und Handelszahl `trade_count` je Stunde) und Minutenvolatilität (Standardabweichung der 1-Minuten-ln-Renditen je Stunde) werden je Stunde und Zelle **nur beschreibend** berichtet; sie gehen in keinen Test ein.
- Anteil der Stunden mit Median Kosten in R unter 0,25 R (Schwelle aus der Hypothese und PR #408) wird beschreibend berichtet.

### 5.2 Entclusterung und effektives n

- Benachbarte Stunden sind über die überlappenden ATR-Fenster und die Volatilitätsbündelung autokorreliert. Statt Fälle auszudünnen trägt das der Block-Bootstrap über **Kalenderwochen** (7 Tage, Montag 00:00 UTC bis Sonntag 24:00 UTC, nicht überlappend): Jeder Block enthält jede Zelle einmal, die Wochentagsstruktur bleibt erhalten. 10 000 Ziehungen, fester Seed, im Code vor dem Laden der Daten eingefroren. Angebrochene Randwochen zählen als eigene, kürzere Blöcke.
- n_eff = ⌊n / D⌋ mit dem Designeffekt D aus dem Tagescluster wie in S6 (PROTOKOLL.md 1.3, A3): Cluster = Kalendertag UTC, D = Varianz des Mittelwerts aus Tagesclustern geteilt durch s² / n, mindestens 1. n_eff wird je Abschnitt und Stundengruppe berichtet und ist kein Kriterium.
- Mindestzahlen, gezählt im Zähllauf vor jeder Auswertung (nur Fallzahlen, keine Kosten): mindestens 5000 gültige Fälle je Abschnitt und mindestens 100 je Zelle. Wird eine davon verfehlt, lautet das Ergebnis des Abschnitts bzw. der Zelle „nicht prüfbar“.

## 6. Messgröße und Entscheidung

- Messgröße: Kosten in R (Abschnitt 5.1)
- Kleinster Effekt: 0,05 R Unterschied im Median der Kosten in R zwischen den besten und schlechtesten Stunden
- Mindestzahl Fälle: 5000 je Abschnitt und 100 je Zelle (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)
- Stoppregel: Ausgewertet werden alle gültigen Fälle des Zeitraums, es gibt kein vorzeitiges Stoppen und keine Zwischenauswertung. Unter der Mindestzahl lautet das Ergebnis „nicht prüfbar“.

### 6.1 Test

- **Hauptvergleich Stunden:** Im Training wird der Median der Kosten in R je UTC-Stunde (über alle Wochentage) bestimmt. Die 6 günstigsten Stunden bilden Gruppe G, die 6 teuersten Gruppe T (Gleichstand: kleinere Stundenzahl zuerst). Beide Gruppen werden danach fest eingefroren und im Bericht genannt, bevor die Validierung gelesen wird. Δ_h = Median(T) − Median(G) in R, getrennt im Training und in der Validierung.
- **Zweiter Vergleich Wochentag:** Im Training werden der günstigste und der teuerste Wochentag (Median über alle Stunden) bestimmt und eingefroren. Δ_w = Median(teuerster) − Median(günstigster) in R, in Training und Validierung.
- 95-%-Konfidenzintervall und p-Wert per Block-Bootstrap über Kalenderwochen (5.2); beide Mediane werden in jeder Ziehung neu berechnet. p zweiseitig: p = min(1, 2 · (1 + min(#Δ* ≤ 0, #Δ* ≥ 0)) / (1 + 10 000)).
- Hinweis: Im Training sind die Gruppen auf denselben Daten ausgewählt, der Trainingstest ist dadurch nach oben verzerrt und nur eine notwendige Bedingung. Beweiskraft hat der Test in der Validierung mit den eingefrorenen Gruppen.
- **Stabilität:** Spearman-Rangkorrelation der 24 Stunden-Mediane zwischen aufeinanderfolgenden Jahren (2020→2021, 2021→2022, 2022→2023, 2023→2024). Kriterium: ρ ≥ 0,5 für jedes der vier Jahrespaare.

### 6.2 Mehrfachtest

- Holm-Bonferroni über die 2 Hauptvergleiche (Stunden, Wochentag), α = 5 %, je Abschnitt (m = 2; eigene Familie wie S1/S8).
- Zellvergleiche (Stunde × Wochentag) werden nur beschreibend berichtet (Median und Bootstrap-Intervall je Zelle), ohne Test.

### 6.3 Entscheidung

- **BESTANDEN** nur, wenn alle drei Bedingungen erfüllt sind: (1) Hauptvergleich Stunden im Training **und** in der Validierung nach Holm signifikant, (2) Δ_h ≥ 0,05 R in beiden Abschnitten, (3) Stabilitätskriterium aus 6.1 erfüllt.
- Der Wochentagsvergleich zählt für die Holm-Korrektur, ist aber keine Bedingung für BESTANDEN; er wird berichtet.
- Sonst **NICHT BESTANDEN**; bei verfehlter Mindestzahl **nicht prüfbar**.
- Auch ein BESTANDEN liefert nur einen Zeitfilter für Kosten, keine Richtung und keine Setup-Evidenz (Abschnitt 2).

## 7. Bekannte Grenzen

- Die Studie betrachtet nur Daten bis 2024-12-31, da der Holdout-Zeitraum gesperrt ist.
- Es wird nur eine feste Gebührenstruktur mit Slippage-Annahme verwendet, keine dynamischen Kostenmodelle.
- Die Ergebnisse gelten nur für den Papierhandel unter festen Gebühren und nicht für Echtgeld-Handel.
- Gebühr und Slippage sind je Stunde konstant (Protokoll-Kostenmodell). Gemessen wird also nur, wie der ATR-Stop-Abstand die Kosten in R über den Tag verschiebt. Dass echte Slippage in ruhigen Stunden höher sein kann, bildet die Studie nicht ab.
- Die Kostensätze sind die USD-M-Taker-Sätze des Protokolls, die Kurse kommen aus BTCUSDT Spot (Spot-Taker-Gebühr bei Binance ist höher). Das ist eine bewusste Vereinfachung: Die Messgröße hängt nur vom Verhältnis ATR zu Kurs ab, das sich zwischen Spot und Perpetual kaum unterscheidet.
- Wick-Stopps (STOP_BY_WICK) und CPI-Nähe aus dem Gegenargument werden nicht gemessen.
- Training und Validierung sind für S8 schon ausgewertet worden (Abschnitt 3); die Daten sind nicht frisch.

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
| 2026-11-07 | 0.2 | Von Hand ergänzt: Vorbelastung S4/S6/S8 begründet (3), Instrument, Zeitraum und Datensplit (4.1), Ereignisdefinition mit `BASE_COSTS` und S7b-Stop 1,5 × ATR(14) (5.1, zwei Abweichungen als Vorschlag), Wochenblock-Bootstrap und n_eff (5.2), Test (6.1), Holm über 2 Vergleiche (6.2), Entscheidung (6.3), kleinster Effekt von Prozentpunkten auf 0,05 R korrigiert, Stoppregel ohne vorzeitiges Stoppen. Spezifikations-Hash gilt nur für 0.1 |
