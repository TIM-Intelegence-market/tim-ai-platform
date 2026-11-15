# S36 – SFP mit Orderflow-Konfluenz, HTF→Exec, BTC/ETH/SOL (Präregistrierung 1.0, eingefroren 15.11.2026)

Auftrag Uzi (14.11.): "TIM sollte die Pattern auch tracken", dann "p4". Grundlage: GOAT-Handelsmodell (Bild im Thread) und der Muster-Schatten `muster-schatten/1.0` (PR #265, `src/analysis/patterns.py`). Diese Studie fragt rückwirkend, ob die Regeln des Schattens nach Kosten einen Vorteil haben. Entwurf: **nichts gelaufen, kein Ergebnis gesehen.** Mit **[Ergänzung]** markiert sind Festlegungen, die das Modell offenließ; sie gelten ab dem Einfrieren (1.0) und ändern sich danach nicht mehr.

## Version 1.0 – eingefroren (15.11.2026, Uzis Wort "einfrieren")
Ab hier ändert sich nichts mehr; was unten steht und im Entwurf davor, gilt in der Fassung der Änderungen 0.2 und 0.3. **Es wurde bis hierher kein R-Wert gerechnet**, nur Trade-Anzahlen (Variante M 425 / 123, Variante L 438 / 158, Training / Validierung, gepoolt BTC/ETH/SOL). Festlegungen der Auswertung (Phasen `train`, `valid` in `src/research_lab/studies/s36.py`):
- **Konfigurationen:** `SFP-alle-M` und `SFP-alle-L`, Holm über m = 2 (nicht Getestete zählen als p = 1).
- **Kosten der Auswertung:** M: Einstieg Taker 0,06 % plus 0,03 % Slippage, Ziel Taker plus 0,03 %, Stop Taker plus 0,05 %, Zeitausstieg Taker plus 0,03 %. L: Einstieg und Ziel Maker 0,02 %, Stop und Zeitausstieg wie M. Dazu die tatsächlichen Funding-Raten je Markt (Binance USD-M, `Funding`). Die Kostenrechnung des Schattens (0,14 % pauschal) wird in der Studie nicht verwendet.
- **Netto-R je Trade** = Brutto-R minus Kosten in R minus Funding in R; Bestehen wird an dieser **ungewichteten** Größe gemessen.
- **Bootstrap:** Block nach ISO-Woche, 10 000 Ziehungen, Seed 36, einseitig 90 % (10-%-Quantil des Mittels).
- **Zufallskontrolle** (nur für Konfigurationen, die n, Netto und Bootstrap bestehen): gleiche Trade-Zahl, Richtung, Stop- und Zielabstand als Bruchteil des Einstiegs; Einstieg zum Schluss einer zufälligen Exec-Kerze desselben Marktes und Profils im Abschnitt; gleiche Ausstiege (Stop zuerst, 96 Kerzen Haltezeit) und Kosten wie die Variante; 1000 Ziehungen, Seed 36; p = Anteil der Ziehungen mit Mittel ≥ real.
- **Leave-one-year-out:** Mittel-Netto-R bleibt > 0, wenn ein beliebiges Jahr weggelassen wird (mindestens zwei Jahre).
- **Training (2020–2023, SOL ab 09/2020) besteht,** wenn gleichzeitig n ≥ 60, Netto > +0,15 R, Bootstrap-Untergrenze > 0, Holm-adjustiertes p ≤ 0,01, Leave-one-year-out ok. **Validierung (2024)** nur für bestandene Konfigurationen, einmal: n ≥ 30, Netto > +0,15 R, Bootstrap-Untergrenze > 0.
- **Gestrichen gegenüber dem Entwurf:** Die Zusatzfragen (mit gegen ohne Konfluenz, gültiger gegen ungültiger OB) werden nicht gerechnet. Je Profil und Markt gibt es nur beschreibende Zahlen (Anzahl, Netto-Mittel).
- **Bericht:** alle Läufe, auch ein Fehlschlag. Holdout 2025 bleibt gesperrt (nur Uzis ausdrückliches Wort, genau einmal). Kein neuer Lauf mit geänderten Regeln auf denselben Daten; eine Variante wäre eine neue Studie.

## Änderung 0.3 (15.11.2026, vor jedem R-Wert, Uzis Wort "limit")
Die Zählung 0.2 (425 Trades Training, 123 Validierung, gepoolt) bleibt Grundlage. Neu: **zwei Einstiegsvarianten**, beide mit denselben Setups und Exec-OBs, Holm über m = 2:
- **M (Markt):** wie bisher, Einstieg zum Schlusskurs der Retest-Kerze, Taker-Kosten 0,14 % pro Runde im Schatten, in der Studie die strengere Rechnung. Konfluenzen dürfen an der Retest-Kerze gemessen werden.
- **L (Limit):** Limit-Order an der Kante des Exec-OB (Long: Oberkante, Short: Unterkante), platziert mit der ersten Kerze nach dem Armieren. Es zählen nur Konfluenzen, die **vor** der Order feststehen: RVOL am Ursprungs-OB und beim SFP zusätzlich RVOL und gefangene Trader (Delta gegen die Richtung, ≥ 0,10) der HTF-Sweep-Kerze. Mindestens eine. **Fill nur, wenn der Kurs das Limit um mindestens 0,01 % durchhandelt**; Berühren allein zählt nicht. In der Fill-Kerze wird nur der Stop geprüft (Stop gewinnt), das Ziel zählt erst ab der nächsten Kerze. Kosten: Einstieg und Ziel als Maker 0,02 %, Stop als Taker 0,06 % plus 0,05 % Slippage, Zeitausstieg als Taker 0,06 % plus 0,03 %. Der Kostenfilter (≤ 0,25 R) rechnet mit dem Stop-Fall.
- R:R ≥ 1,5, Stop, Ziel, Tages- und Sperrregel unverändert. Der Limit-Schatten im Live-Betrieb (#265) bleibt vorerst Variante M; L läuft nur im Rückblick.
- Das Kriterium (Training n ≥ 60, Netto > +0,15 R, Bootstrap-Untergrenze > 0, Zufallskontrolle) gilt je Variante; Holm über beide.

## Änderung 0.2 (15.11.2026, nach dem ergebnisblinden Zähllauf, Uzis Wort "sfp")
Der Zähllauf von 0.1 (nur Anzahlen, keine R; Datei `~/tim-research/results/s36/count.json` auf der PS5) ergab: alle 15 Konfigurationen liegen im Training (2020–2023) unter n = 60 (Maximum day-SFP mit 46, QM/OB 0 bis 5 je Profil). Daraufhin wird die Studie **vor jedem Blick auf Ergebnisse in R** verengt:
- Nur **SFP**. QM und OB bleiben im Vorwärts-Schatten (#265) und werden nicht zurückgeblickt (n zu klein).
- **Eine** Konfiguration `SFP-alle`: die fünf Profile gepoolt, **BTCUSDT, ETHUSDT, SOLUSDT** (S35a-Infrastruktur, SOL erst ab 01.09.2020). Holm entfällt (m = 1). Je Profil und je Markt wird nur beschreibend gezählt und später nur beschreibend gezeigt, nicht getestet.
- Tages- und Sperrregel gelten je Markt und Profil-Strom wie in der Plan-Mechanik des Schattens, nicht über Märkte hinweg [Ergänzung].
- Kriterium Training n ≥ 60 über alle Märkte und Profile, sonst "nicht testbar" und Ablage. Alles Weitere unten gilt für diese eine Konfiguration; die Abschnitte "Konfigurationen" und "Erfolgskriterium" sind entsprechend zu lesen (15 → 1, m = 15 → 1, ETH/SOL zusätzlich zu BTC).

## Fragestellung
Haben QM, OB und SFP auf einem höheren Zeitrahmen, mit Einstieg über einen sauberen OB im Exec-Zeitrahmen und mindestens einer Orderflow-Konfluenz, für BTCUSDT nach allen Kosten einen positiven Erwartungswert, der sich von zufälligen Einstiegen gleicher Geometrie unterscheidet?

## Was nicht neu gebaut wird
Die Detektoren, Konfluenzen und die Plan-Mechanik (Einstieg am Schluss der Retest-Kerze, Stop hinter der Exec-Zone, R:R ≥ 1,5, Tages- und Sperrregel) sind **dieselben Funktionen** wie im Schatten (`patterns.py`, `pattern_shadow.advance`), damit Rückblick und Vorwärts-Schatten dieselbe Regel messen. Die Studie liefert nur die Kerzen (Aggregation der S8-Minutenbars, Delta aus aggTrades) und die Auswertung.

## Konfigurationen (genau 15, Holm über alle 15)
5 Profile (Day 1h→15m, Week-a 4h→15m, Week-b 1d→30m, Swing-a 1d→1h, Swing-b 1w→4h) × 3 Muster (QM, OB, SFP). Id: `<Profil>-<Muster>`, z. B. `day-OB`. Ein QM-/SFP-Setup nutzt denselben Exec-OB-Einstieg wie im Schatten. 5m-Ausführung (Daytrading-Profil des Modells) gibt es hier und im Schatten nicht; Day läuft auf 15m **[Ergänzung]**.

## Regeln (alle wie `muster-schatten/1.0`, hier zur Sicherheit aufgeführt)
- Kerzen: nur geschlossene, UTC; Wochen ab Montag.
- OB: letzte Gegenkerze am Ursprung des Impulses nach BOS/MSS (`chart_live.market_structure`, Swing-Breite 3). Gültig nur, wenn die 6 Kerzen davor eine Spanne ≥ 2,5 × ATR(14) haben (keine Kompression darunter).
- QM: MSS; Zone um die linke Schulter (−0,5/+0,1 ATR), Ziel = gebrochener Strong-Level, ungültig jenseits des Kopfes.
- SFP: Docht durch einen unberührten bestätigten Swing, Schluss zurück; Ziel = nächster Gegen-Swing.
- Setup lebt höchstens 20 HTF-Kerzen. Exec-OB gleicher Richtung, nach dem Setup entstanden, in Reichweite ±0,5 HTF-ATR der Zone. Wartezeit auf den Retest 24 Exec-Kerzen, Haltezeit 96.
- Konfluenzen (mindestens 1): RVOL ≥ 1,5 am Ursprung-OB, RVOL ≥ 1,5 an der Retest-Kerze (Mittel der 20 Vorkerzen), gefangene Trader = Delta der Retest-Kerze (Taker-Kauf minus -Verkauf, geteilt durch Volumen) gegen die Handelsrichtung, |Anteil| ≥ 0,10.
- Einstieg am Schluss der Retest-Kerze, Stop = Exec-Zone ∓ 0,1 ATR, Ziel = Setup-Ziel, R:R ≥ 1,5, Kosten ≤ 0,25 R, sonst kein Trade. Stop vor Ziel in derselben Kerze.
- Tagesregel: höchstens 2 Trades je UTC-Tag, höchstens 2,0 R gewichteten Tagesverlust (1 R = 1 % angenommen). Nach Verlust oder verpasstem Plan nur Setups, die danach entstanden sind.
- Risikogewicht für die Ergebnisse: 0,7 bei einer Konfluenz, 1,0 bei zwei oder mehr, doppelt ab HTF 4h. **Bestehen wird an der ungewichteten Netto-R je Trade gemessen** **[Ergänzung]**; die gewichtete Summe wird zusätzlich berichtet.

## Daten und Abschnitte
BTCUSDT Binance Perp, 2020-09 bis 2024 (Funding ab 09/2020). **Training 2020–2023, Validierung 2024.** Holdout 2025 gesperrt: wird nicht gelesen, nur mit Uzis ausdrücklichem Wort, genau einmal. Prospektive Schatten-Trades (ab Start des Schattens) werden nicht in Training oder Validierung gemischt.

## Kosten
Wie S34/S35a: Taker 0,06 %/Seite, Slippage 0,03 % (Stop 0,05 %), tatsächliche Funding-Raten. Der Schatten rechnet vereinfachend 0,14 % pro Runde; die Studie ist die strengere Rechnung.

## Erfolgskriterium (je Konfiguration, alle zugleich)
Training: n ≥ 60, Netto > +0,15 R je Trade, Bootstrap-Untergrenze (90 %, Block nach Woche, 10 000 Ziehungen, Seed 36) > 0, Zufallskontrolle (gleiche Trade-Zahl, Richtung, Stop- und Zielabstand, zufällige Einstiege im Markt, 1000 Ziehungen) mit Holm-korrigiertem p ≤ 0,01 (m = 15; nicht getestete zählen als p = 1), Leave-one-year-out ohne Vorzeichenwechsel.
Validierung 2024 (nur Konfigurationen, die das Training bestehen, einmal): n ≥ 30, Netto > +0,15 R, Bootstrap-Untergrenze (90 %) > 0, gleiches Vorzeichen.
**Zusatzfrage (kein Bestehen):** Hilft die Konfluenz? Vergleich je Muster: mit mindestens 1 Konfluenz gegen derselbe Plan ohne Konfluenz-Pflicht, und gültiger gegen ungültiger OB (Kompression) mit gleicher Mechanik.

## Ablauf
1. Zähllauf ergebnisblind auf der PS5: nur Anzahl Trades je Konfiguration und Abschnitt, keine R. Ist n < 60 im Training, wird die Konfiguration als "nicht testbar" gemeldet und nicht gerechnet (Holm-m bleibt 15).
2. Einfrieren auf 1.0 per PR nach Uzis "einfrieren" (Entwurf 0.1 wird dann Version 1.0).
3. `train`, danach `valid` nur mit dem Trainingsergebnis, Bericht aller Läufe, auch fehlgeschlagener; Negativwissen wird abgelegt.

## Erwartung
Level-Reaktionen waren in S22 bis S30 nach Kosten nicht belegt; Konfluenz-Pflicht und HTF→Exec sind eine neue Frage, aber der Kostenanteil (rund 0,3 bis 0,5 R bei engem Exec-Stop) ist hoch. Ein negatives Ergebnis ist wahrscheinlich und wird so berichtet.
