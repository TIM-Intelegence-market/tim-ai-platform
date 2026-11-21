# S38 – Enger Vortag, danach Ausbruch (Präregistrierung 1.0, 15.11.2026)

Auftrag Uzi 15.11. ("Go") nach einem Reel (Aussage: Nach dem engsten Tag der Woche folgt eine große Bewegung, Richtung unbekannt, "plan für die Bewegung"). Quelle: Social-Media-Behauptung ohne Zahlen, nur Hypothese. Eingefroren auf Uzis Wort vor jedem Ergebnis; nach dem ersten Ergebnis wird nichts mehr geändert. Protokoll 1.3, Kosten, Bootstrap und Zufallskontrolle wie S34/S35a/S37.

## Hypothese
Nach einem UTC-Tag mit ungewöhnlich kleiner Spanne bringt der Ausbruch aus dieser Spanne am Folgetag im Mittel mehr als er nach Kosten kostet (positive Netto-R). Die Richtung wird nicht vorhergesagt: gehandelt wird der erste Ausbruch.

## Regel (fest)
- Engtag: UTC-Tag d mit Spanne (Hoch − Tief)/Eröffnung ≤ Schwelle × Mittel der Spannen (gleiche Definition) der 20 Tage davor. Tage mit weniger als 90 % gültigen Minuten zählen nicht (weder als Engtag noch im 20-Tage-Mittel).
- Handel am Folgetag d+1 (UTC): Stop-Einstieg 0,05 % jenseits des Hochs (Long) bzw. Tiefs (Short) des Engtags, der erste Ausbruch des Tages zählt, höchstens ein Trade je Markt und Tag. [Ergänzung] Brechen beide Seiten in derselben Minute, entfällt der Tag (gezählt).
- Stop: gegenüberliegendes Extrem des Engtags ∓ 0,05 %; Risiko mindestens 0,5 % vom Einstieg (sonst auf 0,5 % verbreitert). Ziel 2,0 R. Zeitstopp 1440 Minuten nach Einstieg. Stop vor Ziel in derselben Minute.
- Märkte: BTCUSDT, ETHUSDT, SOLUSDT (SOL ab 01.09.2020), S8-1.2.0-Minutenbars.

## Konfigurationen (genau 3, Holm über 3)
Schwelle {0,45; 0,60; 0,75} × Mittel der 20 Vortage. Ids `T-045`, `T-060`, `T-075`.
Referenz (keine Konfiguration, nicht in Holm, nur Ausweis): `T-alle` = dieselbe Ausbruchsregel an jedem Tag ohne Engtag-Filter. Sie zeigt, ob "eng" etwas beiträgt.

## Daten und Abschnitte
Training 2020–2022. Validierung 2023–2024 (nur Konfigurationen, die das Training bestehen, genau einmal). Holdout 2025 gesperrt, nicht gelesen.

## Kosten
Taker 0,06 %/Seite, Slippage 0,03 % (Stop 0,05 %), tatsächliche Binance-Funding-Raten (wie S34/S35a).

## Erfolgskriterium (je Konfiguration, alle zugleich)
Training: n ≥ 100, Netto > +0,15 R, 90-%-Bootstrap-Untergrenze > 0 (iid, 10 000, Seed 38), Zufallskontrolle (gleiche Zahl/Richtung/Stop-Ziel-Abstände, zufällige Einstiege alle 5 Minuten im Markt, 1000 Ziehungen) Holm-p ≤ 0,01, Leave-one-year-out > 0, kein Jahr > 60 % der R.
Validierung: n ≥ 60, Netto > +0,15 R, Untergrenze > 0, gleiches Vorzeichen.
Zusatz (Ausweis, keine Bedingung): Netto-R von T-alle; mittlere Spanne von d+1 geteilt durch die von d für Engtage gegenüber allen Tagen.
n unter der Mindestzahl = "nicht prüfbar".

## Ablauf
1. Einfrieren per PR (Spezifikation, `studies/s38.py`, Tests). 2. Zähllauf Training auf der PS5: `python -m src.research_lab.studies.s38 --phase train`. 3. Validierung nur bei bestandenem Training. 4. Bericht aller Läufe.

## Erwartung
Breakout-Strategien auf Krypto zahlen etwa 0,2 % Kosten je Runde gegen Stops von 1–3 %; ein Vorsprung ist nicht wahrscheinlich, ehrlich berichten.
