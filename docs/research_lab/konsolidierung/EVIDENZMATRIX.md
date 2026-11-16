# Evidenzmatrix (Stand 16.11.2026)

Erzeugt aus `ergebnisse/*.json` und dem Register (`python3 -m src.research_lab.konsolidierung.evidenz`). Mehrere Studien desselben Datenclusters zählen als eine Quelle. Studien können in mehreren Zeilen vorkommen; das ist keine zusätzliche Bestätigung.

Abdeckung: 69 von 69 gefundenen Studien und Berichten sind einer Erkenntnis zugeordnet. Nicht zugeordnet (reine Infrastruktur, Entwürfe ohne Ergebnis oder noch nicht ausgewertet): keine.

## Übersicht

| Nr | Erkenntnis | Richtung | Evidenzstand |
|---|---|---|---|
| E1 | Die Trendregel S7b-D20-T3 (Donchian-20-Ausbruch in Richtung SMA200, 4h, Ziel 3 R, ATR-Stop, höchstens eine Position) hatte 2020–2024 auf BTC, ETH und SOL nach Kosten eine positive Erwartung. | positiv (Hypothese) | historisch gut ausgesehen: ja. Korrigiert reproduziert: ja (Prüftiefe A). Außerhalb der Entwicklung bestätigt: nein (S32 negativ; T15 auf BTC/ETH 2017–2019 positiv, aber p 0,079, siehe E1b; kein ungesehener Abschlusstest). Prospektiv beobachtet: 7 geschlossene Papier-Trades, zu wenig. |
| E1b | Außerhalb des Entwicklungszeitraums (BTC/ETH Spot, 2017-08 bis 2019-12, T15) zeigt die Trendregel C3 eine positive, aber nicht belegte Erwartung nach Kosten. | positiv, nicht signifikant | Außerhalb der Entwicklung getestet: ja (T15 und S32). Bestätigt: nein (P1 nicht erfüllt); das Merkmal „außerhalb der Entwicklung bestätigt“ bleibt unbesetzt. |
| E2 | Die Trendregel überträgt sich nicht auf andere Coins: Auf dem einzigen unabhängigen Universum (137 Coins, Punkt-in-Zeit) ist die Erwartung nach Kosten nicht von null verschieden. | negativ | Außerhalb der Entwicklung getestet: ja (negativ). Korrigiert reproduziert: nein (nur berichtet). |
| E3 | Orderflow-Regeln (OF2, OFX-Suche, S19, S31/S31b, S2) haben keinen belegten Vorteil. | negativ / nicht belegt | historisch gut ausgesehen: OF2 ja (n 56). Korrigiert reproduziert: Kennzahlen ja (Prüftiefe B), Vorteil nein. Außerhalb der Entwicklung: nein. Prospektiv: OF-Schatten n 25, Regel nachträglich, keine Aussage. |
| E4 | Indikator-Merkmale (Kerzen, Orderflow, Funding, Open Interest, Positionierung) sortieren BTC-1h-Trades zum Teil, tragen aber nach Kosten keine Handelsregel. | negativ | historisch gut ausgesehen: Sortiereffekt ja, Gewinn nein. Korrigiert reproduziert: Zahlen im Logbuch in den Ergebnisdateien gefunden (Prüftiefe C+). Außerhalb der Entwicklung: nein. |
| E5 | Kosten dominieren kurzfristige Regeln mit engen Stops: Je kleiner der Stop-Abstand, desto größer die Kosten in R, bis sie jeden Brutto-Vorteil verbrauchen. | negativ | Korrigiert reproduziert: Prüftiefe B (S34–S38) und C+ (Rest). Außerhalb der Entwicklung: nein (gleiche Daten, gleiche Kostenannahme). |
| E6 | Frühe Regelfamilien (R4: 48 Varianten, S4, S6, S13, S14) haben keinen Vorteil; S9 und S10 sind am Zähl-Gate gescheitert. | negativ | Außerhalb der Entwicklung: Validierungsabschnitt (negativ). Prospektiv: nein. |
| E7 | Funding-Carry (Spot long, Perp short) ist eine Kapitalrendite mit Basis-, Liquidations- und Gegenparteirisiko, kein Handelsvorteil. In der Validierung liegt sie bei konstantem Nominal im Bereich eines Geldmarktzinses. | keine belastbare Aussage | historisch gut ausgesehen: ja (Training). Korrigiert reproduziert: Prüftiefe A für K-Carry (eigene Rechnung). Außerhalb der Entwicklung: Validierung schwach. Prospektiv: nein. |
| E8 | Die Kombination von Trend (C1) und Carry (C2) bringt formal einen Diversifikationsgewinn (Korrelation um null), ändert aber nichts an der Beweislage des Trendanteils. | keine belastbare Aussage | Korrigiert reproduziert: ja (eigene Rechnung). Außerhalb der Entwicklung: nein. |
| E9 | Gegenüber einfachen, auf gleiche Schwankung skalierten Referenzen zeigt die Trendregel keinen Vorsprung: Ihr Vorteil kann Trendexposure auf im Nachhinein gewählten Coins sein. | negativ | Korrigiert reproduziert: ja (Prüftiefe A, eigene Tagesreihen). Außerhalb der Entwicklung: nein. |
| E10 | Prospektive Beobachtungen (Papier-Journale, Schatten, Mini-Test) erlauben bisher keine belastbare Aussage, weder für noch gegen eine Regel. | keine Aussage | Prospektiv beobachtet: ja, aber n 2–35 je Fenster. Keine andere Stufe erreicht. |
| E11 | Ein Tagesziel von 50 USDT im Durchschnitt würde selbst bei unterstellter Gültigkeit der besten Erwartung (C1, K1) viel Kapital brauchen. Das Ziel ist ein Richtwert, keine Pflicht. | Konsequenzrechnung | Rechnung, keine Evidenzstufe. |
| E12 | Die Kerzen und Kontrakte von Bitunix stimmen für BTC, ETH und SOL mit Binance überein; die Regel ist dort technisch ausführbar. Gebühren, Funding-Einheit und Verhalten bei Stress sind unbestätigt. | Voraussetzung offen | Korrigiert reproduziert: ja (Kerzen). Gebühren: Annahme. |
| E13 | Level-, Volumenprofil- und VWAP-Regeln auf BTC/ETH/SOL zwischen 1m und 4h haben keinen Vorteil nach Kosten. | negativ | Korrigiert reproduziert: Prüftiefe B (S34, S35a, S36, S38). Außerhalb der Entwicklung: nicht erreicht. |
| E14 | Prognose- und Risikobausteine (GARCH, Verteilungs- und Kalibrierstudien, KI-Pläne) sind brauchbar als Anzeige- und Risikoschicht, aber keine Quelle eines Handelsvorteils. | keine Handelsaussage | Korrigiert reproduziert: Prüftiefe C/C+. |
| E15 | Makrofilter (Realzins, Dollar, Liquidität u. a.) auf die Trendtrades sind nicht belegt. | keine belastbare Aussage | historisch gut ausgesehen: nur F5. Korrigiert reproduziert: nein. Außerhalb der Entwicklung: nein. |
| E16 | Studien ohne Ergebnis (Entwürfe, laufende Läufe, nicht zugängliche Dateien) liefern keine Evidenz und zählen weder für noch gegen eine Regel. | keine Aussage | Keine Evidenzstufe erreicht. |
| E17 | Plattform-, Abnahme- und Governance-Berichte belegen Datenqualität und Verfahren, nicht Profitabilität. Der Stand der Live-Regeln ist: keine einzige stützt sich auf eine bestandene Studie. | keine Handelsaussage | Keine Evidenzstufe; Verfahren. |

