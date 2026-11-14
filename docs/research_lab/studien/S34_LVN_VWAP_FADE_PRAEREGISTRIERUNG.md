# S34 – LVN am Wochen-VAH/VAL plus ≥ 2 Sigma vom Tages-VWAP, Rückkehr zum VWAP (Präregistrierung 1.0, 13.11.2026)

Auftrag Uzi (12./13.11.). Spezifikation 1.0 wird wie geschrieben eingefroren. Ergänzungen, die die Spezifikation offenließ, sind mit **[Ergänzung]** markiert und bewusst konservativ gewählt. Nach dem ersten Blick auf Ergebnisse wird nichts mehr geändert.

## Hypothese
BTC steht an einem Low-Volume-Node (LVN) im Bereich des Wochen-VAH (Long gespiegelt: VAL) und ≥ +2 Sigma (Long: ≤ −2 Sigma) vom Tages-VWAP. Der Preis kehrt zum Tages-VWAP zurück, bevor der Stop greift. (Short oben, Long unten.)

## Regel (fest, keine Parameterjagd)
- Wochenprofil: Volume Profile der laufenden Woche (UTC, Montag 00:00 bis Signalzeit, ohne Zukunft), VAH/VAL bei 70 % (Modul `orderflow_ml.profile.value_area`, Start am POC, größere Nachbar-Bin zuerst). **[Ergänzung]** Bins: log-Raster 0,1 % Breite (entspricht den S8-Profilbins, Tagesprofile werden darauf umgelegt), Volumen = aggressives Volumen (Basiseinheit).
- LVN: Profilknoten mit Volumen < 50 % des Medians der 10 Nachbar-Bins (je 5 darunter/darüber). **[Ergänzung]** Alle 10 Nachbarn müssen innerhalb der Profilspanne liegen. Der Knoten ist der Bin, in dem der Signalschluss liegt. Abstand der Knotenmitte zum VAH (Short) bzw. VAL (Long) ≤ 0,15 %.
- VWAP-Band: Tages-VWAP (UTC-Tag), Abweichung Schlusskurs der 5m-Kerze ≥ 2,0 Sigma (preis-volumengewichtete Standardabweichung der Minutenpreise, Minutenpreis = Quote-/Basisvolumen). **[Ergänzung]** Frühestens 60 Minuten nach UTC-Tagesbeginn; Wochenprofil mindestens 24 h alt (kein Signal vor Dienstag 00:00 UTC).
- Signal auf Kerzenschluss 5m, Einstieg zur Öffnung der nächsten Kerze (Eröffnungspreis der ersten Minute).
- Ziel: Tages-VWAP zum Signalzeitpunkt (fester Preis). Stop: Hoch (Short) / Tief (Long) der Signalkerze ± 0,1 %. Zeitstopp 4 h (Schluss der letzten Minute). **[Ergänzung]** Liegt der Einstieg schon jenseits von Stop oder Ziel, entfällt der Trade und wird als Zähler ausgewiesen. Treffen Stop und Ziel in derselben Minute, gilt der Stop.
- Max. 1 Trade pro UTC-Tag und Richtung (der erste Signal-Kandidat).

## Daten und Abschnitte
BTCUSDT Spot-Minutenbars S8 1.2.0 (Binance aggTrades). Training 2020–2023 nur Regelprüfung. Validierung 2024 genau einmal ohne Nachjustieren. Holdout 2025 gesperrt (wird nicht gelesen).

## Kosten (Bitunix, Cross-Margin, Zähllauf)
Taker 0,06 %/Seite; Slippage 0,03 %/Seite (Stop-Füllung 0,05 %), darin der Spread (Protokoll 1.1); Funding: tatsächliche Binance-USD-M-Funding-Raten (Long zahlt positive Rate) für alle Abrechnungszeitpunkte in der Haltedauer. **[Ergänzung]** Gebühr/Slippage-Werte wie Forschungsprotokoll 1.1. Spot-Bars dienen als Preisreihe.

## Erfolgskriterium (alle zugleich, eines fehlt = nicht bestanden)
1. ≥ 60 Trades im Training UND ≥ 60 in der Validierung, getrennt.
2. Netto-Mittel > +0,15 R nach Kosten in beiden, gleiches Vorzeichen.
3. Untere Grenze des 90-%-Bootstrap-Intervalls (iid, 10 000 Ziehungen, Seed 34) des Netto-Mittels in der Validierung > 0.
4. Leave-one-year-out: Mittel ohne jeweils ein Jahr bleibt > 0; kein Jahr trägt > 60 % der Gesamt-R; Jahre mit < 10 Trades zählen nicht als tragend (werden ausgewiesen). **[Ergänzung]** Über Training + Validierung gepoolt.
5. Zufallskontrolle: gleiche Trade-Zahl, gleiche Richtungsmischung, gleicher Stop- und Zielabstand (in % des Einstiegs), zufällige 5m-Einstiege im selben Abschnitt, 1000 Ziehungen, p ≤ 0,05 (Anteil Ziehungen mit Netto-Mittel ≥ Real). **[Ergänzung]** Schwelle p ≤ 0,05, da die Spezifikation keinen Wert nennt (nur eine Hypothese, kein Holm).

## Ablauf
1. Zähllauf Training (Anzahlen, Trichter, Netto-R, Bootstrap, LOYO, Zufallskontrolle) mit `python -m src.research_lab.studies.s34 --phase train`.
2. Validierung nur bei Training n ≥ 60 UND Netto > +0,15 R (im Code als Sperre).
3. Bericht mit Ja/Nein je Kriterium, alle Läufe offengelegt, keine Nachsuche. Rauchtest vor dem Einfrieren: BTC Februar 2020 zur Lauffähigkeitsprüfung (0 Signale, Ergebnis nicht verwendet).

## Erwartung
Kosten ≈ 0,2 % pro Runde gegen Stops von ~0,3–1 %; S30 (VWAP-Band-Test) bestand nicht. Wahrscheinlich wenige Trades (n < 60 → "nicht prüfbar").
