# S16: Funding-Extreme als Kontraindikator: Verteilung der 24-h-Rendite nach extremem Funding (ohne Carry) (Präregistrierung, Entwurf)

| Feld | Wert |
|---|---|
| Studie | S16 |
| Version | **1.0 – freigegeben** von Uzi am 06.11.2026 um 20:37 Ortszeit („s16frei“); Regeln vor dem ersten Datenzugriff eingefroren |
| Erzeugt | 2026-11-06 09:18 Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |
| Idee | I-0001 aus Quelle „Wöchentliche KI-Runde“ (`data/research/IDEEN.jsonl` auf dem Mac) |
| Vorlage | Ereignis-Studie (wie S1) |
| Spezifikation | SHA-256 `25621adf840d848bc556da909d55b657f995c860fb7e08e6692e2d3b978e55a1` (gilt für Entwurf 0.1 vom Generator; die Ergänzungen in 0.2 und 1.0 sind von Hand und vom Hash **nicht** gedeckt; maßgeblich für 1.0 ist der Commit dieser Datei) |
| Protokoll | `../PROTOKOLL.md` Version 1.3 |
| Holdout | ab 2025-01-01, wird nur mit Uzis ausdrücklichem Wort geladen |
| Register | Eigene Familie außerhalb des Holdout-Registers (wie S1/S8); belegt keine Registerplätze. |

## 1. Fragestellung

Nach Funding-Werten im obersten bzw. untersten Dezil (rollierend, nur Vergangenheit) unterscheidet sich die Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags von der Gesamtverteilung, weil überhitzte Positionierung Liquidationskaskaden begünstigt.

## 2. Hypothese und Herkunft

Nach Funding-Werten im obersten bzw. untersten Dezil (rollierend, nur Vergangenheit) unterscheidet sich die Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags von der Gesamtverteilung, weil überhitzte Positionierung Liquidationskaskaden begünstigt. Untersucht wird nur die Renditeverteilung als Ereignisstudie, nicht Carry und keine Trefferquote wie in S5.

Gegenargument: Extreme Funding-Werte clustern stark in wenigen Marktphasen. Die effektive Stichprobe ist daher viel kleiner als die Zahl der Funding-Termine, und überlappende 24-h-Fenster sind autokorreliert. S5 hat gezeigt, dass seltene Signale an der Stichprobe scheitern. Funding ist zudem breit bekannt, ein möglicher Effekt dürfte weitgehend wegarbitriert sein.

## 3. Vorbelastung

S5 (Funding-Carry) nutzt dasselbe Funding-Archiv und hat gezeigt, dass seltene Signale an der Stichprobe scheitern. S16 begegnet dem mit der Entclusterung und dem effektiven n in Abschnitt 5.2 und mit dem Block-Bootstrap in Abschnitt 6.1. S16 misst keine Carry-Erträge und keine Trefferquote, sondern nur die Verteilung nach dem Funding-Termin.

## 4. Daten

- archive_spot_klines (Binance Spot-Kerzen (Archiv))
- archive_usdm_klines (Binance USD-M-Kerzen und Funding (Archiv))

### 4.1 Instrumente und Zeitraum

- Instrumente: BTCUSDT, ETHUSDT und SOLUSDT, USD-M Perpetual (wie S4/S5, Universum nach PROTOKOLL.md 3.1 mit dessen Survivorship-Grenze).
- Reihen: Funding-Termine (`fundingRate`, je 8 h) und 1h-Kerzen USD-M aus `archive_usdm_klines`. Die Spot-Kerzen werden in 0.2 nicht benutzt; Renditen und Rückschläge kommen aus den USD-M-Kerzen.
- Zeitraum: ab Datenbeginn (Funding BTC/ETH ab 2020-01, SOL ab 2020-10, wie S5) bis 2024-12-31. Ereignisse zählen erst nach 90 Tagen Vorlauf je Instrument (Abschnitt 5.1).
- Datensplit nach PROTOKOLL.md 3.2: Training Datenbeginn bis 2022-12-31, Validierung 2023-01-01 bis 2024-12-31. Beide Abschnitte werden getrennt ausgewertet und berichtet; kein Abschnitt liest Daten des nächsten. Ein 24-h-Fenster, das über das Abschnittsende reicht, zählt nicht.
- Der Holdout ab 2025-01-01 wird nicht geladen.