## Einzelne Erkenntnisse

### E1: Die Trendregel S7b-D20-T3 (Donchian-20-Ausbruch in Richtung SMA200, 4h, Ziel 3 R, ATR-Stop, höchstens eine Position) hatte 2020–2024 auf BTC, ETH und SOL nach Kosten eine positive Erwartung.

- **Richtung:** positiv (Hypothese)
- **Unterstützende Studien:** S7, S7b, K-C1, K-T15. Eigene Nachrechnung: gespeicherte Handelslisten bit-genau reproduziert (T1). Netto je Trade (K1) Training +0,221 R (n 292), Validierung +0,264 R (n 207), gepoolt +0,239 R, 95-%-Band 0,080 bis 0,415 R, Newey-West t 2,92. Bleibt positiv unter K2 (konservativ: +0,207 / +0,237 R) und K3 (pessimistisch: +0,154 / +0,182 R); Gebühr und Schlupf müssten auf das 4,4-Fache von K1 steigen, bis die Erwartung null erreicht. Zufallseinstiege in SMA200-Richtung schlagen die Regel selten (p 0,035 / 0,001). 97,5 % / 100,0 % der 81 Nachbarzellen positiv; Weglassen eines Jahres oder Instruments kippt das Vorzeichen nicht; Long +0,22 R, Short +0,27 R.
- **Gegenbelege:** S32, S7b-Sonde, S25, K-Ref, K-T15. S32: dieselbe Regel auf 137 anderen Coins (Punkt-in-Zeit-Universum), Validierung: −0,0255 R bei n 3.311, Zufalls-p 0,547, 95-%-Band −0,150 bis +0,101 R. Deflated Sharpe bei N = 64: Training 0,42, Validierung 0,43, gepoolt 0,78 (Schwelle 0,95; bei N = 26.707 0,15). Eine Kerze Verzögerung: Training +0,181 R, Validierung −0,007 R. Sondenlauf Juli–Oktober 2026 (S7b-Sonde, zufällig gesehen): 35 Trades, −5,8 R. Einfache Referenz R2 (SMA200 lang/flat, gleiche Schwankung): Sharpe 1,55 gegen 1,36. S25: GARCH-Größe bringt keinen Vorteil. T15 (E1b, BTC/ETH 2017–2019, ein Lauf): +0,154 R unter K2, p 0,079 (Schwelle 0,05 verfehlt); Zufallseinstiege in SMA200-Richtung erreichen dort im Mittel +0,177 R.
- **Datenüberschneidung:** Ein Datencluster (TREND-4H): dieselben Binance-4h-Kerzen BTC/ETH/SOL 2020–2024, Validierung 2023–2024 mehrfach verbraucht (S7b, S25, S7b-Makro). S7, S7b und die eigene Nachrechnung sind eine Evidenzquelle, nicht drei.
- **Unsicherheit:** Coins im Nachhinein gewählt (Survivorship). Beste 5 % der Trades = 62,6 % der Summe; 2020 liefert 49 von 119 R, 2021 −0,03 R je Trade; Drawdown 21,0 R (ca. 21 % bei 1 % Risiko); im oberen Volatilitäts-Terzil +0,00 R je Trade (n 99). Zufallseinstiege in Trendrichtung erreichen im Training schon +0,097 R, ein Teil des Vorteils ist Trendseite plus Auszahlungsgeometrie.
- **Praktische Konsequenz:** Nur als Hypothese für den Vorwärts-Papiertest (S7b-Forward). Keine Live-Aktivierung, keine Skalierung. Stufe 4 braucht mindestens 30 geschlossene Papier-Trades unter K2 oder einen freigegebenen Holdout-Lauf.
- **Evidenzstand:** historisch gut ausgesehen: ja. Korrigiert reproduziert: ja (Prüftiefe A). Außerhalb der Entwicklung bestätigt: nein (S32 negativ; T15 auf BTC/ETH 2017–2019 positiv, aber p 0,079, siehe E1b; kein ungesehener Abschlusstest). Prospektiv beobachtet: 7 geschlossene Papier-Trades, zu wenig.

