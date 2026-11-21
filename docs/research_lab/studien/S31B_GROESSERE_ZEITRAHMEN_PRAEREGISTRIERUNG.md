# S31b – Orderflow-Regeln auf 1h und 4h (Präregistrierung 1.0, 12.11.2026)

Folge von S31 (Zähllauf: alle Regeln auf 15m/30m unter 100 Trades, Kostengate verwirft fast alles). Uzi: "ja mach" (12.11.).
Nur die Zeitrahmen ändern sich, keine Regel und keine Schwelle. Nichts wird nach Sicht der Zahlen verändert.

## Konfigurationen (Budget: genau 2)
- A: `tf_value = tf_sfp = 60` (1h-Kerzen für alle Modelle)
- B: `tf_value = tf_sfp = 240` (4h-Kerzen für alle Modelle)
Alle übrigen Parameter = OF2 1.0 (`DEFAULT_CONFIG`), `of_gate` an (nur Orderflow-bestätigte Signale) und aus (Preis-Zwilling), wie S31.

## Regeln
M1–M7 (OF2 1.0: Failed Auction, Akzeptanz, SFP, Absorption, Stacked-Retest, Stop-Run, Poor Edge) und B6, B7 (S31 1.0), je Konfiguration. Hinweis: Tageskerzen-Verlauf wird täglich zurückgesetzt, B6 braucht ≥ 8 Kerzen am Tag und kann bei 4h nicht auslösen (6 Kerzen); das ist vorab so.

## Daten und Abschnitte
S8 1.2.0 Spot-Bars, Metrics (ab 2020-09) wie S31. Training 2020–22. Validierung 2023–24 nur für Regeln, die das Training bestehen. Holdout 2025+ gesperrt.

## Erfolgskriterium (je Regel und Konfiguration, alle zugleich)
n ≥ 100 Trades im Training, brutto ≥ +0,15 R, netto > 0 nach Bitunix-Kosten (Taker 0,06 %/Seite, Slippage wie OF2), Vorsprung vor Zufalls-Entries (OF2-`random`-Vergleich, 1000 Ziehungen, p ≤ 0,01 nach Holm über alle geprüften Regeln × 2 Konfigurationen), jedes Jahr nicht negativ, OF-Variante besser als Preis-Zwilling.

## Ablauf
1. Zähllauf (nur Anzahlen, keine R-Werte). Regeln unter 100 Trades: "nicht prüfbar".
2. Auswertung nur für Regeln mit n ≥ 100. Danach ggf. Validierung, dann Papier-Schatten am Mac. Holdout nur mit Uzis ausdrücklichem Wort.
3. Bericht mit Ja/Nein je Regel, keine Nachsuche.

## Erwartung
Größere Stops senken die Kosten in R, aber die Signalzahl sinkt mit größeren Kerzen. Dass ≥ 100 Trades zusammenkommen, ist nicht sicher; dann ist das Ergebnis "nicht prüfbar".