## 5. Ereignisse und Vergleich

- Funding-Werte im obersten Dezil
- Funding-Werte im untersten Dezil

Vergleich: Verteilung der nächsten 24-h-Rendite und des maximalen Rückschlags im Vergleich zur Gesamtverteilung

### 5.1 Ereignisdefinition

- Zeitpunkt t ist ein Funding-Termin eines Instruments. Die Dezilgrenzen (10. und 90. Perzentil) kommen aus den Funding-Werten desselben Instruments in den 90 Tagen vor t, **ohne** den Wert bei t (nur Vergangenheit).
- Oberstes Dezil: Funding bei t > 90. Perzentil. Unterstes Dezil: Funding bei t < 10. Perzentil.
- Start ist die Eröffnung der ersten 1h-Kerze ab t. 24-h-Rendite = Schluss der Kerze, die 24 h nach dem Start endet, geteilt durch den Startkurs, minus 1. Maximaler Rückschlag = tiefstes Tief in diesen 24 h geteilt durch den Startkurs, minus 1 (≤ 0).
- Gesamtverteilung: dieselben zwei Messgrößen an **allen** Funding-Terminen desselben Abschnitts nach dem Vorlauf, über die drei Instrumente gepoolt.

### 5.2 Entclusterung und effektives n

- Je Instrument und Gruppe zählt höchstens ein Ereignis je 24 h: das erste; das nächste zählt erst, wenn es mindestens 24 h nach dem zuletzt gezählten liegt. Die Gruppen werden getrennt entclustert.
- Die Mindestzahl 500 gilt für entclusterte Ereignisse je Gruppe, über die drei Instrumente gepoolt, gezählt im Zähllauf vor jeder Auswertung (nur Ereigniszahlen, keine Renditen).
- Zusätzlich wird n_eff = ⌊n / D⌋ berichtet, mit dem Designeffekt D aus dem Tagescluster über alle Instrumente wie in S6 (PROTOKOLL.md 1.3, A3): Cluster = Kalendertag UTC, D = Varianz des Mittelwerts aus Tagesclustern geteilt durch s² / n, mindestens 1. n_eff ist eine Angabe, kein Kriterium.

## 6. Messgröße und Entscheidung

- Messgröße: Verteilung der 24-h-Rendite und des maximalen Rückschlags
- Kleinster Effekt: 0,1 Prozentpunkte, für beide Messgrößen (Median der 24-h-Rendite und Median des maximalen Rückschlags), Festlegung (c)
- Mindestzahl Fälle: 500 entclusterte Ereignisse je Gruppe (oberstes und unterstes Dezil) über 2020–2024 gesamt, die Zahl je Abschnitt wird mit ausgewiesen (Festlegung (b)); sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung
- Stoppregel: Ausgewertet werden alle entclusterten Ereignisse im Zeitraum, es gibt keinen Abbruch bei 500. Hat eine Gruppe weniger als 500, lautet ihr Ergebnis „nicht prüfbar“. Es gibt keine Zwischenauswertung und keinen Abbruch nach dem Ergebnis.

### 6.1 Test