### E1b: Außerhalb des Entwicklungszeitraums (BTC/ETH Spot, 2017-08 bis 2019-12, T15) zeigt die Trendregel C3 eine positive, aber nicht belegte Erwartung nach Kosten.

- **Richtung:** positiv, nicht signifikant
- **Unterstützende Studien:** K-T15. Vorab eingefrorener Einzellauf (Zusatzprotokoll 1.1-T15), derselbe Code wie T1–T13: n 157 Trades, E[R] unter K2 +0,154 R (95-%-Band −0,056 bis +0,391 R), einseitiges Monatsblock-p 0,0793 (Schwelle 0,05; P1 nicht erfüllt). K1 +0,146 R, K0 +0,152 R. Je Jahr: 2017 −0,03 R (n 28), 2018 +0,15 R (n 65), 2019 +0,24 R (n 64). BTC +0,12 R (n 98), ETH +0,22 R (n 59); Long +0,07 R (n 88), Short +0,27 R (n 69).
- **Gegenbelege:** K-Ref, S32. Zufallseinstiege in SMA200-Richtung (gleiche Kosten K1, gleiche Häufigkeit und Positionsgrenze) erreichen im selben Zeitraum im Mittel +0,177 R, die Regel +0,146 R (p 0,60): der Donchian-Einstieg bringt dort nichts über die Trendseite hinaus. Nach Abzug des Funding-Kostenanteils aus 2020–2024 (0,031 R je Trade) bleiben +0,123 R (ergänzend p 0,13). Beste 5 % der Trades = 98,3 % der Summe; größter Rückgang 12,5 R über 316 Tage.
- **Datenüberschneidung:** Neue Daten (Spot 2017–2019, nicht Teil des Laborarchivs, das 2020-01 beginnt): kein zeitlicher Überlapp mit den Entwicklungsdaten, aber dieselben Instrumente BTC und ETH (Überlebensauswahl, hohe Wechselkorrelation) und nicht auszuschließendes Vorwissen über die Preisgeschichte.
- **Unsicherheit:** Aussagekraft begrenzt: n 157, nur etwa 19,8 Monate mit Signalmöglichkeit (acht Datenlücken setzen den 200er-Vorlauf zurück), Power etwa 50 % bei +0,24 R, kleinste bei 80 % Power nachweisbare Erwartung +0,35 R. Das Band enthält 0 und zugleich den Wert aus 2020–2024. Spot statt Perpetual; Funding, Basis, Leerverkauf und Liquidation sind nicht abgebildet.
- **Praktische Konsequenz:** Kein Nachweis und keine Widerlegung. Die positive Richtung außerhalb der Entwicklung stützt die Hypothese nur schwach; der fehlende Vorsprung gegenüber Zufallseinstiegen in Trendrichtung spricht dafür, dass ein Vorteil, falls vorhanden, vor allem aus der Trendseite und der Auszahlungsgeometrie kommt. Das Gesamturteil bleibt Stufe 2.
- **Evidenzstand:** Außerhalb der Entwicklung getestet: ja (T15 und S32). Bestätigt: nein (P1 nicht erfüllt); das Merkmal „außerhalb der Entwicklung bestätigt“ bleibt unbesetzt.

### E2: Die Trendregel überträgt sich nicht auf andere Coins: Auf dem einzigen unabhängigen Universum (137 Coins, Punkt-in-Zeit) ist die Erwartung nach Kosten nicht von null verschieden.

- **Richtung:** negativ
- **Unterstützende Studien:** S32. S32 (ein Lauf, Validierung 2023–2024): −0,0255 R je Trade bei n 3.311, Zufalls-p 0,547, 95-%-Band −0,150 bis +0,101 R. Ergebnisdatei gelesen und mit SHA-256 festgehalten; nicht neu gerechnet (Kerzen der 137 Coins liegen nicht im Container).
- **Gegenbelege:** S7b. Das Band schließt auch +0,10 R ein: ein kleiner Vorteil ist nicht ausgeschlossen, nur nicht gezeigt. E1 spricht für BTC/ETH/SOL, nicht für den Korb.
- **Datenüberschneidung:** Gleiche Regel, gleiche Zeit (2023–2024), anderes Universum (Top-25 je Monat nach Punkt-in-Zeit, ohne BTC/ETH/SOL). Training 2020-07 bis 2022 lag im Altcoin-Aufwärtsmarkt; ob delistete Märkte fehlen (Survivorship), ist nicht geprüft.
- **Unsicherheit:** Die Zahlen sind NUR BERICHTET: Die Handelsliste lag nicht vor, nur Aggregate wurden gelesen. Der Lauf ist einmalig und vorab eingefroren; er zählt als Gegenbeleg, nicht als Beweis für das Fehlen eines Vorteils.
- **Praktische Konsequenz:** Nicht annehmen, dass die Regel allgemein „Trend verfolgt“. Wirkung bleibt an BTC/ETH/SOL gebunden; das ist ohne unabhängige Bestätigung ein Zeichen für Auswahl im Nachhinein.
- **Evidenzstand:** Außerhalb der Entwicklung getestet: ja (negativ). Korrigiert reproduziert: nein (nur berichtet).

