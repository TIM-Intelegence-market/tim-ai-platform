# S37 – Fade-Checkliste (Flowread) auf BTC/ETH/SOL, Teil a ohne Gamma (Präregistrierung 1.0, 15.11.2026)

Auftrag Uzi 15.11.: Studie aus dem Flowread-Guide "The Fade Checklist", Rechnung auf PS4/PS5. Quelle ist Marketing ohne Zahlen: nur Hypothese.
Eingefroren auf Uzis Wort (15.11.2026, "Bau s37") vor jedem Blick auf Ergebnisse. Nach dem ersten Ergebnis wird nichts mehr geändert. Protokoll PROTOKOLL.md 1.3. Aufbau wie S34/S35a (gleiche Kosten, Bootstrap, Zufallskontrolle).

## Hypothese
Ein Fade zum Tages-VWAP gelingt nur, wenn alle Checks zugleich erfüllt sind (Kontext vor Auslöser). Frage: Bringt die Konjunktion nach Kosten mehr als jeder Einzelfilter (S34/S35a)?

## Abbildung der 5 Checks auf Krypto
| Guide | S37 Teil a | Status |
|---|---|---|
| 1 Gamma positiv | **nicht testbar**: keine kostenlose Options-Historie 2020–2024 | nur Vorwärts-Schatten (S33/A1), Teil b |
| 2 Level (Gamma-Strike + DEX) | Ersatz: Vortags-VAL (Long) / Vortags-VAH (Short), Profil wie S35a Klasse P, Berührung ±0,05 % | Ersatz, keine Gamma-Aussage |
| 3 Eröffnung in Vortags-Value-Area | UTC-Tagesbeginn: Eröffnungspreis 00:00 UTC innerhalb [VAL, VAH] des Vortagsprofils (24 h, kein US-Session-Schnitt, [Ergänzung]) | testbar |
| 4 ≥ ±2 VWAP-Abweichung auf dem Level | Tages-VWAP ± 2,0 Sigma wie S34, ab 60 min nach Tagesbeginn, Schluss der Kerze ≥ 2σ UND Berührung von Check 2 | testbar |
| 5 Absorption, dann Gegenseite | Kerze k: Volumen ≥ 1,5× Median der letzten 20 Kerzen UND Spanne ≤ 0,8× Median-Spanne (Anstrengung ohne Ergebnis) UND Delta gegen die Handelsrichtung; Kerze k+1 schließt in Handelsrichtung mit Delta in Handelsrichtung ≥ 0,10. Einstieg Open k+2 | testbar (aggTrades-Minutenbars), Footprint nicht verwendet |

## Konfigurationen (genau 4, Holm über 4)
Zeitrahmen {5m, 15m} × Check 3 {an, aus}. "aus" ist die Kontrolle: zeigt, ob die Eröffnungsregel etwas beiträgt.
Ids: `F-<TF>m-vaOn|vaOff`.

## Handel
[Ergänzung] Signalkerze k, Bestätigungskerze k+1, Einstieg zur Öffnung von k+2. Ziel: Tages-VWAP bei Schluss von k+1 (fester Preis). Richtung: Long wenn k bei ≤ −2σ schließt und das Vortags-VAL berührt, Short spiegelbildlich mit +2σ und VAH. Stop: Extrem der Kerze k ± 0,1 %, Risiko mindestens 0,5 % vom Einstieg (sonst auf 0,5 % verbreitert). Zeitstopp 4 h. Stop vor Ziel in derselben Minute. Liegt der Einstieg jenseits von Stop/Ziel: Trade entfällt, wird gezählt. Je Markt, Tag, Richtung höchstens 1 Trade.
Märkte BTCUSDT, ETHUSDT, SOLUSDT (Trades ab 01.09.2020), S8 1.2.0 Minutenbars.

## Daten und Abschnitte
Training 2020–2022. Validierung 2023–2024 (nur Konfigurationen, die das Training bestehen, genau einmal). Holdout 2025 gesperrt, nicht gelesen.

## Kosten
Wie S34/S35a: Taker 0,06 %/Seite, Slippage 0,03 % (Stop 0,05 %), echte Binance-Funding-Raten.

## Erfolgskriterium (je Konfiguration, alle zugleich)
Training: n ≥ 100, Netto > +0,15 R, 90-%-Bootstrap-Untergrenze > 0 (iid, 10 000, Seed 37), Zufallskontrolle (gleiche Zahl/Richtung/Stop-Ziel-Abstände, 1000 Ziehungen) Holm-p ≤ 0,01, Leave-one-year-out > 0, kein Jahr > 60 % der R.
Validierung: n ≥ 60, Netto > +0,15 R, Untergrenze > 0, gleiches Vorzeichen.
Zusatz: vaOn muss vaOff in Netto-R schlagen, sonst gilt Check 3 als wirkungslos (Ausweis, keine Bestehensbedingung).
n < Mindestzahl = "nicht prüfbar".

## Teil b (Gamma, nur Vorwärts)
Checks 1+2 als Schatten-Filter auf die Trades von Teil a, sobald S33 (A1-Aufzeichnung) 60 Tage hat. Keine Mischung mit Teil a. Kein Beleg ohne neue Präregistrierung.

## Ablauf
1. Einfrieren per PR (Spezifikation + Tests, Modul `studies/s37.py` auf Basis s34/s35a). 2. Zähllauf Training auf PS5: `python -m src.research_lab.studies.s37 --phase train`; PS4 nur für Zufallskontrolle (Training 2020–23 ist dort vorhanden). 3. Validierung nur bei bestandenem Training. 4. Bericht aller Läufe.

## Erwartung
Kosten ≈ 0,4 R gegen 0,5 % Risiko; S30 und S34 deuten auf kein Edge. Fünf Filter zusammen ergeben wahrscheinlich n < 100 = "nicht prüfbar".
