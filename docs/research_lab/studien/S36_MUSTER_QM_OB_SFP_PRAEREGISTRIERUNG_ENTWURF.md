# S36 – QM, OB und SFP mit Orderflow-Konfluenz, HTF→Exec, BTC (Präregistrierung, Entwurf 0.1, 14.11.2026)

Auftrag Uzi (14.11.): "TIM sollte die Pattern auch tracken", dann "p4". Grundlage: GOAT-Handelsmodell (Bild im Thread) und der Muster-Schatten `muster-schatten/1.0` (PR #265, `src/analysis/patterns.py`). Diese Studie fragt rückwirkend, ob die Regeln des Schattens nach Kosten einen Vorteil haben. Entwurf: **nichts gelaufen, kein Ergebnis gesehen.** Mit **[Ergänzung]** markiert sind Festlegungen, die das Modell offenließ; sie gelten ab dem Einfrieren (1.0) und ändern sich danach nicht mehr.

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