### E3: Orderflow-Regeln (OF2, OFX-Suche, S19, S31/S31b, S2) haben keinen belegten Vorteil.

- **Richtung:** negativ / nicht belegt
- **Unterstützende Studien:** OFX, S19, S31, S31b, S2, S26. OFX: 27.023 Konfigurationen × 300 Filter = 8.106.900 Varianten, 0 bestehen das Sieb; bestes t bei n ≥ 130 ist 2,66; aus Tausenden unabhängiger Nullversuche wäre ein Zufallsmaximum von etwa 3 zu erwarten (die effektive Zahl unabhängiger Versuche ist nicht bestimmt). S19: Familien T, H, E ohne Nachweis, I, A, C nicht testbar. S31/S31b: keine Regel erreicht n ≥ 100. S2: nicht beurteilbar (Power-Gate). S26: Absorption −0,48 R, Initiative −0,44 R (Validierung).
- **Gegenbelege:** OF2, S31, OF2-Kostengrenze. OF2 Training: 56 Trades, +0,27 R je Trade, Zufallseinstiege −0,09 R (Labor-p 0,006). S31 B1 34 Trades +0,33 R, B2 13 Trades +0,44 R. Gegen den Befund: eigenes 95-%-Band −0,20 bis +0,66 R, beste 5 % der Trades = 108 % der Summe, Median −0,35 R, Deflated Sharpe (N = 64) etwa 0,06.
- **Datenüberschneidung:** Ein Datencluster (OF-MIN): S8-Minutenbalken BTC 2020–2024. S31 B1–B5 sind OF2-Modelle, OFX sucht auf demselben Training. Nicht unabhängig.
- **Unsicherheit:** n 56 ist weit unter jeder tragfähigen Mindestzahl; die Suche über 8,1 Mio. Varianten erzeugt Spitzenwerte aus Zufall. Rohdaten der PS5 nicht neu gerechnet (Prüftiefe B auf Ergebnisdateien).
- **Praktische Konsequenz:** Kein Orderflow-Signal für Papier-Trading. Die Datensammlung bleibt als Beobachtung; OF2 nur als Hypothese, die auf neuen (prospektiven) Daten mit vorab festgelegter Mindestzahl geprüft werden müsste.
- **Evidenzstand:** historisch gut ausgesehen: OF2 ja (n 56). Korrigiert reproduziert: Kennzahlen ja (Prüftiefe B), Vorteil nein. Außerhalb der Entwicklung: nein. Prospektiv: OF-Schatten n 25, Regel nachträglich, keine Aussage.

### E4: Indikator-Merkmale (Kerzen, Orderflow, Funding, Open Interest, Positionierung) sortieren BTC-1h-Trades zum Teil, tragen aber nach Kosten keine Handelsregel.

- **Richtung:** negativ
- **Unterstützende Studien:** S20, S21, S22, S24, S26, S27, S28, E0/E1. S24: Modell M2 sortiert echt (Abstand 0,135 R, p 0,004), aber NEHMEN verliert nach Kosten −0,378 R (n 11.181). S22: Abstand H1 +0,115 R (p 0,051), NEHMEN −0,173 R. S27: NEHMEN −0,049 / −0,098 R. S28: Abstand +0,135 R, Holm nicht bestanden, nach Kosten −0,04 R. S20/S21: Kerzen-, Orderflow- und Funding-Merkmale verbessern das Mechanik-Modell nicht. E0/E1: Brutto je Trade −0,03 bis +0,04 R, Kosten 0,09–0,42 R.
- **Gegenbelege:** S24. Einziger positiver Teilbefund: der Sortiereffekt von S24-M2 (0,135 R, p 0,004). Er ist ein Unterschied zwischen Gruppen, kein positiver Mittelwert.
- **Datenüberschneidung:** Ein Datencluster (BTC-1H): dieselben Standard-Trades und dieselbe Validierung 2023–2024 in S20–S28. Die p-Werte sind nicht unabhängig und wurden nicht über alle Studien korrigiert.
- **Unsicherheit:** Brutto der Ausgangstrades ist etwa null (E0): es gibt nichts zu sortieren, wofür sich die Kosten lohnen. Mehrfachtest über neun Studien auf denselben Daten.
- **Praktische Konsequenz:** Als Filter für eine Regel mit positivem Brutto-Ergebnis weiter prüfbar (z. B. für E1), nicht als eigenständige Regel.
- **Evidenzstand:** historisch gut ausgesehen: Sortiereffekt ja, Gewinn nein. Korrigiert reproduziert: Zahlen im Logbuch in den Ergebnisdateien gefunden (Prüftiefe C+). Außerhalb der Entwicklung: nein.

### E5: Kosten dominieren kurzfristige Regeln mit engen Stops: Je kleiner der Stop-Abstand, desto größer die Kosten in R, bis sie jeden Brutto-Vorteil verbrauchen.

