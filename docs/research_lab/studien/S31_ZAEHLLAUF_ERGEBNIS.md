# S31 Zähllauf Training 2020–22: Ergebnis (12.11.2026)

STATUS: PARTIAL (Zähllauf fertig, Auswertung entfällt nach Vorab-Regel „n < 100 = nicht prüfbar“)
SCOPE: Broncx-Bootcamp-Orderflow-Regeln B1–B8 (Präregistrierung 1.0), BTCUSDT Spot-Bars S8 1.2.0, Metrics (Perp-OI, Taker-Ratio) ab 2020-09, Bitunix-Kosten, Kostengate 0,15 R wie OF2. PS5, Code = Branch dieses PRs auf OFX-Stand, Datei results/s31/count_training.json.

EVIDENCE
| Regel | Quelle der Zahl | Trades Training | Netto R/Trade | Urteil |
|---|---|---|---|---|
| B1 Failed Auction | OF2 1.0 M1 (nur OF) | 34 | +0,33 | nicht prüfbar (n<100) |
| B2 Akzeptanz+Retest | OF2 1.0 M2 (nur OF) | 13 | +0,44 | nicht prüfbar |
| B4 SFP/Gefangene (auch B3) | OF2 1.0 M3 (nur OF) | 2 | +0,21 | nicht prüfbar |
| B5 Absorption/Stacked/Stop-Run | OF2 1.0 M5/M6 (nur OF) | 1 / 6 | −1,10 / −0,21 | nicht prüfbar |
| B6 Spot-/Perp-Divergenz | S31 Zähllauf | 0 (OF) / 0 (Preis) | n. a. | nicht prüfbar |
| B7 Sweep + Open Interest | S31 Zähllauf | 18 (OF) / 80 (Preis) | nicht ausgewertet | nicht prüfbar |
| B8 nPOC-Magnet | nur Ziel in OF2 (`Levels.targets`), kein eigener Auslöser gebaut | – | – | nicht gebaut |

B6/B7 Trichter: B6 1.958 Kandidaten (Preis), alle am Kostengate (> 0,15 R) verworfen, 0 übrig. B7 rund 12.200 Kandidaten, 80 nach Kostengate, 18 mit Orderflow-Bestätigung (2020: 4, 2021: 11, 2022: 3; Metrics erst ab 2020-09).
Gesamt OF2 (alle Modelle, nur OF): 56 Trades, +0,27 R, Zufall −0,09 R, p = 0,006; gesamt 130 Trades −0,01 R.

RISKS: 15-min-Auslöser haben Stops unter ~1 %; bei Bitunix-Kosten verwirft das Kostengate fast alles. Kein Bootcamp-Orderflow-Regelwerk liefert im Training ≥ 100 Trades; keine Regel erreicht das Ja-Kriterium. B6-Divergenz-Definition (neues Tagesextrem + Rot/Grün-Schluss) ist eine vorab gesetzte Lesart des Bootcamp, andere Lesarten wären neue Studien.
NEXT: Kein Validierungslauf (nichts besteht Training). Offene Wege nur mit Uzis Wort: größere Zeitrahmen für B1/B2 (30m–4h) mit eigener Studie, B8 als Auslöser, Orderbuch-Regeln erst nach Recorder-Daten.
