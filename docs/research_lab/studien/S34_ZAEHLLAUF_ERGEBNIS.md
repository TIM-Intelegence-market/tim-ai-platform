# S34 – Zähllauf Training: Ergebnis (14.11.2026)

Präregistrierung: `S34_LVN_VWAP_FADE_PRAEREGISTRIERUNG.md` (PR #262). BTCUSDT, Training 2020-01-01 bis 2023-12-31, Bitunix-Kosten wie S35a. Lauf auf dem PS5, Ergebnisdatei `results/s34/s34_train_2026-11-14.json` (PS5).

**STATUS: nicht bestanden.** Validierung 2024 gesperrt (n < 60), Holdout 2025 nicht berührt.

| Größe | Wert |
|---|---|
| 5m-Kerzen im Fenster | 347.013 |
| Kerzen ≥ 2 σ vom Tages-VWAP | 21.491 |
| davon LVN am Wochen-VAH/VAL (≤ 0,15 %) = Signale = Trades | **53** |
| Trades pro Jahr | 2020: 12, 2021: 5, 2022: 12, 2023: 24 |
| brutto R / netto R | −0,016 / **−1,213** |
| Stop / Ziel / Zeit | 75 % / 21 % / 4 % |
| mittlerer Stop | 0,20 % |
| Bootstrap-Untergrenze (90 %) | −1,573 |
| Zufallskontrolle (1000 Ziehungen) | Zufallsmittel −1,205, p = 0,47 |
| Leave-one-year-out | nicht bestanden (alle Mittel negativ) |

## Befund
Mit 53 Trades liegt der Lauf unter der Mindestzahl 60. Brutto-R ist null: die Hypothese "Rückkehr zum VWAP vor dem Stop" zeigt keinen Vorsprung (Ziel in nur 21 % der Fälle). Die engen Stops (0,20 %) lassen die Kosten (≈ 0,2 % je Runde) auf rund 1,2 R anwachsen. Ergebnis wie beim S30-VWAP-Band-Test: nicht bestanden.

## Offenlegung
Läufe: ein Rauchtest BTC Februar 2020 (Lauffähigkeit, 0 Signale, nicht verwendet) und dieser Zähllauf. Nichts nachjustiert.