- **Richtung:** negativ
- **Unterstützende Studien:** S34, S35a, S36, S38, S30, Stop-Analyse-30m, E0/E1, S17. S34: Brutto −0,02 R, Kosten 1,2 R je Trade (Stop im Mittel 0,20 %). S35a: bestes Brutto +0,06 R, netto −0,25 R. S36: Brutto +0,10 R, Kosten 0,15 R. S38: netto +0,005 R. S30: Kosten 0,12–0,17 R. Stop-Analyse 30m: Kosten 2,4–2,8 R je Stopp. E0/E1: Kosten 0,09–0,42 R. Zum Vergleich trägt C1 0,041 R Kosten je Trade bei einem mittleren Stop von 3,8 %.
- **Gegenbelege:** S6, Kraken-Kosten. Bitunix-Gebühren sind unbestätigt (Taker 0,06 % und Maker 0,02 % nur von Uzi genannt); ein günstigerer Tarif oder Maker-Ausführung würde das Bild verbessern. S6 (Maker-Limits) bestand nicht.
- **Datenüberschneidung:** Mehrere Cluster (BTC-1H, LEVEL-INTRADAY, PROSPEKTIV); Kosten stammen aus den Annahmen des Protokolls, nicht aus Bitunix-Füllungen. Kraken-Messung (5 bp, 22 Füllungen) stützt die Annahmen als eher vorsichtig.
- **Unsicherheit:** Bitunix-Handelshistorie fehlt (nur Live-Aufzeichnung); Schlupf bei Stopps in schnellen Märkten unterschätzt möglich (Kraken: Börsen-Stops 15 bp früher).
- **Praktische Konsequenz:** Bei 0,16 % Kosten je Umschlag (K1) kostet ein Stop von 1 % schon 0,16 R je Trade, ein Stop von 0,2 % rund 0,8 R; der Brutto-Vorteil müsste das übersteigen, und in den geprüften Studien tat er das nie. Jede Kandidatenregel braucht den Kostenanteil in R als Pflichtangabe vor der Auswertung.
- **Evidenzstand:** Korrigiert reproduziert: Prüftiefe B (S34–S38) und C+ (Rest). Außerhalb der Entwicklung: nein (gleiche Daten, gleiche Kostenannahme).

### E6: Frühe Regelfamilien (R4: 48 Varianten, S4, S6, S13, S14) haben keinen Vorteil; S9 und S10 sind am Zähl-Gate gescheitert.

- **Richtung:** negativ
- **Unterstützende Studien:** R4, S4, S6, S13, S14, S9, S10. R4: 42 Varianten scheitern schon im Training, 6 in der Validierung, SPA p 0,46 / 0,43, StepM wählt keine. S4: alle Varianten −0,12 bis −0,23 R. S6: Treffer 72–82 %, Erwartung −0,07 bis −0,11 R. S13: Training −0,044 / −0,042 R. S14: −0,19 bis −0,36 R. S9: höchstens 11 Signale statt 500; S10: 241 von 500.
- **Gegenbelege:** S13. S13-NY Validierung +0,030 R, aber Drawdown über der Grenze und Walk-Forward −0,021 R. Sonst keine Gegenbelege.
- **Datenüberschneidung:** Ein Datencluster (FRÜH): BTC/ETH/SOL 2020–2024 mit Protokoll 1.x. 6 von 48 Varianten bestanden das Training und scheiterten erst in der Validierung: Die Trennung von Training und Validierung entfernt Scheintreffer des Trainings.
- **Unsicherheit:** Prüftiefe C+ (Ergebnisdateien gelesen, nicht neu gerechnet); Studien vor Protokoll 1.3 mit weniger strenger Mehrfachtestkorrektur.
- **Praktische Konsequenz:** Verworfen. Die hohe Trefferquote allein (S4, S6) ist kein Profitabilitätsnachweis: 72–82 % bei negativer Erwartung.
- **Evidenzstand:** Außerhalb der Entwicklung: Validierungsabschnitt (negativ). Prospektiv: nein.

### E7: Funding-Carry (Spot long, Perp short) ist eine Kapitalrendite mit Basis-, Liquidations- und Gegenparteirisiko, kein Handelsvorteil. In der Validierung liegt sie bei konstantem Nominal im Bereich eines Geldmarktzinses.

- **Richtung:** keine belastbare Aussage
- **Unterstützende Studien:** K-Carry, S33-Carry. K-Carry (BTC+ETH, Binance-Funding als Stellvertreter): konstante Stückzahl Training 84,4 % je Jahr, Validierung 13,9 % (Kriterium CG1 formal bestanden). Monatlich neu abgesichert (konstantes Nominal): 11,3 % / 5,3 % je Jahr gegen angenommenen Geldmarkt 0,8 % / 5,1 %. S33-Carry: immer in Position +8,5 % je Jahr, 2022 nur +2 %.
- **Gegenbelege:** S5. Die konstante Stückzahl führt zu verdecktem Hebel: Ohne Nachjustieren wäre die Marge der Perp-Short-Position 2020 aufgebraucht gewesen (ETH nach 42, BTC nach 309 Tagen), der Nachschussbedarf stieg bis zum 14-Fachen (BTC) bzw. 37-Fachen (ETH) des anfänglichen Nominalwerts. Der formale Bestehenswert von CG1 ist deshalb kein Beleg. S5 (95 % Trefferquote mit Carry): nicht testbar, zu wenige Episoden.
- **Datenüberschneidung:** Ein Datencluster (CARRY): Binance-Funding 2020–2024; Bitunix-Funding und -Einheit nicht bestätigt. Geldmarktzinsen sind eine Annahme aus dem Gedächtnis, nicht aus TIM-Daten.
- **Unsicherheit:** Schutzabstand zur Liquidation, Spot-Gebühren auf Bitunix, Gegenparteirisiko der Börse und Steuer nicht modelliert. Die Zinsannahme entscheidet über den Vorsprung.
- **Praktische Konsequenz:** Keine Grundlage für das Tagesziel; allenfalls Beobachtung. 50 USDT je Tag wären bei +8,5 % je Jahr rund 215.000 USDT Kapital (S33-Carry-Bericht).
- **Evidenzstand:** historisch gut ausgesehen: ja (Training). Korrigiert reproduziert: Prüftiefe A für K-Carry (eigene Rechnung). Außerhalb der Entwicklung: Validierung schwach. Prospektiv: nein.

