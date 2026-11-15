# S35a – Zähllauf Training: Ergebnis (14.11.2026)

Präregistrierung: `S35A_LEVEL_ORDERFLOW_PRAEREGISTRIERUNG.md` (PR #262). Training 2020-01-01 bis 2022-12-31 (SOL ab 2020-09-01), BTC/ETH/SOL, Bitunix-Kosten (Taker 0,06 %/Seite, Slippage 0,03 %, Stop 0,05 %, Binance-Funding). Lauf auf dem PS5, Ergebnisdatei `results/s35a/s35a_train_2026-11-14.json` (PS5).

**STATUS: nicht bestanden, alle 12 Konfigurationen.** Validierung 2023–24 und Holdout 2025 wurden nicht gerechnet (Sperre im Code und in der Präregistrierung).

| Konfiguration | n | Signale/Tag | brutto R | netto R | Bootstrap-Untergrenze 90 % | Stop-Anteil | bestanden |
|---|---|---|---|---|---|---|---|
| E-bounce-5m | 3367 | 3.07 | +0.021 | -0.330 | -0.361 | 63 % | Nein |
| E-bounce-15m | 2218 | 2.02 | -0.028 | -0.338 | -0.375 | 63 % | Nein |
| E-break-5m | 4024 | 3.67 | +0.056 | -0.289 | -0.317 | 62 % | Nein |
| E-break-15m | 3353 | 3.06 | +0.062 | -0.253 | -0.284 | 60 % | Nein |
| V-bounce-5m | 4817 | 4.40 | -0.058 | -0.414 | -0.440 | 65 % | Nein |
| V-bounce-15m | 3114 | 2.84 | -0.051 | -0.365 | -0.395 | 63 % | Nein |
| V-break-5m | 5248 | 4.79 | +0.034 | -0.322 | -0.346 | 62 % | Nein |
| V-break-15m | 4342 | 3.96 | +0.046 | -0.280 | -0.307 | 61 % | Nein |
| P-bounce-5m | 4680 | 4.27 | -0.004 | -0.367 | -0.393 | 62 % | Nein |
| P-bounce-15m | 3494 | 3.19 | -0.030 | -0.354 | -0.383 | 61 % | Nein |
| P-break-5m | 4836 | 4.41 | +0.051 | -0.313 | -0.339 | 61 % | Nein |
| P-break-15m | 4177 | 3.81 | +0.039 | -0.297 | -0.325 | 61 % | Nein |

## Befund
- Das Ziel ≥ 1 Signal/Tag ist in allen 12 Konfigurationen erreicht (2,0 bis 4,8 pro Tag über alle Märkte). Die Mindestzahl n ≥ 100 ist überall weit übertroffen.
- Brutto liegt zwischen −0,06 und +0,06 R: kein erkennbarer Vorsprung vor dem Zufall. Netto liegt bei −0,25 bis −0,41 R. Die Kosten (rund 0,2–0,3 R je Trade bei 0,5 % Mindestrisiko) bleiben ohne Kanten-Vorsprung sicher negativ.
- Keine Konfiguration erreicht netto > +0,15 R. Die Bootstrap-Untergrenze ist durchweg negativ. Zufallskontrolle, Holm und Leave-one-year-out wurden nicht mehr getestet: Das Code-Gate testet nur, was die ersten drei Bedingungen besteht.
- Alle Läufe offengelegt: ein Rauchtest BTC März 2020 (Lauffähigkeit, 481 Trades über alle Konfigurationen, nicht bewertet) und dieser Zähllauf. Kein Lauf ist fehlgeschlagen oder verworfen.

## Risiken / Grenzen
Minutenbars Spot, Delta nur aus Minutenvolumen (kein Footprint), feste Ergänzungen der Präregistrierung (Berührung ±0,05 %, Delta ≥ 0,10, Mindestrisiko 0,5 %, Ziel 2 R). Abweichende Parameter wurden bewusst nicht getestet.

## Nächster Schritt
Keine Validierung. Gamma/GEX (S35b) bleibt Vorwärts-Schatten ohne Historie.