- Für jede Gruppe und Messgröße: Δ = Median der Ereignisse minus Median der Gesamtverteilung, in Prozentpunkten.
- 95-%-Konfidenzintervall per Block-Bootstrap über Kalendertage UTC: Blocklänge 10 Tage, 10 000 Ziehungen. Die Blöcke enthalten alle Instrumente gemeinsam, die Gleichzeitigkeit bleibt also erhalten. Beide Mediane werden in jeder Ziehung neu berechnet. Der Seed ist fest und wird vor dem Laden der Daten im Code eingefroren.
- p-Wert zweiseitig aus derselben Bootstrap-Verteilung: p = min(1, 2 · (1 + min(#Δ* ≤ 0, #Δ* ≥ 0)) / (1 + 10 000)).

### 6.2 Mehrfachtest

- 2 Gruppen (oberstes und unterstes Dezil) × 2 Messgrößen (24-h-Rendite und maximaler Rückschlag) = 4 Vergleiche, Holm-Bonferroni mit α = 5 % (PROTOKOLL.md 7.2, hier als eigene Familie mit m = 4).
- Holm wird je Abschnitt getrennt über dieselben 4 Vergleiche angewandt.

### 6.3 Urteil (Festlegung (a))

- Ein Vergleich besteht, wenn er **in Training und Validierung** nach Holm signifikant ist, |Δ| ≥ 0,1 Prozentpunkte in beiden Abschnitten erreicht und Δ in beiden Abschnitten dasselbe Vorzeichen hat.
- Studie: **BESTANDEN**, wenn mindestens ein Vergleich einer prüfbaren Gruppe besteht; **NICHT BESTANDEN**, wenn keiner besteht; **nicht prüfbar**, wenn keine Gruppe 500 entclusterte Ereignisse erreicht. Eine Gruppe unter 500 ist für sich „nicht prüfbar“ und wird nicht ausgewertet.

### 6.4 Umsetzung (vor dem Datenzugriff festgelegt)

- Code: `src/research_lab/studies/s16.py`, Seed 1616, Zähllauf und Auswertung getrennt aufrufbar.
- Funding-Zeitstempel werden auf die Minute abgerundet; Start ist die 1h-Kerze, die zu dieser Minute oder danach öffnet.
- Fehlt eine der 24 Stundenkerzen, zählt der Termin nicht (weder als Ereignis noch in der Gesamtverteilung); die Zahl wird berichtet.
- Dezile nach `statistics.quantiles(n=10, method="inclusive")`; strenge Ungleichungen, Werte gleich der Grenze sind kein Ereignis.
- Vorlauf 90 Tage ab Datenbeginn je Instrument: BTC/ETH Funding ab 2020-01-01, SOL ab 2020-10-01.
- Bootstrap: gleitende Blöcke aus 10 aufeinanderfolgenden UTC-Tagen des Abschnitts, so viele Blöcke, bis die Tageszahl des Abschnitts erreicht ist.

## 7. Bekannte Grenzen

- Die Studie betrachtet nur Daten bis 2024-12-31, Holdout-Zeitraum ist gesperrt.
- Es wird nur die Renditeverteilung als Ereignisstudie untersucht, nicht Carry und keine Trefferquote wie in S5.
- Die effektive Stichprobe ist aufgrund von Clustering und Autokorrelation kleiner als die Anzahl der Funding-Termine.
- Überlappende 24-h-Fenster sind autokorreliert. Dagegen stehen die Entclusterung (höchstens ein Ereignis je 24 h, Abschnitt 5.2) und der Block-Bootstrap über 10-Tage-Blöcke (Abschnitt 6.1). Die Gesamtverteilung bleibt überlappend, das trägt der Bootstrap.

## 8. Feste Grenzen

- Nur Papier, kein Echtgeld, keine echten Orders.
- Risikogrenzen und Kostenmodell ändern sich nie automatisch.
- Holdout ab 2025-01-01 wird nie geladen; öffnen nur mit Zustimmung von Uzi und Barti, Uzis ausdrückliches Wort bleibt Pflicht.
- Kein automatischer Merge; gemergt wird nur nach Uzis „merge“.
- Eine neue Strategie-Version zählt im Papier erst nach bestandenem prospektivem Test und Uzis Karte.

## Änderungsprotokoll

| Datum | Version | Änderung |
|---|---|---|
| 2026-11-06 | 0.1 | Entwurf vom Studien-Generator aus Idee I-0001 |
| 2026-11-06 | 0.2 | Von Hand ergänzt: Instrumente, Zeitraum und Datensplit (4.1), Ereignisdefinition (5.1), Entclusterung und n_eff (5.2), Test (6.1), Holm über 4 Vergleiche (6.2), Stoppregel ohne Abbruch bei 500, Leerformeln in 3 und 7 durch Verweise ersetzt. Spezifikations-Hash gilt nur für 0.1 |
| 2026-11-06 | 1.0 | **Freigegeben von Uzi 06.11.2026 20:37 Ortszeit („s16frei“).** Festlegungen: (a) Training und Validierung müssen beide bestehen (6.3); (b) mindestens 500 entclusterte Ereignisse je Gruppe über 2020–2024 gesamt, je Abschnitt ausgewiesen; (c) kleinster Effekt 0,1 Prozentpunkte für beide Messgrößen. Umsetzung 6.4 vor dem Datenzugriff eingefroren |