### E8: Die Kombination von Trend (C1) und Carry (C2) bringt formal einen Diversifikationsgewinn (Korrelation um null), ändert aber nichts an der Beweislage des Trendanteils.

- **Richtung:** keine belastbare Aussage
- **Unterstützende Studien:** K-C1, K-Carry. T12: Korrelation der Tagesrenditen −0,05 (konstante Stückzahl) bzw. −0,006 (monatlich neu abgesichert), Kriterium G10 formal bestanden.
- **Gegenbelege:** S32. Der Trendanteil erfüllt G7 und G8 nicht; der Carryanteil erreicht in der Validierung etwa den Geldmarkt (E7).
- **Datenüberschneidung:** Beide Teile aus 2020–2024 mit denselben Instrumenten (BTC, ETH).
- **Unsicherheit:** Gewichte und Hebel des Carryanteils sind Annahmen; Kosten und Liquidationsrisiko des Carry nicht voll modelliert.
- **Praktische Konsequenz:** C2 wird nicht gegenüber C1 bevorzugt; der Carry ersetzt keinen fehlenden Trendbeleg.
- **Evidenzstand:** Korrigiert reproduziert: ja (eigene Rechnung). Außerhalb der Entwicklung: nein.

### E9: Gegenüber einfachen, auf gleiche Schwankung skalierten Referenzen zeigt die Trendregel keinen Vorsprung: Ihr Vorteil kann Trendexposure auf im Nachhinein gewählten Coins sein.

- **Richtung:** negativ
- **Unterstützende Studien:** K-Ref. T10 (gepoolt, Hebel höchstens 3, Netto, nicht aufgezinst): C1 119 %, Sharpe 1,36, Rückgang 20,9 %; R1 (gleichgewichteter Korb, Buy and Hold) 113 %, Sharpe 1,28, Rückgang 33,8 %; R2 (SMA200 lang/flat) 136 %, Sharpe 1,55, Rückgang 25,0 %.
- **Gegenbelege:** K-C1. C1 hat einen kleineren Rückgang als R1 und etwas mehr Rendite als R1; gegenüber R2 liegen Rendite und Sharpe niedriger.
- **Datenüberschneidung:** Gleiche Coins, gleiche Jahre. BTC, ETH und SOL sind im Rückblick Gewinner des Zeitraums; Buy and Hold auf ihnen ist selbst eine nachträglich gewählte Referenz.
- **Unsicherheit:** R1 und R2 sind auf die Tagesschwankung von C1 heruntergerechnet (Hebel 0,22 bzw. 0,35), Umschichtung kostet 0,09 % je Seite; alle drei Reihen ohne Zins auf nicht investiertes Kapital (gleich behandelt). Die Rangfolge hängt am Zeitraum 2020–2024.
- **Praktische Konsequenz:** Der Beitrag der Ausbruchsregel über eine einfache Trendfilter-Position hinaus ist nicht gezeigt. Wer Trendexposure will, kann sie einfacher haben.
- **Evidenzstand:** Korrigiert reproduziert: ja (Prüftiefe A, eigene Tagesreihen). Außerhalb der Entwicklung: nein.

### E10: Prospektive Beobachtungen (Papier-Journale, Schatten, Mini-Test) erlauben bisher keine belastbare Aussage, weder für noch gegen eine Regel.

- **Richtung:** keine Aussage
- **Unterstützende Studien:** S7b-Forward, Plan-Journale, OF-Schatten, Exit-Schatten, K1. S7b-Forward: 4 bzw. 3 geschlossene Trades, +3,771 R bzw. +6,847 R, alle Short. Plan-Journale (84 Pläne): −9,32 R, KI90 −0,36 bis +0,12 R je Plan; ohne das Level-Journal 76 Pläne +8,39 R, KI90 −0,10 bis +0,18 R. OF-Schatten (25 Pläne, nur Long, Regel nach Ansicht der Zwischenstände geschrieben). Exit-Schatten: 7 Trades mit TP2.
- **Gegenbelege:** S7b-Sonde, Kraken-Echtgeldtest, Bitunix-Konto. S7b-Sonde (Juli–Oktober 2026): 35 Trades, −5,8 R, −0,17 R je Trade, zufällig gesehen; mit +0,24 R (E1) und mit 0 R verträglich. Kraken-Echtgeldtest und Bitunix-Konto: nicht zugänglich bzw. nur berichtet.
- **Datenüberschneidung:** Zeitlich benachbarte Fenster (Sonde und Forward), überlappende Pläne auf 15m und 1h, eine Marktphase. Nicht unabhängig.
- **Unsicherheit:** Zu kleine Zahlen; die Vorzeichen der Plan-Journale hängen an 27 Ausschlüssen laut Korrekturdatei (Zeitpunkt der Festlegung nicht geprüft).
- **Praktische Konsequenz:** Weiterlaufen lassen mit vorab festgelegter Auswertung (30 Trades für Stufe 4, 100 für das endgültige Urteil); nichts daraus ableiten, bevor die Zahl erreicht ist.
- **Evidenzstand:** Prospektiv beobachtet: ja, aber n 2–35 je Fenster. Keine andere Stufe erreicht.

