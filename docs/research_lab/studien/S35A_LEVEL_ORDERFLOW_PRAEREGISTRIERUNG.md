# S35a – Level plus Orderflow-Bestätigung, Rückprall und Ausbruch, BTC/ETH/SOL (Präregistrierung 1.0, 13.11.2026)

Auftrag Uzi (12./13.11.). Grundlage: Entwurf 0.1 "Level of Gamma". Nur Teil a (ohne Gamma). Gamma/GEX läuft nur als Vorwärts-Schatten, hat keine Historie und ist **nicht** Teil dieses Backtests. Die Details, die der Entwurf offenließ, sind mit **[Ergänzung]** markiert und bewusst konservativ. Nach dem ersten Blick auf Ergebnisse wird nichts mehr geändert.

## Konfigurationen (genau 12, Holm über alle 12)
3 Level-Klassen × 2 Modi × 2 Zeitrahmen: 
- Klassen: **E** Extremmarken (Vortag-Hoch/Tief, Vorwoche-Hoch/Tief Mo–So, Vormonat-Hoch/Tief; UTC), **V** VWAP-Bänder (Tages-VWAP ± 2,0 Sigma, wie S34, ab 60 min nach Tagesbeginn), **P** Volumenprofil des Vortags (POC, VAH-Oberkante, VAL-Unterkante, 70 %, Modul `orderflow_ml.profile.value_area`, log-Raster 0,1 %).
- Modi: **bounce** (Rückprall), **break** (Ausbruch).
- Zeitrahmen: 5m, 15m.
Ids: `<Klasse>-<Modus>-<TF>m`, z. B. `E-bounce-5m`.

## Regeln (je geschlossene Kerze des Zeitrahmens)
- Berührung **[Ergänzung]**: Kerzenspanne schneidet das Band Level ± 0,05 %. Das Level steht vor der Kerze fest (VWAP-Band aus Minuten bis Kerzenbeginn).
- Seite: Schluss der Vorkerze über dem Level = Unterstützung, darunter = Widerstand.
- Orderflow-Bestätigung **[Ergänzung]**: Delta der Kerze (Taker-Kauf minus Taker-Verkauf in Quote, aus aggTrades-Minutenbars) geteilt durch das Kerzenvolumen, |Delta| ≥ 0,10 in Handelsrichtung. Footprint-Merkmale werden nicht verwendet.
- bounce: Berührung, Schluss auf der Ursprungsseite (Unterstützung: Schluss ≥ Level, Long; Widerstand: Schluss ≤ Level, Short), Delta in Handelsrichtung ≥ 0,10.
- break: Schluss mindestens 0,05 % jenseits des Levels (Unterstützung: darunter → Short; Widerstand: darüber → Long), Delta in Handelsrichtung ≥ 0,10.
- Einstieg zur Öffnung der nächsten Kerze. Stop **[Ergänzung]**: bounce = Kerzentief/-hoch ∓ 0,05 %; break = Level ± 0,1 % zur Gegenseite; Risiko mindestens 0,5 % vom Einstieg (Kostendeckel: Stop wird auf 0,5 % verbreitert, wenn näher). Ziel 2,0 R. Zeitstopp 6 h. Stop vor Ziel in derselben Minute.
- Je Konfiguration, Markt, UTC-Tag und Richtung höchstens ein Trade (erstes Signal).
- Märkte: BTCUSDT, ETHUSDT, SOLUSDT (Binance aggTrades, S8-Minutenbars, Download von data.binance.vision, 2020–2024). SOL ab 11.08.2020 (Spot), Funding ab 09/2020, daher Trades erst ab 01.09.2020.

## Daten und Abschnitte
Training 2020–2022. Validierung 2023–2024 (nur Konfigurationen, die das Training bestehen, einmal). Holdout 2025 gesperrt (nur Uzis ausdrückliches Wort, genau einmal; wird nicht gelesen).

## Kosten
Wie S34: Taker 0,06 %/Seite, Slippage 0,03 % (Stop 0,05 %), tatsächliche Funding-Raten je Markt.

## Erfolgskriterium (je Konfiguration, alle zugleich)
Training: n ≥ 100 (alle Märkte), Netto > +0,15 R, Bootstrap-Untergrenze (90 %, iid, 10 000, Seed 34) > 0, Zufallskontrolle (gleiche Trade-Zahl/Richtung/Stop-/Zielabstand, zufällige 5m-Einstiege im Markt, 1000 Ziehungen) mit Holm-korrigiertem p ≤ 0,01 (m = 12; ungetestete Konfigurationen zählen als p = 1; getestet wird nur, was die ersten drei Bedingungen besteht), Leave-one-year-out (wie S34). 
Validierung: n ≥ 60, Netto > +0,15 R, Bootstrap-Untergrenze (90 %) > 0, gleiches Vorzeichen wie im Training. 
Ziel (nicht Bestehensbedingung): ≥ 1 Signal pro Tag über alle Märkte, wird je Konfiguration ausgewiesen.

## Ablauf
1. Rauchtest/Tests, Einfrieren per PR. 2. `python -m src.research_lab.studies.s35a --phase train`. 3. `--phase valid` nur mit dem Trainingsergebnis. 4. Bericht aller Läufe, auch fehlgeschlagener.

## Erwartung
Kosten ≈ 0,2 % pro Runde gegen 0,5 % Risiko = rund 0,4 R. Ein Netto-Vorsprung ist unwahrscheinlich; ehrlich berichten.