### E11: Ein Tagesziel von 50 USDT im Durchschnitt würde selbst bei unterstellter Gültigkeit der besten Erwartung (C1, K1) viel Kapital brauchen. Das Ziel ist ein Richtwert, keine Pflicht.

- **Richtung:** Konsequenzrechnung
- **Unterstützende Studien:** Bitunix-Edge, K-Bitunix, OF2-Kostengrenze. Reine Arithmetik mit E[R] +0,239 und 8,5 Trades je Monat: etwa 24,3 R je Jahr, also 751 USDT je R; bei 1 % Risiko je Trade ≈ 75.101 USDT, bei 0,5 % ≈ 150.203 USDT. Mit der unteren Grenze des 95-%-Bands (0,080 R) bei 1 % Risiko ≈ 222.807 USDT. Bitunix-Edge-Bericht für OF2: 364.000 USDT (1 % Risiko) bis 1,46 Mio. USDT (0,25 %). Mit 10.000 USDT wären 7,5 % Risiko je Trade nötig; der historische Drawdown von 21,0 R entspräche dann 157 % des Kontos.
- **Gegenbelege:** –. Keine. Die Rechnung gilt nur, wenn die Erwartung stimmt (E1) und gleichmäßig verteilt anfällt; sie ist keine Prognose.
- **Datenüberschneidung:** Modellrechnung auf Basis von E1 beziehungsweise OF2 (n 56); gleiche Datencluster.
- **Unsicherheit:** Gewinne sind ungleichmäßig (Monate −8,5 bis +17,9 R); Drawdown bis ca. 21 R, also etwa 21 % des Kapitals bei 1 % Risiko je Trade; Steuern, Kontoführung, Slippage über K1 hinaus nicht enthalten.
- **Praktische Konsequenz:** Mit einem kleinen Konto ist das Ziel nur über ein Risiko je Trade erreichbar, bei dem der historische Drawdown das Konto aufbrauchen würde. Höheres Risiko (Hebel) skaliert Gewinne und Drawdowns gleichermaßen und ändert die Erwartung je R nicht: Hebel ist kein Vorteil.
- **Evidenzstand:** Rechnung, keine Evidenzstufe.

### E12: Die Kerzen und Kontrakte von Bitunix stimmen für BTC, ETH und SOL mit Binance überein; die Regel ist dort technisch ausführbar. Gebühren, Funding-Einheit und Verhalten bei Stress sind unbestätigt.

- **Richtung:** Voraussetzung offen
- **Unterstützende Studien:** K-Bitunix. T13: Netto je Trade auf Bitunix-Kerzen 0,2194 R gegen Binance 0,2460 R (Δ −0,027 R), 252 gemeinsame Signale; Mindestkontrakt bei 1.000 USDT 100 % ausführbar; Spreads (Momentaufnahme ≈ 90 s) BTC 0,016 bp, ETH 0,056 bp, SOL 1,41 bp.
- **Gegenbelege:** Bitunix-Konto. Bitunix liefert keine historischen Trades; die Gebühren (Taker 0,06 %, Maker 0,02 %) stammen nur von Uzi, FEES_VERIFIED ist False. Bitunix-Konto: Netto etwa −1.900 USDT in 365 Tagen bei 1.024 USDT Gebühren (nur berichtet, diskretionär, nicht TIM).
- **Datenüberschneidung:** Bitunix-Kerzen ab 2022-04-17; überlappend mit E1.
- **Unsicherheit:** Funding-Einheit unklar (Prozent?), Tiefe nur als Momentaufnahme, Ausführung bei Stopps unter Stress unbekannt.
- **Praktische Konsequenz:** Offene Vorbedingungen vor einem Papier-Test auf Bitunix: Gebührentabelle bestätigen, Funding-Einheit klären, Fills im Papiermodus aufzeichnen.
- **Evidenzstand:** Korrigiert reproduziert: ja (Kerzen). Gebühren: Annahme.

### E13: Level-, Volumenprofil- und VWAP-Regeln auf BTC/ETH/SOL zwischen 1m und 4h haben keinen Vorteil nach Kosten.

- **Richtung:** negativ
- **Unterstützende Studien:** S34, S35a, S36, S38, S30, VWAP-1W-2sigma. S34 (n 53): netto −1,21 R. S35a: alle 12 Varianten −0,25 bis −0,41 R. S36: −0,05 / −0,09 R. S38: +0,005 R, Untergrenzen unter 0. S30: Fade-Raster netto negativ, Ausbruch −0,25 R. VWAP-1W-2σ: als Kaufsignal allein trägt es nicht, schon vor Kosten.
- **Gegenbelege:** S37. S37: n 1–5 je Variante, keine Aussage. Keine Gegenbelege.
- **Datenüberschneidung:** Ein Datencluster (LEVEL-INTRADAY): überlappende Zeiträume, Training 2020–2023.
- **Unsicherheit:** Nur Trainingsdaten (S30, S34–S38): keine Validierung gerechnet, weil das Training schon scheiterte oder zu wenige Fälle lieferte; VWAP-1W-2σ mit Validierung 2024, aber ohne Kosten.
- **Praktische Konsequenz:** Verworfen als Quelle für eine Handelsregel; Level können als Anzeige bleiben.
- **Evidenzstand:** Korrigiert reproduziert: Prüftiefe B (S34, S35a, S36, S38). Außerhalb der Entwicklung: nicht erreicht.

### E14: Prognose- und Risikobausteine (GARCH, Verteilungs- und Kalibrierstudien, KI-Pläne) sind brauchbar als Anzeige- und Risikoschicht, aber keine Quelle eines Handelsvorteils.

- **Richtung:** keine Handelsaussage
- **Unterstützende Studien:** S15, S1, S17, S39, S16. S15: GARCH(1,1) prognostiziert die Schwankung besser als 14-Tage-Varianz. S1: CPI-Stunde im Median 1,40-mal so unruhig. S17: Tageszeit-Wirkung auf Kosten 0,04–0,12 R. S39: kein Typ mit belegtem Muster, Holm-p mindestens 0,224.
- **Gegenbelege:** S25. S25: Positionsgröße nach GARCH-Prognose bringt für S7b-D20-T3 keinen Vorteil.
- **Datenüberschneidung:** Cluster PROGNOSE, FRÜH; teils dieselben Kerzen.
- **Unsicherheit:** Vorhersagegüte der Schwankung sagt nichts über Handelsgewinn.
- **Praktische Konsequenz:** Für Positionsgrößen und Anzeigen nutzbar; nicht als Gewinnquelle.
- **Evidenzstand:** Korrigiert reproduziert: Prüftiefe C/C+.

### E15: Makrofilter (Realzins, Dollar, Liquidität u. a.) auf die Trendtrades sind nicht belegt.

- **Richtung:** keine belastbare Aussage
- **Unterstützende Studien:** S7b-Makro. S7b-Makro: F5 besteht nach fünf Versuchen; der Glückstest über fünf Filter ergibt p = 0,066, F1–F4 bestehen nicht. F5 läuft als Vorwärts-Log.
- **Gegenbelege:** S7b. Der Test über mehrere Filter erreicht die Schwelle nicht; ein einzelner Treffer nach fünf Versuchen ist bei dieser Zahl kein Beleg.
- **Datenüberschneidung:** TREND-4H: dieselbe Handelsliste wie E1, dieselbe verbrauchte Validierung.
- **Unsicherheit:** Mehrfachtest nicht bestanden; Prüftiefe C (Bericht gelesen, nicht nachgerechnet).
- **Praktische Konsequenz:** Nicht verwenden. F5 weiter als Vorwärts-Log beobachten, ohne den Filter an E1 zu hängen.
- **Evidenzstand:** historisch gut ausgesehen: nur F5. Korrigiert reproduziert: nein. Außerhalb der Entwicklung: nein.

### E16: Studien ohne Ergebnis (Entwürfe, laufende Läufe, nicht zugängliche Dateien) liefern keine Evidenz und zählen weder für noch gegen eine Regel.

- **Richtung:** keine Aussage
- **Unterstützende Studien:** S8, S12, S18, S23, S29, S33, GEX-Wand, L1, KI1, T07, Move-Kalibrierung. S8 (läuft, keine Auswertung), S12 (Sammler seit 02.11.2026), S18 (Ergebnis nicht vor Januar), S23 (nur Entwurf), S29 (kein Ergebnis auffindbar), S33 (Optionsflow-Entwurf), GEX-Wand (Entwurf), L1, KI1, T07 (Entwürfe), Move-Kalibrierung (Detektor, kein Handelsbezug).
- **Gegenbelege:** –. Keine.
- **Datenüberschneidung:** Teils Datenbasis anderer Studien (S8-Minutenbalken, Move-Kalibrierung für S39).
- **Unsicherheit:** Status laut Logbuch oder Gedächtnis; S29 ist laut Gedächtnis auf der PS5 gelaufen, eine Ergebnisdatei wurde nicht gefunden.
- **Praktische Konsequenz:** Gelistet, damit nichts verschwindet. Sobald Ergebnisse vorliegen, einzeln nach Protokoll prüfen.
- **Evidenzstand:** Keine Evidenzstufe erreicht.

### E17: Plattform-, Abnahme- und Governance-Berichte belegen Datenqualität und Verfahren, nicht Profitabilität. Der Stand der Live-Regeln ist: keine einzige stützt sich auf eine bestandene Studie.

- **Richtung:** keine Handelsaussage
- **Unterstützende Studien:** Überzeugungsregister, V1-Juli, tim-master-P1, Prüfberichte-Chart, V2, F4, Kraken-Kosten. Überzeugungsregister (12.11.2026, 253 Aussagen): keine Live-Regel stützt sich auf eine bestandene Studie, 7 Live-Regeln sind widerlegt, mehr als 150 Prüfungen auf BTC 2020–2024 ohne fortlaufenden Gesamtzähler, Validierung 2023–2024 mehrfach verbraucht. V1-Juli: NOT_COMPLETE, 1-Minuten-Abdeckung 42,6 % / 60,7 %, 63 ungeklärte Lücken. tim-master P1: kein Setup mit positiver Evidenz im Register. Prüfberichte Chart: 295 von 331 Prüfungen PASS, kein Edge-Beleg.
- **Gegenbelege:** –. Keine.
- **Datenüberschneidung:** Eigenbewertung des Labors; deckt sich mit dieser Konsolidierung.
- **Unsicherheit:** Das Überzeugungsregister ist selbst eine Inventur des Labors, keine unabhängige Prüfung.
- **Praktische Konsequenz:** Die Zählung „mehr als 150 Prüfungen“ ist die Grundlage für die Mehrfachtest-Rechnung (E1: N = 64 bis 26.707). Eine fortlaufende Versuchszählung ist eine Vorbedingung für jede künftige Aussage über Signifikanz.
- **Evidenzstand:** Keine Evidenzstufe; Verfahren.

